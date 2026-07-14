"""후보 단지의 상승 시그널 지표.

과거 국토부 실거래 데이터로 계산한 시그널이며, 미래 수익률 예측이 아니다.
점수는 항상 근거 배지와 함께 노출한다. 거래 표본이 적은 단지는 점수를
계산하지 않고 '표본 부족'으로 표시한다.

지표 4종
- momentum   : 최근 6개월 평균 ㎡당가 vs 직전 6개월 (가격 모멘텀)
- turnover   : 최근 6개월 거래건수 vs 직전 6개월 (거래 회전율 변화)
- recovery   : 조회 기간 내 월별 중위 ㎡당가 고점 대비 현재 수준 (전고점 회복률)
- leaderGap  : 같은 지역 대장 단지(세대수 최대) ㎡당가 대비 할인율 (키맞추기 갭)
"""
import datetime
import statistics

import config
import molit_transactions
import real_estate_search

LOOKBACK_MONTHS = config.MOLIT_SIGNAL_LOOKBACK_MONTHS
MIN_WINDOW_DEALS = config.SIGNAL_MIN_WINDOW_DEALS
MIN_TOTAL_DEALS = config.SIGNAL_MIN_TOTAL_DEALS

# 절대 스케일 정규화 경계. 후보군 상대 정규화(min-max)는 표본이 작을 때
# 순위가 요동치므로 해석 가능한 고정 경계를 쓴다.
_SCALES = {
    "momentum": (-10.0, 10.0),   # 6개월 ±10%
    "turnover": (0.5, 2.0),      # 거래량 0.5배~2배
    "leaderGap": (0.0, 30.0),    # 대장 대비 0~30% 할인
    "recoveryRoom": (0.0, 25.0), # 전고점까지 남은 여력 0~25%
}
_WEIGHTS = {"momentum": 0.40, "turnover": 0.25, "leaderGap": 0.20, "recoveryRoom": 0.15}
_DISTRICT_LEADER_INDEX = None
_DISTRICT_LEADER_CANDIDATE_LIMIT = 20

SIGNAL_NOTE = (
    "상승 시그널은 국토부 실거래가 기반 과거 지표(가격 모멘텀·거래량 변화·전고점 회복률·"
    "대장 단지 대비 갭)의 합성 점수입니다. 미래 수익률을 보장하지 않으며 투자 판단의 참고 자료입니다."
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


def raw_signals(name, region="", households=0):
    """단지 하나의 시그널 원자료. leaderGap은 후보군 레벨에서 채운다."""
    transactions = molit_transactions.transactions_for_apartment(
        name, region=region, area_label="", lookback_months=LOOKBACK_MONTHS,
    )
    deals = [item for item in transactions if _ppsm(item) > 0 and item.get("dealDate")]
    result = {
        "dealCount": len(deals),
        "status": "ok",
        "momentumPct": None,
        "turnoverRatio": None,
        "recentDealCount": 0,
        "priorDealCount": 0,
        "recoveryPct": None,
        "currentPpsm": None,
        "leaderGapPct": None,
    }
    if len(deals) < MIN_TOTAL_DEALS:
        result["status"] = "insufficient"
        return result

    recent_cut = _months_ago(6)
    prior_cut = _months_ago(12)
    recent = [item for item in deals if _month_key(item["dealDate"]) > recent_cut]
    prior = [item for item in deals if prior_cut < _month_key(item["dealDate"]) <= recent_cut]
    result["recentDealCount"] = len(recent)
    result["priorDealCount"] = len(prior)

    if len(recent) >= MIN_WINDOW_DEALS and len(prior) >= MIN_WINDOW_DEALS:
        recent_avg = statistics.mean(_ppsm(item) for item in recent)
        prior_avg = statistics.mean(_ppsm(item) for item in prior)
        if prior_avg > 0:
            result["momentumPct"] = round((recent_avg / prior_avg - 1) * 100, 1)
    if prior:
        result["turnoverRatio"] = round(len(recent) / len(prior), 2)

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
    if ratio is not None and ratio >= 1.3:
        badges.append({"kind": "turnover", "label": f"거래량 {ratio:.1f}배 증가", "tone": "up"})
    recovery = signals.get("recoveryPct")
    if recovery is not None and recovery < 97:
        badges.append({"kind": "recovery", "label": f"전고점 대비 {recovery - 100:.0f}%", "tone": "wait"})
    gap = signals.get("leaderGapPct")
    if gap is not None and gap >= 5:
        region = signals.get("leaderRegion") or "해당 지역"
        badges.append({"kind": "leaderGap", "label": f"{region} 대장 대비 -{gap:.0f}%", "tone": "mention"})
    return badges


def _composite_score(signals):
    parts = {
        "momentum": _scaled(signals.get("momentumPct"), "momentum"),
        "turnover": _scaled(signals.get("turnoverRatio"), "turnover"),
        "leaderGap": _scaled(signals.get("leaderGapPct"), "leaderGap"),
        "recoveryRoom": _scaled(
            None if signals.get("recoveryPct") is None else max(0.0, 100 - signals["recoveryPct"]),
            "recoveryRoom",
        ),
    }
    available = {key: value for key, value in parts.items() if value is not None}
    if not available:
        return None
    total_weight = sum(_WEIGHTS[key] for key in available)
    score = sum(_WEIGHTS[key] * value for key, value in available.items()) / total_weight
    return round(score * 100)


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
    if not candidates or not molit_transactions.configured():
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

    # 지역별 대장: 검색 조건과 무관하게 구 전체에서 유효 실거래가 있는
    # 최대 세대수 단지 한 곳만 사용한다.
    leaders = {}
    for region in {row.get("region", "") for row in candidates if row.get("region")}:
        entity, signals = _absolute_leader(region, candidates)
        if entity:
            leaders[region] = {"entity": entity, "signals": signals or {}}

    for row in candidates:
        signals = row.get("signals") or {}
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
            signals["score"] = _composite_score(signals)
            signals["badges"] = _badges(signals)
        else:
            signals["score"] = None
            signals["badges"] = (
                [{"kind": "insufficient", "label": "거래 표본 부족", "tone": "wait"}]
                if signals.get("status") == "insufficient" else []
            )
        row["signals"] = signals
