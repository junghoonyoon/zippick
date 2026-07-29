"""입주물량 보정계수를 실제 준공 실적으로 산출한다.

왜 필요한가. `supply_forecast`의 근거인 청약홈 `공급규모`는 일반·특별공급
세대수다. 재건축·재개발 단지의 조합원 분양분과 청약홈에 올라오지 않는
공급이 빠져서, 그대로 쓰면 입주물량이 실제보다 적게 잡힌다.

어떻게 구하는가. 한국부동산원 공동주택 단지 목록에는 단지별 `세대수`와
`사용승인일`이 있다. 사용승인일이 곧 준공이므로 이걸 연도별로 합치면
실제 준공 세대수가 나온다. 같은 기간 청약홈 분양 집계와 나누면 계수가 된다.

    보정계수 = 실제 준공 세대수 ÷ 같은 시기 청약홈 분양 세대수

주의할 점이 두 가지 있다.

첫째, 청약홈 API 데이터는 2022년 이전이 매우 부실하다(2021년 121건).
그 구간을 넣으면 계수가 조합원 비율이 아니라 데이터 결측률이 된다.
그래서 2023년 이후만 쓴다.

둘째, 지역별 계수는 쓰지 않는다. 분양 시점의 `입주예정월`과 실제
`사용승인일`은 지연 때문에 어긋나고, 지역을 좁힐수록 이 시차가 계수를
망가뜨린다. 실제로 광명시 0.04, 수원팔달구 4.48처럼 말이 안 되는 값이 나온다.
전국 지역별 중앙값 하나만 쓴다.

실행:
    PYTHONPATH=pipeline python3 pipeline/supply_calibration.py
"""

import argparse
import collections
import csv
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEOUL_MASTER = ROOT / "data" / "서울시_공동주택_단지_목록_한국부동산원_20250918.csv"
GYEONGGI_MASTER = ROOT / "data" / "경기도_아파트_단지_목록_한국부동산원_20250918.csv"
SUPPLY_PATH = ROOT / "data" / "입주예정_전국.csv"

# 청약홈 데이터가 신뢰할 만한 구간. 그 이전은 결측이 심하다.
CALIBRATION_YEARS = (2023, 2024)
# 지역별 계수를 계산할 때 이 정도 표본은 있어야 의미가 있다.
MIN_REGION_HOUSEHOLDS = 1500


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _region_of(row):
    if row.get("자치구"):
        return row["자치구"].strip()
    city = (row.get("시군구") or "").strip()
    district = (row.get("일반구") or "").strip()
    if district and city.endswith("시"):
        return f"{city[:-1]}{district}"
    return city


def completed_by_region_year(paths=None):
    """사용승인일 기준 실제 준공 세대수. 조합원 분양분이 모두 포함된다."""
    paths = paths or [SEOUL_MASTER, GYEONGGI_MASTER]
    totals = collections.Counter()
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if "아파트" not in (row.get("단지종류명") or ""):
                    continue
                households = _digits(row.get("세대수"))
                approved = _digits(row.get("사용승인일"))
                region = _region_of(row)
                if not households or len(approved) < 4 or not region:
                    continue
                totals[(region, int(approved[:4]))] += int(households)
    return totals


def offered_by_region_year(path=None):
    """청약홈 분양 세대수. 일반·특별공급만 잡힌다."""
    path = Path(path or SUPPLY_PATH)
    totals = collections.Counter()
    if not path.exists():
        return totals
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            region = (row.get("자치구") or row.get("시군구") or "").strip()
            month = str(row.get("입주예정월") or "")
            households = _digits(row.get("세대수"))
            if region and len(month) >= 4 and households:
                totals[(region, int(month[:4]))] += int(households)
    return totals


def calibrate(years=CALIBRATION_YEARS, completed=None, offered=None):
    completed = completed if completed is not None else completed_by_region_year()
    offered = offered if offered is not None else offered_by_region_year()

    regions = {region for region, _year in offered}
    ratios = []
    detail = []
    for region in regions:
        built = sum(completed.get((region, y), 0) for y in years)
        sold = sum(offered.get((region, y), 0) for y in years)
        if sold < MIN_REGION_HOUSEHOLDS or built <= 0:
            continue
        ratios.append(built / sold)
        detail.append({"region": region, "completed": built, "offered": sold,
                       "ratio": built / sold})

    # 준공 자료는 서울·경기만 있다. 분양 쪽을 전국으로 두고 나누면 분모가
    # 커져서 계수가 1 밑으로 내려간다. 같은 지역 집합에서만 비교한다.
    covered = {region for region, _year in completed}
    total_built = sum(
        v for (region, y), v in completed.items() if y in years and region in covered
    )
    total_sold = sum(
        v for (region, y), v in offered.items() if y in years and region in covered
    )
    detail.sort(key=lambda d: -d["ratio"])
    return {
        "years": list(years),
        "regionCount": len(ratios),
        "median": round(statistics.median(ratios), 2) if ratios else None,
        "mean": round(statistics.fmean(ratios), 2) if ratios else None,
        "aggregate": round(total_built / total_sold, 2) if total_sold else None,
        "totalCompleted": total_built,
        "totalOffered": total_sold,
        "detail": detail,
    }


def main():
    parser = argparse.ArgumentParser(description="입주물량 보정계수 산출")
    parser.add_argument("--show", type=int, default=6, help="상·하위 몇 개 지역을 볼지")
    args = parser.parse_args()

    result = calibrate()
    if not result["median"]:
        print("계산에 쓸 표본이 부족합니다.")
        return 1

    print(f"기준 연도 {result['years']}")
    print(f"실제 준공 {result['totalCompleted']:,}세대 / 청약홈 분양 {result['totalOffered']:,}세대")
    print(f"합계 기준 계수 {result['aggregate']}")
    print(f"지역 {result['regionCount']}곳 · 중앙값 {result['median']} · 평균 {result['mean']}")
    print()
    print("중앙값을 쓰는 이유: 평균은 재개발이 몰린 소수 지역에 끌려간다.")
    print()
    detail = result["detail"]
    for row in detail[: args.show]:
        print(f"  {row['region']:12} {row['completed']:>8,} / {row['offered']:>8,} = {row['ratio']:.2f}")
    print("  ...")
    for row in detail[-args.show:]:
        print(f"  {row['region']:12} {row['completed']:>8,} / {row['offered']:>8,} = {row['ratio']:.2f}")
    print()
    print("지역별 편차가 큰 것은 조합원 비율 차이만이 아니라 입주예정월과")
    print("실제 사용승인일의 시차 때문이다. 그래서 지역 계수는 쓰지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
