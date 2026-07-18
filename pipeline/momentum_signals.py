"""후보 단지의 최근 가격·거래 흐름 지표.

과거 국토부 실거래 데이터로 계산한 시그널이며, 미래 수익률 예측이 아니다.
점수는 항상 근거 배지와 함께 노출한다. 거래 표본이 적은 단지는 점수를
계산하지 않고 '표본 부족'으로 표시한다.

점수 지표 4종
- priceMomentum     : 최근 6개월 vs 직전 6개월 ㎡당가 중앙값, 같은 평형대끼리 비교 (40점)
- turnover          : 최근 6개월 거래건수 vs 직전 6개월 (25점)
- districtRelative  : 구 세대수 상위 고정 단지군의 가격 흐름 중앙값 대비 (20점)
- recentPersistence : 최근 3개월 vs 직전 3개월 ㎡당가 중앙값, 같은 평형대끼리 비교 (15점)

가격 변화는 평형대(10㎡ 밴드)가 두 구간에 모두 있는 거래만으로 계산한다.
구간별 거래 평형 구성이 바뀌면(예: 직전엔 59㎡ 위주, 최근엔 84㎡ 위주)
평균 ㎡당가가 실제 시세와 무관하게 움직이는 것을 막기 위해서다.

직거래·해제 거래는 molit_transactions 소스 단계에서 제외되고, 여기서는
추가로 평형대 중앙값에서 ±30% 넘게 벗어난 거래(중개거래로 신고된
특수관계 거래·입력 오류 추정)를 점수 계산에서 제외한다.

전고점 회복률과 대장 단지 대비 가격 차이는 점수 밖의 참고 정보로만 제공한다.
"""
import datetime
import statistics

import config
import molit_transactions
import real_estate_search

LOOKBACK_MONTHS = config.MOLIT_SIGNAL_LOOKBACK_MONTHS
MIN_WINDOW_DEALS = config.SIGNAL_MIN_WINDOW_DEALS
MIN_TOTAL_DEALS = config.SIGNAL_MIN_TOTAL_DEALS
# v8은 중립 산식이 적용되지 않은 채 v7로 잘못 저장된 과거 캐시까지
# 명확히 무효화하기 위한 버전이다.
SCORE_FORMULA_VERSION = 8

# 결측 항목의 중립값. '정보 없음'을 0점(최악)으로 처리하면 비교군이 없는
# 구의 단지가 구조적으로 불리해지므로, 모르는 항목은 평균 수준으로 간주한다.
# 표본 부족 위험은 sampleConfidence 라벨과 점수 상한 규칙이 별도로 담당한다.
_NEUTRAL_VALUES = {
    "priceMomentum": 0.0,
    "turnover": 1.0,
    "districtRelative": 0.0,
    "recentPersistence": 0.0,
}
SURGE_RECENT3_PCT = 10.0  # 최근 3개월 상승률이 이 이상이면 '단기 급등 직후'로 경고

# 상승 패턴(점수 밖 참고 정보) 판정 기준.
# 월 2건 이상 거래된 '유효 월'의 전월 대비 변화만 사용하고,
# 유효 월 사이 간격이 2개월을 넘으면 그 구간 변화는 세지 않는다.
PATTERN_MIN_DEALS_PER_MONTH = 2
PATTERN_MAX_MONTH_GAP = 2
PATTERN_MIN_CHANGES = 3      # 이보다 적으면 패턴을 판정하지 않음
PATTERN_MAX_CHANGES = 6      # 최근 변화 6회까지만 반영
PATTERN_STEADY_SHARE = 0.7   # 상승(하락) 방향 일관성 기준
PATTERN_VOLATILE_MAD_PCT = 2.5  # 월간 변화율 MAD가 이 이상이면 '등락 반복'
TURNOVER_SMOOTHING = 3  # 라플라스 스무딩. 2건→4건(2.0배)이 20건→40건과 같은 점수를 받는 왜곡 방지
CONFIDENCE_HIGH_DEALS = 30   # 최근 12개월 창 거래 수 기준
CONFIDENCE_MEDIUM_DEALS = 12
AREA_BAND_SIZE = 10  # ㎡. 59↔84 같은 평형 혼합을 걸러내는 밴드 폭
BAND_MIN_DEALS_PER_SIDE = 2
OUTLIER_PCT = 0.30  # 평형대 중앙값 대비 이 비율을 넘게 벗어난 거래는 제외
OUTLIER_MIN_BAND_DEALS = 5  # 이 미만 표본의 밴드는 정상 거래 오폐기 위험이 커서 필터하지 않음
_DISTRICT_BENCHMARK_LIMIT = 12
_DISTRICT_BENCHMARK_MIN = 3
_DISTRICT_MOMENTUM_CACHE = {}

