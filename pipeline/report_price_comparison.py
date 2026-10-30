"""주변 비슷한 단지와 비교해 이 단지 시세가 싼지, 적정한지, 비싼지 판단한다.

동네·연식·브랜드 차이로 원래 비싼 단지와 단순 가격을 견주면 판단이 틀어진다.
그래서 두 단지의 가격 비율이 평소(지난 3년 반)보다 벌어졌는지, 좁혀졌는지를 본다.
비교 단지는 1km 이내, 세대수 ±20%, 준공연도 차이 5년 이내에서 고른다.
"""

import collections
import datetime
import statistics

import molit_transactions
import real_estate_search
import kakao_station_distances


WINDOW_MONTHS = 6
# '지금'은 최근 6개월, '평소'는 그 전 6개월 구간 7개(3년 반)의 비율 중간값이다.
HISTORY_WINDOWS = 7
LOOKBACK_MONTHS = WINDOW_MONTHS * (HISTORY_WINDOWS + 1)
MIN_WINDOW_TRADES = 3
LOW_DATA_TRADES = 5
MIN_USUAL_WINDOWS = 4
MIN_PEERS = 2
MAX_PEERS = 4
SHIFT_THRESHOLD_PP = 3.0
MAX_DISTANCE_METERS = 1000
MAX_APPROVAL_YEAR_GAP = 5
PEER_HOUSEHOLD_GAP = 0.2
MAX_DISCOVERY_CANDIDATES = 20


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


def _transactions(entity, area_label):
    return molit_transactions.transactions_for_apartment(
        entity.get("name") or "",
        region=entity.get("district") or "",
        area_label=area_label,
        lookback_months=LOOKBACK_MONTHS,
        entity=entity,
    )


def _window_index(deal_date, today):
    try:
        date = datetime.date.fromisoformat(str(deal_date or "")[:10])
    except ValueError:
        return None
    months_back = (today.year - date.year) * 12 + today.month - date.month
    return months_back // WINDOW_MONTHS if months_back >= 0 else None


def _window_prices(trades, today):
    """6개월 구간별 거래가격 목록. 0이 최근 6개월이다."""
    groups = collections.defaultdict(list)
    for trade in trades or []:
        price = float(trade.get("dealAmountEok") or 0)
        index = _window_index(trade.get("dealDate"), today)
        if price > 0 and index is not None and index <= HISTORY_WINDOWS:
            groups[index].append(price)
    return groups


def _window_medians(trades, today):
    return {index: (statistics.median(prices), len(prices))
            for index, prices in _window_prices(trades, today).items()}


def _median_count(groups, indices):
    prices = [price for index in indices for price in groups.get(index, [])]
    return (statistics.median(prices), len(prices)) if prices else (None, 0)


def _peer_gap(own, peer, current=(0,)):
    """이 단지 ÷ 비교 단지 가격 비율의 평소 값과 지금 값. 거래가 부족하면 이유를 돌려준다.

    ``current``는 '지금'으로 묶은 구간이다. 이 단지 거래가 뜸하면 최근 12개월(0, 1)을 쓴다.
    """
    usual = []
    for index in range(max(current) + 1, HISTORY_WINDOWS + 1):
        own_median, own_count = _median_count(own, (index,))
        peer_median, peer_count = _median_count(peer, (index,))
        if own_count >= MIN_WINDOW_TRADES and peer_count >= MIN_WINDOW_TRADES:
            usual.append(own_median / peer_median * 100)
    if len(usual) < MIN_USUAL_WINDOWS:
        return None, "history"
    peer_now, peer_count = _median_count(peer, current)
    if peer_count < MIN_WINDOW_TRADES:
        return None, "recent"
    own_now, _own_count = _median_count(own, current)
    usual_ratio = statistics.median(usual)
    current_ratio = own_now / peer_now * 100
    return {
        "usualRatio": round(usual_ratio, 1),
        "currentRatio": round(current_ratio, 1),
        "shiftPp": round(current_ratio - usual_ratio, 1),
        "usualWindowCount": len(usual),
    }, ""


def _candidates(target, *, nearby):
    """가격은 보지 않고 위치·규모·연식으로 비교 후보를 고른다."""
    target_households = int(target.get("households") or 0)
    target_year = _approved_year(target)
    own_key = _physical_key(target)
    seen, found = {own_key}, []
    for entity in real_estate_search.APARTMENT_MASTER:
        key = _physical_key(entity)
        if (key in seen or entity.get("aggregate") or entity.get("status")
                or not entity.get("households")
                or abs(int(entity["households"]) - target_households) > target_households * PEER_HOUSEHOLD_GAP):
            continue
        year = _approved_year(entity)
        if not year or abs(year - target_year) > MAX_APPROVAL_YEAR_GAP:
            continue
        distance = _peer_distance_meters(target, entity)
        if distance is None or distance > MAX_DISTANCE_METERS:
            continue
        seen.add(key)
        found.append((distance, entity.get("name") or "", entity, distance))
    found.sort(key=lambda entry: entry[:2])
    return [(entity, distance) for _rank, _name, entity, distance in found[:MAX_DISCOVERY_CANDIDATES]]


