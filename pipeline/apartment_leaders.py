#!/usr/bin/env python3
"""시·군·구와 전용면적 구간별 대장아파트 순위를 계산한다.

실거래와 단지 마스터만 사용하며, 단지명 자체를 대장으로 지정하지 않는다.
지하철 거리·브랜드처럼 현재 원천에 없는 값은 ``None``으로 유지하고 결과의
데이터 보유율과 경고에 반영한다.
"""
import argparse
import calendar
import datetime
import hashlib
import json
import math
import os
import statistics
from pathlib import Path

import config
import molit_transactions
import real_estate_search


SETTINGS_PATH = config.ROOT / "data" / "apartment_leader_settings.json"
CACHE_DIR = config.CACHE_DIR / "apartment_leaders"
AREA_BUCKETS = {
    "lt39": {"label": "39㎡ 미만", "low": None, "high": 39},
    "39-49": {"label": "39~49㎡", "low": 39, "high": 50},
    "50-69": {"label": "50~69㎡", "low": 50, "high": 70},
    "70-89": {"label": "70~89㎡", "low": 70, "high": 90},
    "90plus": {"label": "90㎡ 이상", "low": 90, "high": None},
}
CATEGORY_FIELDS = {
    "overall": "overallScore",
    "price": "priceScore",
    "leadership": "leadershipScore",
    "residence": "residenceScore",
    "new_build": "newBuildScore",
    "value": "valueScore",
}
CATEGORY_LABELS = {
    "overall": "종합",
    "price": "가격",
    "leadership": "상승 선도",
    "residence": "실거주",
    "new_build": "신축",
    "value": "가성비",
}
MAX_REASON_COUNT = 4
DEFAULT_LIMIT = 5


def _load_settings():
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


SETTINGS = _load_settings()
CALCULATION_VERSION = SETTINGS["calculationVersion"]
DEFAULT_AREA_BUCKET = SETTINGS["defaultAreaBucket"]


def area_bucket(exclusive_area):
    """전용면적을 문서의 다섯 구간 중 하나로 분류한다."""
    try:
        value = float(exclusive_area)
    except (TypeError, ValueError):
        return None
    if value < 39:
        return "lt39"
    if value < 50:
        return "39-49"
    if value < 70:
        return "50-69"
    if value < 90:
        return "70-89"
    return "90plus"


def percentile_ranks(values):
    """동점은 평균 순위를 쓰는 0~100 백분위 순위를 반환한다."""
    available = sorted(float(value) for value in values if value is not None)
    if not available:
        return [None for _value in values]
    if len(available) == 1:
        return [100.0 if value is not None else None for value in values]
    positions = {}
    index = 0
    while index < len(available):
        end = index + 1
        while end < len(available) and available[end] == available[index]:
            end += 1
        positions[available[index]] = ((index + end - 1) / 2) / (len(available) - 1) * 100
        index = end
    return [
        round(positions[float(value)], 1) if value is not None else None
        for value in values
    ]


