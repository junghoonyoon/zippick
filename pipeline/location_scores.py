#!/usr/bin/env python3
"""Apartment purchase-judgment composite score.

This is not an official creator formula. It is a data-backed complex score for
quickly comparing apartment cards with the data already available in the app.
Current listing asking prices and future supply are intentionally excluded from
this free score because those feeds are not connected yet.
"""

import datetime

import apartment_leaders
import kakao_station_distances
import real_estate_search


SCORE_FORMULA_VERSION = "purchase-judgment-v3"
MIN_PRICE_RANK_PEERS = 3
HOUSEHOLD_SCORE_BANDS = (
    (3000, None, 100.0, "3,000세대 이상"),
    (2000, 2999, 90.0, "2,000~2,999세대"),
    (1000, 1999, 78.0, "1,000~1,999세대"),
    (500, 999, 58.0, "500~999세대"),
    (300, 499, 42.0, "300~499세대"),
    (1, 299, 25.0, "1~299세대"),
)


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_score(value):
    if value is None:
        return None
    return max(0.0, min(100.0, float(value)))


def _count_text(value, unit):
    count = int(_float_or_none(value) or 0)
    return f"{count:,}{unit}" if count else ""


def _distance_text(value):
    distance = _float_or_none(value)
    if distance is None:
        return ""
    return f"{round(distance):,}m 거리"


def _price_text(value):
    price = _float_or_none(value)
    if price is None:
        return ""
    if price >= 1:
        return f"{price:.1f}".rstrip("0").rstrip(".") + "억원"
    return f"{round(price * 10000):,}만원"


def _candidate_price_reason(row):
    mid_price = _float_or_none(row.get("midPriceEok"))
    latest_price = _float_or_none(row.get("latestDealPriceEok"))
    if mid_price:
        return mid_price, f"예상 매수가 {_price_text(mid_price)} 기준"
    if latest_price:
        return latest_price, f"최근 실거래 {_price_text(latest_price)} 기준"
    return None, ""


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text[:7] + "-01"):
        try:
            return datetime.date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _leader_price_comparison_text(ratio):
    if ratio >= 1.05:
        return "대표 단지보다 높은 가격 추정"
    if ratio >= 0.95:
        return "대표 단지와 비슷한 가격 추정"
    if ratio >= 0.85:
        return "대표 단지에 가까운 가격 추정"
    if ratio >= 0.75:
        return "대표 단지보다 낮은 가격 추정"
    if ratio >= 0.65:
        return "대표 단지보다 꽤 낮은 가격 추정"
    if ratio >= 0.5:
        return "대표 단지의 절반 이상 가격 추정"
    return "대표 단지보다 많이 낮은 가격 추정"


def _region_group_key(row):
    region = real_estate_search.compact(row.get("region") or "")
    legal_dong = real_estate_search.compact(row.get("legalDong") or "")
    return region or legal_dong or "전체"


def _ranking_price_value(row):
    signals = row.get("signals") or {}
    ppsm = _float_or_none(signals.get("currentPpsm"))
    if ppsm and ppsm > 0:
        return ppsm
    for key in ("midPriceEok", "latestDealPriceEok", "averagePriceEok", "maxPriceEok", "minPriceEok"):
        price = _float_or_none(row.get(key))
        if price and price > 0:
            return price
    return None


def _price_rank_label(top_percent):
    if top_percent <= 10:
        return "최상위권 가격"
    if top_percent <= 25:
        return "상위권 가격"
    if top_percent <= 40:
        return "중상위권 가격"
    if top_percent <= 60:
        return "중간권 가격"
    if top_percent <= 80:
        return "중저가권 가격"
    return "낮은 가격"


def _price_burden_label(top_percent):
    if top_percent <= 10:
        return "가격 부담 높음"
    if top_percent <= 25:
        return "가격 부담 다소 높음"
    if top_percent <= 40:
        return "가격 부담 보통"
    if top_percent <= 60:
        return "중간 가격대"
    if top_percent <= 80:
        return "가격 부담 낮은 편"
    return "가격 부담 낮음"


def _price_rank_score(top_percent):
    if top_percent <= 10:
        return 100
    if top_percent <= 25:
        return 88
    if top_percent <= 40:
        return 74
    if top_percent <= 60:
        return 60
    if top_percent <= 80:
        return 44
    return 28


