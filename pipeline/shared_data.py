"""One authoritative source for collected apartment facts.

Production owns the collected files. Development reads an automatically refreshed,
read-only snapshot over the existing authenticated SSH connection. Calculated
scores, reports, personal settings and credentials are never transferred.
"""
import argparse
import datetime
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time

import config
import persistent_json_store
import process_runtime


SOURCE_HOST = os.environ.get("ZIPPICK_DATA_HOST", "maesuhalkkayo.exe.xyz")
SOURCE_ROOT = os.environ.get("ZIPPICK_DATA_ROOT", "/home/exedev/apps/zippick/shared/cache")
MIRROR_ROOT = config.CACHE_DIR / "shared_source"
REFRESH_SECONDS = max(30, int(os.environ.get("ZIPPICK_DATA_REFRESH_SECONDS", "60")))
FACT_FILES = (
    "apartment_station_distances.json", "education_environment_records.json",
    "regional_price_index.json", "market_indicators.json", "regional_price_index_history.json",
    "building_register_records.json", "reconstruction_planning_records.json", "seoul_reconstruction_plans.json",
    "reconstruction_ordinance_verification.json", "price_data_revision.json",
)
REQUIRED_FILES = FACT_FILES[:2]
_LOCK = threading.RLock()
_SYNC_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD = None
_LISTENERS = []
CONTROL_ROOT = Path("/tmp")


class SharedDataError(RuntimeError):
    pass


@functools.lru_cache(maxsize=16)
def _auto_mode(cache_dir, source_root):
    # 실행 경로는 프로세스 설정이다. 거래 한 건을 읽을 때마다 상위 경로의
    # 심볼릭 링크를 다시 풀지 않는다. 설정 경로가 바뀌면 별도 키를 쓴다.
    return "primary" if cache_dir.resolve() == Path(source_root) else "replica"


def mode():
    selected = os.environ.get("ZIPPICK_DATA_MODE", "auto").strip().lower()
    if selected not in {"auto", "primary", "replica", "isolated"}:
        raise SharedDataError("공용 데이터 실행 모드가 올바르지 않아요.")
    if selected != "auto":
        return selected
    # exe.dev releases all point to the same persistent source directory.
    return _auto_mode(config.CACHE_DIR, SOURCE_ROOT)


def read_only():
    return mode() == "replica"


def cache_path(relative):
    if read_only():
        return MIRROR_ROOT / "current" / relative
    return config.CACHE_DIR / relative


def require_writer():
    if read_only():
        raise SharedDataError("수집 자료는 운영 원본에서만 갱신해요. 로컬은 공용 원본을 읽어요.")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _read_state():
    return persistent_json_store.read_json_object(MIRROR_ROOT / "status.json")


def revision():
    if not read_only():
        return ""
    try:
        current = MIRROR_ROOT / "current"
        # 동기화는 검증된 세대 디렉터리를 가리키는 링크를 한 번에 교체한다.
        # 링크 대상은 매번 읽어 다른 프로세스의 갱신도 즉시 감지하되,
        # 반복적인 전체 경로 resolve는 생략한다.
        target = os.readlink(current)
        version = os.path.basename(target)
        if re.fullmatch(r"[0-9a-f]{64}", version):
            return version if os.path.isdir(os.path.join(MIRROR_ROOT, target)) else ""
        return current.resolve(strict=True).name
    except OSError:
        # 이전 설치의 일반 디렉터리와 끊어진 링크도 기존과 같이 처리한다.
        try:
            return (MIRROR_ROOT / "current").resolve(strict=True).name
        except OSError:
            return ""


def data_revision():
    """A cheap, process-independent version for calculated transaction caches."""
    if read_only():
        return revision()
    path = cache_path("price_data_revision.json")
    try:
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return "initial"


