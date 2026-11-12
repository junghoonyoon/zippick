"""Selected-complex, selected-area monthly facts for five-year downturn review.

Reads the shared collected source only. A missing month is never a zero-trade
month; use only the contiguous available period ending in the last closed month.
"""
import datetime

import molit_transactions as molit

VERSION = "liquidity-history-v1"
LOOKBACK_MONTHS = 60


def for_apartment(row, entity=None, today=None):
    today = today or datetime.date.today()
    result = {"version": VERSION, "status": "unavailable", "requestedMonths": LOOKBACK_MONTHS,
              "asOf": today.isoformat(), "source": "국토교통부 실거래", "months": []}
    if row.get("priceIdentityVerified") is not True or not entity:
        return {**result, "reason": "단지와 평형이 확인되지 않아 과거 거래를 연결하지 못했어요."}
    name, region = row["name"], row.get("region") or row.get("regionLabel") or ""
    area = row.get("displayAreaLabel") or row.get("areaLabel")
    if not area:
        return {**result, "reason": "선택한 평형을 확인하지 못했어요."}
    periods = list(reversed(molit._deal_months_for_day(LOOKBACK_MONTHS + 1, today.isoformat())[1:]))
    approved = str(row.get("approvedAt") or "")[:7].replace("-", "")
    if len(approved) != 6 or not approved.isdigit():
        year = int(row.get("buildYear") or 0)
        approved = f"{year}01" if year > 0 else ""
    periods = [period for period in periods if not approved or period >= approved]
    sources = molit.source_rows_for_entity(entity, region)
    codes = sorted({code for source in sources for code in molit.related_lawd_codes(molit._row_lawd_cd(source))})
    if not codes or not periods:
        return {**result, "reason": "비교할 과거 거래 원본을 확인하지 못했어요."}
    kind = molit.transaction_kind_for_apartment(name, region)
    available = {period: all(molit._read_cached_month_memory(code, period, transaction_kind=kind) is not None
                            for code in codes) for period in periods}
    selected = []
    for period in reversed(periods):
        if not available[period]:
            break
        selected.append(period)
    selected.reverse()
    if not selected:
        return {**result, "reason": "최근 완료된 달의 실거래 원본이 없어 과거 거래를 비교하지 못했어요."}
    trades = molit.transactions_for_apartment_cached(name, region=region, area_label=area,
                                                    lookback_months=LOOKBACK_MONTHS + 1, entity=entity)
    buckets = {period: [] for period in selected}
    for trade in trades:
        period = str(trade.get("dealDate") or "")[:7].replace("-", "")
        price = float(trade.get("dealAmountEok") or 0)
        if period in buckets and price > 0:
            buckets[period].append(price)
    if not any(buckets.values()):
        return {**result, "reason": "선택한 평형의 과거 실거래를 확인하지 못했어요."}
    return {**result, "status": "ready", "areaLabel": area, "windowMonths": len(selected),
            "startPeriod": selected[0], "endPeriod": selected[-1],
            "coverageComplete": len(selected) == LOOKBACK_MONTHS,
            "months": [{"period": period, "count": len(buckets[period]),
                        "price": round(sum(buckets[period]) / len(buckets[period]), 4) if buckets[period] else None}
                       for period in selected]}