def _price_burden_score(top_percent):
    if top_percent <= 10:
        return 35
    if top_percent <= 25:
        return 55
    if top_percent <= 40:
        return 72
    if top_percent <= 60:
        return 86
    if top_percent <= 80:
        return 96
    return 88


def _price_rankings(rows):
    groups = {}
    for row in rows:
        price = _ranking_price_value(row)
        if price is None:
            continue
        groups.setdefault(_region_group_key(row), []).append((row, price))

    rankings = {}
    for group_rows in groups.values():
        if len(group_rows) < MIN_PRICE_RANK_PEERS:
            continue
        ordered = sorted(group_rows, key=lambda item: item[1], reverse=True)
        count = len(ordered)
        previous_price = None
        previous_rank = 0
        for index, (row, price) in enumerate(ordered, start=1):
            if previous_price is None or price != previous_price:
                previous_rank = index
                previous_price = price
            top_percent = max(1, round(previous_rank * 100 / count))
            rankings[id(row)] = {
                "rank": previous_rank,
                "count": count,
                "topPercent": top_percent,
                "label": _price_rank_label(top_percent),
                "score": _price_rank_score(top_percent),
            }
    return rankings


def _weighted_score(parts):
    available = [
        part for part in parts
        if part.get("score") is not None and part.get("weight", 0) > 0
    ]
    total_possible_weight = sum(part.get("weight", 0) for part in parts if part.get("weight", 0) > 0)
    if not available or total_possible_weight <= 0:
        return None, 0.0
    weighted = sum(part["score"] * part["weight"] / 100 for part in available)
    available_weight = sum(part["weight"] for part in available)
    normalized = weighted * 100 / available_weight
    return round(normalized), round(available_weight / total_possible_weight, 2)


def _price_level_score(row, signals):
    price_rank = row.get("_locationPriceRank") or {}
    if price_rank:
        score = price_rank.get("score")
        rank = price_rank.get("rank")
        count = price_rank.get("count")
        top_percent = price_rank.get("topPercent")
        label = price_rank.get("label")
        return score, f"지역 후보 {rank}/{count}위 · 상위 {top_percent}% · {label}"

    ppsm = _float_or_none(signals.get("currentPpsm"))
    reference = _float_or_none(signals.get("leaderReferencePpsm"))
    if ppsm and reference:
        ratio = ppsm / reference
        if ratio >= 0.95:
            score = 100
        elif ratio >= 0.85:
            score = 88
        elif ratio >= 0.75:
            score = 74
        elif ratio >= 0.65:
            score = 60
        elif ratio >= 0.5:
            score = 44
        else:
            score = 28
        return score, f"㎡당 {round(ppsm):,}만원 · {_leader_price_comparison_text(ratio)}"
    price, price_reason = _candidate_price_reason(row)
    if price:
        if price >= 30:
            return 100, price_reason
        if price >= 20:
            return 88, price_reason
        if price >= 15:
            return 76, price_reason
        if price >= 10:
            return 62, price_reason
        if price >= 7:
            return 48, price_reason
        return 34, price_reason
    return None, "가격 데이터 없음"


def _scale_score(row):
    households = int(_float_or_none(row.get("households")) or 0)
    band = _household_score_band(households)
    if band:
        return band["score"]
    return None


def _household_score_band(households):
    for minimum, maximum, score, label in HOUSEHOLD_SCORE_BANDS:
        if households >= minimum and (maximum is None or households <= maximum):
            return {"score": score, "label": label}
    return None


def _household_score_reason(row):
    households = int(_float_or_none(row.get("households")) or 0)
    household_text = _count_text(households, "세대")
    band = _household_score_band(households)
    if band:
        return f"{household_text} · {band['label']} 구간"
    return "세대수 데이터 없음"


def _leadership_score(row, signals):
    scale = _scale_score(row)
    price_score, _reason = _price_level_score(row, signals)
    households = int(_float_or_none(row.get("households")) or 0)
    household_text = _count_text(households, "세대")
    if signals.get("isRegionalLeader") or signals.get("isDistrictLeader"):
        return 100.0, f"{household_text} · 지역 대표 단지" if household_text else "지역 대표 단지"
    parts = [value for value in (scale, price_score) if value is not None]
    if not parts:
        return None, "대표성 데이터 없음"
    return round(sum(parts) / len(parts), 1), _household_score_reason(row)


