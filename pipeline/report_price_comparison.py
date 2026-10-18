"""Same-area, same-period transaction comparison for a paid apartment report."""

import datetime
import statistics

import molit_transactions
import real_estate_search


MIN_TRADES = 3
MIN_PEERS = 2
LOOKBACK_PERIODS = (3, 6, 12)
MAX_PRICE_GAP = 0.20
MAX_HOUSEHOLD_GAP = 0.65
MAX_APPROVAL_YEAR_GAP = 15
MAX_DISCOVERY_CANDIDATES = 60


def _months(end_month, count):
    return {
        molit_transactions._shift_month(end_month, -offset)
        for offset in range(count)
    }


def _average_in_months(transactions, months):
    prices = [
        float(trade.get("dealAmountEok") or 0)
        for trade in transactions
        if str(trade.get("dealDate") or "")[:7].replace("-", "") in months
        and float(trade.get("dealAmountEok") or 0) > 0
    ]
    return (statistics.mean(prices), len(prices)) if prices else (None, 0)


def _area_adjusted_average(transactions, months, target_area):
    prices = []
    for trade in transactions:
        if str(trade.get("dealDate") or "")[:7].replace("-", "") not in months:
            continue
        try:
            area = float(trade.get("exclusiveArea") or 0)
            price = float(trade.get("dealAmountEok") or 0)
        except (TypeError, ValueError):
            continue
        if area > 0 and price > 0 and abs(area / target_area - 1) <= .10:
            prices.append(price * target_area / area)
    return (statistics.mean(prices), len(prices)) if prices else (None, 0)


