"""국토부 실거래를 바탕으로 지역 흐름 화면에 쓸 지표를 만든다.

이 모듈은 지역 간 인과관계를 단정하지 않는다. 과거·현재 구간의 실제
거래 변화를 보여 주고, 다음 지역은 가격과 거래량 신호와 과거 반복 사례를 함께
계산해 표시한다. 원본 거래는 ``molit_transactions``가 받아 둔 국토부 월별 캐시를 쓴다.
"""
import datetime
import itertools
import json
import statistics
import threading
import time
from pathlib import Path

import config
import molit_transactions


CACHE_DIR = config.CACHE_DIR / "market_flow"
CACHE_TTL_SECONDS = 60 * 60 * 6
CACHE_LOCK = threading.Lock()
REFRESH_LOCK = threading.Lock()
REFRESHING_CACHE_PATHS = set()
MIN_WINDOW_DEALS = 8
# `올랐다`는 단순한 미세 변동이 아니라, 3개월 비교에서 1% 이상 오른 경우로
# 통일한다. 현재·과거·다음 사례가 모두 같은 기준을 써야 상승 순서를 비교할 수 있다.
MIN_FLOW_PRICE_RISE_PCT = 1.0
# 화면에서 말하는 `다음 후보`는 이미 가장 많이 오른 지역이 아니라, 현재 상승
# 지역보다 덜 올랐지만 상승폭이 커지기 시작한 지역이어야 한다.
MIN_STAGE_CHANGE_PCT = 0.5
MIN_TARGET_LAG_PCT = 1.0
MIN_TARGET_CURRENT_RISE_PCT = 0.0
# 흐름 지도는 한 번에 읽히는 현재·과거·다음 장면이 목적이라, 분석 간격을
# 3개월로 고정한다. 화면의 제목·비교 기준·계산 창을 모두 같은 3개월로 맞춘다.
FLOW_PERIOD_MONTHS = 3
WINDOW_MONTHS = FLOW_PERIOD_MONTHS
# 경로가 과거에도 같은 순서로 움직였는지 확인하려면 현재 창보다 긴 거래
# 이력이 필요하다. 최근 10년 안에서 3개월 간격의 완료된 순서를 검증한다.
HISTORY_MONTHS = 120
MIN_HISTORICAL_PATTERN_COUNT = 5
SNAPSHOT_SCHEMA_VERSION = 8
MAX_DISPLAY_ROUTES = 30
FLOW_STATUS_NEXT_CANDIDATE = "next_candidate"
FLOW_STATUS_ALREADY_RISING = "already_rising"
FLOW_STATUS_WAITING = "waiting"
FLOW_STATUS_PRIORITY = {
    FLOW_STATUS_NEXT_CANDIDATE: 0,
    FLOW_STATUS_ALREADY_RISING: 1,
    FLOW_STATUS_WAITING: 2,
}
ROUTE_COLORS = (
    "#3182f6", "#f59f35", "#2fb36f", "#8b5cf6", "#ef5da8", "#12a594",
    "#d97706", "#64748b", "#0ea5e9", "#84cc16", "#dc2626", "#7c3aed",
)