def _scale_reason(row):
    return _household_score_reason(row)


def _regional_presence_score(row):
    scale = _scale_score(row)
    if scale is not None:
        return scale, _household_score_reason(row)
    return None, "세대수 데이터 없음"


def _transport_score(entity):
    station = kakao_station_distances.cached_station(entity) or {}
    distance = station.get("nearestStationDistance")
    if distance is None:
        distance = station.get("stationDistanceLowerBound")
    score = apartment_leaders.station_score(distance)
    if score is None:
        return None, "역거리 미수집"
    name = station.get("nearestStationName") or "가까운 역"
    distance_text = f"{round(float(distance)):,}m"
    return score, f"{name} · 직선 {distance_text}"


def _education_score(row):
    education = row.get("educationEnvironment") or {}
    score = _clamp_score(education.get("score"))
    if score is None:
        return None, "교육환경 데이터 준비 중"
    school_names = education.get("elementarySchoolNames") or []
    elementary_distance = _distance_text(education.get("elementaryDistanceMeters"))
    if education.get("basis") == "nearby_school_access":
        if school_names:
            distance_part = f" · {elementary_distance}" if elementary_distance else ""
            return score, f"{school_names[0]}{distance_part}"
        if education.get("middleSchoolNames"):
            middle_distance = _distance_text(education.get("middleDistanceMeters"))
            distance_part = f" · {middle_distance}" if middle_distance else ""
            return score, f"{education.get('middleSchoolNames')[0]}{distance_part}"
        return score, "주변 학교와 학원 접근성 기준"
    if school_names:
        distance_part = f" · {elementary_distance}" if elementary_distance else " · 배정권역"
        return score, f"{school_names[0]}{distance_part}"
    if education.get("middleZoneName"):
        return score, f"{education.get('middleZoneName')} 기준"
    return score, "배정학교와 주변 교육 접근성 기준"


def _product_score(row):
    status = str(row.get("status") or "").strip()
    if status in apartment_leaders.RANKABLE_PRESALE_STATUSES:
        return 100, f"{status} · 신축 예정"
    age = int(_float_or_none(row.get("buildingAge")) or 0)
    build_year = int(_float_or_none(row.get("buildYear")) or 0)
    if not build_year:
        return None, "연식 데이터 없음"
    if age <= 5:
        score = 100
    elif age <= 10:
        score = 85
    elif age <= 15:
        score = 70
    elif age <= 20:
        score = 55
    elif age <= 25:
        score = 40
    elif age <= 30:
        score = 25
    else:
        score = 15
    return score, f"{build_year}년 사용승인"


def _liquidity_score(row):
    recent_count = int(_float_or_none(row.get("recent3TradeCount")) or 0)
    count = recent_count or int(_float_or_none(row.get("transactionCount")) or 0)
    period = "최근 3개월" if recent_count else "최근"
    if count >= 20:
        return 100.0, f"{period} 거래 {count:,}건"
    if count >= 10:
        return 82.0, f"{period} 거래 {count:,}건"
    if count >= 5:
        return 62.0, f"{period} 거래 {count:,}건"
    if count >= 2:
        return 38.0, f"{period} 거래 {count:,}건"
    if count == 1:
        return 18.0, f"{period} 거래 1건"
    return None, "최근 거래 부족"


def _flow_score(signals):
    score = _clamp_score(signals.get("score"))
    if score is None:
        return None, "흐름 데이터 없음"
    momentum = _float_or_none(signals.get("momentumPct"))
    if momentum is None:
        return score, "최근 가격·거래 흐름 기준"
    return score, f"최근 6개월 {momentum:+.1f}% · 가격·거래 흐름"