# 절대 스케일 정규화 경계. 가격·거래량의 실제 방향을 중심으로 점수를
# 계산하고, 전고점·대장 대비 가격은 점수 밖의 참고 정보로만 남긴다.
_SCALES = {
    "priceMomentum": (-10.0, 10.0),    # 최근 6개월 가격 변화
    "turnover": (0.5, 2.0),            # 최근/직전 6개월 거래량 배수
    "districtRelative": (-5.0, 5.0),   # 구 대표 단지군 중앙값 대비 가격 흐름
    "recentPersistence": (-5.0, 5.0),  # 최근 3개월 가격 흐름 지속성
}
_WEIGHTS = {
    "priceMomentum": 40,
    "turnover": 25,
    "districtRelative": 20,
    "recentPersistence": 15,
}
_COMPONENT_LABELS = {
    "priceMomentum": "최근 6개월 가격 변화",
    "turnover": "거래량 변화",
    "districtRelative": "같은 구 대표 단지 대비",
    "recentPersistence": "최근 3개월 지속성",
}
MAX_LATEST_DEAL_AGE_DAYS = 120
_DISTRICT_LEADER_INDEX = None
_DISTRICT_LEADER_CANDIDATE_LIMIT = 20

SIGNAL_NOTE = (
    "최근 가격·거래 흐름 점수는 국토부 실거래가 기반 최근 6개월 같은 평형대 가격 변화·"
    "거래량 변화·같은 구 대표 단지 대비·최근 3개월 지속성을 합산한 0~100점 지표입니다. "
    "저평가 여부나 미래 수익률을 의미하지 않습니다."
)


def _month_key(deal_date):
    return str(deal_date or "")[:7]


def _months_ago(months):
    today = datetime.date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        year -= 1
        month += 12
    return f"{year}-{month:02d}"


def _deal_age_days(value):
    try:
        deal_date = datetime.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.date.today() - deal_date).days)


def _ppsm(item):
    area = float(item.get("exclusiveArea") or 0)
    amount = float(item.get("dealAmountManwon") or 0)
    if area <= 0 or amount <= 0:
        return 0
    return amount / area


