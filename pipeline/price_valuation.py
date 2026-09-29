"""집픽의 현재 적정가격 범위와 쌈·적정·비쌈 판정을 만든다.

이 모듈은 매물 호가를 모델 입력으로 사용하지 않는다. 최근 같은 면적 실거래로
중심가와 범위를 만들고, 거래가 뜸한 동안의 지역·주변 단지 흐름만 제한적으로
시간 보정한다. 금리와 공급은 현재 거래가격을 임의로 움직이지 않고 향후 위험
근거로 따로 남긴다.
"""

import datetime
import math
import statistics


MODEL_VERSION = "zippick-current-value-v1"
MIN_SAMPLE_COUNT = 3
MAX_TRADE_AGE_DAYS = 120
MAX_MARKET_ADJUSTMENT_PCT = 3.0


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


def _unavailable(reason, row, today=None):
    return {
        "status": "unavailable",
        "verdict": "hold",
        "modelVersion": MODEL_VERSION,
        "asOf": str(today or datetime.date.today()),
        "reason": reason,
        "market": _market_context(row),
        "macro": _macro_context(row),
    }


def valuation_for_candidate(row, today=None):
    """Return a server-owned fair-price contract for one candidate row."""
    if not isinstance(row, dict) or row.get("priceIdentityVerified") is not True:
        return _unavailable("단지를 정확히 확인하지 못해 가격을 판단할 수 없어요.", row or {}, today)

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
    age_days = _age_days(latest_date, today)
    low = _positive(row.get("valuationEstimateMinPriceEok"))
    center = _positive(row.get("valuationEstimateMidPriceEok"))
    high = _positive(row.get("valuationEstimateMaxPriceEok"))

    if not has_leave_one_out:
        return _unavailable("평가할 거래를 뺀 비교 자료가 없어 가격 판단을 보류했어요.", row, today)
    if sample_count < MIN_SAMPLE_COUNT:
        return _unavailable("비슷한 면적의 거래가 3건 미만이라 가격 판단을 보류했어요.", row, today)
    if age_days is None or age_days > MAX_TRADE_AGE_DAYS:
        return _unavailable("최근 거래가 오래돼 현재 가격 판단을 보류했어요.", row, today)
    if not low or not center or not high:
        return _unavailable("가격 범위를 계산할 실거래 자료가 부족해요.", row, today)

    market = _market_context(row)
    # 최근 거래 이후 비어 있는 기간만 보정한다. 이미 거래가격에 담긴 6개월
    # 상승률을 다시 더하지 않도록 보정 폭을 35%로 줄이고 최대 3%로 제한한다.
    blended = market.get("blended6mPct")
    adjustment_pct = 0.0
    if blended is not None and age_days > 30:
        elapsed_share = min(age_days, MAX_TRADE_AGE_DAYS) / 180
        adjustment_pct = _clamp(blended * elapsed_share * 0.35, -MAX_MARKET_ADJUSTMENT_PCT, MAX_MARKET_ADJUSTMENT_PCT)
    factor = 1 + adjustment_pct / 100
    center *= factor
    low *= factor
    high *= factor

    # 25~75백분위가 지나치게 좁을 때 표본 수·최신성에 맞는 최소 폭을 둔다.
    minimum_half_width_pct = 4.0 if sample_count >= 10 else 5.0 if sample_count >= 5 else 7.0
    if age_days > 60:
        minimum_half_width_pct += 1.0
    if market["status"] != "available":
        minimum_half_width_pct += 1.0
    minimum_half_width = center * minimum_half_width_pct / 100
    low = min(low, center - minimum_half_width)
    high = max(high, center + minimum_half_width)
    width_pct = (high - low) / center * 100

    quality = "high" if sample_count >= 10 and age_days <= 45 and market["status"] == "available" else (
        "medium" if sample_count >= 5 and age_days <= 90 else "low"
    )
    reasons = [f"비슷한 면적의 이전 실거래 {sample_count}건을 사용했어요."]
    reasons.append("평가할 최근 거래는 기준가격 계산에서 뺐어요.")
    if market["status"] == "available":
        reasons.append("단지·같은 구·주변 비교 단지의 6개월 흐름을 함께 확인했어요.")
    else:
        reasons.append("지역·주변 단지 흐름 자료가 부족해 실거래 범위를 더 넓게 잡았어요.")
    if adjustment_pct:
        direction = "올려" if adjustment_pct > 0 else "낮춰"
        reasons.append(f"마지막 거래 뒤 시장 변화를 반영해 중심가를 {abs(adjustment_pct):.1f}% {direction} 봤어요.")

    return {
        "status": "ready",
        "verdict": "compare_price",
        "modelVersion": MODEL_VERSION,
        "asOf": str(today or datetime.date.today()),
        "areaLabel": str(row.get("displayAreaLabel") or row.get("areaLabel") or ""),
        "fairPrice": {
            "lowEok": round(max(0.01, low), 2),
            "centerEok": round(center, 2),
            "highEok": round(max(high, low), 2),
            "widthPct": round(width_pct, 1),
            "method": "평가할 거래를 제외한 실거래 가격대 + 거래 공백 기간의 지역·주변 흐름 보정",
        },
        "dataQuality": {
            "level": quality,
            "sampleCount": sample_count,
            "latestTradeDate": latest_date,
            "latestTradeAgeDays": age_days,
            "marketContextAvailable": market["status"] == "available",
        },
        "marketAdjustmentPct": round(adjustment_pct, 2),
        "latestTradeExcluded": has_leave_one_out,
        "market": market,
        "macro": _macro_context(row),
        "reasons": reasons,
        "limitations": ["층·향·수리 상태와 실제 매물 상태는 반영하지 못했어요."],
    }


def verdict_for_price(valuation, price_eok):
    """Classify a price against a ready valuation. Useful for APIs and tests."""
    if not isinstance(valuation, dict) or valuation.get("status") != "ready":
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
        row["valuation"] = valuation_for_candidate(row, today=today)
