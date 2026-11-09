"""집픽의 현재 적정가격 범위와 쌈·적정·비쌈 판정을 만든다.

이 모듈은 매물 호가를 모델 입력으로 사용하지 않는다. 최근 같은 면적 실거래로
중심가와 범위를 만든다. 한국부동산원 주간 매매가격지수가 있으면 거래마다 계약한
주부터 이번 주까지의 지역 변화만큼 가격을 옮겨 오늘 기준으로 맞춘다. 지수가
없으면 거래가 뜸한 동안의 지역·주변 단지 흐름만 제한적으로 시간 보정한다.
금리와 공급은 현재 거래가격을 임의로 움직이지 않고 향후 위험 근거로 따로 남긴다.
"""

import datetime
import math
import statistics

import molit_transactions
import regional_price_index


MODEL_VERSION = "zippick-current-value-v5"
MIN_SAMPLE_COUNT = 3
MAX_TRADE_AGE_DAYS = 120
COMPARISON_WINDOWS = (6, 12, 24)
MAX_MARKET_ADJUSTMENT_PCT = 3.0
# 24개월의 확인된 지수 변화를 반영한다. 짧은 기간용 10% 상한으로
# 장기 상승분을 잘라내지 않되, 100%를 넘는 변화는 참고값으로 제한한다.
MAX_INDEX_ADJUSTMENT_PCT = 100.0


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive(value):
    number = _number(value)
    return number if number is not None and number > 0 else None


def _age_days(value, today=None):
    try:
        date = datetime.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None
    return max(0, ((today or datetime.date.today()) - date).days)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _cached_history(row):
    """Read the exact complex's selected area; never fan out into live API calls."""
    if not row.get("name"):
        return [], "not_available"
    import budget_candidates

    entity = budget_candidates._price_lookup_entity(row)
    if not entity:
        return [], "identity_unavailable"
    area = _positive(row.get("latestDealExclusiveArea"))
    area_label = f"전용 {area:g}㎡" if area else row.get("displayAreaLabel") or row.get("areaLabel")
    if not area_label:
        return [], "area_unavailable"
    transactions = molit_transactions.transactions_for_apartment_cached(
        row["name"], region=row.get("region") or row.get("regionLabel") or "",
        area_label=area_label, lookback_months=COMPARISON_WINDOWS[-1], entity=entity,
    )
    return transactions, "cached"


