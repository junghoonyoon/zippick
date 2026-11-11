"""Collect whole-site building registers on the primary, preserving good records."""
import argparse
import datetime as dt
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import apartment_reconstruction as reconstruction
import building_hub
import persistent_json_store as store
import shared_data

STOP_CODES = {"20", "21", "22", "30", "31", "32", "99", "401", "403", "429", "missing_key"}
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="building-register")
_LOCK = threading.Lock()
_JOBS = {}
_BLOCKED_UNTIL = 0


def request(entity):
    """Only reports request collection; lists use cached common facts."""
    global _BLOCKED_UNTIL
    if shared_data.read_only():
        return False
    key = reconstruction.parcel_key(entity)
    if not key or not entity.get("apartmentId"):
        return False
    path = shared_data.cache_path(reconstruction.FACT_FILE)
    try:
        old = reconstruction._read(str(path), reconstruction._stamp(path))["records"].get(key) or {}
    except (OSError, ValueError, TypeError):
        return False
    checked = reconstruction._date(old.get("checkedAt"))
    if checked and 0 <= (dt.date.today() - checked).days < 30 and old.get("status") in ("ok", "no_records") and not old.get("lastError"):
        return False
    with _LOCK:
        previous = _JOBS.get(key)
        if previous and not previous[0].done():
            return True
        if time.monotonic() < _BLOCKED_UNTIL or (previous and time.monotonic() - previous[1] < 60):
            return False
        if sum(not job.done() for job, _ in _JOBS.values()) >= 20:
            return False
        def run():
            global _BLOCKED_UNTIL
            try:
                result = collect([entity])
                if result["stoppedCode"]:
                    _BLOCKED_UNTIL = time.monotonic() + 900
            except (OSError, ValueError):
                # Record a terminal state, including local persistence failures.
                import logging
                logging.getLogger(__name__).exception("building register collection failed for parcel %s", key)
        for expired, (job, when) in list(_JOBS.items()):
            if job.done() and time.monotonic() - when > 900:
                del _JOBS[expired]
        _JOBS[key] = (_POOL.submit(run), time.monotonic())
    return True


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save_record(key, entry):
    shared_data.require_writer()
    path = shared_data.cache_path(reconstruction.FACT_FILE)
    with store.exclusive_file_lock(path):
        # A malformed existing file must never be replaced with an empty store.
        data = json.loads(path.read_text()) if path.exists() else {"version": 1, "records": {}}
        if not isinstance(data.get("records"), dict):
            raise ValueError("invalid building register records")
        previous = data["records"].get(key, {})
        if entry.get("status") in ("connection_error", "access_denied") and previous.get("snapshot"):
            entry = {**previous, "lastError": {k: v for k, v in entry.items() if k != "snapshot"}}
        elif entry.get("status") == "no_records" and previous.get("snapshot", {}).get("records"):
            entry = {**previous, "lastError": {"status": "empty_after_success", "checkedAt": _now()}}
        data["records"][key] = entry
        data["updatedAt"] = _now()
        store.write_json_atomically(path, data)


def collect(entities, *, refresh=False, fetcher=None):
    shared_data.require_writer()
    fetcher = fetcher or building_hub.fetch_recap_records
    path = shared_data.cache_path(reconstruction.FACT_FILE)
    data = json.loads(path.read_text()) if path.exists() else {"records": {}}
    stats = {"startedAt": _now(), "total": len(entities), "processed": 0, "success": 0,
             "usable": 0, "partial": 0, "unmatched": 0,
             "noRecords": 0, "failed": 0, "reused": 0, "identityMissing": 0, "unprocessed": 0,
             "requests": 0, "stoppedCode": None}
    seen = set()
    for entity in entities:
        key, parcel = reconstruction.parcel_key(entity), reconstruction.parcel(entity)
        if not key:
            stats["identityMissing"] += 1
            stats["processed"] += 1
            continue
        old = data.get("records", {}).get(key) or {}
        checked = reconstruction._date(old.get("checkedAt"))
        recent = checked and 0 <= (dt.date.today() - checked).days < 30
        if key in seen or (not refresh and recent and old.get("status") in ("ok", "no_records") and not old.get("lastError")):
            stats["reused"] += 1
            fact_status = reconstruction.profile(entity, old).get("status")
            stats["usable" if fact_status == "ready" else "partial" if fact_status == "partial" else "unmatched"] += 1
            stats["processed"] += 1
            continue
        seen.add(key)
        try:
            for attempt in range(2):
                stats["requests"] += 1
                try:
                    snapshot = fetcher(parcel["sigunguCd"], parcel["bjdongCd"], parcel["bun"], parcel["ji"], plat_gb_cd=parcel["platGbCd"])
                    break
                except building_hub.BuildingHubError as exc:
                    if exc.code != "connection_error" or attempt:
                        raise
                    time.sleep(0.5)
            state = "ok" if snapshot["records"] else "no_records"
            entry = {"status": state, "checkedAt": _now(), "snapshot": snapshot}
            stats["success" if state == "ok" else "noRecords"] += 1
            fact_status = reconstruction.profile(entity, entry).get("status")
            stats["usable" if fact_status == "ready" else "partial" if fact_status == "partial" else "unmatched"] += 1
        except building_hub.BuildingHubError as exc:
            stopped = exc.code in STOP_CODES
            entry = {"status": "access_denied" if stopped else "connection_error",
                     "checkedAt": _now(), "errorCode": exc.code}
            stats["failed"] += 1
            if stopped:
                stats["stoppedCode"] = exc.code
        save_record(key, entry)
        data.setdefault("records", {})[key] = entry
        stats["processed"] += 1
        if stats["stoppedCode"]:
            break
    stats["unprocessed"] = stats["total"] - stats["processed"]
    stats["finishedAt"] = _now()
    # Collection results contain counts only, never scores or user inputs.
    run_path = shared_data.cache_path("building_register_last_run.json")
    with store.exclusive_file_lock(run_path):
        store.write_json_atomically(run_path, stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="")
    parser.add_argument("--district", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.name:
        parser.error("--name 또는 --all을 지정하세요.")
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    import real_estate_search
    entities = [e for e in real_estate_search._search_entities()
                if not e.get("aggregate") and e.get("apartmentId")
                and (not args.district or e.get("district") == args.district)
                and (not args.name or any(args.name in name for name in [e.get("name", ""), *(e.get("aliases") or [])]))]
    selected = entities[:args.limit]
    if args.dry_run:
        print(json.dumps({"matched": len(entities), "selected": len(selected),
                          "identityMissing": sum(not reconstruction.parcel_key(e) for e in selected)}, ensure_ascii=False))
        return
    result = collect(selected, refresh=args.refresh)
    result["outsideLimit"] = max(0, len(entities) - len(selected))
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result["failed"] or result["unprocessed"] else 0)


if __name__ == "__main__":
    main()
