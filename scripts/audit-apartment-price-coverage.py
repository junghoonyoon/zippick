#!/usr/bin/env python3
"""Read-only audit of every search entity against locally stored MOLIT trades.

No network requests or guessed prices. Report unmatched parcels for evidence review.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import apartment_identity as identity
import molit_transactions as molit
import real_estate_search as search


def audit():
    months = set(molit._deal_months(24))
    by_address, by_name = defaultdict(list), defaultdict(set)
    file_count = 0
    for path in molit.TRANSACTION_CACHE_DIR.glob("*.json"):
        # 매매와 분양권 모두 공식 실거래다. 분양권 캐시는 `presale_` 접두사를
        # 쓰므로, 이를 빼면 신축 단지가 거래 없음으로 잘못 집계된다.
        match = re.fullmatch(r"(?:presale_)?(\d{5})_(\d{6})", path.stem)
        if not match or match[2] not in months:
            continue
        payload = json.loads(path.read_text())
        file_count += 1
        for trade in payload.get("items", []):
            if not molit._is_market_transaction(trade):
                continue
            dong = molit._legal_dong_leaf(trade.get("legalDong"))
            parcel = identity.parcel_key(trade.get("jibun"))
            by_address[(match[1], dong, parcel)].append(trade)
            by_name[(match[1], dong, search.compact(trade.get("apartment")))].add(parcel)
    results = []
    for entity in search.APARTMENT_MASTER:
        if entity.get("aggregate") or not entity.get("district"):
            continue
        # 카드와 리포트가 쓰는 정확히 같은 해석기를 사용한다. 특히 1·2단지
        # 공통 거래처럼 검수한 범위가 있으면, 단순 단지명 색인으로 누락시키지
        # 않는다.
        sources = molit.source_rows_for_entity(entity, entity.get("district"))
        matched, other_parcels = [], set()
        for row in sources:
            code = molit._row_lawd_cd(row)
            dong = molit._legal_dong_leaf(molit._source_legal_dong(row))
            parcel = identity.parcel_key(molit._source_jibun(row))
            matched.extend(t for t in by_address.get((code, dong, parcel), [])
                           if molit._matches_transaction(row, t, entity["name"]))
            for name in [entity["name"], *molit._row_name_values(row)]:
                other_parcels.update(by_name.get((code, dong, search.compact(name)), set()))
        matched = molit._dedupe_transactions(matched)
        state = "available" if matched else "address_review" if other_parcels else "no_cached_trades"
        results.append({
            "name": entity["name"], "apartmentId": entity.get("apartmentId", ""),
            "region": entity.get("district"), "legalDong": entity.get("legalDong"),
            "jibun": entity.get("jibun"), "status": state,
            "transactionCount": len(matched),
            "latestDealDate": matched[0].get("dealDate") if matched else None,
            "otherTransactionParcels": sorted(other_parcels) if not matched else [],
        })
    return {
        "scope": "검색 마스터 전체·로컬 매매 캐시 최근 24개월; 미수집 지역과 분양권은 가격 미확보로 집계",
        "cachedMonthCount": file_count, "checkedEntityCount": len(results),
        "counts": dict(Counter(row["status"] for row in results)), "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit()
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