# 경로 자체는 생활권의 인접성을 기준으로 정해 둔 화면 구조다. 순위와 점수,
# 과거·현재의 설명은 이 목록이 아니라 매 요청 시 국토부 실거래로 계산한다.
FLOW_ROUTES = (
    {
        "id": "east-seoul", "color": "#3182f6",
        "nodes": (
            ("송파구", ("11710",), 37.5145, 127.1059),
            ("광진구", ("11215",), 37.5384, 127.0822),
            ("중랑구", ("11260",), 37.6063, 127.0927),
        ),
    },
    {
        "id": "gangnam-seongbuk", "color": "#f59f35",
        "nodes": (
            ("강남구", ("11680",), 37.5172, 127.0473),
            ("성동구", ("11200",), 37.5633, 127.0369),
            ("동대문구", ("11230",), 37.5744, 127.0396),
        ),
    },
    {
        "id": "mapo-goyang", "color": "#2fb36f",
        "nodes": (
            ("마포구", ("11440",), 37.5663, 126.9019),
            ("은평구", ("11380",), 37.6027, 126.9291),
            # 고양시는 덕양·일산동·일산서구 거래를 함께 본다.
            ("고양시", ("41281", "41285", "41287"), 37.6584, 126.8320),
        ),
    },
    {
        "id": "north-seoul", "color": "#8b5cf6",
        "nodes": (
            ("성북구", ("11290",), 37.5894, 127.0167),
            ("강북구", ("11305",), 37.6396, 127.0257),
            ("도봉구", ("11320",), 37.6688, 127.0471),
        ),
    },
    {
        "id": "seocho-uiwang", "color": "#ef5da8",
        "nodes": (
            ("서초구", ("11650",), 37.4837, 127.0324),
            ("과천시", ("41290",), 37.4292, 126.9876),
            ("의왕시", ("41430",), 37.3447, 126.9683),
        ),
    },
    {
        "id": "yeongdeungpo-bucheon", "color": "#12a594",
        "nodes": (
            ("영등포구", ("11560",), 37.5264, 126.8963),
            ("구로구", ("11530",), 37.4955, 126.8874),
            ("부천시", ("41190",), 37.5034, 126.7660),
        ),
    },
    {
        "id": "dongjak-anyang", "color": "#d97706",
        "nodes": (
            ("동작구", ("11590",), 37.5124, 126.9393),
            ("관악구", ("11620",), 37.4784, 126.9516),
            ("안양시", ("41171", "41173"), 37.3943, 126.9568),
        ),
    },
    {
        "id": "gangseo-paju", "color": "#64748b",
        "nodes": (
            ("강서구", ("11500",), 37.5509, 126.8495),
            ("김포시", ("41570",), 37.6152, 126.7156),
            ("파주시", ("41480",), 37.7599, 126.7800),
        ),
    },
)

FLOW_ADJACENT_REGION_PAIRS = (
    ("강남구", "성동구"),
    ("강남구", "서초구"),
    ("서초구", "동작구"),
    ("서초구", "과천시"),
    ("과천시", "의왕시"),
    ("동작구", "관악구"),
    ("관악구", "안양시"),
    ("동작구", "영등포구"),
    ("영등포구", "구로구"),
    ("구로구", "부천시"),
    ("강서구", "김포시"),
    ("김포시", "파주시"),
    ("강서구", "마포구"),
    ("마포구", "은평구"),
    ("은평구", "고양시"),
    ("성동구", "광진구"),
    ("성동구", "동대문구"),
    ("성동구", "성북구"),
    ("광진구", "송파구"),
    ("광진구", "동대문구"),
    ("광진구", "중랑구"),
    ("동대문구", "중랑구"),
    ("동대문구", "성북구"),
    ("성북구", "중랑구"),
    ("성북구", "강북구"),
    ("강북구", "도봉구"),
)


