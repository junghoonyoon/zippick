"""세대수·연식이 비슷한 단지와 비교해 이 단지 시세가 싼지, 적정한지, 비싼지 판단한다.

동네·연식·브랜드 차이로 원래 비싼 단지와 단순 가격을 견주면 판단이 틀어진다.
그래서 해마다 비교 단지보다 얼마나 싸거나 비쌌는지 구하고, 지금 차이를 그 평소 값과 비교한다.
비교 단지는 가까운 곳부터 찾고, 부족하면 같은 구로, 그래도 부족하면 조건을 넓힌다.
넓혀서 얻은 결과는 정확도가 낮으므로 '자료 적음'으로 표시한다.
"""

import collections
import datetime
import statistics

import molit_transactions
import real_estate_search
import kakao_station_distances


WINDOW_MONTHS = 6
# '지금'은 최근 6개월, '평소'는 지난 연도별 가격 차이의 중간값이다.
HISTORY_YEARS = 4
LOOKBACK_MONTHS = 60
# 이 단지 거래가 뜸하면 '지금'을 6개월 → 12개월 → 24개월로 넓힌다.
CURRENT_MONTHS = (6, 12, 24)
MIN_OWN_TRADES = 3
MIN_WINDOW_TRADES = 2
LOW_DATA_TRADES = 5
MIN_USUAL_YEARS = 2
MIN_PEERS = 2
MAX_PEERS = 4
SHIFT_THRESHOLD_PP = 3.0
# 평소 차이를 모를 때의 단순 가격 비교 기준. 동네 차이가 섞여 있어 더 넓게 본다.
SIMPLE_THRESHOLD_PCT = 5.0
MAX_DISTANCE_METERS = 1000
AREA_ADJUST_RATIO = 0.10
MIN_PEER_HOUSEHOLDS = 100
MAX_DISCOVERY_CANDIDATES = 12
# 위에서부터 차례로 찾고, 비교 단지 2곳을 채우면 멈춘다.
PEER_TIERS = (
    {"key": "nearby", "householdGap": 0.5, "yearGap": 10},
    {"key": "district", "householdGap": 0.5, "yearGap": 10},
    {"key": "district_wide", "householdFloor": 0.3, "yearGap": 15},
    {"key": "district_any"},
)


def _peer_entity(peer):
    """Resolve the exact peer rather than an approximate same-name search hit."""
    for key in ("apartmentId", "kaptCode", "complexNo"):
        value = str(peer.get(key) or "").strip()
        if value:
            for entity in real_estate_search.APARTMENT_MASTER:
                if str(entity.get(key) or "").strip() == value:
                    return entity
            return None
    name = real_estate_search.compact(peer.get("name"))
    region = real_estate_search.compact(peer.get("region"))
    dong = real_estate_search.compact(peer.get("legalDong"))
    jibun = str(peer.get("jibun") or "").strip()
    for entity in real_estate_search.APARTMENT_MASTER:
        if (
            real_estate_search.compact(entity.get("name")) == name
            and real_estate_search.compact(entity.get("district")) == region
            and real_estate_search.compact(entity.get("legalDong")) == dong
            and str(entity.get("jibun") or "").strip() == jibun
        ):
            return entity
    return None


def _physical_key(entity):
    district = real_estate_search.compact(entity.get("district") or entity.get("region"))
    dong = real_estate_search.compact(entity.get("legalDong"))
    jibun = str(entity.get("jibun") or "").strip()
    return (district, dong, jibun or real_estate_search.compact(entity.get("name")))


def alternative_facts(peers):
    """Attach verified master facts to budget alternatives without changing identity."""
    result = []
    for peer in peers or []:
        item = dict(peer)
        entity = _peer_entity(peer)
        if entity:
            year = _approved_year(entity)
            if year:
                item["buildingAge"] = max(0, datetime.date.today().year - year)
            if entity.get("households"):
                item["households"] = entity["households"]
        result.append(item)
    return result


def _approved_year(entity):
    try:
        return int(str(entity.get("approvedAt") or "")[:4])
    except ValueError:
        return None