def _scaled(value, key):
    low, high = _SCALES[key]
    if value is None:
        return None
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _area_band(item):
    return int(float(item.get("exclusiveArea") or 0) // AREA_BAND_SIZE)


def _month_gap(earlier, later):
    try:
        earlier_year, earlier_month = int(str(earlier)[:4]), int(str(earlier)[5:7])
        later_year, later_month = int(str(later)[:4]), int(str(later)[5:7])
    except (TypeError, ValueError):
        return 99
    return (later_year - earlier_year) * 12 + (later_month - earlier_month)


def _rise_pattern(result, monthly, monthly_median, window_end):
    """월별 중앙값의 방향 일관성·변동성으로 상승 패턴을 판정한다.

    점수에는 반영하지 않는 참고 라벨이다. '안정적 상승이 좋다'는 가정이
    백테스트로 검증되기 전까지는 배점에 넣지 않는다.
    """
    valid_months = [
        month for month in sorted(monthly_median)
        if len(monthly.get(month) or []) >= PATTERN_MIN_DEALS_PER_MONTH and month <= window_end
    ]
    changes = []
    for previous, current_month in zip(valid_months, valid_months[1:]):
        if _month_gap(previous, current_month) > PATTERN_MAX_MONTH_GAP:
            continue
        base = monthly_median[previous]
        if base <= 0:
            continue
        changes.append((monthly_median[current_month] / base - 1) * 100)
    changes = changes[-PATTERN_MAX_CHANGES:]
    result["patternChangeCount"] = len(changes)
    result["patternUpCount"] = sum(1 for value in changes if value > 0)
    result["patternDownCount"] = sum(1 for value in changes if value < 0)
    if len(changes) < PATTERN_MIN_CHANGES:
        return
    center = statistics.median(changes)
    mad = statistics.median(abs(value - center) for value in changes)
    result["patternVolatilityPct"] = round(mad, 1)
    rise_share = result["patternUpCount"] / len(changes)
    fall_share = result["patternDownCount"] / len(changes)
    net = sum(changes)
    if result.get("isRecentSurge"):
        result["risePattern"] = "surge"
    elif rise_share >= PATTERN_STEADY_SHARE and net > 0 and mad <= PATTERN_VOLATILE_MAD_PCT:
        result["risePattern"] = "steady_rise"
    elif fall_share >= PATTERN_STEADY_SHARE and net < 0:
        result["risePattern"] = "steady_fall"
    elif mad >= PATTERN_VOLATILE_MAD_PCT:
        result["risePattern"] = "choppy"
    else:
        result["risePattern"] = "flat"


def _sample_confidence(result):
    """점수의 표본 신뢰도. 최근 12개월 창 거래 수와 평형 매칭 여부로 판정한다."""
    window_deals = int(result.get("recentDealCount") or 0) + int(result.get("priorDealCount") or 0)
    if window_deals >= CONFIDENCE_HIGH_DEALS and result.get("momentumBandMatched"):
        return "high"
    if window_deals >= CONFIDENCE_MEDIUM_DEALS:
        return "medium"
    return "low"


def _filter_price_outliers(deals):
    """평형대 중앙값에서 ±30% 넘게 벗어난 거래를 제외한다.

    '중개거래'로 신고됐어도 특수관계 거래나 입력 오류로 보이는 극단가가
    소표본 창의 중앙값과 월별 전고점을 끌어당기는 것을 막는다.
    표본 5건 미만인 밴드는 시세 기준 자체가 불안정해 필터하지 않는다.
    """
    bands = {}
    for item in deals:
        bands.setdefault(_area_band(item), []).append(item)
    kept, excluded = [], 0
    for band_items in bands.values():
        if len(band_items) < OUTLIER_MIN_BAND_DEALS:
            kept.extend(band_items)
            continue
        band_median = statistics.median(_ppsm(item) for item in band_items)
        if band_median <= 0:
            kept.extend(band_items)
            continue
        for item in band_items:
            if abs(_ppsm(item) / band_median - 1) > OUTLIER_PCT:
                excluded += 1
            else:
                kept.append(item)
    return kept, excluded


def _band_matched_change(recent, prior):
    """두 구간의 ㎡당가 변화율. 같은 평형대(10㎡ 밴드)끼리 중앙값으로 비교한다.

    양쪽 구간에 모두 거래가 있는 밴드만 사용하고, 밴드별 변화율을
    거래 수(min(최근, 직전))로 가중 평균한다. 겹치는 밴드가 없으면
    전체 중앙값 비교로 폴백하고 matched=False를 함께 반환한다.
    """
    recent_bands, prior_bands = {}, {}
    for item in recent:
        recent_bands.setdefault(_area_band(item), []).append(_ppsm(item))
    for item in prior:
        prior_bands.setdefault(_area_band(item), []).append(_ppsm(item))
    changes = []
    for band, recent_values in recent_bands.items():
        prior_values = prior_bands.get(band) or []
        if len(recent_values) < BAND_MIN_DEALS_PER_SIDE or len(prior_values) < BAND_MIN_DEALS_PER_SIDE:
            continue
        prior_median = statistics.median(prior_values)
        if prior_median <= 0:
            continue
        pct = (statistics.median(recent_values) / prior_median - 1) * 100
        changes.append((min(len(recent_values), len(prior_values)), pct))
    if changes:
        total_weight = sum(weight for weight, _ in changes)
        weighted = sum(weight * pct for weight, pct in changes) / total_weight
        return round(weighted, 1), True
    prior_all = [_ppsm(item) for item in prior]
    recent_all = [_ppsm(item) for item in recent]
    if not prior_all or not recent_all:
        return None, False
    prior_median = statistics.median(prior_all)
    if prior_median <= 0:
        return None, False
    return round((statistics.median(recent_all) / prior_median - 1) * 100, 1), False


def raw_signals(name, region="", households=0):
    """단지 하나의 시그널 원자료. leaderGap은 후보군 레벨에서 채운다."""
    transactions = molit_transactions.transactions_for_apartment(
        name, region=region, area_label="", lookback_months=LOOKBACK_MONTHS,
    )
    deals = [item for item in transactions if _ppsm(item) > 0 and item.get("dealDate")]
    deals, outlier_excluded = _filter_price_outliers(deals)
    result = {
        "dealCount": len(deals),
        "outlierExcludedCount": outlier_excluded,
        "status": "ok",
        "momentumPct": None,
        "momentumBandMatched": False,
        "recent3BandMatched": False,
        "turnoverRatio": None,
        "turnoverSmoothed": None,
        "sampleConfidence": None,
        "isRecentSurge": False,
        "risePattern": None,
        "patternChangeCount": 0,
        "patternUpCount": 0,
        "patternDownCount": 0,
        "patternVolatilityPct": None,
        "recentDealCount": 0,
        "priorDealCount": 0,
        "recent3Pct": None,
        "recent3DealCount": 0,
        "prior3DealCount": 0,
        "latestDealDate": max((item["dealDate"] for item in deals), default=None),
        "latestDealAgeDays": None,
        "districtMomentumPct": None,
        "districtRelativePct": None,
        "districtComparisonCount": 0,
        "recoveryPct": None,
        "currentPpsm": None,
        "leaderGapPct": None,
    }
    if len(deals) < MIN_TOTAL_DEALS:
        result["status"] = "insufficient"
        return result

    result["latestDealAgeDays"] = _deal_age_days(result["latestDealDate"])
    if result["latestDealAgeDays"] is not None and result["latestDealAgeDays"] > MAX_LATEST_DEAL_AGE_DAYS:
        result["status"] = "stale"
        return result

    # 실거래 신고는 계약 후 30일 이내라 진행 중인 달은 항상 과소 집계된다.
    # 미완성 월이 최근 창에만 섞이면 거래량·가격이 하향 편향되므로,
    # 모든 비교 창을 마지막 완성 월까지로 자른다.
    window_end = _months_ago(1)
    recent_cut = _months_ago(7)
    prior_cut = _months_ago(13)
    recent = [item for item in deals if recent_cut < _month_key(item["dealDate"]) <= window_end]
    prior = [item for item in deals if prior_cut < _month_key(item["dealDate"]) <= recent_cut]
    result["recentDealCount"] = len(recent)
    result["priorDealCount"] = len(prior)

    if len(recent) >= MIN_WINDOW_DEALS and len(prior) >= MIN_WINDOW_DEALS:
        momentum, matched = _band_matched_change(recent, prior)
        result["momentumPct"] = momentum
        result["momentumBandMatched"] = matched
    if prior:
        result["turnoverRatio"] = round(len(recent) / len(prior), 2)
        # 점수에는 스무딩 값을 쓴다. 소표본(2→4건)의 2.0배가 만점권이 되는 것을 막는다.
        result["turnoverSmoothed"] = round(
            (len(recent) + TURNOVER_SMOOTHING) / (len(prior) + TURNOVER_SMOOTHING), 2
        )

    recent3_cut = _months_ago(4)
    prior3_cut = _months_ago(7)
    recent3 = [item for item in deals if recent3_cut < _month_key(item["dealDate"]) <= window_end]
    prior3 = [item for item in deals if prior3_cut < _month_key(item["dealDate"]) <= recent3_cut]
    result["recent3DealCount"] = len(recent3)
    result["prior3DealCount"] = len(prior3)
    if len(recent3) >= 2 and len(prior3) >= 2:
        recent3_pct, recent3_matched = _band_matched_change(recent3, prior3)
        result["recent3Pct"] = recent3_pct
        result["recent3BandMatched"] = recent3_matched

    # 가격·거래량 핵심 구간이 모두 있어야 0~100점의 의미가 유지된다.
    if result["momentumPct"] is None or result["turnoverRatio"] is None:
        result["status"] = "insufficient"
        return result

    monthly = {}
    for item in deals:
        monthly.setdefault(_month_key(item["dealDate"]), []).append(_ppsm(item))
    monthly_median = {month: statistics.median(values) for month, values in monthly.items()}
    peak = max(monthly_median.values())
    trough = min(monthly_median.values())
    months_sorted = sorted(monthly_median)
    current_months = months_sorted[-3:]
    current = statistics.mean(monthly_median[month] for month in current_months)
    result["currentPpsm"] = round(current, 1)
    if peak > 0:
        result["recoveryPct"] = round(current / peak * 100, 1)

    # 시간 맥락: 지금 가격대가 처음 등장했던 과거 시점 (한 줄 판단용)
    result["priceSpreadPct"] = round((peak - trough) / trough * 100, 1) if trough > 0 else None
    result["isAtPeak"] = bool(result["recoveryPct"] is not None and result["recoveryPct"] >= 97)
    result["isAtTrough"] = bool(
        not result["isAtPeak"]
        and len(monthly_median) >= 6
        and trough > 0
        and current <= trough * 1.02
    )
    result["priceLevelMonth"] = None
    current_window = set(current_months)
    recency_cut = _months_ago(4)
    for month in months_sorted:
        if month in current_window:
            continue
        if monthly_median[month] >= current * 0.98:
            if month < recency_cut:
                result["priceLevelMonth"] = month
            break
    result["sampleConfidence"] = _sample_confidence(result)
    result["isRecentSurge"] = bool(
        result["recent3Pct"] is not None and result["recent3Pct"] >= SURGE_RECENT3_PCT
    )
    _rise_pattern(result, monthly, monthly_median, window_end)
    return result


def _badges(signals):
    badges = []
    momentum = signals.get("momentumPct")
    if momentum is not None:
        badges.append({
            "kind": "momentum",
            "label": f"최근 6개월 {momentum:+.1f}%",
            "tone": "up" if momentum >= 2 else ("risk" if momentum <= -2 else "wait"),
        })
    ratio = signals.get("turnoverRatio")
    if ratio is not None and ratio >= 1.3 and int(signals.get("recentDealCount") or 0) >= 5:
        badges.append({"kind": "turnover", "label": f"거래량 {ratio:.1f}배 증가", "tone": "up"})
    relative = signals.get("districtRelativePct")
    if relative is not None and abs(relative) >= 1:
        badges.append({
            "kind": "districtRelative",
            "label": f"구 대표 단지 대비 {relative:+.1f}%p",
            "tone": "up" if relative > 0 else "risk",
        })
    recent3 = signals.get("recent3Pct")
    if recent3 is not None:
        badges.append({
            "kind": "recentPersistence",
            "label": f"최근 3개월 {recent3:+.1f}%",
            "tone": "up" if recent3 >= 1 else ("risk" if recent3 <= -1 else "wait"),
        })
    if signals.get("isRecentSurge") and recent3 is not None:
        badges.append({
            "kind": "surge",
            "label": f"최근 3개월 {recent3:+.1f}% 급등 직후",
            "tone": "risk",
        })
    pattern = signals.get("risePattern")
    if pattern == "steady_rise":
        badges.append({
            "kind": "pattern",
            "label": f"꾸준한 상승 · 월간 {signals.get('patternUpCount')}/{signals.get('patternChangeCount')}회 상승",
            "tone": "up",
        })
    elif pattern == "steady_fall":
        badges.append({
            "kind": "pattern",
            "label": f"꾸준한 하락 · 월간 {signals.get('patternDownCount')}/{signals.get('patternChangeCount')}회 하락",
            "tone": "risk",
        })
    elif pattern == "choppy":
        badges.append({"kind": "pattern", "label": "월별 등락 반복", "tone": "wait"})
    # 아래 두 항목은 가격 위치를 이해하기 위한 참고 정보이며 점수에는 반영하지 않는다.
    recovery = signals.get("recoveryPct")
    if recovery is not None and recovery < 97:
        badges.append({"kind": "recovery", "label": f"전고점 대비 {recovery - 100:.0f}%", "tone": "wait"})
    gap = signals.get("leaderGapPct")
    if gap is not None and gap >= 5:
        region = signals.get("leaderRegion") or "해당 지역"
        badges.append({"kind": "leaderGap", "label": f"{region} 대장 대비 -{gap:.0f}%", "tone": "mention"})
    return badges


def _effective_turnover(signals):
    """점수·상한 판정용 거래량 배수. 스무딩 값을 우선하고 구버전 캐시는 원시값으로 폴백."""
    smoothed = signals.get("turnoverSmoothed")
    return smoothed if smoothed is not None else signals.get("turnoverRatio")


def _score_details(signals):
    values = {
        "priceMomentum": signals.get("momentumPct"),
        "turnover": _effective_turnover(signals),
        "districtRelative": signals.get("districtRelativePct"),
        "recentPersistence": signals.get("recent3Pct"),
    }
    breakdown = {}
    for key, maximum in _WEIGHTS.items():
        normalized = _scaled(values.get(key), key)
        available = normalized is not None
        if not available:
            # 결측은 0점(최악)이 아니라 중립값으로 간주한다. 자세한 근거는
            # _NEUTRAL_VALUES 주석 참고.
            normalized = _scaled(_NEUTRAL_VALUES[key], key)
        points = round(maximum * normalized)
        breakdown[key] = {
            "label": _COMPONENT_LABELS[key],
            "points": points,
            "maxPoints": maximum,
            "available": available,
            "neutral": not available,
            "value": values.get(key),
        }

    raw_score = sum(item["points"] for item in breakdown.values())
    caps = []
    momentum = signals.get("momentumPct")
    turnover = _effective_turnover(signals)
    recent3 = signals.get("recent3Pct")
    if momentum is not None and turnover is not None and momentum <= 0 and turnover <= 1:
        caps.append({
            "code": "price_and_volume_weak",
            "maxScore": 44,
            "label": "가격이 오르지 않고 거래량도 늘지 않아 최대 44점",
        })
    if recent3 is None:
        # 표본 부족(모름)과 상승 멈춤(확인된 약세)은 다르지만, 미확인 상태로
        # 최상위 구간에 오르는 것은 막아야 하므로 상한은 동일하게 둔다.
        caps.append({
            "code": "recent_rise_unconfirmed",
            "maxScore": 69,
            "label": "최근 3개월 흐름을 확인할 표본이 부족해 최대 69점",
        })
    elif recent3 <= 0:
        caps.append({
            "code": "recent_rise_unconfirmed",
            "maxScore": 69,
            "label": "최근 3개월 상승이 이어지지 않아 최대 69점",
        })
    cap = min([100, *(item["maxScore"] for item in caps)])
    return {
        "score": min(raw_score, cap),
        "rawScore": raw_score,
        "breakdown": breakdown,
        "caps": caps,
        "formulaVersion": SCORE_FORMULA_VERSION,
    }


def _composite_score(signals):
    if signals.get("status", "ok") != "ok":
        return None
    return _score_details(signals)["score"]


def _district_leader_index():
    """구 전체 단지에서 세대수 순으로 대장 후보를 고정한다.

    검색 결과에 포함된 단지만 비교하면 조건에 따라 대장이 바뀌므로,
    한국부동산원 단지 마스터 전체를 기준으로 후보군을 한 번만 만든다.
    """
    global _DISTRICT_LEADER_INDEX
    if _DISTRICT_LEADER_INDEX is not None:
        return _DISTRICT_LEADER_INDEX

    grouped = {}
    for entity in real_estate_search.APARTMENT_MASTER:
        region_key = real_estate_search.compact(entity.get("district"))
        households = int(entity.get("households") or 0)
        if not region_key or households <= 0 or entity.get("aggregate"):
            continue
        grouped.setdefault(region_key, []).append(entity)
    _DISTRICT_LEADER_INDEX = {
        region_key: sorted(
            entities,
            key=lambda entity: (-(int(entity.get("households") or 0)), entity.get("name") or ""),
        )[:_DISTRICT_LEADER_CANDIDATE_LIMIT]
        for region_key, entities in grouped.items()
    }
    return _DISTRICT_LEADER_INDEX


_DISTRICT_ENTITY_SIGNALS_CACHE = {}


def _district_entity_signals(region):
    """구 세대수 상위 고정 단지군(최대 12곳)의 (entity, signals) 목록. 프로세스 캐시."""
    region_key = real_estate_search.compact(region)
    if not region_key:
        return []
    if region_key in _DISTRICT_ENTITY_SIGNALS_CACHE:
        return _DISTRICT_ENTITY_SIGNALS_CACHE[region_key]
    pairs = []
    for entity in _district_leader_index().get(region_key, [])[:_DISTRICT_BENCHMARK_LIMIT]:
        try:
            signals = raw_signals(entity.get("name", ""), region=region)
        except Exception:
            continue
        pairs.append((entity, signals))
    _DISTRICT_ENTITY_SIGNALS_CACHE[region_key] = pairs
    return pairs


def _district_benchmark(region):
    """구 세대수 상위 고정 단지군의 momentumPct 중앙값.

    검색 조건에 따라 비교군이 바뀌면 같은 단지의 점수가 요청마다 달라지므로,
    한국부동산원 단지 마스터에서 세대수 상위 단지로 기준을 고정한다.
    유효 표본이 3곳 미만이면 None을 반환하고 호출부가 검색 후보군으로 폴백한다.
    """
    region_key = real_estate_search.compact(region)
    if not region_key:
        return {"momentumPct": None, "count": 0}
    if region_key in _DISTRICT_MOMENTUM_CACHE:
        return _DISTRICT_MOMENTUM_CACHE[region_key]
    momentums = [
        signals["momentumPct"]
        for _entity, signals in _district_entity_signals(region)
        if signals.get("status") == "ok" and signals.get("momentumPct") is not None
    ]
    benchmark = {
        "momentumPct": round(statistics.median(momentums), 1) if len(momentums) >= _DISTRICT_BENCHMARK_MIN else None,
        "count": len(momentums),
    }
    _DISTRICT_MOMENTUM_CACHE[region_key] = benchmark
    return benchmark


def district_peer_reports(name, region, limit=3):
    """구 대표 단지(세대수 상위)의 점수 요약. 직접 검색 리포트의 비교 섹션용."""
    name_key = real_estate_search.compact(name)
    peers = []
    for entity, signals in _district_entity_signals(region):
        if real_estate_search.compact(entity.get("name", "")) == name_key:
            continue
        if signals.get("status") != "ok":
            continue
        details = _score_details(signals)
        peers.append({
            "name": entity.get("name", ""),
            "region": region,
            "households": int(entity.get("households") or 0),
            "score": details["score"],
            "momentumPct": signals.get("momentumPct"),
        })
        if len(peers) >= limit:
            break
    return peers


def _entity_name_keys(entity):
    return {
        real_estate_search.compact(value)
        for value in [entity.get("name"), *(entity.get("aliases") or [])]
        if real_estate_search.compact(value)
    }


def _row_name_keys(row):
    return {
        real_estate_search.compact(value)
        for value in (row.get("name"), row.get("displayName"), row.get("searchQuery"))
        if real_estate_search.compact(value)
    }


def _absolute_leader(region, candidates):
    """해당 구 전체에서 실거래 시그널이 유효한 최대 세대수 단지 1곳을 반환한다."""
    region_key = real_estate_search.compact(region)
    entities = _district_leader_index().get(region_key, [])
    if not entities:
        return None, None

    candidate_signals = []
    for row in candidates:
        if real_estate_search.compact(row.get("region")) == region_key:
            candidate_signals.append((_row_name_keys(row), row.get("signals") or {}))

    fallback = None
    for entity in entities:
        entity_keys = _entity_name_keys(entity)
        signals = next(
            (signals for row_keys, signals in candidate_signals if row_keys.intersection(entity_keys)),
            None,
        )
        if signals is None:
            try:
                signals = raw_signals(entity.get("name", ""), region=region)
            except Exception:
                signals = {"status": "error", "dealCount": 0}
        if fallback is None:
            fallback = (entity, signals)
        if signals.get("status") == "ok" and signals.get("currentPpsm"):
            return entity, signals
    return fallback or (None, None)


def attach_signals(candidates):
    """후보 목록에 signals를 부착한다. 대장은 구 전체에서 고정한다."""
    # API가 잠시 느려져 회로가 열려도 디스크에 저장된 월별 실거래로 계산한다.
    if not candidates:
        return
    if not molit_transactions.configured():
        for row in candidates:
            row["signals"] = {
                "status": "unavailable",
                "dealCount": 0,
                "score": None,
                "badges": [],
                "scoreFormulaVersion": SCORE_FORMULA_VERSION,
            }
        return
    for row in candidates:
        try:
            row["signals"] = raw_signals(
                row.get("name", ""),
                region=row.get("region", ""),
                households=row.get("households") or 0,
            )
        except Exception:
            row["signals"] = {"status": "error", "dealCount": 0}

    # 같은 구 대비 흐름: 구 세대수 상위 고정 단지군의 중앙값과 비교한다.
    # 검색 결과에 잡힌 후보군을 쓰면 검색 조건이 바뀔 때마다 같은 단지의
    # 점수가 달라져 재현성이 깨지므로, 고정 기준을 우선 사용하고
    # 표본이 부족한 구에서만 검색 후보군 중앙값으로 폴백한다.
    for row in candidates:
        signals = row.get("signals") or {}
        if signals.get("status") != "ok" or signals.get("momentumPct") is None:
            continue
        benchmark = _district_benchmark(row.get("region", ""))
        if benchmark["momentumPct"] is not None:
            signals["districtMomentumPct"] = benchmark["momentumPct"]
            signals["districtRelativePct"] = round(signals["momentumPct"] - benchmark["momentumPct"], 1)
            signals["districtComparisonCount"] = benchmark["count"]
            signals["districtBasis"] = "district_top_households"
            continue
        peers = [
            (other.get("signals") or {}).get("momentumPct")
            for other in candidates
            if other is not row
            and other.get("region", "") == row.get("region", "")
            and (other.get("signals") or {}).get("status") == "ok"
            and (other.get("signals") or {}).get("momentumPct") is not None
        ]
        if peers:
            district_momentum = round(statistics.median(peers), 1)
            signals["districtMomentumPct"] = district_momentum
            signals["districtRelativePct"] = round(signals["momentumPct"] - district_momentum, 1)
            signals["districtComparisonCount"] = len(peers)
            signals["districtBasis"] = "search_candidates"

    # 지역별 대장: 검색 조건과 무관하게 구 전체에서 유효 실거래가 있는
    # 최대 세대수 단지 한 곳만 사용한다.
    leaders = {}
    for region in {row.get("region", "") for row in candidates if row.get("region")}:
        entity, signals = _absolute_leader(region, candidates)
        if entity:
            leaders[region] = {"entity": entity, "signals": signals or {}}

    for row in candidates:
        signals = row.get("signals") or {}
        signals["scoreFormulaVersion"] = SCORE_FORMULA_VERSION
        leader = leaders.get(row.get("region", ""))
        if signals.get("status") == "ok" and leader is not None:
            leader_entity = leader["entity"]
            is_leader = bool(_row_name_keys(row).intersection(_entity_name_keys(leader_entity)))
            signals["leaderRegion"] = row.get("region", "")
            signals["leaderName"] = leader_entity.get("name")
            signals["leaderHouseholds"] = int(leader_entity.get("households") or 0)
            signals["leaderBasis"] = "district_households"
            signals["isRegionalLeader"] = is_leader
        if (
            signals.get("status") == "ok"
            and leader is not None
            and not signals.get("isRegionalLeader")
            and signals.get("currentPpsm")
        ):
            leader_ppsm = (leader.get("signals") or {}).get("currentPpsm") or 0
            if leader_ppsm > 0:
                signals["leaderGapPct"] = round((1 - signals["currentPpsm"] / leader_ppsm) * 100, 1)
        if signals.get("status") == "ok":
            details = _score_details(signals)
            signals["score"] = details["score"]
            signals["scoreRaw"] = details["rawScore"]
            signals["scoreBreakdown"] = details["breakdown"]
            signals["scoreCaps"] = details["caps"]
            signals["scoreFormulaVersion"] = details["formulaVersion"]
            signals["badges"] = _badges(signals)
        else:
            signals["score"] = None
            signals["badges"] = (
                [{"kind": "insufficient", "label": "거래 표본 부족", "tone": "wait"}]
                if signals.get("status") == "insufficient"
                else ([{"kind": "stale", "label": "최근 거래 없음", "tone": "wait"}]
                      if signals.get("status") == "stale" else [])
            )
        row["signals"] = signals
