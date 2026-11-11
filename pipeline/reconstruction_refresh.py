"""Report-triggered collection always updates the shared production source."""
import json
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
import shared_data


_SYNC_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconstruction-source")
_SYNC_LOCK = threading.Lock()
_SYNC_JOB = None


def start():
    shared_data.start()
    projects.request()
    ordinances.request()


def _primary(entity):
    pending = buildings.request(entity)
    pending_parcel = parcels.request(entity)
    pending_projects = projects.request()
    ordinances.request()
    result = reconstruction.analyze(entity)
    waiting = []
    if pending:
        waiting.append("건축물대장")
    if pending_parcel:
        waiting.append("대표 지번의 건축 기준")
    if pending_projects and (result.get("projectPlan") or {}).get("status") in ("not_collected", "connection_error"):
        waiting.append("서울시 정비계획")
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
    with (opener or urlopen)(request, timeout=8) as response:
        raw = response.read(1_000_001)
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
    return ({k: v for k, v in local.items() if k != "sourceRevision"}
            == {k: v for k, v in remote.items() if k != "sourceRevision"})


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
    try:
        remote = _request_primary(entity)
        if remote.get("status") == "loading":
            return _loading(entity, remote.get("reason") or "운영 서버에서 빠진 자료를 수집하고 있어요.")
        local = reconstruction.analyze(entity)
        if _same_facts(local, remote):
            return local
        # A full source publication can exceed a browser request's time limit.
        # Share one background sync across reports; polling must stay responsive.
        with _SYNC_LOCK:
            if _SYNC_JOB is not None and _SYNC_JOB.done():
                job, _SYNC_JOB = _SYNC_JOB, None
                if job.result().get("status") != "ready":
                    raise shared_data.SharedDataError("shared source refresh failed")
                local = reconstruction.analyze(entity)
                if _same_facts(local, remote):
                    return local
            if _SYNC_JOB is None:
                _SYNC_JOB = _SYNC_POOL.submit(shared_data.sync_once)
        return _loading(entity, "수집한 건축 자료를 공용 원본에서 가져오고 있어요.")
    except (URLError, OSError, ValueError, TypeError, KeyError, shared_data.SharedDataError):
        result = reconstruction.analyze(entity)
        result.update(status="stale" if result.get("profile", {}).get("scope") else "connection_error",
                      heading="운영 원본의 건축 자료를 불러오지 못했어요", summary="", grade="unknown",
                      reason="운영 서버의 자료 수집 또는 연결에 문제가 생겼어요. 잠시 뒤 다시 불러오기를 눌러 주세요.")
        result["feasibility"] = reconstruction.feasibility(result)
        return result
