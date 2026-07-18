#!/usr/bin/env python3
"""국토부 실거래가 공개시스템 CSV를 예산 후보용 가격대로 집계한다."""
import argparse
import csv
import datetime
import statistics
from collections import defaultdict
from pathlib import Path

import real_estate_search


SOURCE_URL = "https://rt.molit.go.kr/pt/xls/xls.do?mobileAt=v"


def _read_lines(path):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding).splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 문자 인코딩을 확인하지 못했어요.")


def _data_rows(path):
    lines = _read_lines(path)
    header_index = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith('"NO"')),
        None,
    )
    if header_index is None:
        raise ValueError("국토부 CSV 헤더를 찾지 못했어요.")
    return list(csv.DictReader(lines[header_index:]))


def _number(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _district(value):
    parts = str(value or "").split()
    return parts[1] if len(parts) >= 2 else str(value or "").strip()


def _deal_date(row):
    year_month = str(row.get("계약년월") or "").strip()
    day = str(row.get("계약일") or "").strip()
    if len(year_month) != 6 or not day.isdigit():
        return ""
    return f"{year_month[:4]}-{year_month[4:]}-{int(day):02d}"


def _is_market_transaction(row):
    deal_type = str(
        row.get("거래유형")
        or row.get("거래 유형")
        or row.get("dealingGbn")
        or ""
    ).replace(" ", "").strip()
    cancellation = str(row.get("해제사유발생일") or row.get("cdealDay") or "").strip()
    return deal_type != "직거래" and cancellation in {"", "-"}


def _percentile(values, ratio):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = round((len(ordered) - 1) * ratio)
    return ordered[max(0, min(index, len(ordered) - 1))]


def build_price_bands(source_path, min_transactions=3, min_area=50.0, max_area=60.0, max_price_eok=10.0):
    groups = defaultdict(list)
    raw_count = 0
    for row in _data_rows(source_path):
        raw_count += 1
        name = str(row.get("단지명") or "").strip()
        area = _number(row.get("전용면적(㎡)"))
        price_manwon = _number(row.get("거래금액(만원)"))
        if not real_estate_search._is_usable_apartment_name(name):
            continue
        if not _is_market_transaction(row):
            continue
        if not min_area <= area <= max_area:
            continue
        if price_manwon <= 0 or price_manwon > max_price_eok * 10000:
            continue
        district = _district(row.get("시군구"))
        legal_dong = str(row.get("법정동") or "").strip()
        jibun = str(row.get("지번") or "").strip()
        groups[(
            district,
            real_estate_search.compact(legal_dong),
            real_estate_search.compact(jibun),
            real_estate_search.compact(name),
        )].append({
            "name": name,
            "legalDong": legal_dong,
            "jibun": jibun,
            "area": area,
            "priceEok": price_manwon / 10000,
            "dealDate": _deal_date(row),
        })

    bands = []
    for (district, _, _, _), rows in groups.items():
        if len(rows) < min_transactions:
            continue
        prices = [row["priceEok"] for row in rows]
        areas = [row["area"] for row in rows]
        latest_row = max(
            (row for row in rows if row["dealDate"]),
            key=lambda row: row["dealDate"],
            default=None,
        )
        latest = latest_row["dealDate"] if latest_row else ""
        name = max((row["name"] for row in rows), key=len)
        bands.append({
            "name": name,
            "region": district,
            "legal_dong": rows[0]["legalDong"],
            "jibun": rows[0]["jibun"],
            "min_price_억": round(_percentile(prices, 0.1), 2),
            "mid_price_억": round(statistics.median(prices), 2),
            "average_price_억": round(statistics.mean(prices), 2),
            "max_price_억": round(_percentile(prices, 0.9), 2),
            "area_label": f"전용 {round(min(areas))}~{round(max(areas))}㎡",
            "updated_at": latest or datetime.date.today().isoformat(),
            "source_note": f"국토부 실거래 {len(rows)}건 · 10~90백분위",
            "price_source": "molit_csv",
            "market_transaction_only": "true",
            "transaction_count": len(rows),
            "latest_deal_date": latest,
            "latest_deal_price_억": round(latest_row["priceEok"], 2) if latest_row else "",
            "source_url": SOURCE_URL,
        })
    bands.sort(key=lambda row: (row["region"], row["mid_price_억"], row["name"]))
    return bands, raw_count


def write_price_bands(rows, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name", "region", "legal_dong", "jibun", "min_price_억", "mid_price_억", "average_price_억", "max_price_억",
        "area_label", "updated_at", "source_note", "price_source",
        "market_transaction_only",
        "transaction_count", "latest_deal_date", "latest_deal_price_억", "source_url",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="국토부 실거래가 공개시스템 CSV")
    parser.add_argument(
        "--output",
        default=str(real_estate_search.config.ROOT / "data" / "seoul_small_apartment_price_bands.csv"),
    )
    parser.add_argument("--min-transactions", type=int, default=3)
    args = parser.parse_args()
    rows, raw_count = build_price_bands(args.source, min_transactions=max(1, args.min_transactions))
    write_price_bands(rows, args.output)
    print(f"원본 {raw_count:,}건에서 가격대 {len(rows):,}개를 만들었습니다: {args.output}")


if __name__ == "__main__":
    main()