def _comparison_inputs(row, today):
    """Use the shortest period with three trades, then compare floors within it.

    Only valuation inputs are replaced. Card prices, scores and the evaluated
    transaction keep their original basis.
    """
    default_months = int(_number(row.get("tradeLookbackMonths")) or 6)
    info = {"periodMonths": default_months, "periodWidened": default_months > 6,
            "source": "provided", "windows": [], "reconstructed": False,
            "selectionPolicy": "recent_period_before_floor"}
    enough = (int(_number(row.get("valuationEstimateSampleCount")) or 0) >= MIN_SAMPLE_COUNT
              and all(_positive(row.get(key)) for key in (
                  "valuationEstimateMinPriceEok", "valuationEstimateMidPriceEok", "valuationEstimateMaxPriceEok")))
    # The common case needs no extra master/cache scan.
    if enough and default_months <= 6 and _floor_comparison(row)[0]["status"] == "matched":
        return row, info
    try:
        cached, source = _cached_history(row)
    except Exception:
        cached, source = [], "lookup_failed"
    info["source"] = source
    latest_date = str(row.get("latestDealDate") or "")[:10]
    latest_price = _positive(row.get("latestDealPriceEok"))
    latest_floor = _number(row.get("latestDealFloor"))
    target_area = _positive(row.get("latestDealExclusiveArea"))
    pool, removed = [], False
    for trade in cached:
        date = str(trade.get("dealDate") or "")[:10]
        price = _positive(trade.get("dealAmountEok"))
        area = _positive(trade.get("exclusiveArea"))
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            continue
        if not price or date > latest_date or date > today.isoformat():
            continue
        if target_area and (not area or abs(area - target_area) > 1):
            continue
        if not latest_price and date == latest_date:
            # A missing target price cannot identify the evaluated deal safely.
            continue
        same_floor = latest_floor is None or _number(trade.get("floor")) == latest_floor
        if not removed and date == latest_date and latest_price and abs(price - latest_price) < .005 and same_floor:
            removed = True
            continue
        pool.append([date, price, str(trade.get("floor") or "")])
    # The supplied valuationTrades already exclude the evaluated transaction.
    supplied = [list(trade) for trade in row.get("valuationTrades") or []
                if isinstance(trade, (list, tuple)) and len(trade) >= 2
                and _positive(trade[1]) and str(trade[0])[:10] <= latest_date]
    if len(supplied) > len(pool):
        pool = supplied
    candidates = []
    for months in COMPARISON_WINDOWS:
        periods = set(molit_transactions._deal_months_for_day(months, today.isoformat()))
        trades = [trade for trade in pool if str(trade[0])[:7].replace("-", "") in periods]
        floor, _ = _floor_comparison({**row, "valuationTrades": trades})
        info["windows"].append({"periodMonths": months, "sampleCount": len(trades),
                                "similarFloorCount": floor["sampleCount"]})
        candidates.append((months, trades))
        if len(trades) >= MIN_SAMPLE_COUNT:
            break
    # 최근 다른 층 거래를 버리고 예전의 비슷한 층 거래만 고르지 않는다.
    # 같은 기간 안에 비슷한 층 3건이 있으면 아래 valuation_for_candidate에서 고른다.
    chosen = next(((months, trades) for months, trades in candidates if len(trades) >= MIN_SAMPLE_COUNT), None)
    if chosen is None:
        if default_months > COMPARISON_WINDOWS[-1]:
            return {**row, "valuationEstimateMinPriceEok": None, "valuationEstimateMidPriceEok": None,
                    "valuationEstimateMaxPriceEok": None, "valuationEstimateSampleCount": 0}, info
        return row, info
    months, trades = chosen
    estimate = molit_transactions._current_price_estimate([
        {"dealDate": trade[0], "dealAmountEok": trade[1]} for trade in trades
    ])
    if not estimate:
        return row, info
    info.update({"periodMonths": months, "periodWidened": months > 6, "reconstructed": True})
    return {**row, "valuationTrades": trades,
            "valuationEstimateMinPriceEok": estimate["minPriceEok"],
            "valuationEstimateMidPriceEok": estimate["midPriceEok"],
            "valuationEstimateMaxPriceEok": estimate["maxPriceEok"],
            "valuationEstimateSampleCount": estimate["sampleCount"]}, info


def _floor_comparison(row):
    """평가 거래와 층이 비슷한, 평가 거래를 제외한 실거래를 고른다."""
    target = _positive(row.get("latestDealFloor"))
    trades = row.get("valuationTrades")
    if target is None or not isinstance(trades, list):
        return {"status": "unknown", "targetFloor": target, "sampleCount": 0}, []
    target = int(target)
    known = [trade for trade in trades if isinstance(trade, (list, tuple)) and len(trade) >= 3
             and _positive(trade[2]) is not None]
    # 저층은 별도 집단으로 보고, 그 밖의 층은 가까운 층끼리 비교한다.
    matches = [trade for trade in known if (
        int(float(trade[2])) <= 3 if target <= 3
        else int(float(trade[2])) > 3 and abs(int(float(trade[2])) - target) <= 3
    )]
    status = "matched" if len(matches) >= MIN_SAMPLE_COUNT else "insufficient"
    return {
        "status": status,
        "targetFloor": target,
        "sampleCount": len(matches),
        "knownFloorCount": len(known),
        "rule": "1~3층" if target <= 3 else "앞뒤 3층",
    }, matches