def _jeonse_ratio_score(row):
    ratio = _float_or_none(row.get("jeonseRatioPct"))
    if ratio is None or ratio <= 0:
        return None, "전세 실거래 데이터 없음"
    deposit = _float_or_none(row.get("latestJeonseDepositEok"))
    sale_basis = _float_or_none(row.get("jeonseSalePriceBasisEok"))
    count = int(_float_or_none(row.get("jeonseTransactionCount")) or 0)
    date = str(row.get("latestJeonseDate") or "").strip()
    if ratio >= 70:
        score = 100
    elif ratio >= 65:
        score = 88
    elif ratio >= 60:
        score = 74
    elif ratio >= 55:
        score = 60
    elif ratio >= 50:
        score = 44
    else:
        score = 28
    details = [f"전세가율 {ratio:g}%"]
    if deposit and sale_basis:
        details.append(f"전세 {_price_text(deposit)} · 매매 기준 {_price_text(sale_basis)}")
    if count:
        details.append(f"전세 거래 {count}건")
    if date:
        details.append(f"마지막 거래 {date}")
    return score, " · ".join(details)


def _latest_trade_in_estimate_range_score(row):
    latest = _float_or_none(row.get("latestDealPriceEok"))
    low = _float_or_none(row.get("currentEstimateMinPriceEok"))
    high = _float_or_none(row.get("currentEstimateMaxPriceEok"))
    if not latest or not low or not high:
        return None, "최근 실거래와 추정 범위 데이터 없음"
    low, high = min(low, high), max(low, high)
    if low <= latest <= high:
        return 100, f"최근 거래 {_price_text(latest)} · 예상 가격 안"
    nearest = low if latest < low else high
    gap = abs(latest - nearest) / nearest if nearest else 0
    if gap <= 0.03:
        score = 82
    elif gap <= 0.07:
        score = 62
    elif gap <= 0.12:
        score = 42
    else:
        score = 22
    direction = "높아요" if latest > high else "낮아요"
    return score, f"최근 거래 {_price_text(latest)} · 예상 {_price_text(low)}~{_price_text(high)}보다 {direction}"


def _leader_gap_price_score(row, signals):
    gap = _float_or_none(signals.get("leaderGapPct"))
    if gap is None:
        ppsm = _float_or_none(signals.get("currentPpsm"))
        reference = _float_or_none(signals.get("leaderReferencePpsm"))
        if ppsm and reference:
            gap = (1 - ppsm / reference) * 100
    if gap is None:
        current = _float_or_none(row.get("latestDealPriceEok")) or _float_or_none(row.get("midPriceEok"))
        leader_price = (
            _float_or_none(signals.get("leaderPrice12m"))
            or _float_or_none(signals.get("leaderRepresentativeMedianPrice12m"))
        )
        if current and leader_price:
            gap = (1 - current / leader_price) * 100
    if gap is None:
        return None, "지역 대장 가격 비교 데이터 없음"
    if 20 <= gap <= 45:
        score = 100
    elif 10 <= gap < 20 or 45 < gap <= 60:
        score = 82
    elif 0 <= gap < 10 or 60 < gap <= 70:
        score = 58
    elif gap < 0:
        score = 30
    else:
        score = 42
    if gap >= 0:
        return score, f"지역 대장보다 {gap:.1f}% 낮음"
    return score, f"지역 대장보다 {abs(gap):.1f}% 높음"


def _price_rank_burden_score(row, signals):
    price_rank = row.get("_locationPriceRank") or {}
    if price_rank:
        score = _price_burden_score(price_rank.get("topPercent") or 100)
        return (
            score,
            f"지역 후보 {price_rank.get('rank')}/{price_rank.get('count')}위 · {_price_burden_label(price_rank.get('topPercent') or 100)}",
        )
    price_score, price_reason = _price_level_score(row, signals)
    return price_score, price_reason


def _recovery_score(row, signals):
    recovery = _float_or_none(signals.get("recoveryPct"))
    fallback_basis = ""
    if recovery is None:
        current = (
            _float_or_none(row.get("currentEstimateMidPriceEok"))
            or _float_or_none(row.get("latestDealPriceEok"))
            or _float_or_none(row.get("midPriceEok"))
        )
        peak = (
            _float_or_none(row.get("recentMaxPriceEok"))
            or _float_or_none(row.get("maxPriceEok"))
            or _float_or_none(row.get("highestDealPriceEok"))
        )
        if current and peak:
            recovery = round(current / peak * 100, 1)
            fallback_basis = "최근 최고가 기준 · "
    if recovery is None:
        return None, "전고점 회복률 데이터 없음"
    if 82 <= recovery <= 94:
        score = 100
    elif 74 <= recovery < 82:
        score = 84
    elif 94 < recovery <= 98:
        score = 70
    elif 60 <= recovery < 74:
        score = 58
    elif recovery > 98:
        score = 48
    else:
        score = 34
    if recovery >= 100:
        return score, f"{fallback_basis}전고점 이상 · {recovery:.1f}%"
    return score, f"{fallback_basis}전고점 대비 {100 - recovery:.1f}% 낮음"