def bump_data_revision():
    """Publish a new version after any successful primary transaction write."""
    require_writer()
    path = cache_path("price_data_revision.json")
    with persistent_json_store.exclusive_file_lock(path):
        persistent_json_store.write_json_atomically(path, {
            "changedAt": _now(), "revision": str(time.time_ns()),
        })


def status():
    selected = mode()
    if selected != "replica":
        return {"mode": selected, "status": "primary" if selected == "primary" else "isolated"}
    state = _read_state()
    usable = all(cache_path(name).is_file() for name in REQUIRED_FILES)
    try:
        checked = datetime.datetime.fromisoformat(state.get("lastCheckedAt", ""))
        overdue = (datetime.datetime.now(datetime.timezone.utc) - checked).total_seconds() > REFRESH_SECONDS * 2 + 30
    except (ValueError, TypeError):
        overdue = True
    if usable and overdue and not state.get("error"):
        state["error"] = "공용 원본 연결 확인이 늦어지고 있어요. 마지막 정상 자료를 사용해요."
    return {**state, "mode": selected, "readOnly": True, "source": "운영 공용 원본",
            "revision": revision(), "status": ("stale" if state.get("error") else "ready") if usable else "unavailable"}


def subscribe(callback):
    with _LOCK:
        if callback not in _LISTENERS:
            _LISTENERS.append(callback)


_MANIFEST_SCRIPT = r'''
import json, pathlib, re, sys
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
names = ["apartment_station_distances.json", "education_environment_records.json", "regional_price_index.json", "market_indicators.json", "regional_price_index_history.json", "building_register_records.json", "reconstruction_planning_records.json", "seoul_reconstruction_plans.json", "reconstruction_ordinance_verification.json", "price_data_revision.json"]
paths = [root / name for name in names]
paths += list((root / "molit_transactions").glob("*.json"))
files = {}
for path in paths:
    if not path.is_file() or path.is_symlink():
        continue
    relative = path.relative_to(root).as_posix()
    if relative not in names and not re.fullmatch(r"molit_transactions/(?:rent_|presale_)?\d{5}_\d{6}\.json", relative):
        continue
    stat = path.stat()
    files[relative] = [stat.st_size, stat.st_mtime_ns]
print(json.dumps(files, sort_keys=True, separators=(",", ":")))
'''


def _ssh_options():
    # Reuse one authenticated connection; every refresh must not open a new login.
    # UNIX socket paths are kept short even when the project path is long.
    digest = hashlib.sha256((str(MIRROR_ROOT) + SOURCE_HOST).encode()).hexdigest()[:10]
    directory = CONTROL_ROOT / f"zippick-data-{os.getuid()}-{digest}"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise SharedDataError("공용 데이터 연결 보관 위치를 확인해 주세요.")
    directory.chmod(0o700)
    return ["-oBatchMode=yes", "-oConnectTimeout=8", "-oControlMaster=auto",
            "-oControlPersist=120", "-oControlPath=" + str(directory / "s"),
            "-oServerAliveInterval=15", "-oServerAliveCountMax=2"]


def _source_manifest():
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", SOURCE_HOST) or SOURCE_HOST.startswith("-"):
        raise SharedDataError("공용 원본 서버 설정을 확인해 주세요.")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", SOURCE_ROOT) or ".." in Path(SOURCE_ROOT).parts:
        raise SharedDataError("공용 원본 경로 설정을 확인해 주세요.")
    command = "python3 -c " + shlex.quote(_MANIFEST_SCRIPT) + " " + shlex.quote(SOURCE_ROOT)
    for attempt in range(2):
        try:
            result = process_runtime.run(
                ["ssh", *_ssh_options(), SOURCE_HOST, command],
                check=True, capture_output=True, timeout=25, text=True,
            )
            break
        except (OSError, subprocess.SubprocessError):
            if attempt:
                raise
    manifest = json.loads(result.stdout)
    if not isinstance(manifest, dict) or not all(name in manifest for name in REQUIRED_FILES):
        raise SharedDataError("운영 원본의 역·학교 자료를 찾지 못했어요.")
    if not any(name.startswith("molit_transactions/") for name in manifest):
        raise SharedDataError("운영 원본의 실거래 자료를 찾지 못했어요.")
    for name, values in manifest.items():
        if name not in FACT_FILES and not re.fullmatch(r"molit_transactions/(?:rent_|presale_)?\d{5}_\d{6}\.json", name):
            raise SharedDataError("공용 원본에 허용되지 않은 파일이 있어요.")
        if not isinstance(values, list) or len(values) != 2 or not all(isinstance(value, int) and value >= 0 for value in values):
            raise SharedDataError("공용 원본의 파일 정보를 확인하지 못했어요.")
    return manifest


