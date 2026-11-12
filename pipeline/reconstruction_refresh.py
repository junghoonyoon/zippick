"""Report-triggered collection always updates the shared production source."""
import json
import logging
import ssl
import subprocess
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import apartment_reconstruction as reconstruction
import collect_building_register as buildings
import collect_reconstruction_planning as parcels
import collect_reconstruction_ordinance as ordinances
import collect_seoul_reconstruction_plans as projects
import collect_regional_reconstruction_plans as regional_projects
import shared_data
import process_runtime


LOG = logging.getLogger(__name__)

class SourceConnectionError(RuntimeError):
    def __init__(self, code, stage):
        super().__init__(code)
        self.code, self.stage = code, stage



def _connection_failure(exc, stage):
    """Expose a safe diagnostic code, never a URL, credential, or raw stderr."""
    if isinstance(exc, SourceConnectionError):
        return {"status": "error", "stage": exc.stage, "code": exc.code}
    cause = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(cause, ssl.SSLCertVerificationError):
        code = "tls_verification_failed"
    elif getattr(exc, "code", None):
        code = "http_" + str(exc.code)
    elif isinstance(exc, subprocess.CalledProcessError):
        code = {60: "tls_verification_failed", 28: "request_timeout",
                22: "http_error", 6: "dns_failed", 7: "connection_failed"}.get(exc.returncode, "transport_failed")
    elif isinstance(cause, (TimeoutError, subprocess.TimeoutExpired)):
        code = "request_timeout"
    elif isinstance(exc, (ValueError, TypeError, KeyError)):
        code = "invalid_source_response"
    else:
        code = "connection_failed"
    return {"status": "error", "stage": stage, "code": code}



_SYNC_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconstruction-source")
_SYNC_LOCK = threading.Lock()
_SYNC_JOB = None


def start():
    shared_data.start()
    projects.request()
    regional_projects.request()
    ordinances.request()


def _primary(entity):
    pending = buildings.request(entity)
    pending_parcel = parcels.request(entity)
    pending_projects = projects.request()
    pending_regional = regional_projects.request(entity)
    ordinances.request()
    result = reconstruction.analyze(entity)
    waiting = []
    if pending:
        waiting.append("건축물대장")
    if pending_parcel:
        waiting.append("대표 지번의 건축 기준")
    if pending_projects and (result.get("projectPlan") or {}).get("status") in ("not_collected", "connection_error"):
        waiting.append("서울시 정비계획")
    if pending_regional and (result.get("projectPlan") or {}).get("status") in ("not_collected", "connection_error", "stale"):
        waiting.append("지역 정비계획")
    if waiting:
        result.update(status="loading", heading="공식 건축 자료를 불러오고 있어요",
                      reason=f"{'·'.join(waiting)}을 확인하고 있어요.", summary="")
    return result


def _request_primary(entity, *, opener=None):
    # Only public complex identity is forwarded. Keys and personal inputs stay local.
    host = shared_data.SOURCE_HOST
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("invalid shared source host")
    query = urlencode({"apartment_id": entity["apartmentId"], "name": entity["name"],
                       "region": " ".join(filter(None, (entity.get("province"), entity.get("district")))),
                       "legal_dong": entity.get("legalDong", ""), "jibun": entity.get("jibun", "")})
    request = Request(f"https://{host}/api/apartment-reconstruction?{query}",
                      headers={"Accept": "application/json", "User-Agent": "Zippick/1.0 shared-source-refresh"})
    try:
        with (opener or urlopen)(request, timeout=8) as response:
            raw = response.read(1_000_001)
    except URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        # Match the verified system-TLS fallback used by the transaction and
        # Seoul source readers. Python 3.14 can reject a chain the OS validates.
        # Keep HTTPS, certificate/hostname verification, identity and size checks.
        response = process_runtime.run(
            ["curl", "--fail", "--silent", "--show-error", "--proto", "=https",
             "--max-time", "8", "--max-filesize", "1000000",
             "--header", "Accept: application/json",
             "--user-agent", "Zippick/1.0 shared-source-refresh", request.full_url],
            capture_output=True, check=True, timeout=10,
        )
        raw = response.stdout
    if len(raw) > 1_000_000:
        raise ValueError("oversized source response")
    model = json.loads(raw)["reconstructionConditions"]
    if (model.get("version") != reconstruction.VERSION
            or str(model.get("apartmentId")) != str(entity["apartmentId"])
            or any(str((model.get("identity") or {}).get(k) or "") != str(entity.get(k) or "")
                   for k in ("legalDong", "jibun"))):
        raise ValueError("shared source identity mismatch")
    return model


