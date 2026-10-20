"""Verified parcel changes between the apartment register and transaction feed.

Keep the original identity intact. Never infer a parcel change from a name alone.
Every mapping is tied to a source id, district code, legal dong and old parcel.
"""
import json
from functools import lru_cache
from pathlib import Path

import apartment_identity

PATH = Path(__file__).resolve().parents[1] / "data" / "apartment_transaction_addresses.json"


@lru_cache(maxsize=1)
def entries():
    return json.loads(PATH.read_text(encoding="utf-8")).get("entries", [])


def expand_source_rows(rows):
    expanded = []
    for row in rows:
        expanded.append(row)
        for entry in entries():
            if not entry.get("sourceUrl") or not entry.get("verifiedAt"):
                continue
            if str(row.get("단지고유번호") or "") != entry.get("apartmentId"):
                continue
            code = str(row.get("필지고유번호") or row.get("법정동코드") or row.get("lawdCd") or "")[:5]
            if code != entry.get("lawdCd") or row.get("법정동") != entry.get("legalDong"):
                continue
            if apartment_identity.parcel_key(row.get("지번")) != apartment_identity.parcel_key(entry.get("sourceJibun")):
                continue
            if not entry.get("transactionJibun"):
                continue
            expanded.append({
                **row,
                "지번": entry["transactionJibun"],
                "transactionAddressCorrection": dict(entry),
            })
    return expanded