def _manifest_revision(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_snapshot(directory, manifest, previous=None):
    # Reuse only unchanged hard links to the last fully validated snapshot.
    # All newly copied files still need full validation before publication.
    previous_manifest = persistent_json_store.read_json_object(previous / "source-manifest.json") if previous else {}
    for name, (size, _mtime) in manifest.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise SharedDataError("공용 원본을 온전히 내려받지 못했어요.")
        prior = previous / name if previous else None
        try:
            unchanged = (prior is not None and previous_manifest.get(name) == manifest[name]
                         and not prior.is_symlink() and os.path.samefile(path, prior))
        except OSError:
            unchanged = False
        if unchanged:
            continue
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
        if not isinstance(value, dict):
            raise SharedDataError("공용 자료 형식이 올바르지 않아요.")
        if name in REQUIRED_FILES and (not isinstance(value.get("records"), dict) or not value["records"]):
            raise SharedDataError("공용 원본의 역·학교 기록 형식이 올바르지 않아요.")
        if name.startswith("molit_transactions/") and not isinstance(value.get("items"), list):
            raise SharedDataError("공용 원본의 실거래 기록 형식이 올바르지 않아요.")
        if name == "reconstruction_planning_records.json":
            records = value.get("records")
            if not isinstance(records, dict) or any(not isinstance(entry, dict) for entry in records.values()):
                raise SharedDataError("공용 원본의 재건축 기준 기록 형식이 올바르지 않아요.")
        if name == "reconstruction_ordinance_verification.json":
            records = value.get("records")
            if not isinstance(records, dict) or any(not isinstance(entry, dict) for entry in records.values()):
                raise SharedDataError("공용 원본의 조례 확인 기록 형식이 올바르지 않아요.")
        if name == "seoul_reconstruction_plans.json":
            records = value.get("records")
            if (not isinstance(records, dict) or any(not isinstance(entry, dict) for entry in records.values())
                    or (records and (len(records) != value.get("totalCount")
                        or value.get("sourceUrl") != "https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do"
                        or any(not row.get("bsns_name") or not row.get("site_code_nm") or not row.get("basic_info_seq")
                               for row in records.values())))):
                raise SharedDataError("공용 원본의 서울 정비계획 전체 건수를 확인하지 못했어요.")
        if name == "building_register_records.json":
            records = value.get("records")
            if not isinstance(records, dict) or any(not isinstance(entry, dict) for entry in records.values()):
                raise SharedDataError("공용 원본의 건축물대장 기록 형식이 올바르지 않아요.")
            for entry in records.values():
                snapshot = entry.get("snapshot")
                if snapshot is None:
                    continue
                if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("records"), list)
                        or any(not isinstance(row, dict) for row in snapshot["records"])
                        or len(snapshot["records"]) != snapshot.get("totalCount")):
                    raise SharedDataError("공용 원본의 건축물대장 전체 건수를 확인하지 못했어요.")