def _market_context(row):
    signals = row.get("signals") if isinstance(row.get("signals"), dict) else {}
    peers = row.get("peers") if isinstance(row.get("peers"), list) else []
    peer_values = [
        value
        for peer in peers
        if isinstance(peer, dict)
        and (value := _number(peer.get("momentumPct"))) is not None
    ]
    peer_median = statistics.median(peer_values) if peer_values else None
    local = _number(signals.get("momentumPct"))
    district = _number(signals.get("districtMomentumPct"))
    leader = _number(signals.get("leaderMomentumPct"))
    # 평가 대상 단지의 최근 거래가 자기 시장 보정값까지 끌어올리지 않도록
    # 보정에는 같은 구·주변 단지·대장 흐름만 사용한다.
    comparison_values = [value for value in (district, peer_median, leader) if value is not None]
    blended = None
    if comparison_values:
        weighted = []
        if district is not None:
            weighted.extend([district, district])
        if peer_median is not None:
            weighted.append(peer_median)
        if leader is not None:
            weighted.append(leader)
        blended = statistics.median(weighted)
    return {
        "status": "available" if comparison_values else "unavailable",
        "apartment6mPct": local,
        "district6mPct": district,
        "peer6mPct": round(peer_median, 2) if peer_median is not None else None,
        "leader6mPct": leader,
        "comparisonCount": len(peer_values),
        "blended6mPct": round(blended, 2) if blended is not None else None,
    }


def _macro_context(row):
    indicators = row.get("marketIndicators")
    if not isinstance(indicators, dict):
        return {
            "status": "unavailable",
            "message": "한국은행 기준금리 자료를 아직 불러오지 못했어요. 가격 범위는 실거래와 주변 시세로 계산했어요.",
        }
    base_rate = _number(indicators.get("baseRatePct"))
    mortgage_rate = _number(indicators.get("mortgageRatePct"))
    rate_change = _number(indicators.get("mortgageRateChangePp12m"))
    base_rate_change = _number(indicators.get("baseRateChangePp12m"))
    if base_rate is None and mortgage_rate is None:
        reason = str(indicators.get("reason") or "")
        message = (
            "한국은행 기준금리 연결 설정이 아직 없어 금리 상황을 함께 보여드리지 못해요. "
            "가격 범위는 실거래와 주변 시세로 계산했어요."
            if "API 키" in reason
            else "한국은행 기준금리 자료를 지금 불러오지 못했어요. 가격 범위는 실거래와 주변 시세로 계산했어요."
        )
        return {
            "status": "unavailable",
            "message": message,
        }
    changes = []
    if base_rate is not None:
        changes.append(f"기준금리 {base_rate:g}%")
    if base_rate_change is not None and abs(base_rate_change) >= 0.005:
        direction = "높아요" if base_rate_change > 0 else "낮아요"
        changes.append(f"1년 전보다 {abs(base_rate_change):g}%p {direction}")
    message = " · ".join(changes)
    if message:
        message += ". "
    message += "금리는 향후 시장 위험으로 확인하고 현재 실거래 적정가를 임의로 바꾸지 않아요."
    return {
        "status": "available",
        "asOf": str(indicators.get("asOf") or ""),
        "baseRatePct": base_rate,
        "baseRateChangePp12m": base_rate_change,
        "mortgageRatePct": mortgage_rate,
        "mortgageRateChangePp12m": rate_change,
        "source": str(indicators.get("source") or "한국은행 ECOS"),
        "message": message,
    }


