"""분양 예정 단지로 지역별 입주 시기와 물량을 집계한다.

입주물량은 전세에 먼저 오고 매매가 따라간다. 그래서 매수 시점 판단에는
`지금 가격`만큼 `언제 공급이 몰리는가`가 중요하다.

집계 근거는 청약홈 분양정보의 `공급규모`인데, 이 값은 일반·특별공급
세대수라 재건축 조합원 분양분이 빠진다. 그대로 쓰면 실제보다 적게 잡히므로
실제 준공 실적으로 구한 보정계수를 곱한다(supply_calibration.py 참고).

두 숫자를 모두 들고 다닌다. `offeredHouseholds`는 청약홈에 공고된 원본이고
`totalHouseholds`는 보정 후 추정치다. 리포트에서 둘을 함께 보여줘야
독자가 어디까지가 사실이고 어디부터가 추정인지 구분할 수 있다.

보정을 해도 지역주택조합, 오피스텔, 공공임대는 여전히 빠진다.
그래서 `공급 없음`이라고 단정하면 안 된다.
"""

import csv
import datetime
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 전국 수집본이 있으면 그걸 먼저 쓴다. 없으면 서울·경기 보강본으로 버틴다.
# 두 파일은 컬럼이 같아서 같은 로더로 읽힌다.
NATIONWIDE_PATH = ROOT / "data" / "입주예정_전국.csv"
SUPPLEMENT_PATH = ROOT / "data" / "분양권_입주예정_아파트_보강.csv"


def default_paths():
    return [path for path in (NATIONWIDE_PATH, SUPPLEMENT_PATH) if path.exists()]

# 이 규모를 넘어서면 전세 시장에 눈에 띄는 영향이 생긴다고 본다.
# 절대 기준이 아니라 리포트 문구의 강약을 가르는 임계값이다.
HEAVY_HOUSEHOLDS = 3000
NOTABLE_HOUSEHOLDS = 1000

SOURCE_LABEL = "청약홈 분양정보(한국부동산원) 기준 입주 예정"
SOURCE_URL = "https://www.data.go.kr/data/15098547/openapi.do"

# 청약홈 공급규모는 일반·특별공급 세대수라 재건축 조합원 분양분이 빠진다.
# 한국부동산원 단지 목록의 사용승인일·세대수로 실제 준공 실적을 집계해
# 2023~2024년 서울·경기를 비교한 결과, 지역별 계수 중앙값이 1.42였다.
# (합계 기준 1.76, 평균 1.56. 재개발이 몰린 소수 지역이 평균을 끌어올려
#  중앙값을 쓴다.) 산출 과정은 supply_calibration.py 에 있다.
#
# 지역별 계수는 쓰지 않는다. 분양 시점의 입주예정월과 실제 사용승인일이
# 지연으로 어긋나서 지역을 좁힐수록 계수가 망가진다. 실제로 광명시 0.04,
# 수원팔달구 4.48처럼 말이 안 되는 값이 나온다.
ADJUSTMENT_FACTOR = 1.42
ADJUSTMENT_BASIS = (
    "2023~2024년 서울·경기 실제 준공 실적과 청약홈 분양 집계를 비교해 구한 "
    "전국 공통 계수 1.42를 곱했습니다"
)

_CACHE = {}


def _compact(value):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def _half_label(year, month):
    return f"{year}년 {'상반기' if month <= 6 else '하반기'}"


def _half_key(year, month):
    return year * 2 + (0 if month <= 6 else 1)