def _jeonse_freshness_score(row):
    count = int(_float_or_none(row.get("jeonseTransactionCount")) or 0)
    date = _parse_date(row.get("latestJeonseDate"))
    if not count and not date:
        return None, "전세 거래 건수와 최신성 데이터 없음"
    count_score = 100 if count >= 5 else 78 if count >= 3 else 55 if count >= 1 else 25
    if date:
        age_days = max(0, (datetime.date.today() - date).days)
        fresh_score = 100 if age_days <= 90 else 78 if age_days <= 180 else 55 if age_days <= 365 else 30
        reason = f"전세 거래 {count}건 · 마지막 {date.isoformat()}"
    else:
        fresh_score = 40
        reason = f"전세 거래 {count}건 · 날짜 미확인"
    return round((count_score + fresh_score) / 2, 1), reason


def _investment_gap_score(row):
    deposit = _float_or_none(row.get("latestJeonseDepositEok"))
    sale_basis = _float_or_none(row.get("jeonseSalePriceBasisEok"))
    if not deposit or not sale_basis:
        return None, "매매가와 전세가 차이 데이터 없음"
    gap = max(0.0, sale_basis - deposit)
    gap_ratio = gap / sale_basis * 100 if sale_basis else None
    if gap_ratio is None:
        return None, "매매가와 전세가 차이 데이터 없음"
    if gap_ratio <= 30:
        score = 100
    elif gap_ratio <= 35:
        score = 88
    elif gap_ratio <= 40:
        score = 74
    elif gap_ratio <= 45:
        score = 60
    elif gap_ratio <= 50:
        score = 44
    else:
        score = 28
    return score, f"필요한 내 돈 {_price_text(gap)} · 매매가의 {gap_ratio:.1f}%"


def _commute_access_score(row):
    score = _float_or_none(row.get("commuteAccessScore"))
    reason = str(row.get("commuteAccessReason") or "").strip()
    if score is not None:
        return score, reason or "입력한 직장권을 권역 기준으로 반영"
    if row.get("commuteMatched"):
        return 75.0, "입력한 직장권과 권역 기준 1차 일치"
    if row.get("commuteAccessRequested"):
        return None, "입력한 직장권의 실제 이동시간 데이터 없음"
    return None, "직장권 실제 이동시간 데이터 없음"


def _regional_representation_score(row, signals):
    if signals.get("isRegionalLeader") or signals.get("isDistrictLeader"):
        return 100.0, "지역 대장 단지"
    price_score, price_reason = _price_level_score(row, signals)
    scale_score = _scale_score(row)
    values = [value for value in (price_score, scale_score) if value is not None]
    if not values:
        return None, "가격·거래 대표성 데이터 없음"
    return round(sum(values) / len(values), 1), price_reason or _household_score_reason(row)


def _brand_product_score(row, entity):
    brand = str((entity or {}).get("brand") or row.get("brand") or "").strip()
    if not brand:
        return None, "주차·평면·브랜드 데이터 없음"
    score = _clamp_score(apartment_leaders.SETTINGS.get("brandScores", {}).get(brand))
    if score is None:
        return None, f"{brand} · 브랜드 점수 데이터 없음"
    return score, f"{brand} 브랜드 반영 · 주차·평면 미반영"


def _confirmed_change_score(row):
    catalyst = row.get("newsCatalyst") or {}
    if isinstance(catalyst, dict) and str(catalyst.get("label") or "").strip():
        return 100.0, str(catalyst.get("label")).strip()
    return None, "확정 변화 데이터 없음"