def _index_adjusted_estimate(row, today=None):
    """거래마다 지역 주간 지수 변화를 반영한 가격대를 다시 계산한다.

    지수나 거래 목록이 없거나, 한 건이라도 계약 주의 지수를 찾지 못하면
    None을 돌려 기존 계산을 쓰게 한다. 일부 거래만 옮기면 범위가 뒤틀린다.
    """
    trades = row.get("valuationTrades")
    if not isinstance(trades, list) or len(trades) < MIN_SAMPLE_COUNT:
        return None
    series = regional_price_index.series_for_region(regional_price_index.region_for_row(row))
    latest = regional_price_index.latest_point(series, today=today)
    if not latest:
        return None
    original, adjusted, adjustments, limited = [], [], [], False
    for trade in trades:
        try:
            deal_date, price = str(trade[0])[:10], float(trade[1])
        except (IndexError, TypeError, ValueError):
            return None
        base_value = regional_price_index.value_on(series, deal_date)
        if price <= 0 or not base_value:
            return None
        raw_change_pct = (latest["value"] / base_value - 1) * 100
        limited = limited or abs(raw_change_pct) > MAX_INDEX_ADJUSTMENT_PCT
        change_pct = _clamp(
            raw_change_pct,
            -MAX_INDEX_ADJUSTMENT_PCT, MAX_INDEX_ADJUSTMENT_PCT,
        )
        original.append({"dealDate": deal_date, "dealAmountEok": price})
        adjusted.append({"dealDate": deal_date, "dealAmountEok": price * (1 + change_pct / 100)})
        adjustments.append({"dealDate": deal_date, "originalPriceEok": round(price, 4),
                            "adjustedPriceEok": round(price * (1 + change_pct / 100), 4),
                            "changePct": round(change_pct, 2), "rawChangePct": round(raw_change_pct, 2),
                            "floor": str(trade[2]) if len(trade) > 2 else ""})
    before = molit_transactions._current_price_estimate(original)
    after = molit_transactions._current_price_estimate(adjusted)
    if not before or not after or not before.get("midPriceEok"):
        return None
    return {
        "low": after["minPriceEok"],
        "center": after["midPriceEok"],
        "high": after["maxPriceEok"],
        "centerChangePct": round((after["midPriceEok"] / before["midPriceEok"] - 1) * 100, 2),
        "regionLabel": series["label"],
        "asOf": latest["period"],
        "limited": limited,
        "transactions": adjustments,
    }


def _index_unavailable_reason(row, today):
    trades = row.get("valuationTrades")
    if not isinstance(trades, list) or len(trades) < MIN_SAMPLE_COUNT:
        return "비교 거래의 날짜와 가격 자료가 부족해 주간 지수를 적용하지 못했어요."
    series = regional_price_index.series_for_region(regional_price_index.region_for_row(row))
    if not regional_price_index.latest_point(series, today=today):
        return "최근 21일 안의 지역 주간 지수가 없어 과거 거래를 현재 기준으로 보정하지 못했어요."
    dates = [str(trade[0])[:10] for trade in trades if trade]
    missing = [day for day in dates if regional_price_index.value_on(series, day) is None]
    if missing:
        return f"{min(missing)} 등 비교 거래 시점의 주간 지수가 없어 현재 기준으로 보정하지 못했어요."
    return "거래별 지역 주간 지수를 연결하지 못해 현재 기준 보정률을 계산하지 못했어요."


def _unavailable(reason, row, today=None, comparison=None):
    return {
        "status": "unavailable",
        "verdict": "hold",
        "modelVersion": MODEL_VERSION,
        "asOf": str(today or datetime.date.today()),
        "reason": reason,
        "market": _market_context(row),
        "macro": _macro_context(row),
        "comparisonSearch": comparison or {},
    }