def sync_once():
    if not read_only():
        return status()
    with _SYNC_LOCK, persistent_json_store.exclusive_file_lock(MIRROR_ROOT / "sync"):
        old = _read_state()
        incoming = None
        stage = "source_manifest"
        try:
            manifest = _source_manifest()
            version = _manifest_revision(manifest)
            changed = revision() != version
            if changed:
                generations = MIRROR_ROOT / "generations"
                generations.mkdir(parents=True, exist_ok=True)
                incoming = Path(tempfile.mkdtemp(prefix=".incoming-", dir=generations))
                previous = MIRROR_ROOT / "current"
                transport = shlex.join(["ssh", *_ssh_options()])
                command = ["rsync", "-a", "--checksum", "--files-from=-", "-e", transport]
                if previous.exists():
                    command.append("--link-dest=" + str(previous.resolve()))
                command += [SOURCE_HOST + ":" + SOURCE_ROOT.rstrip("/") + "/", str(incoming) + "/"]
                stage = "download"
                process_runtime.run(command, input="\n".join(sorted(manifest)) + "\n", text=True,
                               check=True, capture_output=True, timeout=180)
                stage = "verify_source"
                if _source_manifest() != manifest:
                    raise SharedDataError("동기화 중 운영 자료가 갱신됐어요. 다음 주기에 다시 받아요.")
                stage = "validate_snapshot"
                _validate_snapshot(incoming, manifest, previous if previous.exists() else None)
                persistent_json_store.write_json_atomically(incoming / "source-manifest.json", manifest)
                destination = generations / version
                if not destination.exists():
                    incoming.rename(destination)
                    incoming = None
                next_link = MIRROR_ROOT / (".current-" + str(os.getpid()))
                next_link.unlink(missing_ok=True)
                next_link.symlink_to(destination)
                os.replace(next_link, MIRROR_ROOT / "current")
            state = {"lastCheckedAt": _now(), "lastSuccessAt": _now(), "error": "",
                     "fileCount": len(manifest), "rawTransactionFiles": sum(name.startswith("molit_transactions/") for name in manifest)}
            persistent_json_store.write_json_atomically(MIRROR_ROOT / "status.json", state)
            if changed:
                for callback in tuple(_LISTENERS):
                    callback()
                # These directories contain only reproducible, downloaded facts.
                snapshots = sorted((MIRROR_ROOT / "generations").glob("[0-9a-f]" * 64), key=lambda path: path.stat().st_mtime, reverse=True)
                for obsolete in snapshots[3:]:
                    if obsolete != (MIRROR_ROOT / "current").resolve():
                        shutil.rmtree(obsolete)
        except (OSError, ValueError, SharedDataError, subprocess.SubprocessError) as exc:
            if isinstance(exc, subprocess.CalledProcessError):
                diagnostic = exc.stderr or ""
                if isinstance(diagnostic, bytes):
                    diagnostic = diagnostic.decode("utf-8", errors="replace")
                (MIRROR_ROOT / "connection-error.txt").write_text(diagnostic[-4000:], encoding="utf-8")
            persistent_json_store.write_json_atomically(MIRROR_ROOT / "status.json", {
                **old, "lastCheckedAt": _now(),
                "error": str(exc) if isinstance(exc, SharedDataError) else "공용 원본 연결 또는 자료 검증에 실패했어요. 마지막 정상 자료를 유지해요.",
                "errorStage": stage, "errorType": type(exc).__name__,
                "errorCode": getattr(exc, "returncode", None),
            })
        finally:
            if incoming and incoming.exists():
                shutil.rmtree(incoming)
        return status()


def start():
    global _THREAD
    if not read_only():
        return status()
    result = sync_once()
    if result["status"] == "unavailable":
        raise SharedDataError("공용 원본에 연결하지 못해 서버를 시작하지 않았어요. 연결 상태를 확인해 주세요.")
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()

            def refresh():
                while not _STOP.wait(REFRESH_SECONDS):
                    sync_once()

            _THREAD = threading.Thread(target=refresh, name="shared-data-reader", daemon=True)
            _THREAD.start()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="운영 공용 원본과 로컬 읽기 자료를 동기화한다.")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    result = status() if args.status else sync_once()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["status"] == "unavailable" or result.get("error") else 0)