def _relative_flow_score(signals):
    scores = []
    reasons = []
    district = _float_or_none(signals.get("districtRelativePct"))
    leader = _float_or_none(signals.get("leaderRelativePct"))
    if district is not None:
        scores.append(100 if district >= 5 else 82 if district >= 2 else 62 if district >= 0 else 40 if district >= -3 else 22)
        reasons.append(f"지역 평균 대비 {district:+.1f}%")
    if leader is not None:
        scores.append(100 if leader >= 3 else 80 if leader >= 0 else 55 if leader >= -3 else 32)
        reasons.append(f"대장 대비 {leader:+.1f}%")
    if not scores:
        return None, "지역 평균·대장 대비 상승률 데이터 없음"
    return round(sum(scores) / len(scores), 1), " · ".join(reasons)


def _sample_confidence_score(row, signals):
    confidence = str(signals.get("sampleConfidence") or "").strip().lower()
    if confidence == "high":
        return 100.0, "실거래 표본 신뢰도 높음"
    if confidence == "medium":
        return 72.0, "실거래 표본 신뢰도 보통"
    if confidence == "low":
        return 38.0, "실거래 표본 신뢰도 낮음"
    count = int(_float_or_none(row.get("transactionCount")) or 0)
    if count >= 12:
        return 72.0, f"최근 거래 {count}건 · 표본 보통"
    if count >= 3:
        return 38.0, f"최근 거래 {count}건 · 표본 적음"
    return None, "실거래 표본 데이터 부족"


def _metric(key, label, weight, score, reason):
    score = _clamp_score(score)
    if score is None:
        return {
            "key": key,
            "label": label,
            "points": None,
            "maxPoints": weight,
            "score": None,
            "reason": reason,
            "status": "missing",
        }
    points = round(score * weight / 100, 1)
    return {
        "key": key,
        "label": label,
        "points": points,
        "maxPoints": weight,
        "score": round(score),
        "reason": reason,
        "status": "ok",
    }


def _metric_lookup(metrics, key):
    for metric in metrics:
        if metric.get("key") == key:
            return metric
    return {}


def _category_summary(key, score, metrics):
    if score is None:
        return "반영할 데이터 없음"
    if key == "price":
        estimate = _metric_lookup(metrics, "estimate_range")
        estimate_score = _clamp_score(estimate.get("score"))
        estimate_reason = str(estimate.get("reason") or "")
        if estimate_score is not None:
            if estimate_score >= 80:
                return "최근 거래가 예상 가격과 잘 맞아요"
            if "높아요" in estimate_reason:
                return "최근 거래가 예상 가격보다 높아 가격 확인이 필요해요"
            if "낮아요" in estimate_reason:
                return "최근 거래가 예상 가격보다 낮게 찍혔어요"
            return "최근 거래가 예상 가격과 조금 달라요"
        price_rank = _metric_lookup(metrics, "price_rank")
        price_rank_reason = str(price_rank.get("reason") or "")
        price_rank_score = _clamp_score(price_rank.get("score"))
        if price_rank_score is not None:
            if price_rank_score >= 85:
                return "지역 안에서는 가격 부담이 낮은 편이에요"
            if price_rank_score >= 65:
                return "지역 안에서는 중간 가격대예요"
            return "지역 안에서는 가격 부담이 있는 편이에요"
        if price_rank_reason:
            return price_rank_reason
        return "가격 기준을 더 확인해야 해요"
    if key == "jeonse":
        ratio = _metric_lookup(metrics, "jeonse_ratio")
        ratio_score = _clamp_score(ratio.get("score"))
        if ratio_score is None:
            return "같은 평형 전세 거래를 더 확인해야 해요"
        if ratio_score >= 74:
            return "전세금 비중이 높아 내 돈 부담이 낮은 편이에요"
        if ratio_score >= 44:
            return "전세금 비중은 보통이에요"
        return "전세금 비중이 낮아 내 돈이 많이 들어가요"
    if key == "demand":
        if score >= 80:
            return "역·학교 접근성이 좋은 편이에요"
        if score >= 60:
            return "입지는 무난하지만 세부 확인이 필요해요"
        return "입지 조건은 더 따져봐야 해요"
    if key == "product":
        age = _metric_lookup(metrics, "age")
        age_reason = str(age.get("reason") or "")
        if "분양권" in age_reason:
            return "신축 예정이라 연식은 좋은 편이에요"
        if score >= 80:
            return "단지 규모와 연식이 좋은 편이에요"
        if score >= 60:
            return "단지 조건은 무난해요"
        return "단지 조건은 아쉬운 편이에요"
    if key == "market":
        if score >= 80:
            return "거래와 가격 흐름이 좋은 편이에요"
        if score >= 60:
            return "거래 흐름은 보통이에요"
        return "거래 흐름은 조심해서 봐야 해요"
    available = [metric for metric in metrics if metric.get("score") is not None]
    return available[0]["reason"] if available else "반영할 데이터 없음"