def _entity_coordinates(entity):
    direct = kakao_station_distances._valid_coordinates(entity.get("latitude"), entity.get("longitude"))
    if direct:
        return direct
    cached = kakao_station_distances.cached_station(entity) or {}
    coordinates = kakao_station_distances._valid_coordinates(cached.get("latitude"), cached.get("longitude"))
    if coordinates:
        return coordinates
    address = kakao_station_distances.entity_address(entity)
    geocode = kakao_station_distances._load_cache().get("geocodes", {}).get(
        kakao_station_distances._coordinate_key(address), {})
    if address and geocode.get("address") == address:
        return kakao_station_distances._valid_coordinates(geocode.get("latitude"), geocode.get("longitude"))
    return None


def _peer_distance_meters(target, peer):
    own_coordinates, peer_coordinates = _entity_coordinates(target), _entity_coordinates(peer)
    return kakao_station_distances._distance_meters(*own_coordinates, *peer_coordinates) \
        if own_coordinates and peer_coordinates else None


def _resolve_report_coordinates(entity):
    """Resolve missing coordinates only for complexes selected for the report."""
    coordinates = _entity_coordinates(entity)
    if coordinates:
        return coordinates
    address = kakao_station_distances.entity_address(entity)
    try:
        # A neighborhood-only address resolves to its center, not the complex.
        if entity.get("jibun") or entity.get("address"):
            found = kakao_station_distances._coordinates_for_entity(entity, address) or {}
        else:
            found = kakao_station_distances.geocode_apartment_keyword(entity) or {}
        return kakao_station_distances._valid_coordinates(found.get("latitude"), found.get("longitude"))
    except Exception:
        return None


def _transactions(entity, area_label):
    return molit_transactions.transactions_for_apartment_cached(
        entity.get("name") or "",
        region=entity.get("district") or "",
        area_label=area_label,
        lookback_months=LOOKBACK_MONTHS,
        entity=entity,
        allow_stale=True,
    )


def _months_back(date, today):
    return (today.year - date.year) * 12 + today.month - date.month