def _parse_month(value):
    match = re.match(r"(\d{4})-(\d{1,2})", str(value or "").strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return (year, month) if 1 <= month <= 12 else None


def _region_key(row):
    """CSV 한 행이 속한 시군구 이름. 서울은 자치구, 경기는 시군구를 쓴다."""
    return str(row.get("자치구") or row.get("시군구") or "").strip()


def _load_one(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            month = _parse_month(row.get("입주예정월"))
            households = re.sub(r"\D", "", str(row.get("세대수") or ""))
            region = _region_key(row)
            if not month or not households or not region:
                continue
            rows.append(
                {
                    "region": region,
                    "sido": str(row.get("시도") or "").strip(),
                    "legalDong": str(row.get("법정동") or "").strip(),
                    "name": str(row.get("대표단지명") or "").strip(),
                    "year": month[0],
                    "month": month[1],
                    "households": int(households),
                }
            )
    return rows


def load_rows(path=None):
    """입주예정월과 세대수가 모두 있는 행만 남긴다.

    전국본과 보강본을 함께 읽을 때 같은 단지가 두 번 세어지면 물량이
    부풀려진다. 단지명·지역·입주월이 같으면 한 건으로 본다.
    """
    paths = [path] if path else default_paths()
    seen = set()
    merged = []
    for one in paths:
        for row in _load_one(one):
            key = (_compact(row["name"]), _compact(row["region"]), row["year"], row["month"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def _rows(path=None):
    key = str(path) if path else "__default__"
    if key not in _CACHE:
        _CACHE[key] = load_rows(path)
    return _CACHE[key]


def _region_matches(row_region, region):
    """`남양주시` 검색에 `양주시` 물량이 섞이면 안 된다.

    budget_candidates 와 같은 원칙을 쓴다. 짧은 쪽이 긴 쪽의 접두일 때만
    상위-하위 관계로 인정하고, 그 외 부분 문자열 일치는 버린다.
    """
    left, right = _compact(row_region), _compact(region)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 2:
        return False
    return longer.startswith(shorter)


def outlook(region, today=None, horizon_months=36, path=None):
    """한 지역의 향후 입주 물량 전망.

    반환값은 화면·리포트가 그대로 쓸 수 있는 형태로 맞춘다. 데이터가
    없을 때 0으로 채우지 않고 status 로 구분한다. 없는 것과 0인 것은 다르다.
    """
    today = today or datetime.date.today()
    matched = [r for r in _rows(path) if _region_matches(r["region"], region)]
    if not matched:
        return {
            "status": "unavailable",
            "region": region,
            "reason": "이 지역의 분양 예정 자료가 아직 수집되지 않았습니다.",
            "source": SOURCE_LABEL,
            "sourceUrl": SOURCE_URL,
        }

    start = _half_key(today.year, today.month)
    limit = today.year * 12 + today.month + horizon_months
    buckets = {}
    complexes = []
    for row in matched:
        if row["year"] * 12 + row["month"] > limit:
            continue
        key = _half_key(row["year"], row["month"])
        if key < start:
            continue
        label = _half_label(row["year"], row["month"])
        bucket = buckets.setdefault(
            key,
            {"label": label, "households": 0, "offeredHouseholds": 0, "count": 0},
        )
        bucket["offeredHouseholds"] += row["households"]
        bucket["households"] += round(row["households"] * ADJUSTMENT_FACTOR)
        bucket["count"] += 1
        complexes.append(row)

    if not buckets:
        return {
            "status": "none",
            "region": region,
            "reason": (
                f"향후 {horizon_months // 12}년 안에 입주 예정으로 확인된 분양 단지가 "
                "없습니다. 다만 조합원 분양분은 이 집계에 잡히지 않습니다."
            ),
            "source": SOURCE_LABEL,
            "sourceUrl": SOURCE_URL,
        }

    timeline = [buckets[key] for key in sorted(buckets)]
    total = sum(b["households"] for b in timeline)
    offered_total = sum(b["offeredHouseholds"] for b in timeline)
    peak = max(timeline, key=lambda b: b["households"])
    # 한 반기에 몰리는 양과 기간 전체 누적을 함께 본다. 반기별로는 나뉘어
    # 보여도 3년 내내 이어지면 전세 시장에는 똑같이 부담이 된다.
    level = (
        "heavy"
        if peak["households"] >= HEAVY_HOUSEHOLDS or total >= HEAVY_HOUSEHOLDS * 2
        else "notable"
        if peak["households"] >= NOTABLE_HOUSEHOLDS or total >= NOTABLE_HOUSEHOLDS * 2
        else "light"
    )
    return {
        "status": "ok",
        "region": region,
        "level": level,
        "totalHouseholds": total,
        "offeredHouseholds": offered_total,
        "adjustmentFactor": ADJUSTMENT_FACTOR,
        "complexCount": len(complexes),
        "horizonMonths": horizon_months,
        "timeline": timeline,
        "peak": peak,
        "basis": "분양 물량에 조합원 분양분 보정계수를 반영한 추정치",
        "source": SOURCE_LABEL,
        "sourceUrl": SOURCE_URL,
    }


def sentence(result):
    """리포트와 후보 카드에 그대로 넣을 한 문단.

    숫자만 던지지 않고 `그래서 무엇을 해야 하는지`까지 붙인다.
    """
    status = (result or {}).get("status")
    if status == "unavailable":
        return result.get("reason", "")
    if status == "none":
        return result.get("reason", "")

    region = result["region"]
    peak = result["peak"]
    total = result["totalHouseholds"]
    head = (
        f"{region}에 향후 {result['horizonMonths'] // 12}년간 "
        f"{total:,}세대가 입주할 예정입니다. "
        f"{peak['label']}에 {peak['households']:,}세대로 가장 몰립니다."
    )
    if result["level"] == "heavy":
        tail = (
            " 이 정도 물량이 들어오면 그 시기 전세는 약세로 가기 쉽습니다. "
            "전세를 끼고 매수하실 계획이라면 만기가 "
            f"{peak['label']}와 겹치지 않도록 잡으시고, 실거주라면 그 시기에 "
            "오히려 협상 여지가 커질 수 있으니 매수 시점을 늦추는 것도 "
            "검토해 보세요."
        )
    elif result["level"] == "notable":
        tail = (
            " 시장을 뒤흔들 규모는 아니지만 전세 재계약 시점이 겹치면 "
            "협상력이 떨어질 수 있으니 만기 시점을 확인해 두세요."
        )
    else:
        tail = " 물량이 많지 않아 공급이 가격을 누를 가능성은 낮아 보입니다."
    warn = (
        f" 청약홈에 공고된 분양 물량은 {result['offeredHouseholds']:,}세대인데, "
        "여기에는 재건축 조합원 분양분이 빠져 있습니다. 그래서 "
        f"{ADJUSTMENT_BASIS}. 지역과 사업 방식에 따라 실제와 차이가 날 수 있습니다."
    )
    return head + tail + warn


def summary_rows(result, limit=6):
    """막대그래프나 표로 그릴 때 쓰는 단순 배열."""
    if (result or {}).get("status") != "ok":
        return []
    return [
        {
            "label": bucket["label"],
            "households": bucket["households"],
            "complexCount": bucket["count"],
        }
        for bucket in result["timeline"][:limit]
    ]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="지역별 입주 예정 물량 확인")
    parser.add_argument("region", help="예: 노원구, 남양주시, 수원영통구")
    parser.add_argument("--horizon-months", type=int, default=36)
    args = parser.parse_args()

    result = outlook(args.region, horizon_months=args.horizon_months)
    print(sentence(result))
    for row in summary_rows(result, limit=8):
        bar = "█" * max(1, row["households"] // 200)
        print(f"  {row['label']:12} {row['households']:>7,}세대 {bar}")


if __name__ == "__main__":
    main()