def age_score(completion_date, reference_month):
    """준공연월을 완만한 구간 점수로 변환한다."""
    text = str(completion_date or "").strip()
    if not text:
        return None
    try:
        year = int(text[:4])
        month = int(text[5:7]) if len(text) >= 7 and text[4] in {"-", "."} else 1
        reference = _parse_reference_month(reference_month)
        age = max(0, (reference.year * 12 + reference.month - (year * 12 + month)) // 12)
    except (TypeError, ValueError):
        return None
    if age <= 5:
        return 100.0
    if age <= 10:
        return 85.0
    if age <= 15:
        return 70.0
    if age <= 20:
        return 55.0
    if age <= 25:
        return 40.0
    if age <= 30:
        return 25.0
    return 15.0


def station_score(distance_meters):
    """가장 가까운 역까지의 거리 점수. 거리 미보유 시 None이다."""
    if distance_meters is None or distance_meters == "":
        return None
    try:
        distance = float(distance_meters)
    except (TypeError, ValueError):
        return None
    if distance <= 300:
        return 100.0
    if distance <= 500:
        return 90.0
    if distance <= 700:
        return 75.0
    if distance <= 1000:
        return 55.0
    if distance <= 1500:
        return 30.0
    return 10.0


def confidence_for_count(transaction_count):
    count = max(0, int(transaction_count or 0))
    if count >= 10:
        return 100.0, "HIGH", "높음", 1.0
    if count >= 5:
        return 75.0, "MEDIUM", "보통", 0.8
    if count >= 2:
        return 40.0, "LOW", "낮음", 0.5
    if count == 1:
        return 15.0, "CANDIDATE", "후보", 0.2
    return 0.0, "EXCLUDED", "계산 불가", 0.0


def adjusted_price(complex_median, district_median, transaction_count):
    """거래가 적은 단지 가격을 지역 중앙값 쪽으로 보정한다."""
    if complex_median is None or district_median is None:
        return None
    confidence_weight = confidence_for_count(transaction_count)[3]
    if confidence_weight <= 0:
        return None
    return round(
        float(complex_median) * confidence_weight
        + float(district_median) * (1 - confidence_weight),
        4,
    )


def _parse_reference_month(value=None):
    text = str(value or "").strip()
    if not text:
        today = datetime.date.today()
        year, month = today.year, today.month - 1
        if month == 0:
            year -= 1
            month = 12
        return datetime.date(year, month, 1)
    try:
        year, month = map(int, text[:7].split("-"))
        return datetime.date(year, month, 1)
    except (TypeError, ValueError):
        raise ValueError("기준월은 YYYY-MM 형식이어야 합니다.")


def _month_shift(month_date, offset):
    ordinal = month_date.year * 12 + month_date.month - 1 + offset
    return datetime.date(ordinal // 12, ordinal % 12 + 1, 1)


def _month_key(value):
    return str(value or "")[:7]


def _window_dates(reference_month, months):
    reference = _parse_reference_month(reference_month)
    start = _month_shift(reference, -(months - 1))
    end = datetime.date(
        reference.year,
        reference.month,
        calendar.monthrange(reference.year, reference.month)[1],
    )
    return start, end


def _valid_transaction(row):
    try:
        area = float(row.get("exclusiveArea") or 0)
        price = float(row.get("dealAmountManwon") or 0)
        datetime.date.fromisoformat(str(row.get("dealDate") or "")[:10])
    except (TypeError, ValueError):
        return False
    if area <= 0 or price <= 0:
        return False
    if row.get("isCanceled"):
        return False
    if str(row.get("cancellationDate") or "").strip():
        return False
    if real_estate_search.compact(row.get("dealType")) == real_estate_search.compact("직거래"):
        return False
    return True


def _transactions_in_window(transactions, reference_month, months=12, bucket=DEFAULT_AREA_BUCKET):
    start, end = _window_dates(reference_month, months)
    return [
        row for row in transactions
        if _valid_transaction(row)
        and area_bucket(row.get("exclusiveArea")) == bucket
        and start <= datetime.date.fromisoformat(str(row["dealDate"])[:10]) <= end
    ]


def _monthly_medians(transactions, value_getter):
    grouped = {}
    for row in transactions:
        value = value_getter(row)
        if value is not None and value > 0:
            grouped.setdefault(_month_key(row.get("dealDate")), []).append(value)
    return {
        month: statistics.median(values)
        for month, values in grouped.items()
        if values
    }


def _month_value(monthly, target, maximum_gap=3):
    for gap in range(maximum_gap + 1):
        key = _month_shift(target, -gap).strftime("%Y-%m")
        if key in monthly:
            return monthly[key], gap
    return None, None


def _period_return(monthly, reference_month, months):
    reference = _parse_reference_month(reference_month)
    current, current_gap = _month_value(monthly, reference)
    baseline, baseline_gap = _month_value(monthly, _month_shift(reference, -months))
    if current is None or baseline is None or baseline <= 0:
        return None, None
    total_gap = int(current_gap or 0) + int(baseline_gap or 0)
    return round((current / baseline - 1) * 100, 2), total_gap


def _price_per_square_meter(row):
    area = float(row.get("exclusiveArea") or 0)
    price = float(row.get("dealAmountManwon") or 0)
    return price / area if area > 0 and price > 0 else None


def _weighted_score(values, weights):
    pairs = [
        (float(values[key]), float(weight))
        for key, weight in weights.items()
        if values.get(key) is not None and float(weight) > 0
    ]
    if not pairs:
        return None, 0.0
    available_weight = sum(weight for _value, weight in pairs)
    score = sum(value * weight for value, weight in pairs) / available_weight
    return round(score, 1), round(available_weight * 100, 1)


def _entity_id(entity):
    material = entity.get("dedupeKey") or "|".join(str(entity.get(key) or "") for key in (
        "province", "district", "legalDong", "name",
    ))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _region_matches(value, target):
    value_key = real_estate_search.compact(value)
    target_key = real_estate_search.compact(target)
    if not target_key:
        return True
    aliases = {
        "서울": "서울특별시",
        "서울시": "서울특별시",
        "경기": "경기도",
    }
    target_key = real_estate_search.compact(aliases.get(str(target).strip(), target))
    return bool(value_key and (value_key == target_key or value_key in target_key or target_key in value_key))


def matching_entities(sido, sigungu):
    rows = []
    seen = set()
    for entity in real_estate_search.APARTMENT_MASTER:
        if (
            entity.get("aggregate")
            or entity.get("status")
            or not _region_matches(entity.get("province"), sido)
            or not _region_matches(entity.get("district"), sigungu)
        ):
            continue
        key = _entity_id(entity)
        if key in seen:
            continue
        seen.add(key)
        rows.append(entity)
    return rows


def leader_regions():
    grouped = {}
    for entity in real_estate_search.APARTMENT_MASTER:
        if entity.get("aggregate") or entity.get("status"):
            continue
        sido = str(entity.get("province") or "").strip()
        sigungu = str(entity.get("district") or "").strip()
        if sido and sigungu:
            grouped.setdefault(sido, set()).add(sigungu)
    return [
        {"sido": sido, "sigungu": sorted(values)}
        for sido, values in sorted(grouped.items())
    ]


def _lookback_months(reference_month):
    reference = _parse_reference_month(reference_month)
    current = datetime.date.today().replace(day=1)
    difference = (current.year - reference.year) * 12 + current.month - reference.month
    return max(24, min(60, difference + 14))


def _prefetch_region_months(entities, lookback_months, cache_only):
    if cache_only or not molit_transactions.enabled():
        return
    lawd_codes = {
        str(entity.get("lawdCd") or "")[:5]
        for entity in entities
        if str(entity.get("lawdCd") or "")[:5].isdigit()
    }
    months = molit_transactions._deal_months(lookback_months)
    molit_transactions.prefetch_months(
        ((lawd_code, month) for lawd_code in lawd_codes for month in months),
    )


def _load_transactions(entities, reference_month, cache_only):
    lookback_months = _lookback_months(reference_month)
    _prefetch_region_months(entities, lookback_months, cache_only)
    loader = molit_transactions.transactions_for_apartment_cached
    if not cache_only and molit_transactions.enabled():
        # 위에서 월 캐시를 지역 단위로 채웠으므로 개별 단지 조회도 캐시만 읽는다.
        loader = molit_transactions.transactions_for_apartment_cached
    rows = []
    for entity in entities:
        try:
            transactions = loader(
                entity.get("name", ""),
                region=entity.get("district", ""),
                area_label="",
                lookback_months=lookback_months,
                entity=entity,
            )
        except Exception:
            transactions = []
        rows.append((entity, transactions))
    return rows


def _base_metrics(entity, transactions, reference_month, bucket):
    trades12 = _transactions_in_window(transactions, reference_month, 12, bucket)
    trades24 = _transactions_in_window(transactions, reference_month, 24, bucket)
    prices = [float(row["dealAmountManwon"]) for row in trades12]
    ppsm = [_price_per_square_meter(row) for row in trades12]
    ppsm = [value for value in ppsm if value is not None]
    months = {_month_key(row.get("dealDate")) for row in trades12}
    households = int(entity.get("households") or 0)
    count = len(trades12)
    confidence_score, confidence_level, confidence_label, _weight = confidence_for_count(count)
    monthly_prices = _monthly_medians(
        trades24,
        lambda row: float(row.get("dealAmountManwon") or 0),
    )
    return6m, gap6m = _period_return(monthly_prices, reference_month, 6)
    return12m, gap12m = _period_return(monthly_prices, reference_month, 12)
    approved_at = entity.get("approvedAt")
    age = age_score(approved_at, reference_month)
    completion_year = int(str(approved_at)[:4]) if str(approved_at)[:4].isdigit() else None
    station_distance = entity.get("nearestStationDistance")
    return {
        "apartmentId": _entity_id(entity),
        "apartmentName": entity.get("name", ""),
        "sido": entity.get("province", ""),
        "sigungu": entity.get("district", ""),
        "dong": entity.get("legalDong", ""),
        "address": entity.get("address", ""),
        "householdCount": households or None,
        "completionYear": completion_year,
        "brand": entity.get("brand") or None,
        "nearestStationName": entity.get("nearestStationName") or None,
        "nearestStationDistance": station_distance,
        "stationDistanceType": entity.get("stationDistanceType") or None,
        "medianPrice12m": round(statistics.median(prices), 1) if prices else None,
        "medianPricePerSquareMeter12m": round(statistics.median(ppsm), 1) if ppsm else None,
        "transactionCount12m": count,
        "transactionTurnover12m": round(count / households * 100, 3) if households else None,
        "activeTransactionMonths12m": len(months),
        "activeTransactionMonthRatio12m": round(len(months) / 12 * 100, 1),
        "return6m": return6m,
        "return12m": return12m,
        "returnGapMonths6m": gap6m,
        "returnGapMonths12m": gap12m,
        "dataConfidenceScore": confidence_score,
        "confidenceLevel": confidence_level,
        "confidenceLabel": confidence_label,
        "ageScore": age,
        "stationScore": station_score(station_distance),
        "brandScore": SETTINGS.get("brandScores", {}).get(str(entity.get("brand") or "")) or None,
        "_trades12": trades12,
        "_trades24": trades24,
    }


def _apply_percentile(metrics, source_field, target_field):
    ranks = percentile_ranks([row.get(source_field) for row in metrics])
    for row, rank in zip(metrics, ranks):
        row[target_field] = rank


def _district_price_medians(metrics):
    prices = [
        float(trade["dealAmountManwon"])
        for row in metrics for trade in row["_trades12"]
    ]
    ppsm = [
        _price_per_square_meter(trade)
        for row in metrics for trade in row["_trades12"]
    ]
    ppsm = [value for value in ppsm if value is not None]
    return (
        statistics.median(prices) if prices else None,
        statistics.median(ppsm) if ppsm else None,
    )


def _district_returns(metrics, reference_month):
    trades = [trade for row in metrics for trade in row["_trades24"]]
    monthly = _monthly_medians(
        trades,
        lambda row: float(row.get("dealAmountManwon") or 0),
    )
    return (
        _period_return(monthly, reference_month, 6)[0],
        _period_return(monthly, reference_month, 12)[0],
    )


def _score_metrics(metrics, reference_month):
    weights = SETTINGS["weights"]
    district_price, district_ppsm = _district_price_medians(metrics)
    district_return6m, district_return12m = _district_returns(metrics, reference_month)
    for row in metrics:
        row["adjustedMedianPrice12m"] = adjusted_price(
            row["medianPrice12m"], district_price, row["transactionCount12m"],
        )
        row["adjustedMedianPricePerSquareMeter12m"] = adjusted_price(
            row["medianPricePerSquareMeter12m"], district_ppsm, row["transactionCount12m"],
        )
        row["districtReturn6m"] = district_return6m
        row["districtReturn12m"] = district_return12m
        row["relativeReturn6m"] = (
            round(row["return6m"] - district_return6m, 2)
            if row["return6m"] is not None and district_return6m is not None
            else None
        )
        row["relativeReturn12m"] = (
            round(row["return12m"] - district_return12m, 2)
            if row["return12m"] is not None and district_return12m is not None
            else None
        )

    _apply_percentile(metrics, "adjustedMedianPrice12m", "medianPricePercentile")
    _apply_percentile(
        metrics,
        "adjustedMedianPricePerSquareMeter12m",
        "medianPricePerSquareMeterPercentile",
    )
    _apply_percentile(metrics, "relativeReturn6m", "relativeReturn6mPercentile")
    _apply_percentile(metrics, "relativeReturn12m", "relativeReturn12mPercentile")
    _apply_percentile(metrics, "transactionTurnover12m", "transactionTurnoverPercentile")
    _apply_percentile(metrics, "activeTransactionMonthRatio12m", "activeTransactionMonthsPercentile")
    _apply_percentile(metrics, "householdCount", "householdScore")

    for row in metrics:
        row["priceScore"], row["priceScoreCoverage"] = _weighted_score({
            "medianPrice": row["medianPricePercentile"],
            "medianPricePerSquareMeter": row["medianPricePerSquareMeterPercentile"],
        }, weights["price"])
        row["leadershipScore"], row["leadershipScoreCoverage"] = _weighted_score({
            "relativeReturn6m": row["relativeReturn6mPercentile"],
            "relativeReturn12m": row["relativeReturn12mPercentile"],
        }, weights["leadership"])
        row["liquidityScore"], row["liquidityScoreCoverage"] = _weighted_score({
            "transactionTurnover": row["transactionTurnoverPercentile"],
            "activeTransactionMonths": row["activeTransactionMonthsPercentile"],
        }, weights["liquidity"])
        row["overallScore"], row["overallScoreCoverage"] = _weighted_score({
            "price": row["priceScore"],
            "leadership": row["leadershipScore"],
            "liquidity": row["liquidityScore"],
            "age": row["ageScore"],
            "station": row["stationScore"],
        }, weights["overall"])
        row["residenceScore"], row["residenceScoreCoverage"] = _weighted_score({
            "station": row["stationScore"],
            "age": row["ageScore"],
            "price": row["priceScore"],
            "liquidity": row["liquidityScore"],
            "household": row["householdScore"],
        }, weights["residence"])
        is_new_build = (
            row["completionYear"] is not None
            and _parse_reference_month(reference_month).year - row["completionYear"] <= 3
        )
        row["isNewBuild"] = is_new_build
        if is_new_build:
            row["newBuildScore"], row["newBuildScoreCoverage"] = _weighted_score({
                "price": row["priceScore"],
                "liquidity": row["liquidityScore"],
                "station": row["stationScore"],
                "household": row["householdScore"],
                "brand": row["brandScore"],
            }, weights["newBuild"])
        else:
            row["newBuildScore"], row["newBuildScoreCoverage"] = None, 0.0
        row["_expectedValueRaw"], row["valueExpectationCoverage"] = _weighted_score({
            "station": row["stationScore"],
            "age": row["ageScore"],
            "household": row["householdScore"],
            "liquidity": row["liquidityScore"],
        }, weights["valueExpectation"])

    _apply_percentile(metrics, "_expectedValueRaw", "expectedValuePercentile")
    for row in metrics:
        if row["expectedValuePercentile"] is None or row["priceScore"] is None:
            row["valueGap"] = None
            row["valueScore"] = None
        else:
            row["valueGap"] = round(row["expectedValuePercentile"] - row["priceScore"], 1)
            row["valueScore"] = round(max(0, min(100, 50 + row["valueGap"] / 2)), 1)
        row["calculationVersion"] = CALCULATION_VERSION


def _top_percent(percentile):
    if percentile is None:
        return None
    return max(1, min(100, int(math.ceil(100 - float(percentile)))))


def _reason_candidates(row, category):
    reasons = []
    price_top = _top_percent(row.get("priceScore"))
    if price_top is not None:
        reasons.append(("price", row.get("priceScore") or 0, f"{row['sigungu']} {AREA_BUCKETS[row['areaBucket']]['label']} 가격 상위 {price_top}%"))
    relative6m = row.get("relativeReturn6m")
    if relative6m is not None and relative6m >= 0:
        reasons.append(("leadership", row.get("leadershipScore") or 0, f"최근 6개월 지역 평균보다 {relative6m:.1f}%p 초과 상승"))
    elif relative6m is not None and category == "leadership":
        leadership_top = _top_percent(row.get("leadershipScore"))
        if leadership_top is not None:
            reasons.append(("leadership", row.get("leadershipScore") or 0, f"최근 6개월 상대 흐름 상위 {leadership_top}%"))
    turnover_top = _top_percent(row.get("transactionTurnoverPercentile"))
    if turnover_top is not None:
        reasons.append(("liquidity", row.get("liquidityScore") or 0, f"세대수 대비 거래 회전율 상위 {turnover_top}%"))
    active_months = int(row.get("activeTransactionMonths12m") or 0)
    if active_months:
        reasons.append(("active", row.get("activeTransactionMonthsPercentile") or 0, f"최근 12개월 중 {active_months}개월에서 거래 발생"))
    if row.get("ageScore") == 100:
        reasons.append(("age", 100, "준공 5년 이하 신축 단지"))
    if row.get("nearestStationDistance") is not None:
        distance_type = "도보거리" if row.get("stationDistanceType") == "walking" else "직선거리"
        reasons.append(("station", row.get("stationScore") or 0, f"가장 가까운 지하철역까지 {distance_type} {float(row['nearestStationDistance']):,.0f}m"))
    if category == "value" and row.get("valueGap") is not None:
        reasons.append(("value", 120, f"입지·상품성 기대 순위가 가격 순위보다 {row['valueGap']:.1f}점 높음"))
    priorities = {
        "overall": ["price", "leadership", "liquidity", "age", "station", "active"],
        "price": ["price", "liquidity", "active", "age", "station", "leadership"],
        "leadership": ["leadership", "active", "liquidity", "price", "age", "station"],
        "residence": ["station", "age", "price", "liquidity", "active", "leadership"],
        "new_build": ["age", "price", "liquidity", "station", "active", "leadership"],
        "value": ["value", "station", "age", "liquidity", "active", "price"],
    }
    order = {key: index for index, key in enumerate(priorities[category])}
    reasons.sort(key=lambda item: (order.get(item[0], 99), -item[1]))
    return [text for _kind, _impact, text in reasons[:MAX_REASON_COUNT]]


def _warnings(row):
    warnings = []
    count = int(row.get("transactionCount12m") or 0)
    if count <= 1:
        warnings.append("최근 12개월 거래가 1건 이하라 일반 대장 순위에서 제외됩니다.")
    elif count < 5:
        warnings.append(f"최근 12개월 거래가 {count}건으로 가격 신뢰도가 낮습니다.")
    if row.get("stationScore") is None:
        warnings.append("지하철 거리 데이터가 없어 역 접근성은 점수에서 제외했습니다.")
    if row.get("ageScore") is None:
        warnings.append("준공연도 데이터가 없어 연식은 점수에서 제외했습니다.")
    if row.get("householdCount") is None:
        warnings.append("세대수 데이터가 없어 거래 회전율과 규모 점수 일부를 계산하지 못했습니다.")
    if max(int(row.get("returnGapMonths6m") or 0), int(row.get("returnGapMonths12m") or 0)) >= 3:
        warnings.append("월별 거래 간격이 길어 상승 선도력의 신뢰도가 낮습니다.")
    if row.get("isNewBuild") and count < 5:
        warnings.append("입주 초기 단지로 장기 가격 흐름 데이터가 부족합니다.")
    return warnings


def _eligible(row, category):
    count = int(row.get("transactionCount12m") or 0)
    if row.get(CATEGORY_FIELDS[category]) is None:
        return False
    if category == "new_build":
        return bool(row.get("isNewBuild") and count >= 1)
    if count < 2:
        return False
    if category == "leadership":
        return count >= 5 and row.get("leadershipScore") is not None
    if category == "value":
        return (
            count >= 5
            and row.get("expectedValuePercentile") is not None
            and row.get("expectedValuePercentile") >= 50
        )
    return True


def _public_item(row, category, rank):
    score_field = CATEGORY_FIELDS[category]
    item = {
        key: value for key, value in row.items()
        if not key.startswith("_") and key not in {"areaBucket"}
    }
    item.update({
        "rank": rank,
        "score": row.get(score_field),
        "category": category,
        "categoryLabel": CATEGORY_LABELS[category],
        "reasons": _reason_candidates(row, category),
        "warnings": _warnings(row),
        "scores": {
            "price": row.get("priceScore"),
            "leadership": row.get("leadershipScore"),
            "liquidity": row.get("liquidityScore"),
            "age": row.get("ageScore"),
            "station": row.get("stationScore"),
            "household": row.get("householdScore"),
        },
    })
    return item


def _rank_category(metrics, category, limit):
    score_field = CATEGORY_FIELDS[category]
    rows = [row for row in metrics if _eligible(row, category)]
    rows.sort(key=lambda row: (
        -float(row.get(score_field) or 0),
        -float(row.get("dataConfidenceScore") or 0),
        -int(row.get("transactionCount12m") or 0),
        -float(row.get("priceScore") or 0),
        str(row.get("apartmentName") or ""),
    ))
    return [
        _public_item(row, category, index)
        for index, row in enumerate(rows[:limit], 1)
    ]


def calculate_rankings_from_pairs(
    sido,
    sigungu,
    entity_transactions,
    area_bucket_value=DEFAULT_AREA_BUCKET,
    reference_month=None,
    limit=DEFAULT_LIMIT,
):
    if area_bucket_value not in AREA_BUCKETS:
        raise ValueError("지원하지 않는 면적 구간입니다.")
    reference = _parse_reference_month(reference_month).strftime("%Y-%m")
    entity_transactions = list(entity_transactions)
    entities = [entity for entity, _transactions in entity_transactions]
    metrics = [
        _base_metrics(entity, transactions, reference, area_bucket_value)
        for entity, transactions in entity_transactions
    ]
    for row in metrics:
        row["areaBucket"] = area_bucket_value
    _score_metrics(metrics, reference)
    rankings = {
        category: _rank_category(metrics, category, max(1, min(int(limit or DEFAULT_LIMIT), 20)))
        for category in CATEGORY_FIELDS
    }
    trade_complex_count = sum(1 for row in metrics if row["transactionCount12m"] > 0)
    eligible_complex_count = sum(1 for row in metrics if row["transactionCount12m"] >= 2)
    warnings = []
    if not entities:
        warnings.append("해당 지역에 등록된 아파트 단지가 없습니다.")
    elif not trade_complex_count:
        warnings.append("해당 면적 구간의 최근 거래가 없습니다.")
    elif not eligible_complex_count:
        warnings.append("최근 거래가 부족해 신뢰도 높은 대장 단지를 선정하기 어렵습니다.")
    return {
        "region": {"sido": sido, "sigungu": sigungu},
        "referenceMonth": reference,
        "areaBucket": area_bucket_value,
        "areaBucketLabel": AREA_BUCKETS[area_bucket_value]["label"],
        "calculationVersion": CALCULATION_VERSION,
        "lookbackMonths": 12,
        "stationDistanceBasis": None,
        "complexCount": len(entities),
        "tradeComplexCount": trade_complex_count,
        "eligibleComplexCount": eligible_complex_count,
        "rankings": rankings,
        "warnings": warnings,
        "dataAvailability": {
            "transactions": bool(trade_complex_count),
            "completionYear": any(row.get("completionYear") is not None for row in metrics),
            "households": any(row.get("householdCount") is not None for row in metrics),
            "stationDistance": any(row.get("stationScore") is not None for row in metrics),
            "brand": any(row.get("brandScore") is not None for row in metrics),
        },
    }


def calculate_rankings(
    sido,
    sigungu,
    area_bucket_value=DEFAULT_AREA_BUCKET,
    reference_month=None,
    limit=DEFAULT_LIMIT,
    cache_only=False,
):
    reference = _parse_reference_month(reference_month).strftime("%Y-%m")
    entities = matching_entities(sido, sigungu)
    return calculate_rankings_from_pairs(
        sido,
        sigungu,
        _load_transactions(entities, reference, cache_only),
        area_bucket_value=area_bucket_value,
        reference_month=reference,
        limit=limit,
    )


def _cache_path(sido, sigungu, area_bucket_value, reference_month):
    material = "|".join((CALCULATION_VERSION, sido, sigungu, area_bucket_value, reference_month))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def get_leaders(
    sido,
    sigungu,
    area_bucket_value=DEFAULT_AREA_BUCKET,
    reference_month=None,
    category="overall",
    limit=DEFAULT_LIMIT,
    force=False,
    cache_only=False,
):
    if category not in CATEGORY_FIELDS:
        raise ValueError("지원하지 않는 대장 카테고리입니다.")
    reference = _parse_reference_month(reference_month).strftime("%Y-%m")
    path = _cache_path(sido, sigungu, area_bucket_value, reference)
    payload = None
    if path.exists() and not force:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    if payload is None:
        payload = calculate_rankings(
            sido,
            sigungu,
            area_bucket_value=area_bucket_value,
            reference_month=reference,
            limit=max(DEFAULT_LIMIT, int(limit or DEFAULT_LIMIT)),
            cache_only=cache_only,
        )
        if not cache_only:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
    response = {key: value for key, value in payload.items() if key != "rankings"}
    response["category"] = category
    response["categoryLabel"] = CATEGORY_LABELS[category]
    response["items"] = (payload.get("rankings", {}).get(category) or [])[:max(1, min(int(limit or DEFAULT_LIMIT), 20))]
    return response


def apartment_detail(apartment_id, sido, sigungu, area_bucket_value, reference_month=None):
    payload = calculate_rankings(
        sido,
        sigungu,
        area_bucket_value=area_bucket_value,
        reference_month=reference_month,
        limit=20,
        cache_only=True,
    )
    found = {}
    for category, items in payload["rankings"].items():
        for item in items:
            if item.get("apartmentId") == apartment_id:
                found.setdefault("apartment", item)
                found.setdefault("categoryRanks", {})[category] = item["rank"]
    if not found:
        return None
    return {
        **found,
        "region": payload["region"],
        "referenceMonth": payload["referenceMonth"],
        "areaBucket": payload["areaBucket"],
        "calculationVersion": CALCULATION_VERSION,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="지역별 대장아파트 순위를 계산합니다.")
    parser.add_argument("--sido", default="")
    parser.add_argument("--sigungu", default="")
    parser.add_argument("--reference-month", default="")
    parser.add_argument("--area-bucket", default=DEFAULT_AREA_BUCKET, choices=AREA_BUCKETS)
    parser.add_argument("--category", default="overall", choices=CATEGORY_FIELDS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.sido or not args.sigungu:
        parser.error("--sido와 --sigungu를 입력해 주세요.")
    payload = get_leaders(
        args.sido,
        args.sigungu,
        area_bucket_value=args.area_bucket,
        reference_month=args.reference_month,
        category=args.category,
        limit=args.limit,
        force=True,
        cache_only=args.cache_only or args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
