"""Conservative same-complex 59㎡/84㎡ transaction-price comparison."""

import datetime
import statistics


def relative_area_price_signal(transactions, today=None):
    """Compare the 59/84 price ratio with this same complex's earlier ratio."""
    today = today or datetime.date.today()
    recent_start = today - datetime.timedelta(days=183)
    history_start = today - datetime.timedelta(days=730)
    groups = {period: {59: [], 84: []} for period in ("recent", "history")}
    for row in transactions:
        try:
            area = float(row.get("exclusiveArea") or 0)
            price = float(row.get("dealAmountEok") or 0)
            deal_date = datetime.date.fromisoformat(str(row.get("dealDate") or ""))
        except (TypeError, ValueError):
            continue
        area_group = int(area)
        if area_group not in (59, 84) or price <= 0 or not history_start <= deal_date <= today:
            continue
        period = "recent" if deal_date >= recent_start else "history"
        groups[period][area_group].append((price, deal_date))

    counts = {
        period: {str(area): len(rows) for area, rows in by_area.items()}
        for period, by_area in groups.items()
    }
    if not all(len(rows) >= 3 for by_area in groups.values() for rows in by_area.values()):
        return {"state": "insufficient", "counts": counts}

    recent = {
        area: statistics.median(price for price, _ in rows)
        for area, rows in groups["recent"].items()
    }
    history = {
        area: statistics.median(price for price, _ in rows)
        for area, rows in groups["history"].items()
    }
    recent_ratio = recent[84] / recent[59]
    history_ratio = history[84] / history[59]
    ratio_change = recent_ratio / history_ratio - 1
    cheaper_area = 84 if ratio_change <= -0.07 else 59 if ratio_change >= 0.07 else None
    return {
        "state": "ready",
        "cheaperArea": cheaper_area,
        "recentMedianPriceEok": {str(area): round(price, 2) for area, price in recent.items()},
        "recentGapEok": round(recent[84] - recent[59], 2),
        "ratioChangePercent": round(ratio_change * 100, 1),
        "counts": counts,
        "latestDealDate": max(date for rows in groups["recent"].values() for _, date in rows).isoformat(),
        "basis": "같은 단지의 최근 6개월과 그 전 약 18개월 실거래 중위가격 비교",
    }