def _transactions(entity, area_label):
    return molit_transactions.transactions_for_apartment(
        entity.get("name") or "",
        region=entity.get("district") or "",
        area_label=area_label,
        lookback_months=12,
        entity=entity,
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


def _approved_year(entity):
    try:
        return int(str(entity.get("approvedAt") or "")[:4])
    except ValueError:
        return None


def _additional_candidates(target, already_selected):
    """Find comparable physical complexes before checking their actual area trades."""
    target_households = int(target.get("households") or 0)
    target_year = _approved_year(target)
    if target_households <= 0:
        return []
    excluded = {_physical_key(target), *already_selected}
    district = real_estate_search.compact(target.get("district"))
    dong = real_estate_search.compact(target.get("legalDong"))
    candidates = []
    for entity in real_estate_search.APARTMENT_MASTER:
        if (real_estate_search.compact(entity.get("district")) != district
                or entity.get("aggregate") or entity.get("status")
                or _physical_key(entity) in excluded):
            continue
        households = int(entity.get("households") or 0)
        year = _approved_year(entity)
        if households <= 0 or abs(households / target_households - 1) > MAX_HOUSEHOLD_GAP:
            continue
        if target_year and year and abs(year - target_year) > MAX_APPROVAL_YEAR_GAP:
            continue
        candidates.append(entity)
    candidates.sort(key=lambda entity: (
        0 if real_estate_search.compact(entity.get("legalDong")) == dong else 1,
        abs(int(entity.get("households") or 0) / target_households - 1),
        abs((_approved_year(entity) or target_year or 0) - (target_year or 0)),
        entity.get("name") or "",
    ))
    return candidates[:MAX_DISCOVERY_CANDIDATES]


def _candidate_fit(target, peer_entity, own_average, peer_average):
    target_households = int(target.get("households") or 0)
    peer_households = int(peer_entity.get("households") or 0)
    target_year = _approved_year(target)
    peer_year = _approved_year(peer_entity)
    price_gap = abs(peer_average / own_average - 1)
    household_gap = abs(peer_households / target_households - 1) if target_households and peer_households else 1
    age_gap = abs(peer_year - target_year) / MAX_APPROVAL_YEAR_GAP if target_year and peer_year else 1
    location_gap = 0 if real_estate_search.compact(target.get("legalDong")) == real_estate_search.compact(peer_entity.get("legalDong")) else 1
    return (price_gap / MAX_PRICE_GAP * .45 + household_gap / MAX_HOUSEHOLD_GAP * .30
            + age_gap * .15 + location_gap * .10)


def _district_candidates(target, excluded):
    """Last resort: use every distinct complex in the same district."""
    district = real_estate_search.compact(target.get("district"))
    seen = {_physical_key(target), *excluded}
    for entity in real_estate_search.APARTMENT_MASTER:
        key = _physical_key(entity)
        if (real_estate_search.compact(entity.get("district")) != district
                or entity.get("aggregate") or entity.get("status") or key in seen):
            continue
        seen.add(key)
        yield entity


def _relaxed_fit(target, peer_entity, own_average, peer_average):
    """Prefer similar prices, then nearby places and comparable buildings."""
    price_gap = abs(peer_average / own_average - 1)
    own_households = int(target.get("households") or 0)
    peer_households = int(peer_entity.get("households") or 0)
    household_gap = min(1, abs(peer_households / own_households - 1)) if own_households and peer_households else 1
    own_year, peer_year = _approved_year(target), _approved_year(peer_entity)
    age_gap = min(1, abs(own_year - peer_year) / 15) if own_year and peer_year else 1
    dong_gap = 0 if real_estate_search.compact(target.get("legalDong")) == real_estate_search.compact(peer_entity.get("legalDong")) else 1
    return price_gap * 3 + household_gap * .25 + age_gap * .15 + dong_gap * .2


def compare(row, entity, peers, area_label):
    """Return a peer mean only when two or more peers have enough matching trades."""
    area_label = str(area_label or "").strip()
    if not entity or not molit_transactions._area_target(area_label):
        return {"status": "unavailable", "reason": "전용면적을 확인하지 못했어요."}
    try:
        own_trades = _transactions(entity, area_label)
    except Exception:
        own_trades = []
    if not own_trades:
        return {"status": "unavailable", "reason": "같은 면적의 실거래가 부족해요."}

    latest_month = max(str(trade.get("dealDate") or "")[:7] for trade in own_trades)
    try:
        latest_date = datetime.date.fromisoformat(latest_month + "-01")
    except ValueError:
        return {"status": "unavailable", "reason": "거래 날짜를 확인하지 못했어요."}
    today = datetime.date.today()
    age_months = (today.year - latest_date.year) * 12 + today.month - latest_date.month
    if age_months > 3:
        return {"status": "unavailable", "reason": "최근 거래가 오래돼 주변 단지와 비교하기 어려워요."}

    peer_trades = []
    selected_keys = set()
    for peer in peers or []:
        try:
            peer_entity = _peer_entity(peer)
            if not peer_entity:
                continue
            trades = _transactions(peer_entity, area_label)
        except Exception:
            continue
        key = _physical_key(peer_entity)
        if key in selected_keys or key == _physical_key(entity):
            continue
        selected_keys.add(key)
        peer_trades.append((peer, peer_entity, trades, False))

    additional_trades = None
    reference_results = []

    for period in LOOKBACK_PERIODS:
        months = _months(latest_month.replace("-", ""), period)
        own_average, own_count = _average_in_months(own_trades, months)
        if own_count < MIN_TRADES:
            continue
        matched = []
        for peer, peer_entity, trades, expanded in peer_trades:
            peer_average, peer_count = _average_in_months(trades, months)
            if peer_count < MIN_TRADES or abs(peer_average / own_average - 1) > MAX_PRICE_GAP:
                continue
            matched.append((peer, peer_entity, peer_average, peer_count, expanded))
        if len(matched) < MIN_PEERS:
            if additional_trades is None:
                additional_trades = []
                for candidate in _additional_candidates(entity, selected_keys):
                    try:
                        trades = _transactions(candidate, area_label)
                    except Exception:
                        continue
                    if trades:
                        additional_trades.append((candidate, candidate, trades, True))
            extra = []
            for peer, peer_entity, trades, expanded in additional_trades:
                peer_average, peer_count = _average_in_months(trades, months)
                if peer_count < MIN_TRADES or abs(peer_average / own_average - 1) > MAX_PRICE_GAP:
                    continue
                extra.append((peer, peer_entity, peer_average, peer_count, expanded))
            extra.sort(key=lambda entry: (_candidate_fit(entity, entry[1], own_average, entry[2]), entry[1].get("name") or ""))
            matched.extend(extra[:max(0, 3 - len(matched))])
        if len(matched) < MIN_PEERS:
            continue
        matched = matched[:3]
        peer_rows = [{
            "name": peer.get("name") or "",
            "legalDong": peer_entity.get("legalDong") or "",
            "areaLabel": area_label,
            "averagePriceEok": round(peer_average, 4),
            "transactionCount": peer_count,
        } for peer, peer_entity, peer_average, peer_count, _expanded in matched]
        # Give each apartment equal weight; a very active complex must not
        # silently stand in for all the comparison apartments.
        peer_average = statistics.mean(peer["averagePriceEok"] for peer in peer_rows)
        difference_pct = (own_average / peer_average - 1) * 100
        expanded = any(entry[4] for entry in matched)
        result = {
            "status": "reference" if expanded or period > 6 else "ready",
            "region": entity.get("district") or row.get("region") or "",
            "areaLabel": area_label,
            "periodMonths": period,
            "throughMonth": latest_month,
            "averagePriceEok": round(own_average, 4),
            "transactionCount": own_count,
            "peerAveragePriceEok": round(peer_average, 4),
            "differencePct": round(difference_pct, 1),
            "position": "low" if difference_pct <= -5 else "high" if difference_pct >= 5 else "similar",
            "selectionMethod": "expanded" if expanded else "selected",
            "peers": peer_rows,
        }
        if result["status"] == "reference":
            result["reason"] = (
                "비교 단지의 동네·연식·세대수 차이가 있어 이번 가격 차이는 종합 점수에 넣지 않았어요."
                if expanded else "12개월 거래는 오래돼 이번 가격 차이는 종합 점수에 넣지 않았어요."
            )
        if result["status"] == "ready":
            return result
        fit = statistics.mean(_candidate_fit(entity, peer_entity, own_average, peer_average)
                              for _peer, peer_entity, peer_average, _count, _expanded in matched)
        reference_results.append((fit + {3: 0, 6: .08, 12: .25}[period], result))
    if reference_results:
        return min(reference_results, key=lambda entry: entry[0])[1]
    # A strict price/size screen can exclude active markets such as older
    # complexes with redevelopment expectations. Show actual same-area trades
    # from the district as a clearly labelled reference comparison instead.
    known = list(peer_trades) + list(additional_trades or [])
    seen_keys = {_physical_key(peer_entity) for _, peer_entity, _, _ in known}
    for candidate in _district_candidates(entity, seen_keys):
        try:
            trades = _transactions(candidate, area_label)
        except Exception:
            continue
        if trades:
            known.append((candidate, candidate, trades, True))
    for period in LOOKBACK_PERIODS:
        months = _months(latest_month.replace("-", ""), period)
        own_average, own_count = _average_in_months(own_trades, months)
        if own_count < MIN_TRADES:
            continue
        eligible = []
        for peer, peer_entity, trades, _ in known:
            peer_average, peer_count = _average_in_months(trades, months)
            if peer_count >= MIN_TRADES:
                eligible.append((peer, peer_entity, peer_average, peer_count))
        if len(eligible) < MIN_PEERS:
            continue
        eligible.sort(key=lambda entry: (
            _relaxed_fit(entity, entry[1], own_average, entry[2]),
            entry[1].get("name") or "",
        ))
        peer_rows = [{
            "name": peer.get("name") or "",
            "legalDong": peer_entity.get("legalDong") or "",
            "areaLabel": area_label,
            "averagePriceEok": round(peer_average, 4),
            "transactionCount": peer_count,
        } for peer, peer_entity, peer_average, peer_count in eligible[:3]]
        peer_average = statistics.mean(peer["averagePriceEok"] for peer in peer_rows)
        difference_pct = (own_average / peer_average - 1) * 100
        return {
            "status": "reference",
            "region": entity.get("district") or row.get("region") or "",
            "areaLabel": area_label,
            "periodMonths": period,
            "throughMonth": latest_month,
            "averagePriceEok": round(own_average, 4),
            "transactionCount": own_count,
            "peerAveragePriceEok": round(peer_average, 4),
            "differencePct": round(difference_pct, 1),
            "position": "low" if difference_pct <= -5 else "high" if difference_pct >= 5 else "similar",
            "selectionMethod": "relaxed",
            "peers": peer_rows,
            "reason": "같은 구의 비슷한 면적 거래로 비교 범위를 넓혔어요. 단지 조건이 달라 이번 가격 차이는 종합 점수에 넣지 않았어요.",
        }
    # When no exact-size peers traded, compare homes within 10% of the
    # target area after converting each sale price to the target area.
    own_areas = []
    for trade in own_trades:
        try:
            area = float(trade.get("exclusiveArea") or 0)
        except (TypeError, ValueError):
            continue
        if area > 0:
            own_areas.append(area)
    target_area = (statistics.median(own_areas) if own_areas
                   else sum(molit_transactions._area_target(area_label)) / 2)
    range_label = f"{target_area * .9:.2f}~{target_area * 1.1:.2f}"
    widened = []
    for candidate in _district_candidates(entity, set()):
        try:
            trades = _transactions(candidate, range_label)
        except Exception:
            continue
        if trades:
            widened.append((candidate, trades))
    single_peer_result = None
    for period in LOOKBACK_PERIODS:
        months = _months(latest_month.replace("-", ""), period)
        own_average, own_count = _average_in_months(own_trades, months)
        if own_count < MIN_TRADES:
            continue
        eligible = []
        for candidate, trades in widened:
            peer_average, peer_count = _area_adjusted_average(trades, months, target_area)
            if peer_count >= MIN_TRADES:
                eligible.append((candidate, peer_average, peer_count))
        if not eligible:
            continue
        eligible.sort(key=lambda entry: (
            _relaxed_fit(entity, entry[0], own_average, entry[1]),
            entry[0].get("name") or "",
        ))
        peer_rows = [{
            "name": candidate.get("name") or "",
            "legalDong": candidate.get("legalDong") or "",
            "areaLabel": range_label,
            "averagePriceEok": round(peer_average, 4),
            "transactionCount": peer_count,
        } for candidate, peer_average, peer_count in eligible[:3]]
        peer_average = statistics.mean(peer["averagePriceEok"] for peer in peer_rows)
        difference_pct = (own_average / peer_average - 1) * 100
        result = {
            "status": "reference",
            "region": entity.get("district") or row.get("region") or "",
            "areaLabel": area_label,
            "periodMonths": period,
            "throughMonth": latest_month,
            "averagePriceEok": round(own_average, 4),
            "transactionCount": own_count,
            "peerAveragePriceEok": round(peer_average, 4),
            "differencePct": round(difference_pct, 1),
            "position": "low" if difference_pct <= -5 else "high" if difference_pct >= 5 else "similar",
            "selectionMethod": "area_adjusted",
            "peers": peer_rows,
            "reason": f"같은 구의 전용면적 {range_label}㎡ 거래를 {target_area:.1f}㎡ 가격으로 환산했어요. 단지 조건이 달라 이번 가격 차이는 종합 점수에 넣지 않았어요.",
        }
        if len(peer_rows) >= MIN_PEERS:
            return result
        if single_peer_result is None:
            result["reason"] = "비교할 거래가 있는 단지 1곳의 비슷한 면적 거래를 환산했어요. 참고 별점이므로 다른 단지도 함께 살펴보세요."
            single_peer_result = result
    if single_peer_result:
        return single_peer_result
    return {
        "status": "unavailable",
        "reasonCode": "insufficient_peers",
        "reason": "이 단지 거래는 있지만, 비슷한 면적·가격대·규모의 거래가 있는 비교 단지 2곳을 찾지 못했어요.",
    }