def _category_part(key, label, weight, metrics):
    score, coverage = _weighted_score([
        {"score": metric.get("score"), "weight": metric.get("maxPoints")}
        for metric in metrics
    ])
    available = [metric for metric in metrics if metric.get("score") is not None]
    if score is None:
        part = _part(key, label, weight, None, "반영할 데이터 없음")
    else:
        reason = _category_summary(key, score, metrics)
        part = _part(key, label, weight, score, reason)
        part["basis"] = f"산식: 반영 지표 {len(available)}/{len(metrics)}개 · {score}/100 × {weight:g}점 = {part['points']:g}/{weight:g}점"
    part["coverage"] = coverage
    part["details"] = metrics
    return part


def _purchase_score_parts(row, entity, signals):
    price_rank_score, price_rank_reason = _price_rank_burden_score(row, signals)
    leader_gap_score, leader_gap_reason = _leader_gap_price_score(row, signals)
    estimate_score, estimate_reason = _latest_trade_in_estimate_range_score(row)
    recovery_score, recovery_reason = _recovery_score(row, signals)
    jeonse_score, jeonse_reason = _jeonse_ratio_score(row)
    jeonse_fresh_score, jeonse_fresh_reason = _jeonse_freshness_score(row)
    invest_gap_score, invest_gap_reason = _investment_gap_score(row)
    commute_score, commute_reason = _commute_access_score(row)
    station_score, station_reason = _transport_score(entity) if entity else (None, "역거리 미수집")
    education_score, education_reason = _education_score(row)
    representative_score, representative_reason = _regional_representation_score(row, signals)
    household_score = _scale_score(row)
    change_score, change_reason = _confirmed_change_score(row)
    liquidity_score, liquidity_reason = _liquidity_score(row)
    relative_flow_score, relative_flow_reason = _relative_flow_score(signals)
    confidence_score, confidence_reason = _sample_confidence_score(row, signals)

    demand_metrics = [
        _metric("station", "역 접근성", 5, station_score, station_reason),
        _metric("education", "교육 접근성", 4, education_score, education_reason),
        _metric("representation", "지역 대표성", 3, representative_score, representative_reason),
    ]
    if row.get("commuteAccessRequested") or commute_score is not None:
        demand_metrics.insert(0, _metric("commute", "직장권 접근성", 8, commute_score, commute_reason))

    return [
        _category_part("price", "가격 적정성", 30, [
            _metric("price_rank", "지역 가격 순위", 10, price_rank_score, price_rank_reason),
            _metric("leader_gap", "대장 가격 차이", 7, leader_gap_score, leader_gap_reason),
            _metric("estimate_range", "추정 시세 범위", 8, estimate_score, estimate_reason),
            _metric("recovery", "고점 회복률", 5, recovery_score, recovery_reason),
        ]),
        _category_part("jeonse", "전세가율·투자금 효율", 20, [
            _metric("jeonse_ratio", "전세가율", 12, jeonse_score, jeonse_reason),
            _metric("jeonse_freshness", "전세 거래", 5, jeonse_fresh_score, jeonse_fresh_reason),
            _metric("investment_gap", "필요 투자금", 3, invest_gap_score, invest_gap_reason),
        ]),
        _category_part("demand", "입지·실수요", 20, demand_metrics),
        _category_part("product", "상품성·희소성", 15, [
            _metric("households", "세대수", 6, household_score, _household_score_reason(row)),
            _metric("age", "준공연도", 6, *_product_score(row)),
            _metric("confirmed_change", "확정 변화", 3, change_score, change_reason),
        ]),
        _category_part("market", "거래 유동성·시장 흐름", 15, [
            _metric("liquidity", "최근 거래량", 6, liquidity_score, liquidity_reason),
            _metric("relative_flow", "지역·대장 대비 흐름", 6, relative_flow_score, relative_flow_reason),
            _metric("sample_confidence", "표본 신뢰도", 3, confidence_score, confidence_reason),
        ]),
    ]


