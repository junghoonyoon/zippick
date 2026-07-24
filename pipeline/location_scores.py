#!/usr/bin/env python3
"""Apartment top-card composite score.

This is not an official creator formula. It is a data-backed complex score for
quickly comparing apartment cards with the data already available in the app.
Selected-unit price and trade movement are exposed as a separate analysis so the
same apartment keeps the same composite score when users switch unit sizes.
"""

import apartment_leaders
import kakao_station_distances
import real_estate_search


SCORE_FORMULA_VERSION = "complex-score-v2"
MIN_PRICE_RANK_PEERS = 3


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
    if households >= 3000:
        return 100.0
    if households >= 2000:
        return 90.0
    if households >= 1000:
        return 78.0
    if households >= 500:
        return 58.0
    if households >= 300:
        return 42.0
    if households > 0:
        return 25.0
    return None


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
    if households >= 1000:
        reason = f"{household_text} · 1,000세대 이상"
    elif household_text:
        reason = f"{household_text} · 단지 규모 기준"
    else:
        reason = "가격대와 단지 규모 기준"
    return round(sum(parts) / len(parts), 1), reason


def _scale_reason(row):
    households = int(_float_or_none(row.get("households")) or 0)
    household_text = _count_text(households, "세대")
    if households >= 1000:
        return f"{household_text} · 1,000세대 이상"
    if household_text:
        return f"{household_text} · 단지 규모 기준"
    return "세대수 데이터 없음"


def _regional_presence_score(row):
    households = int(_float_or_none(row.get("households")) or 0)
    household_text = _count_text(households, "세대")
    scale = _scale_score(row)
    if scale is not None:
        if households >= 2000:
            return 90.0, f"{household_text} · 지역에서 눈에 띄는 대단지"
        if households >= 1000:
            return 78.0, f"{household_text} · 지역에서 비교하기 좋은 대단지"
        return scale, f"{household_text} · 단지 규모 기준"
    return None, "지역 대표성 데이터 없음"


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


def _area_analysis(row, signals):
    price_score, price_reason = _price_level_score(row, signals)
    liquidity_score, liquidity_reason = _liquidity_score(row)
    flow_score, flow_reason = _flow_score(signals)
    area_label = row.get("displayAreaLabel") or row.get("areaLabel") or "선택 평형"
    parts = [
        _part("price", "가격 위치", 100, price_score, price_reason),
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
    return {
        "key": key,
        "label": label,
        "points": round(float(score) * weight / 100, 1),
        "maxPoints": weight,
        "score": round(float(score)),
        "reason": reason,
        "status": "ok",
    }


def score_for_candidate(row, entity):
    signals = row.get("signals") or {}
    region_score, region_reason = _regional_presence_score(row)
    scale_score, scale_reason = _scale_score(row), _scale_reason(row)
    transport_score, transport_reason = _transport_score(entity) if entity else (None, "역거리 미수집")
    education_score, education_reason = _education_score(row)
    product_score, product_reason = _product_score(row)

    parts = [
        _part("region", "지역 위상", 20, region_score, region_reason),
        _part("scale", "단지 규모", 20, scale_score, scale_reason),
        _part("transport", "교통 접근성", 20, transport_score, transport_reason),
        _part("education", "교육환경", 20, education_score, education_reason),
        _part("product", "상품성", 20, product_score, product_reason),
    ]
    score, coverage = _weighted_score([
        {"score": part["score"], "weight": part["maxPoints"]}
        for part in parts
    ])
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
        "title": "단지 종합점수",
        "summary": "평형과 상관없는 단지, 교통, 교육, 상품성을 함께 본 점수예요.",
        "parts": parts,
        "areaAnalysis": _area_analysis(row, signals),
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