def valuation_for_candidate(row, today=None):
    """Return a server-owned fair-price contract for one candidate row."""
    if not isinstance(row, dict) or row.get("priceIdentityVerified") is not True:
        return _unavailable("단지를 정확히 확인하지 못해 가격을 판단할 수 없어요.", row or {}, today)
    today = today or datetime.date.today()
    area = _positive(row.get("latestDealExclusiveArea"))
    scope = row.get("tradeAreaScope") or molit_transactions.area_scope(row.get("areaLabel") or row.get("displayAreaLabel") or "")
    if area and scope and not (scope["minSqm"] <= area
                              and (area <= scope["maxSqm"] if scope["upperInclusive"] else area < scope["maxSqm"])):
        return _unavailable("선택한 평형과 최근 거래의 면적이 맞지 않아 가격 자료를 다시 연결해야 해요.", row, today)
    age_days = _age_days(row.get("latestDealDate"), today)
    if age_days is None or str(row.get("latestDealDate"))[:10] > today.isoformat():
        return _unavailable("최근 거래 날짜를 확인하지 못해 가격을 판단할 수 없어요.", row, today)
    row, comparison = _comparison_inputs(row, today)

    has_leave_one_out = all(
        _positive(row.get(field))
        for field in (
            "valuationEstimateMinPriceEok",
            "valuationEstimateMidPriceEok",
            "valuationEstimateMaxPriceEok",
        )
    )
    sample_count = int(_number(row.get("valuationEstimateSampleCount")) or 0)
    latest_date = str(row.get("latestDealDate") or "")
    low = _positive(row.get("valuationEstimateMinPriceEok"))
    center = _positive(row.get("valuationEstimateMidPriceEok"))
    high = _positive(row.get("valuationEstimateMaxPriceEok"))

    if not has_leave_one_out:
        counts = comparison.get("windows") or []
        count = max((window["sampleCount"] for window in counts), default=sample_count)
        scope = "24개월까지 넓혀 현재 확보한" if counts else "현재 확보한"
        reason = f"평가할 거래를 뺀 비교 자료가 부족해요. {scope} 같은 면적의 다른 거래는 {count}건으로, 최소 3건이 필요해요."
        if comparison.get("source") == "lookup_failed":
            reason += " 과거 거래 자료를 불러오지 못해 다시 조회해야 해요."
        return _unavailable(reason, row, today, comparison)
    if sample_count < MIN_SAMPLE_COUNT:
        return _unavailable(f"평가 거래를 제외한 비교 거래는 {sample_count}건이에요. 가격 범위를 만들려면 최소 3건이 필요해요.", row, today, comparison)
    if age_days > 730:
        return _unavailable("최근 거래가 2년보다 오래돼 현재 가격을 판단할 수 없어요.", row, today, comparison)
    if not low or not center or not high:
        return _unavailable("가격 범위를 계산할 실거래 자료가 부족해요.", row, today)

    floor_comparison, floor_trades = _floor_comparison(row)
    valuation_row = row
    if floor_comparison["status"] == "matched":
        floor_estimate = molit_transactions._current_price_estimate([
            {"dealDate": trade[0], "dealAmountEok": trade[1]} for trade in floor_trades
        ])
        if floor_estimate:
            low = _positive(floor_estimate.get("minPriceEok")) or low
            center = _positive(floor_estimate.get("midPriceEok")) or center
            high = _positive(floor_estimate.get("maxPriceEok")) or high
            sample_count = len(floor_trades)
            valuation_row = {**row, "valuationTrades": floor_trades}
        else:
            floor_comparison["status"] = "insufficient"

    market = _market_context(row)
    index_estimate = _index_adjusted_estimate(valuation_row, today)
    adjustment_pct = 0.0
    if index_estimate:
        # 거래마다 이미 오늘 기준으로 옮겼으므로 주변 단지 흐름을 또 더하지 않는다.
        low, center, high = index_estimate["low"], index_estimate["center"], index_estimate["high"]
        adjustment_pct = index_estimate["centerChangePct"]
    else:
        # 최근 거래 이후 비어 있는 기간만 보정한다. 이미 거래가격에 담긴 6개월
        # 상승률을 다시 더하지 않도록 보정 폭을 35%로 줄이고 최대 3%로 제한한다.
        blended = market.get("blended6mPct")
        if blended is not None and age_days > 30:
            elapsed_share = min(age_days, MAX_TRADE_AGE_DAYS) / 180
            adjustment_pct = _clamp(blended * elapsed_share * 0.35, -MAX_MARKET_ADJUSTMENT_PCT, MAX_MARKET_ADJUSTMENT_PCT)
        factor = 1 + adjustment_pct / 100
        center *= factor
        low *= factor
        high *= factor

    # Old trades remain useful evidence, but without a complete time adjustment
    # their nominal prices must not become a confident current buy-price verdict.
    reference_only = floor_comparison["status"] != "matched" or (
        not index_estimate and (age_days > MAX_TRADE_AGE_DAYS or comparison["periodWidened"])
    ) or bool(index_estimate and index_estimate["limited"])

    # 25~75백분위가 지나치게 좁을 때 표본 수·최신성에 맞는 최소 폭을 둔다.
    minimum_half_width_pct = 4.0 if sample_count >= 10 else 5.0 if sample_count >= 5 else 7.0
    if age_days > 60:
        minimum_half_width_pct += 1.0
    if comparison["periodWidened"]:
        minimum_half_width_pct += 2.0 if comparison["periodMonths"] <= 12 else 4.0
    if age_days > MAX_TRADE_AGE_DAYS:
        minimum_half_width_pct += min(4.0, (age_days - MAX_TRADE_AGE_DAYS) / 90)
    if market["status"] != "available":
        minimum_half_width_pct += 1.0
    minimum_half_width = center * minimum_half_width_pct / 100
    low = min(low, center - minimum_half_width)
    high = max(high, center + minimum_half_width)
    width_pct = (high - low) / center * 100

    quality = "high" if sample_count >= 10 and age_days <= 45 and market["status"] == "available" else (
        "medium" if sample_count >= 5 and age_days <= 90 else "low"
    )
    if reference_only or comparison["periodWidened"] or age_days > MAX_TRADE_AGE_DAYS:
        quality = "low"
    reasons = [f"비슷한 면적의 이전 실거래 {sample_count}건을 사용했어요."]
    reasons.append("평가할 최근 거래는 기준가격 계산에서 뺐어요.")
    if index_estimate:
        # 가격을 옮긴 근거는 주간 지수 하나다. 쓰지 않은 주변 단지 흐름은 적지 않는다.
        reasons.append(
            "주간 지수 변화를 제한된 폭으로 반영했어요. 현재 가격으로 완전히 맞춘 값은 아니에요."
            if index_estimate["limited"] else
            f"한국부동산원 {index_estimate['regionLabel']} 주간 가격 변화를 거래마다 반영해 가장 최근 주 기준으로 맞췄어요."
        )
    elif market["status"] == "available":
        reasons.append("단지·같은 구·주변 비교 단지의 6개월 흐름을 함께 확인했어요.")
    else:
        reasons.append("지역·주변 단지 흐름 자료가 부족해 실거래 범위를 더 넓게 잡았어요.")
    if floor_comparison["status"] == "matched":
        reasons.append(f"최근 거래와 층이 비슷한 실거래 {sample_count}건으로 가격대를 계산했어요.")
    else:
        reasons.append("최근 기간에 층이 비슷한 거래가 부족해 같은 면적의 여러 층 거래와 비교했어요. 층별 가격 차이는 보정하지 않았어요.")
    if comparison["periodWidened"]:
        reasons.append(f"최근 6개월 자료가 부족해 {comparison['periodMonths']}개월까지 넓혔어요. 자료의 확실성은 낮게 표시했어요.")
    if age_days > MAX_TRADE_AGE_DAYS:
        reasons.append(f"최근 거래가 {age_days}일 전이라 거래 공백을 감안해 가격 범위를 넓혔어요.")
    if reference_only:
        reasons.append("확보한 거래로 참고 가격대는 보여드리지만, 현재 매물이 싸거나 비싸다고 단정하지 않아요.")
    if index_estimate and index_estimate["limited"]:
        reasons.append("과거와 현재의 지수 차이가 보정 한도를 넘어 참고 가격대로만 표시했어요.")
    if not index_estimate and adjustment_pct:
        direction = "올려" if adjustment_pct > 0 else "낮춰"
        reasons.append(f"마지막 거래 뒤 시장 변화를 반영해 {'참고 가격대' if reference_only else '적정가격'}를 {abs(adjustment_pct):.1f}% {direction} 봤어요.")

    return {
        "status": "ready",
        "verdict": "compare_price",
        "modelVersion": MODEL_VERSION,
        "asOf": str(today or datetime.date.today()),
        "areaLabel": str(row.get("displayAreaLabel") or row.get("areaLabel") or ""),
        "areaScope": row.get("tradeAreaScope") or molit_transactions.area_scope(
            row.get("areaLabel") or row.get("displayAreaLabel") or ""),
        "evaluatedTrade": {"dealAmountEok": row.get("latestDealPriceEok"),
                           "dealDate": row.get("latestDealDate"),
                           "exclusiveArea": row.get("latestDealExclusiveArea"),
                           "floor": row.get("latestDealFloor")},
        "fairPrice": {
            "lowEok": round(max(0.01, low), 2),
            "centerEok": round(center, 2),
            "highEok": round(max(high, low), 2),
            "widthPct": round(width_pct, 1),
            "method": (
                "평가할 거래를 제외한 과거 실거래 참고 가격대"
                if reference_only and (not index_estimate or index_estimate["limited"])
                else "평가할 거래를 제외한 실거래를 한국부동산원 주간 지수로 오늘 기준에 맞춘 가격대"
                if index_estimate
                else "평가할 거래를 제외한 실거래 가격대 + 거래 공백 기간의 지역·주변 흐름 보정"
            ),
        },
        "dataQuality": {
            "level": quality,
            "sampleCount": sample_count,
            "latestTradeDate": latest_date,
            "latestTradeAgeDays": age_days,
            "marketContextAvailable": market["status"] == "available",
            "periodMonths": comparison["periodMonths"],
            "periodWidened": comparison["periodWidened"],
        },
        "referenceOnly": reference_only,
        "comparisonSearch": comparison,
        "comparisonTrades": [{"dealDate": str(trade[0])[:10], "originalPriceEok": float(trade[1]),
                              "floor": str(trade[2]) if len(trade) > 2 else ""}
                             for trade in valuation_row.get("valuationTrades") or []],
        "floorComparison": floor_comparison,
        "marketAdjustmentPct": round(adjustment_pct, 2),
        "indexAdjustment": {
            "status": "applied",
            "source": regional_price_index.SOURCE,
            "region": index_estimate["regionLabel"],
            "asOf": index_estimate["asOf"],
            "centerChangePct": index_estimate["centerChangePct"],
            "limited": index_estimate["limited"],
            "transactions": index_estimate.get("transactions", []),
        } if index_estimate else {"status": "unavailable", "reason": _index_unavailable_reason(valuation_row, today)},
        "latestTradeExcluded": has_leave_one_out,
        "market": market,
        "macro": _macro_context(row),
        "reasons": reasons,
        "limitations": ["동·향·수리 상태와 실제 매물 상태는 반영하지 못했어요." if floor_comparison["status"] == "matched"
                        else "최근 거래의 층은 확인했지만 비슷한 층 거래가 부족해 층별 가격을 계산하지 못했어요. 동·향·수리 상태와 실제 매물 상태도 반영하지 못했어요."],
    }


def verdict_for_price(valuation, price_eok):
    """Classify a price against a ready valuation. Useful for APIs and tests."""
    if not isinstance(valuation, dict) or valuation.get("status") != "ready":
        return "hold"
    if valuation.get("referenceOnly"):
        return "hold"
    if valuation.get("floorComparison", {}).get("status") != "matched":
        return "hold"
    price = _positive(price_eok)
    fair = valuation.get("fairPrice") if isinstance(valuation.get("fairPrice"), dict) else {}
    low = _positive(fair.get("lowEok"))
    high = _positive(fair.get("highEok"))
    if not price or not low or not high:
        return "hold"
    if price < low:
        return "cheap"
    if price > high:
        return "expensive"
    return "fair"


def attach_valuations(candidates, today=None):
    for row in candidates or []:
        scope = molit_transactions.area_scope(row.get("areaLabel") or row.get("displayAreaLabel") or "")
        if scope:
            row["tradeAreaScope"] = scope
        row["valuation"] = valuation_for_candidate(row, today=today)
