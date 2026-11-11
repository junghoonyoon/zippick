"""Import independently checked public planning facts into the shared primary.

This is a manual evidence import, not an automatic parcel or plan collector.
Every input record must include the apartment identity, 법정동 code and the
official reference needed by apartment_reconstruction._reference.
"""
import argparse
import datetime as dt
import json

import apartment_reconstruction as reconstruction
import persistent_json_store as store
import shared_data


def import_verified(records, *, day=None):
    shared_data.require_writer()
    day = day or dt.date.today()
    if not isinstance(records, dict) or not records:
        raise ValueError("no planning records")
    for key, item in records.items():
        if not isinstance(item, dict):
            raise ValueError("invalid planning record")
        entity = item.get("identity") or {}
        if not isinstance(entity, dict) or str(entity.get("apartmentId")) != str(key):
            raise ValueError("apartment identity mismatch")
        if not reconstruction._reference(entity, item, day):
            raise ValueError("unverified parcel reference")
    path = shared_data.cache_path(reconstruction.PLANNING_FILE)
    with store.exclusive_file_lock(path):
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "records": {}}
        if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
            raise ValueError("invalid planning records")
        merged = dict(data["records"])
        success = reused = 0
        for key, item in records.items():
            previous = merged.get(key)
            if previous is not None and not isinstance(previous, dict):
                raise ValueError("invalid existing planning record")
            previous = previous or {}
            if previous:
                identity = previous.get("identity") or {}
                if not isinstance(identity, dict) or any(str(identity.get(k)) != str(item["identity"].get(k))
                        for k in ("apartmentId", "district", "legalDong", "jibun")):
                    raise ValueError("existing apartment identity mismatch")
                old = previous.get("ordinanceReference") or {}
                if old and (not isinstance(old, dict) or not reconstruction._reference(item["identity"], previous, day, allow_expired=True)):
                    raise ValueError("invalid existing parcel reference")
                if reconstruction._date(old.get("checkedAt")) and reconstruction._date(old.get("checkedAt")) > reconstruction._date(item["ordinanceReference"]["checkedAt"]):
                    reused += 1
                    continue
            merged[key] = {**previous, **item}
            merged[key].pop("lastError", None)
            success += 1
        if success:
            data["records"] = merged
            data["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
            store.write_json_atomically(path, data)
    return {"total": len(records), "processed": len(records), "success": success, "reused": reused,
            "failed": 0, "unprocessed": 0, "updatedAt": data.get("updatedAt")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON object containing independently verified records")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as source:
        records = json.load(source)
    print(json.dumps(import_verified(records), ensure_ascii=False))


if __name__ == "__main__":
    main()