def _shift_month(value, offset):
    ordinal = value.year * 12 + value.month - 1 + offset
    return datetime.date(ordinal // 12, ordinal % 12 + 1, 1)


def _base_month():
    """신고가 덜 끝난 이번 달은 빼고 직전 달을 기준월로 삼는다."""
    today = datetime.date.today().replace(day=1)
    return _shift_month(today, -1)


def _month_keys(reference, months=12):
    return [
        _shift_month(reference, -offset).strftime("%Y%m")
        for offset in range(max(1, months))
    ]


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _is_valid_trade(row):
    try:
        price = float(row.get("dealAmountManwon") or 0)
        area = float(row.get("exclusiveArea") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        _parse_date(row.get("dealDate"))
        and price > 0
        and area > 0
        and not str(row.get("cancellationDate") or "").strip()
        and str(row.get("dealType") or "").strip() != "직거래"
    )


def _stats_for_window(trades, end_month, months=WINDOW_MONTHS):
    start = _shift_month(end_month, -(months - 1))
    next_month = _shift_month(end_month, 1)
    end = next_month - datetime.timedelta(days=1)
    values = []
    for row in trades:
        date = _parse_date(row.get("dealDate"))
        if not date or not (start <= date <= end):
            continue
        price = float(row["dealAmountManwon"])
        area = float(row["exclusiveArea"])
        values.append(price / area)
    return {
        "count": len(values),
        "medianPerSquareMeter": round(statistics.median(values), 1) if values else None,
    }


def _regional_signal(trades, reference, lag_months=1):
    trades = [row for row in trades if _is_valid_trade(row)]
    current = _window_signal(trades, reference)
    past_end = _shift_month(reference, -lag_months)
    past = _window_signal(trades, past_end)

    return {
        "pastPriceChangePct": past["priceChangePct"],
        "pastTradeChangePct": past["tradeChangePct"],
        "currentPriceChangePct": current["priceChangePct"],
        "currentTradeChangePct": current["tradeChangePct"],
        "pastTradeCount": past["tradeCount"],
        "pastPreviousTradeCount": past["previousTradeCount"],
        "currentTradeCount": current["tradeCount"],
        "currentPreviousTradeCount": current["previousTradeCount"],
        "lastObservedMonth": reference.strftime("%Y-%m"),
    }


def _window_signal(trades, reference):
    """한 시점의 최근 N개월을 그 직전 N개월과 비교한다."""
    current = _stats_for_window(trades, reference)
    previous = _stats_for_window(trades, _shift_month(reference, -WINDOW_MONTHS))

    def change(later, earlier, field):
        left = later.get(field)
        right = earlier.get(field)
        if left is None or right in (None, 0):
            return None
        return round((left / right - 1) * 100, 1)

    return {
        "priceChangePct": change(current, previous, "medianPerSquareMeter"),
        "tradeChangePct": change(current, previous, "count"),
        "tradeCount": current["count"],
        "previousTradeCount": previous["count"],
    }


def _is_material_price_rise(price_change, trade_count, previous_trade_count):
    """상승 순서에 쓸 만큼 가격·거래 표본이 충분한지 본다."""
    return bool(
        price_change is not None
        and price_change >= MIN_FLOW_PRICE_RISE_PCT
        and trade_count >= MIN_WINDOW_DEALS
        and previous_trade_count >= MIN_WINDOW_DEALS
    )


def _historical_route_pattern(source_trades, current_trades, target_trades, reference):
    """과거에 선행 지역→현재 지역→다음 지역 순서가 이어진 횟수를 센다.

    한 사례는 3개월 간격의 세 시점으로 구성한다. 선행·현재 지역의 가격이
    연속으로 올랐을 때, 다음 지역도 다음 3개월 뒤 올랐는지를 본다. 현재 시점은
    아직 결과가 정해지지 않았으므로 과거 사례에는 넣지 않는다.
    """
    # source 시점의 비교 창(현재 3개월 + 직전 3개월)까지 포함할 수 있는,
    # 완료된 target 시점만 쓴다.
    max_target_offset = HISTORY_MONTHS - (2 * FLOW_PERIOD_MONTHS + 2 * WINDOW_MONTHS - 1)
    qualified = 0
    hits = 0
    observed = 0
    evidence_cases = []
    for offset in range(FLOW_PERIOD_MONTHS, max_target_offset + 1, FLOW_PERIOD_MONTHS):
        target_end = _shift_month(reference, -offset)
        current_end = _shift_month(target_end, -FLOW_PERIOD_MONTHS)
        source_end = _shift_month(current_end, -FLOW_PERIOD_MONTHS)
        source = _window_signal(source_trades, source_end)
        current = _window_signal(current_trades, current_end)
        target = _window_signal(target_trades, target_end)
        prices = (source["priceChangePct"], current["priceChangePct"], target["priceChangePct"])
        if not all(value is not None for value in prices):
            continue
        observed += 1
        if (
            _is_material_price_rise(
                source["priceChangePct"], source["tradeCount"], source["previousTradeCount"],
            )
            and _is_material_price_rise(
                current["priceChangePct"], current["tradeCount"], current["previousTradeCount"],
            )
        ):
            qualified += 1
            target_rose = _is_material_price_rise(
                target["priceChangePct"], target["tradeCount"], target["previousTradeCount"],
            )
            if target_rose:
                hits += 1
            evidence_cases.append({
                "sourceEndMonth": source_end.strftime("%Y-%m"),
                "currentEndMonth": current_end.strftime("%Y-%m"),
                "targetEndMonth": target_end.strftime("%Y-%m"),
                "sourcePriceChangePct": source["priceChangePct"],
                "currentPriceChangePct": current["priceChangePct"],
                "targetPriceChangePct": target["priceChangePct"],
                "targetRose": target_rose,
            })

    return {
        "observedWindows": observed,
        "precedingPatternCount": qualified,
        "targetRiseCount": hits,
        "targetRiseRatePct": round(hits / qualified * 100) if qualified else None,
        "enoughHistory": qualified >= MIN_HISTORICAL_PATTERN_COUNT,
        "minimumPatternCount": MIN_HISTORICAL_PATTERN_COUNT,
        "evidenceCases": evidence_cases,
    }


def _historical_route_pattern_from_series(source_series, current_series, target_series, reference):
    qualified = 0
    hits = 0
    observed = 0
    evidence_cases = []
    for offset, target in sorted(target_series.items()):
        current = current_series.get(offset + FLOW_PERIOD_MONTHS)
        source = source_series.get(offset + FLOW_PERIOD_MONTHS * 2)
        if not source or not current:
            continue
        prices = (source["priceChangePct"], current["priceChangePct"], target["priceChangePct"])
        if not all(value is not None for value in prices):
            continue
        observed += 1
        if (
            _is_material_price_rise(
                source["priceChangePct"], source["tradeCount"], source["previousTradeCount"],
            )
            and _is_material_price_rise(
                current["priceChangePct"], current["tradeCount"], current["previousTradeCount"],
            )
        ):
            qualified += 1
            target_rose = _is_material_price_rise(
                target["priceChangePct"], target["tradeCount"], target["previousTradeCount"],
            )
            if target_rose:
                hits += 1
            evidence_cases.append({
                "sourceEndMonth": _shift_month(reference, -(offset + FLOW_PERIOD_MONTHS * 2)).strftime("%Y-%m"),
                "currentEndMonth": _shift_month(reference, -(offset + FLOW_PERIOD_MONTHS)).strftime("%Y-%m"),
                "targetEndMonth": _shift_month(reference, -offset).strftime("%Y-%m"),
                "sourcePriceChangePct": source["priceChangePct"],
                "currentPriceChangePct": current["priceChangePct"],
                "targetPriceChangePct": target["priceChangePct"],
                "targetRose": target_rose,
            })

    return {
        "observedWindows": observed,
        "precedingPatternCount": qualified,
        "targetRiseCount": hits,
        "targetRiseRatePct": round(hits / qualified * 100) if qualified else None,
        "enoughHistory": qualified >= MIN_HISTORICAL_PATTERN_COUNT,
        "minimumPatternCount": MIN_HISTORICAL_PATTERN_COUNT,
        "evidenceCases": evidence_cases,
    }


def _clamp(value, low, high):
    return max(low, min(high, value))


def _route_step_allowed(left, right):
    return (left["name"], right["name"]) in _flow_corridor_edges()


def _flow_corridor_edges():
    edges = set()
    for route in FLOW_ROUTES:
        nodes = [name for name, _codes, _lat, _lng in route["nodes"]]
        for left, right in zip(nodes, nodes[1:]):
            edges.add((left, right))
    for left, right in FLOW_ADJACENT_REGION_PAIRS:
        edges.add((left, right))
    return edges


def _short_region_name(name):
    text = str(name or "").strip()
    return text[:-1] if text.endswith(("구", "시")) and len(text) > 1 else text


def _score_signal(value, center=0, scale=1):
    if value is None:
        return 0
    return _clamp((float(value) - center) * scale, -18, 18)


def _stage_metrics(source, current, target):
    """먼저·지금·다음 후보의 상대적인 움직임을 계산한다."""
    return {
        "sourceCooldownPct": round(
            float(source["pastPriceChangePct"]) - float(source["currentPriceChangePct"]), 1
        ),
        "currentAccelerationPct": round(
            float(current["currentPriceChangePct"]) - float(current["pastPriceChangePct"]), 1
        ),
        "targetLagPct": round(
            float(current["currentPriceChangePct"]) - float(target["currentPriceChangePct"]), 1
        ),
        "targetAccelerationPct": round(
            float(target["currentPriceChangePct"]) - float(target["pastPriceChangePct"]), 1
        ),
    }


def _is_active_flow_sequence(source, current, target):
    """현재 상승 지역 뒤에서 다음 후보가 따라오는 흐름인지 본다.

    선행 지역이 아직 오르고 있어도 온기가 다음 지역으로 번질 수 있으므로,
    선행 지역의 둔화 여부는 후보 제외 조건이 아니라 점수와 설명에만 쓴다.
    """
    required = (
        source.get("pastPriceChangePct"), source.get("currentPriceChangePct"),
        current.get("pastPriceChangePct"), current.get("currentPriceChangePct"),
        target.get("pastPriceChangePct"), target.get("currentPriceChangePct"),
    )
    if any(value is None for value in required):
        return False
    metrics = _stage_metrics(source, current, target)
    return bool(
        float(current["currentPriceChangePct"]) >= MIN_FLOW_PRICE_RISE_PCT
        and metrics["currentAccelerationPct"] >= MIN_STAGE_CHANGE_PCT
        and metrics["targetLagPct"] >= MIN_TARGET_LAG_PCT
        and metrics["targetAccelerationPct"] >= MIN_STAGE_CHANGE_PCT
        and float(target["currentPriceChangePct"]) >= MIN_TARGET_CURRENT_RISE_PCT
    )


def _flow_status(source, current, target):
    """지금 경로가 다음 후보·이미 상승·대기 중 어디에 해당하는지 나눈다."""
    if _is_active_flow_sequence(source, current, target):
        return FLOW_STATUS_NEXT_CANDIDATE
    metrics = _stage_metrics(source, current, target)
    if (
        float(target["currentPriceChangePct"]) >= MIN_FLOW_PRICE_RISE_PCT
        and metrics["targetAccelerationPct"] >= MIN_STAGE_CHANGE_PCT
        and metrics["targetLagPct"] < MIN_TARGET_LAG_PCT
    ):
        return FLOW_STATUS_ALREADY_RISING
    return FLOW_STATUS_WAITING


def _watch_routes(routes):
    """과거 순서와 최근 가격을 함께 보고, 지역마다 살펴볼 경로를 고른다.

    이미 오른 것으로 확인된 지역은 다른 경로에서 다시 후보로 내지 않는다.
    다음 지역의 상승폭이 아직 커지지 않았다는 이유만으로 후보를 지우지 않는다.
    """
    already_risen = {
        route["nodes"][-1]["name"] for route in routes
        if route["status"] == FLOW_STATUS_ALREADY_RISING
    }
    eligible = []
    for route in routes:
        if route["status"] == FLOW_STATUS_ALREADY_RISING:
            continue
        current = route["nodes"][1]["signal"].get("currentPriceChangePct")
        target = route["nodes"][-1]["signal"].get("currentPriceChangePct")
        target_name = route["nodes"][-1]["name"]
        if (
            target_name in already_risen or current is None or target is None
            or float(current) < MIN_FLOW_PRICE_RISE_PCT
            or float(target) < MIN_TARGET_CURRENT_RISE_PCT
            or float(target) >= float(current)
        ):
            continue
        eligible.append(route)
    eligible.sort(key=lambda route: (
        -(route["historicalPattern"].get("targetRiseRatePct") or 0),
        -(route["historicalPattern"].get("precedingPatternCount") or 0),
        -route["score"],
    ))
    selected = []
    seen_regions = set()
    for route in eligible:
        name = route["nodes"][-1]["name"]
        if name not in seen_regions:
            selected.append(route["id"])
            seen_regions.add(name)
    return selected


def _target_regions(routes, watch_route_ids=None):
    """여러 확산 경로의 마지막 지역을 한 번만 보여줄 수 있게 묶는다."""
    grouped = {}
    if watch_route_ids is None:
        watch_route_ids = [
            route["id"] for route in routes
            if route["status"] == FLOW_STATUS_NEXT_CANDIDATE
        ]
    watch_rank = {route_id: index for index, route_id in enumerate(watch_route_ids)}
    for route in routes:
        target = route["nodes"][-1]
        name = target["name"]
        if name not in grouped:
            grouped[name] = {
                "name": name,
                "status": "other",
                "representativeRouteId": route["id"],
                "routeIds": [],
                "routeCount": 0,
                "watchRank": None,
                "candidateRouteCount": 0,
                "alreadyRisingRouteCount": 0,
                "waitingRouteCount": 0,
                "signal": target["signal"],
            }
        region = grouped[name]
        region["routeIds"].append(route["id"])
        region["routeCount"] += 1
        if route["id"] in watch_rank:
            region["status"] = "watch"
            region["watchRank"] = watch_rank[route["id"]]
            region["representativeRouteId"] = route["id"]
        if route["status"] == FLOW_STATUS_NEXT_CANDIDATE:
            region["candidateRouteCount"] += 1
        elif route["status"] == FLOW_STATUS_ALREADY_RISING:
            region["alreadyRisingRouteCount"] += 1
        else:
            region["waitingRouteCount"] += 1
    return sorted(grouped.values(), key=lambda region: (
        region["status"] != "watch",
        region["watchRank"] if region["watchRank"] is not None else len(routes),
        -region["routeCount"],
        region["name"],
    ))


def _apply_watch_ranking(payload):
    """캐시된 거래 분석에도 같은 후보 순위를 즉시 반영한다."""
    routes = payload.get("routes") or []
    watch_route_ids = _watch_routes(routes)
    target_regions = _target_regions(routes, watch_route_ids)
    payload["watchRouteIds"] = watch_route_ids
    payload["watchRegionCount"] = len(watch_route_ids)
    payload["targetRegionCount"] = len(target_regions)
    payload["targetRegions"] = target_regions
    return payload


def _route_score(source, current, target, historical_pattern=None):
    """다음 후보 점수는 이동 단계의 선명도와 과거 순서 검증을 함께 반영한다."""
    stage = _stage_metrics(source, current, target)
    score = 50.0
    score += _score_signal(stage["sourceCooldownPct"], scale=1.4)
    # 먼저 오른 지역이 완전히 하락 전환한 경로보다, 상승세가 누그러지며 다음
    # 지역으로 이어지는 경로를 앞에 둔다.
    score += _score_signal(source["currentPriceChangePct"], scale=1.5)
    score += _score_signal(stage["currentAccelerationPct"], scale=1.8)
    score += _score_signal(stage["targetLagPct"], scale=1.2)
    score += _score_signal(stage["targetAccelerationPct"], scale=1.5)
    score += _score_signal(current["currentTradeChangePct"], scale=.12)
    score += _score_signal(target["currentTradeChangePct"], scale=.08)
    sample = min(
        source["pastTradeCount"], current["currentTradeCount"], target["currentTradeCount"],
    )
    score -= 8 if sample < MIN_WINDOW_DEALS else 0
    if historical_pattern and historical_pattern.get("enoughHistory"):
        # 과거에 선행·현재 지역이 함께 올랐을 때 다음 지역까지 오른 비율은
        # 후보 순서를 보강하는 근거다. 표본이 적으면 점수에 넣지 않는다.
        hit_rate = historical_pattern.get("targetRiseRatePct")
        if hit_rate is not None:
            score += _clamp((float(hit_rate) - 50) * .16, -8, 8)
    return int(round(_clamp(score, 1, 99)))


def _confidence(source, current, target):
    sample = min(
        source["pastTradeCount"], current["currentTradeCount"], target["currentTradeCount"],
    )
    if sample >= 30:
        return "높음"
    if sample >= MIN_WINDOW_DEALS:
        return "보통"
    return "낮음"


def _cache_path(reference, period_months):
    return CACHE_DIR / f"{reference.strftime('%Y%m')}-{int(period_months)}-window{WINDOW_MONTHS}-history{HISTORY_MONTHS}-schema{SNAPSHOT_SCHEMA_VERSION}.json"


def _read_cached_payload(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _read_cache(path):
    payload = _read_cached_payload(path)
    if payload and time.time() - float(payload.get("cachedAt") or 0) <= CACHE_TTL_SECONDS:
        return payload
    return None


def _write_cache(path, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _refresh_snapshot(reference, period_months, path, refresh_key):
    try:
        payload = _build_snapshot(reference, period_months)
        payload["cachedAt"] = time.time()
        _write_cache(path, payload)
    except Exception:
        # 이전 스냅샷은 계속 보여 주고 다음 요청에서 다시 갱신을 시도한다.
        pass
    finally:
        with REFRESH_LOCK:
            REFRESHING_CACHE_PATHS.discard(refresh_key)


def _schedule_snapshot_refresh(reference, period_months, path):
    """같은 기준월의 무거운 실거래 계산은 한 번만 백그라운드로 돌린다."""
    refresh_key = str(path)
    with REFRESH_LOCK:
        if refresh_key in REFRESHING_CACHE_PATHS:
            return False
        REFRESHING_CACHE_PATHS.add(refresh_key)
    thread = threading.Thread(
        target=_refresh_snapshot,
        args=(reference, period_months, path, refresh_key),
        name="market-flow-refresh",
        daemon=True,
    )
    thread.start()
    return True


def _all_region_codes():
    return sorted({code for region in _flow_regions() for code in region["codes"]})


def _flow_regions():
    regions = {}
    for route in FLOW_ROUTES:
        for name, codes, latitude, longitude in route["nodes"]:
            item = regions.setdefault(name, {
                "name": name,
                "codes": set(),
                "latitude": latitude,
                "longitude": longitude,
            })
            item["codes"].update(str(code) for code in codes)
    return [
        {**item, "codes": tuple(sorted(item["codes"]))}
        for item in sorted(regions.values(), key=lambda row: row["name"])
    ]


def _fetch_region_transactions(reference):
    months = _month_keys(reference, HISTORY_MONTHS)
    codes = _all_region_codes()
    # 10년치 흐름 검증은 요청 수가 크다. 일반 후보 검색의 프리패치 병렬도를
    # 그대로 쓰면 공공데이터 API가 429를 반환할 수 있어 이 화면은 낮춰 받는다.
    molit_transactions.prefetch_months(
        ((code, month) for code in codes for month in months),
        max_workers=2,
    )
    rows = {}
    errors = 0
    for code in codes:
        items = []
        for month in months:
            try:
                items.extend(molit_transactions.fetch_month(code, month))
            except Exception:
                errors += 1
        rows[code] = [item for item in items if _is_valid_trade(item)]
    return rows, errors


def _build_snapshot(reference, period_months):
    transactions_by_code, fetch_errors = _fetch_region_transactions(reference)
    regions = _flow_regions()
    region_rows = []
    max_target_offset = HISTORY_MONTHS - (2 * FLOW_PERIOD_MONTHS + 2 * WINDOW_MONTHS - 1)
    historical_offsets = range(FLOW_PERIOD_MONTHS, max_target_offset + 1, FLOW_PERIOD_MONTHS)
    signal_offsets = range(FLOW_PERIOD_MONTHS, max_target_offset + FLOW_PERIOD_MONTHS * 2 + 1, FLOW_PERIOD_MONTHS)
    for region in regions:
        trades = [trade for code in region["codes"] for trade in transactions_by_code.get(code, [])]
        signal = _regional_signal(trades, reference, period_months)
        historical_series = {
            offset: _window_signal(trades, _shift_month(reference, -offset))
            for offset in signal_offsets
        }
        region_rows.append({
            **region,
            "trades": trades,
            "signal": signal,
            "historicalSeries": historical_series,
        })

    routes = []
    for route_index, (source_region, current_region, target_region) in enumerate(itertools.permutations(region_rows, 3), start=1):
        if (
            not _route_step_allowed(source_region, current_region)
            or not _route_step_allowed(current_region, target_region)
        ):
            continue
        source = source_region["signal"]
        current = current_region["signal"]
        target = target_region["signal"]
        # 과거·현재 구간은 각각 가격 비교가 가능해야 한다. 선행 지역의 과거
        # 상승과 세 지역의 최근 거래 표본이 확인되면 경로를 유지하고, 현재
        # 모습은 다음 후보·이미 상승·대기 중 상태로 나눠 화면에서 설명한다.
        if (
            source["pastPriceChangePct"] is None
            or source["currentPriceChangePct"] is None
            or current["pastPriceChangePct"] is None
            or current["currentPriceChangePct"] is None
            or target["pastPriceChangePct"] is None
            or target["currentPriceChangePct"] is None
            or not _is_material_price_rise(
                source["pastPriceChangePct"],
                source["pastTradeCount"],
                source["pastPreviousTradeCount"],
            )
            or source["currentTradeCount"] < MIN_WINDOW_DEALS
            or source["currentPreviousTradeCount"] < MIN_WINDOW_DEALS
            or current["currentTradeCount"] < MIN_WINDOW_DEALS
            or current["currentPreviousTradeCount"] < MIN_WINDOW_DEALS
            or target["currentTradeCount"] < MIN_WINDOW_DEALS
            or target["currentPreviousTradeCount"] < MIN_WINDOW_DEALS
        ):
            continue
        historical_pattern = _historical_route_pattern_from_series(
            source_region["historicalSeries"],
            current_region["historicalSeries"],
            target_region["historicalSeries"],
            reference,
        )
        if not historical_pattern.get("enoughHistory"):
            continue
        status = _flow_status(source, current, target)
        score = _route_score(source, current, target, historical_pattern)
        nodes = []
        for region in (source_region, current_region, target_region):
            nodes.append({
                "name": region["name"],
                "regions": [region["name"]],
                "latitude": region["latitude"],
                "longitude": region["longitude"],
                "signal": region["signal"],
            })
        routes.append({
            "id": f"data-route-{route_index}",
            "label": " → ".join(_short_region_name(node["name"]) for node in nodes),
            "color": ROUTE_COLORS[(route_index - 1) % len(ROUTE_COLORS)],
            "score": score,
            "confidence": _confidence(source, current, target),
            "status": status,
            "stageMetrics": _stage_metrics(source, current, target),
            "historicalPattern": historical_pattern,
            "nodes": nodes,
        })
    routes.sort(key=lambda route: (
        FLOW_STATUS_PRIORITY.get(route.get("status"), 99),
        -(route["historicalPattern"].get("targetRiseRatePct") or -1),
        -(route["historicalPattern"].get("precedingPatternCount") or 0),
        -route["score"],
        -(route["nodes"][1]["signal"].get("currentPriceChangePct") or -999),
    ))
    if not routes:
        raise ValueError("비교할 수 있는 최근 실거래가 아직 충분하지 않아요.")
    status_counts = {
        status: sum(1 for route in routes if route.get("status") == status)
        for status in FLOW_STATUS_PRIORITY
    }
    total_route_count = len(routes)
    display_routes = routes[:MAX_DISPLAY_ROUTES]
    return _apply_watch_ranking({
        "source": "국토교통부 실거래가 공개시스템 신고 거래",
        "baseMonth": reference.strftime("%Y-%m"),
        "periodMonths": int(period_months),
        "windowMonths": WINDOW_MONTHS,
        "historyMonths": HISTORY_MONTHS,
        "riseCriteria": {
            "minimumPriceChangePct": MIN_FLOW_PRICE_RISE_PCT,
            "minimumTradesPerWindow": MIN_WINDOW_DEALS,
        },
        "candidateCriteria": {
            "minimumStageChangePct": MIN_STAGE_CHANGE_PCT,
            "minimumTargetLagPct": MIN_TARGET_LAG_PCT,
            "minimumTargetCurrentRisePct": MIN_TARGET_CURRENT_RISE_PCT,
        },
        "regionCount": len(regions),
        "routeMode": "data_generated",
        "candidateRouteCount": status_counts[FLOW_STATUS_NEXT_CANDIDATE],
        "totalRouteCount": total_route_count,
        "statusCounts": status_counts,
        "displayRouteLimit": MAX_DISPLAY_ROUTES,
        "routes": display_routes,
        "partialFetchErrors": fetch_errors,
    })


def get_snapshot():
    """3개월 기준 흐름 화면용 실거래 스냅샷을 빠르게 돌려준다.

    최신 계산이 오래 걸릴 때는 이전 결과를 먼저 반환하고, 갱신은 뒤에서 한다.
    캐시가 전혀 없을 때만 준비 상태를 반환한다.
    """
    period = FLOW_PERIOD_MONTHS
    if not molit_transactions.configured():
        raise RuntimeError("국토부 실거래가 연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")
    reference = _base_month()
    path = _cache_path(reference, period)
    with CACHE_LOCK:
        cached = _read_cache(path)
        if cached:
            response = dict(cached)
            response.update({"cached": True, "stale": False, "refreshing": False})
            return _apply_watch_ranking(response)
        stale = _read_cached_payload(path)

    # A temporary upstream circuit break must not hide an already saved snapshot.
    if not molit_transactions.enabled():
        if stale:
            response = dict(stale)
            response.update({"cached": True, "stale": True, "refreshing": False})
            return _apply_watch_ranking(response)
        raise RuntimeError("국토부 실거래가 연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")

    refresh_started = _schedule_snapshot_refresh(reference, period, path)
    if stale:
        response = dict(stale)
        response.update({"cached": True, "stale": True, "refreshing": True})
        return _apply_watch_ranking(response)
    return {
        "pending": True,
        "refreshing": True,
        "baseMonth": reference.strftime("%Y-%m"),
        "periodMonths": int(period),
        "refreshStarted": refresh_started,
    }


def prewarm_snapshot():
    """서버가 켜질 때 최신 흐름 스냅샷을 미리 준비한다."""
    if not molit_transactions.enabled():
        return False
    reference = _base_month()
    period = FLOW_PERIOD_MONTHS
    path = _cache_path(reference, period)
    with CACHE_LOCK:
        if _read_cache(path):
            return False
    return _schedule_snapshot_refresh(reference, period, path)
