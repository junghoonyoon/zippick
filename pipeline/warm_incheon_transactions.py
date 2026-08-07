#!/usr/bin/env python3
"""인천 실거래 캐시 워밍업.

단지 목록(data/인천광역시_아파트_단지_목록_...csv)을 붙여도 후보가 나오지 않는다.
후보 판정이 `최근 실거래가 있는 단지`를 요구하는데, 인천 실거래 캐시가
한 건도 없기 때문이다(캐시 분포: 서울 11xxx 1,730개 · 경기 41xxx 2,531개 · 인천 28xxx 0개).

이 스크립트는 인천 자치구별로 최근 N개월 실거래를 받아 캐시에 채운다.
국토교통부 API 키와 apis.data.go.kr 접근이 필요하므로 운영 환경에서 돌려야 한다.

    export MOLIT_APARTMENT_TRADE_API_KEY=...
    export MOLIT_APARTMENT_RENT_API_KEY=...
    python3 pipeline/warm_incheon_transactions.py            # 최근 6개월
    python3 pipeline/warm_incheon_transactions.py --months 12
    python3 pipeline/warm_incheon_transactions.py --check    # 캐시 현황만 출력
"""

import argparse
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import molit_transactions as molit  # noqa: E402

# 인천광역시 자치구 법정동코드 앞 5자리.
INCHEON_LAWD_CODES = {
    "28110": "중구",
    "28140": "동구",
    "28177": "미추홀구",
    "28185": "연수구",
    "28200": "남동구",
    "28237": "부평구",
    "28245": "계양구",
    "28260": "서구",
    "28710": "강화군",
    "28720": "옹진군",
}


def recent_months(count):
    today = datetime.date.today().replace(day=1)
    months = []
    for step in range(count):
        month = today
        for _ in range(step):
            month = (month - datetime.timedelta(days=1)).replace(day=1)
        months.append(month.strftime("%Y%m"))
    return months


def cached_count():
    cache_dir = getattr(molit, "TRANSACTION_CACHE_DIR", None)
    if not cache_dir or not Path(cache_dir).exists():
        return {}
    counts = {}
    for path in Path(cache_dir).glob("*.json"):
        for code in INCHEON_LAWD_CODES:
            if code in path.name:
                counts[code] = counts.get(code, 0) + 1
    return counts


def check():
    counts = cached_count()
    print("인천 실거래 캐시 현황")
    total = 0
    for code, name in INCHEON_LAWD_CODES.items():
        n = counts.get(code, 0)
        total += n
        print(f"  {code} {name:<8} {n:>4}개")
    print(f"  합계 {total}개")
    if not total:
        print("\n캐시가 비어 있습니다. 키를 설정하고 --check 없이 실행하세요.")
    return total


def warm(months):
    if not config.MOLIT_APARTMENT_TRADE_API_KEY:
        raise SystemExit(
            "MOLIT_APARTMENT_TRADE_API_KEY가 없습니다. 키를 설정하고 다시 실행하세요."
        )
    targets = recent_months(months)
    print(f"인천 {len(INCHEON_LAWD_CODES)}개 구 × {len(targets)}개월 = "
          f"{len(INCHEON_LAWD_CODES) * len(targets)}회 호출", flush=True)

    filled = 0
    failed = []
    for code, name in INCHEON_LAWD_CODES.items():
        got = 0
        for month in targets:
            try:
                rows = molit.fetch_month(code, month)
                got += len(rows or [])
            except Exception as exc:
                failed.append((code, month, f"{type(exc).__name__}: {exc}"))
        filled += got
        print(f"  {code} {name:<8} 거래 {got:>5}건", flush=True)

    print(f"\n총 {filled:,}건 캐시에 채웠습니다.")
    if failed:
        print(f"실패 {len(failed)}건 (앞 5건):")
        for code, month, error in failed[:5]:
            print(f"  {code} {month} — {error}")
    return filled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=config.MOLIT_TRANSACTION_LOOKBACK_MONTHS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
        return
    warm(args.months)
    check()


if __name__ == "__main__":
    main()