def _area_analysis(row, signals):
    price_score, price_reason = _price_level_score(row, signals)
    liquidity_score, liquidity_reason = _liquidity_score(row)
    flow_score, flow_reason = _flow_score(signals)
    jeonse_score, jeonse_reason = _jeonse_ratio_score(row)
    area_label = row.get("displayAreaLabel") or row.get("areaLabel") or "선택 평형"
    parts = [
        _part("price", "가격 위치", 100, price_score, price_reason),
        _part("jeonse", "전세가율", 100, jeonse_score, jeonse_reason),
        _part("liquidity", "거래 유동성", 100, liquidity_score, liquidity_reason),
        _part("flow", "최근 흐름", 100, flow_score, flow_reason),
    ]
    return {
        "title": "선택 평형 가격·거래 분석",
        "areaLabel": area_label,
        "summary": f"{area_label} 기준 가격, 거래 수, 최근 흐름이에요.",
        "leaderLabel": "지역 대표 가격 흐름" if signals.get("isRegionalLeader") or signals.get("isDistrictLeader") else "",
        "parts": parts,
    }


def _part(key, label, weight, score, reason):
    if score is None:
        return {
            "key": key,
            "label": label,
            "points": None,
            "maxPoints": weight,
            "score": None,
            "reason": reason,
            "status": "missing",
        }
    points = round(float(score) * weight / 100, 1)
    points_text = f"{points:g}"
    weight_text = f"{weight:g}"
    score_text = f"{round(float(score)):g}"
    return {
        "key": key,
        "label": label,
        "points": points,
        "maxPoints": weight,
        "score": round(float(score)),
        "reason": reason,
        "basis": f"산식: {score_text}/100 × {weight_text}점 = {points_text}/{weight_text}점",
        "status": "ok",
    }


def _weighted_score_for_categories(parts):
    weighted_parts = []
    for part in parts:
        score = part.get("score")
        coverage = _float_or_none(part.get("coverage"))
        weight = _float_or_none(part.get("maxPoints")) or 0
        if score is None or weight <= 0:
            continue
        effective_weight = weight * (coverage if coverage is not None else 1)
        if effective_weight <= 0:
            continue
        weighted_parts.append({"score": score, "weight": effective_weight})
    if not weighted_parts:
        return None, 0.0
    score, _coverage = _weighted_score(weighted_parts)
    total_weight = sum(_float_or_none(part.get("maxPoints")) or 0 for part in parts)
    available_weight = sum(part["weight"] for part in weighted_parts)
    return score, round(available_weight / total_weight, 2) if total_weight else 0.0


def score_for_candidate(row, entity):
    signals = row.get("signals") or {}
    parts = _purchase_score_parts(row, entity, signals)
    score, coverage = _weighted_score_for_categories(parts)
    if score is None:
        return {"status": "insufficient", "score": None, "parts": parts}
    if score >= 80:
        label = "매우 좋음"
    elif score >= 65:
        label = "좋음"
    elif score >= 50:
        label = "보통"
    else:
        label = "확인 필요"
    return {
        "status": "ok",
        "scoreFormulaVersion": SCORE_FORMULA_VERSION,
        "score": score,
        "label": label,
        "coverage": coverage,
        "title": "현재 데이터 기준 종합 점수",
        "summary": "실거래가, 전세 실거래, 입지, 단지 조건, 거래 흐름을 함께 본 점수예요.",
        "parts": parts,
        "areaAnalysis": {"parts": []},
        "source": "현재 앱 데이터 기준",
        "apartmentKey": real_estate_search.compact(row.get("displayName") or row.get("name")),
    }


def attach_scores(rows, entity_lookup):
    rankings = _price_rankings(rows)
    for row in rows:
        try:
            if id(row) in rankings:
                row["_locationPriceRank"] = rankings[id(row)]
            entity = entity_lookup(row)
            row["locationScore"] = score_for_candidate(row, entity)
        except Exception:
            row["locationScore"] = {"status": "error", "score": None, "parts": []}
        finally:
            row.pop("_locationPriceRank", None)
    return rows