def _same_facts(local, remote):
    # Filesystem stamps differ between primary and replica. Public judgments
    # and every underlying fact must match before skipping another sync.
    return ({k: v for k, v in local.items() if k not in ("sourceRevision", "sourceVerification")}
            == {k: v for k, v in remote.items() if k not in ("sourceRevision", "sourceVerification")})


def _loading(entity, reason):
    result = reconstruction.analyze(entity)
    result.update(status="loading", heading="운영 원본의 건축 자료를 불러오고 있어요",
                  reason=reason, summary="")
    return result


def refresh(entity):
    global _SYNC_JOB
    if not shared_data.read_only():
        return _primary(entity)
    # Replica never calls data providers or writes independent facts. Production
    # collects, then the normal verified snapshot publisher brings the files over.
    stage = "primary_api"
    try:
        remote = _request_primary(entity)
        if remote.get("status") == "loading":
            reconstruction.forget_primary_confirmation(entity)
            return _loading(entity, remote.get("reason") or "운영 서버에서 빠진 자료를 수집하고 있어요.")
        stage = "shared_snapshot"
        reconstruction.confirm_primary_snapshot(entity, remote)
        local = reconstruction.analyze(entity)
        if _same_facts(local, remote):
            return local
        # A full source publication can exceed a browser request's time limit.
        # Share one background sync across reports; polling must stay responsive.
        with _SYNC_LOCK:
            if _SYNC_JOB is not None and _SYNC_JOB.done():
                job, _SYNC_JOB = _SYNC_JOB, None
                sync_status = job.result()
                if sync_status.get("status") != "ready":
                    raise SourceConnectionError(sync_status.get("errorReason") or "snapshot_sync_failed",
                                                sync_status.get("errorStage") or "shared_snapshot")
                local = reconstruction.analyze(entity)
                if _same_facts(local, remote):
                    return local
            if _SYNC_JOB is None:
                _SYNC_JOB = _SYNC_POOL.submit(shared_data.sync_once)
        return _loading(entity, "수집한 건축 자료를 공용 원본에서 가져오고 있어요.")
    except (URLError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError,
            shared_data.SharedDataError, SourceConnectionError) as exc:
        reconstruction.forget_primary_confirmation(entity)
        connection = _connection_failure(exc, stage)
        LOG.warning("reconstruction source failure apartment=%s stage=%s code=%s type=%s",
                    entity.get("apartmentId"), connection["stage"], connection["code"], type(exc).__name__)
        result = reconstruction.analyze(entity)
        sync_failed = connection["stage"] != "primary_api"
        reason = ("운영 API는 응답했지만 최신 원본 파일을 가져오지 못했어요. 다시 불러오기를 눌러 주세요."
                  if sync_failed else
                  "이 기기에서 운영 서버의 인증서를 확인하지 못했어요. 연결 환경을 확인한 뒤 다시 불러오기를 눌러 주세요."
                  if connection["code"] == "tls_verification_failed" else
                  "운영 서버의 건축 자료 요청에 실패했어요. 잠시 뒤 다시 불러오기를 눌러 주세요.")
        result.update(status="stale" if result.get("profile", {}).get("scope") else "connection_error",
                      heading="건축 자료 동기화 연결이 끊겨 최신 상태를 확인하지 못했어요" if sync_failed else "운영 원본의 건축 자료를 불러오지 못했어요",
                      summary="", grade="unknown", reason=reason, sourceConnection=connection)
        result["feasibility"] = reconstruction.feasibility(result)
        return result