def _peer_rows(target, own, area_label, candidates, today, taken, current=(0,)):
    rows, excluded = [], []
    for entity, distance in candidates:
        key = _physical_key(entity)
        if key in taken or len(rows) >= MAX_PEERS:
            continue
        try:
            windows = _window_prices(_transactions(entity, area_label), today)
        except Exception:
            continue
        gap, reason = _peer_gap(own, windows, current)
        if not gap:
            # 평소 비율은 있는데 최근 거래만 부족한 단지는 뺐다고 알려 준다.
            if reason == "recent":
                excluded.append(entity.get("name") or "")
            continue
        taken.add(key)
        price, count = _median_count(windows, current)
        rows.append({
            **gap,
            "name": entity.get("name") or "",
            "legalDong": entity.get("legalDong") or "",
            "households": int(entity.get("households") or 0) or None,
            "approvalYear": _approved_year(entity),
            "distanceMeters": round(distance) if distance is not None else None,
            "areaLabel": area_label,
            "averagePriceEok": round(price, 4),
            "transactionCount": count,
            "diffPct": round((price / _median_count(own, current)[0] - 1) * 100, 1),
            "lowData": count < LOW_DATA_TRADES,
        })
    return rows, excluded


def compare(row, entity, peers, area_label, today=None):
    """주변 비교 단지와의 가격 차이가 평소보다 벌어졌는지 좁혀졌는지로 판정한다.

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
        "approvalYearGap": MAX_APPROVAL_YEAR_GAP,
        "householdsMin": households * (1 - PEER_HOUSEHOLD_GAP),
        "householdsMax": households * (1 + PEER_HOUSEHOLD_GAP),
        "householdsGapRatio": PEER_HOUSEHOLD_GAP,
        "windowMonths": WINDOW_MONTHS,
        "historyMonths": WINDOW_MONTHS * HISTORY_WINDOWS,
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
    own = _window_prices(own_trades, today)
    # 이 단지의 최근 6개월 거래가 적으면 '지금'을 최근 12개월로 넓히고 자료 적음으로 표시한다.
    current = (0,)
    if _median_count(own, current)[1] < MIN_WINDOW_TRADES:
        current = (0, 1)
    if _median_count(own, current)[1] < MIN_WINDOW_TRADES:
        return {"status": "unavailable", "reasonCode": "insufficient_recent_trades",
                "reason": "이 단지의 최근 12개월 거래가 적어 주변과 비교하기 어려워요.", "selectionCriteria": criteria}

    if _entity_coordinates(entity) is None:
        return {"status": "unavailable", "reasonCode": "missing_coordinates",
                "reason": "단지 위치 자료가 없어 가까운 비교 단지를 고르기 어려워요.", "selectionCriteria": criteria}
    taken = {_physical_key(entity)}
    peer_rows, excluded = _peer_rows(entity, own, area_label, _candidates(entity, nearby=True), today, taken, current)
    if len(peer_rows) < MIN_PEERS:
        return {"status": "unavailable", "reasonCode": "insufficient_peers",
                "reason": "1km 안에 비슷한 조건의 거래 자료가 부족해요.",
                "selectionCriteria": criteria}
    scope = "nearby"

    # 단지마다 같은 비중으로 본다. 거래가 많은 한 단지가 결론을 끌고 가지 않게 한다.
    shift = statistics.mean(peer["shiftPp"] for peer in peer_rows)
    usual = statistics.mean(peer["usualRatio"] for peer in peer_rows)
    current_ratio = statistics.mean(peer["currentRatio"] for peer in peer_rows)
    own_price, own_count = _median_count(own, current)
    period_months = WINDOW_MONTHS * len(current)
    peer_average = statistics.mean(peer["averagePriceEok"] for peer in peer_rows)
    latest_month = max((str(trade.get("dealDate") or "")[:7] for trade in own_trades), default="")
    return {
        "status": "ready",
        "method": "usual_gap",
        "region": entity.get("district") or row.get("region") or "",
        "areaLabel": area_label,
        "periodMonths": period_months,
        "periodWidened": len(current) > 1,
        "historyMonths": WINDOW_MONTHS * (HISTORY_WINDOWS + 1 - len(current)),
        "throughMonth": latest_month,
        "averagePriceEok": round(own_price, 4),
        "transactionCount": own_count,
        "peerAveragePriceEok": round(peer_average, 4),
        "differencePct": round((own_price / peer_average - 1) * 100, 1),
        "usualGapPct": round(usual - 100, 1),
        "currentGapPct": round(current_ratio - 100, 1),
        "shiftPp": round(shift, 1),
        "position": "low" if shift < -SHIFT_THRESHOLD_PP else "high" if shift > SHIFT_THRESHOLD_PP else "similar",
        "lowData": len(current) > 1 or own_count < LOW_DATA_TRADES or any(peer["lowData"] for peer in peer_rows),
        "scope": scope,
        "selectionMethod": scope,
        "peers": peer_rows,
        "excludedPeers": [name for name in dict.fromkeys(excluded) if name][:3],
        "selectionCriteria": criteria,
    }