def _priced(trades, today, target_area=None):
    """거래를 (날짜, 가격)으로 정리한다. target_area가 있으면 그 면적 가격으로 환산한다."""
    priced = []
    for trade in trades or []:
        try:
            date = datetime.date.fromisoformat(str(trade.get("dealDate") or "")[:10])
            price = float(trade.get("dealAmountEok") or 0)
            area = float(trade.get("exclusiveArea") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0 or not 0 <= _months_back(date, today) < LOOKBACK_MONTHS:
            continue
        if target_area:
            if area <= 0 or abs(area / target_area - 1) > AREA_ADJUST_RATIO:
                continue
            price = price * target_area / area
        priced.append((date, price))
    return priced


def _recent(priced, today, months):
    prices = [price for date, price in priced if _months_back(date, today) < months]
    return (statistics.median(prices), len(prices)) if prices else (None, 0)


def _yearly(priced, today, months):
    """지난 연도별 중간값과 건수. '지금'에 들어간 거래는 빼서 겹치지 않게 한다."""
    first_year = today.year - HISTORY_YEARS
    groups = collections.defaultdict(list)
    for date, price in priced:
        if first_year <= date.year < today.year and _months_back(date, today) >= months:
            groups[date.year].append(price)
    return {year: (statistics.median(prices), len(prices)) for year, prices in groups.items()}


def _peer_gap(own, peer, today, months):
    """이 단지 ÷ 비교 단지 가격 비율의 연도별 값과 지금 값. 거래가 부족하면 이유를 돌려준다."""
    peer_now, peer_count = _recent(peer, today, months)
    if peer_count < MIN_WINDOW_TRADES:
        return None, "recent"
    own_years, peer_years = _yearly(own, today, months), _yearly(peer, today, months)
    yearly = {
        year: own_years[year][0] / peer_years[year][0] * 100
        for year in own_years
        if year in peer_years
        and own_years[year][1] >= MIN_WINDOW_TRADES and peer_years[year][1] >= MIN_WINDOW_TRADES
    }
    if len(yearly) < MIN_USUAL_YEARS:
        return None, "history"
    usual_ratio = statistics.median(yearly.values())
    current_ratio = _recent(own, today, months)[0] / peer_now * 100
    return {
        "usualRatio": round(usual_ratio, 1),
        "currentRatio": round(current_ratio, 1),
        "shiftPp": round(current_ratio - usual_ratio, 1),
        "yearlyRatios": {str(year): round(ratio, 1) for year, ratio in sorted(yearly.items())},
    }, ""


def _matches_tier(target, entity, tier):
    target_households, households = int(target.get("households") or 0), int(entity.get("households") or 0)
    if households < MIN_PEER_HOUSEHOLDS:
        return False
    if "householdGap" in tier and abs(households - target_households) > target_households * tier["householdGap"]:
        return False
    if households < target_households * tier.get("householdFloor", 0):
        return False
    target_year, year = _approved_year(target), _approved_year(entity)
    return "yearGap" not in tier or bool(year and abs(year - target_year) <= tier["yearGap"])


def _candidates(target, tier):
    """가격은 보지 않고 위치·규모·연식으로 비교 후보를 고른다."""
    target_households = int(target.get("households") or 0)
    target_year = _approved_year(target)
    district = real_estate_search.compact(target.get("district"))
    dong = real_estate_search.compact(target.get("legalDong"))
    target_located = _entity_coordinates(target) is not None
    own_key = _physical_key(target)
    seen, found = {own_key}, []
    for entity in real_estate_search.APARTMENT_MASTER:
        key = _physical_key(entity)
        if key in seen or entity.get("aggregate") or entity.get("status") or not _matches_tier(target, entity, tier):
            continue
        same_district = real_estate_search.compact(entity.get("district")) == district
        same_dong = same_district and real_estate_search.compact(entity.get("legalDong")) == dong
        if tier["key"] != "nearby" and not same_district:
            continue
        distance = _peer_distance_meters(target, entity) if target_located else None
        if tier["key"] == "nearby":
            # 좌표가 없는 단지가 많아, 거리를 모르면 같은 법정동을 가까운 단지로 본다.
            if not (distance <= MAX_DISTANCE_METERS if distance is not None else same_dong):
                continue
        seen.add(key)
        year = _approved_year(entity)
        fit = (abs(int(entity["households"]) / target_households - 1) * .6
               + (abs(year - target_year) / 20 if year else 1) * .4)
        found.append((0 if same_dong else 1, fit, entity.get("name") or "", entity, distance))
    found.sort(key=lambda entry: entry[:3])
    return [(entity, distance) for _dong, _fit, _name, entity, distance in found[:MAX_DISCOVERY_CANDIDATES]]


def _peer_priced(entity, area_label, today, target_area):
    if not target_area:
        return _priced(_transactions(entity, area_label), today)
    range_label = f"{target_area * (1 - AREA_ADJUST_RATIO):.1f}~{target_area * (1 + AREA_ADJUST_RATIO):.1f}"
    return _priced(_transactions(entity, range_label), today, target_area)


def _select_peers(target, own, area_label, months, today, target_area=None):
    """평소 차이를 계산할 수 있는 단지와 지금 가격만 있는 단지를 나눠 모은다."""
    gap_rows, plain_rows, excluded = [], [], []
    taken = {_physical_key(target)}
    own_price = _recent(own, today, months)[0]
    for tier_index, tier in enumerate(PEER_TIERS):
        for entity, distance in _candidates(target, tier):
            key = _physical_key(entity)
            if key in taken or len(gap_rows) >= MAX_PEERS:
                continue
            taken.add(key)
            try:
                priced = _peer_priced(entity, area_label, today, target_area)
            except Exception:
                continue
            gap, reason = _peer_gap(own, priced, today, months)
            if not gap and reason == "recent":
                # 평소 비율은 있는데 최근 거래만 부족한 단지는 뺐다고 알려 준다.
                if priced:
                    excluded.append(entity.get("name") or "")
                continue
            price, count = _recent(priced, today, months)
            row = {
                **(gap or {}),
                "_entity": entity,
                "name": entity.get("name") or "",
                "legalDong": entity.get("legalDong") or "",
                "households": int(entity.get("households") or 0) or None,
                "approvalYear": _approved_year(entity),
                "distanceMeters": round(distance) if distance is not None else None,
                "areaLabel": area_label,
                "averagePriceEok": round(price, 4),
                "transactionCount": count,
                "diffPct": round((price / own_price - 1) * 100, 1),
                "lowData": count < LOW_DATA_TRADES,
                "tier": tier_index,
            }
            (gap_rows if gap else plain_rows).append(row)
        if len(gap_rows) >= MIN_PEERS:
            break
    return gap_rows, plain_rows, excluded


def _target_area(trades, area_label):
    areas = [float(trade.get("exclusiveArea") or 0) for trade in trades]
    areas = [area for area in areas if area > 0]
    if areas:
        return statistics.median(areas)
    low, high = molit_transactions._area_target(area_label)
    return (low + high) / 2


def compare(row, entity, peers, area_label, today=None):
    """비교 단지와의 가격 차이가 평소보다 벌어졌는지 좁혀졌는지로 판정한다.

    평소 차이를 계산할 단지가 부족하면 지금 가격만 비교하고 method를 simple로 표시한다.
    ``peers``는 예전 호출 형태를 위해 받기만 한다. 비교 단지는 가격과 무관하게 새로 고른다.
    """
    today = today or datetime.date.today()
    entity = entity or {}
    area_label = str(area_label or "").strip()
    year, households = _approved_year(entity), int(entity.get("households") or 0)
    criteria = {
        "region": entity.get("district") or "",
        "maxDistanceMeters": MAX_DISTANCE_METERS,
        "priceIndependent": True,
        "windowMonths": WINDOW_MONTHS,
        "historyYears": HISTORY_YEARS,
        "thresholdPp": SHIFT_THRESHOLD_PP,
    }
    if not year or households <= 0:
        return {"status": "unavailable", "reasonCode": "missing_building_criteria",
                "reason": "세대수나 준공연도 자료가 없어 비슷한 단지를 고르기 어려워요.", "selectionCriteria": criteria}
    if not molit_transactions._area_target(area_label):
        return {"status": "unavailable", "reasonCode": "missing_area",
                "reason": "전용면적을 확인하지 못했어요.", "selectionCriteria": criteria}
    try:
        own_trades = _transactions(entity, area_label) or []
    except Exception:
        own_trades = []
    own = _priced(own_trades, today)
    months = next((value for value in CURRENT_MONTHS if _recent(own, today, value)[1] >= MIN_OWN_TRADES), CURRENT_MONTHS[-1])
    if _recent(own, today, months)[1] < MIN_WINDOW_TRADES:
        return {"status": "unavailable", "reasonCode": "insufficient_recent_trades",
                "reason": "이 단지의 최근 2년 거래가 적어 다른 단지와 비교하기 어려워요.", "selectionCriteria": criteria}

    gap_rows, plain_rows, excluded = _select_peers(entity, own, area_label, months, today)
    if len(gap_rows) < MIN_PEERS:
        adjusted_gaps, adjusted_plain, more = _select_peers(
            entity, own, area_label, months, today, target_area=_target_area(own_trades, area_label))
        excluded += more
        # Keep exact-area evidence when available. A converted-area history can
        # replace a simple-only match, but never add the same complex twice.
        gap_keys = {_physical_key(peer['_entity']) for peer in gap_rows}
        for peer in adjusted_gaps:
            key = _physical_key(peer['_entity'])
            if key not in gap_keys:
                peer['_areaAdjusted'] = True
                gap_rows.append(peer)
                gap_keys.add(key)
        plain_rows = [peer for peer in plain_rows if _physical_key(peer['_entity']) not in gap_keys]
        known = gap_keys | {_physical_key(peer['_entity']) for peer in plain_rows}
        for peer in adjusted_plain:
            key = _physical_key(peer['_entity'])
            if key not in known:
                peer['_areaAdjusted'] = True
                plain_rows.append(peer)
                known.add(key)
    if not gap_rows and not plain_rows:
        return {"status": "unavailable", "reasonCode": "insufficient_peers",
                "reason": "같은 구에 최근 거래가 있는 비교 단지를 찾지 못했어요.", "selectionCriteria": criteria}

    simple = bool(plain_rows) and len(gap_rows) < MIN_PEERS
    peer_rows = (sorted([*gap_rows, *plain_rows], key=lambda peer: peer["tier"]) if simple else gap_rows)[:MAX_PEERS]
    area_adjusted = any(peer.get('_areaAdjusted') for peer in peer_rows)
    own_coordinates = _resolve_report_coordinates(entity)
    for peer in peer_rows:
        peer_entity = peer.pop("_entity")
        peer.pop('_areaAdjusted', None)
        if peer["distanceMeters"] is None and own_coordinates:
            peer_coordinates = _resolve_report_coordinates(peer_entity)
            if peer_coordinates:
                peer["distanceMeters"] = round(kakao_station_distances._distance_meters(
                    *own_coordinates, *peer_coordinates))
    tier = max(peer["tier"] for peer in peer_rows)
    own_price, own_count = _recent(own, today, months)
    peer_average = statistics.mean(peer["averagePriceEok"] for peer in peer_rows)
    difference = (own_price / peer_average - 1) * 100
    yearly_gaps = []
    if simple:
        shift = usual_gap = current_gap = None
        position = "low" if difference <= -SIMPLE_THRESHOLD_PCT else "high" if difference >= SIMPLE_THRESHOLD_PCT else "similar"
    else:
        # 해마다 비교 단지들과의 평균 차이를 구한다. 단지마다 같은 비중으로 본다.
        own_years = _yearly(own, today, months)
        for year in sorted({int(year) for peer in peer_rows for year in peer["yearlyRatios"]}):
            ratios = [peer["yearlyRatios"][str(year)] for peer in peer_rows if str(year) in peer["yearlyRatios"]]
            yearly_gaps.append({
                "year": year,
                "gapPct": round(statistics.mean(ratios) - 100, 1),
                "peerCount": len(ratios),
                "tradeCount": own_years[year][1],
                "lowData": own_years[year][1] < LOW_DATA_TRADES,
            })
        usual_gap = round(statistics.median(entry["gapPct"] for entry in yearly_gaps), 1)
        current_gap = round(statistics.mean(peer["currentRatio"] for peer in peer_rows) - 100, 1)
        shift = round(current_gap - usual_gap, 1)
        position = "low" if shift < -SHIFT_THRESHOLD_PP else "high" if shift > SHIFT_THRESHOLD_PP else "similar"
    scope = "nearby" if tier == 0 else "district"
    conditions_relaxed = tier >= 2
    latest_month = max((str(trade.get("dealDate") or "")[:7] for trade in own_trades), default="")
    return {
        "status": "ready",
        "method": "simple" if simple else "usual_gap",
        "region": entity.get("district") or row.get("region") or "",
        "areaLabel": area_label,
        "periodMonths": months,
        "periodWidened": months > WINDOW_MONTHS,
        "yearlyGaps": yearly_gaps,
        "throughMonth": latest_month,
        "averagePriceEok": round(own_price, 4),
        "transactionCount": own_count,
        "peerAveragePriceEok": round(peer_average, 4),
        "differencePct": round(difference, 1),
        "usualGapPct": usual_gap,
        "currentGapPct": current_gap,
        "shiftPp": shift,
        "position": position,
        "lowData": (simple or area_adjusted or conditions_relaxed or len(peer_rows) < MIN_PEERS or months > WINDOW_MONTHS
                    or own_count < LOW_DATA_TRADES or any(peer["lowData"] for peer in peer_rows)),
        "scope": scope,
        "selectionMethod": scope,
        "conditionsRelaxed": conditions_relaxed,
        "areaAdjusted": area_adjusted,
        "peers": peer_rows,
        "excludedPeers": [name for name in dict.fromkeys(excluded) if name][:3],
        "selectionCriteria": criteria,
    }
