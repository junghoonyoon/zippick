"""R-ONE 지역지수로 국토부 실거래를 현재 시점에 맞춰 보정한다."""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import statistics
from pathlib import Path


class RebIndexError(RuntimeError):
    """R-ONE 지수 데이터로 추정할 수 없을 때 발생한다."""


class AmbiguousRegionError(RebIndexError):
    def __init__(self, region, candidates):
        self.region = region
        self.candidates = candidates
        super().__init__(f"지역을 하나로 결정할 수 없어요: {region}")


_METRO_ALIASES = {
    "서울시": "서울",
    "부산시": "부산",
    "대구시": "대구",
    "인천시": "인천",
    "광주시": "광주",
    "대전시": "대전",
    "울산시": "울산",
    "세종시": "세종",
    "제주도": "제주",
    "경기도": "경기",
    "강원도": "강원",
}


def db_path():
    return Path(os.environ.get("REB_INDEX_DB", "~/maesu/data.db")).expanduser()


def status(path=None):
    path = Path(path or db_path())
    if not path.exists():
        return {"ready": False, "rowCount": 0, "latestPeriod": None}
    with sqlite3.connect(path) as con:
        row = con.execute("SELECT COUNT(*), MAX(period) FROM reb_index").fetchone()
    return {"ready": bool(row[0]), "rowCount": row[0], "latestPeriod": row[1]}


def _tokens(region):
    values = re.findall(r"[0-9A-Za-z가-힣]+", str(region or ""))
    return [_METRO_ALIASES.get(value, value) for value in values]


def resolve_region(region, path=None):
    """사용자 지역명을 R-ONE의 계층형 CLS_FULLNM으로 바꾼다."""
    tokens = _tokens(region)
    if not tokens:
        raise RebIndexError("지역을 입력해 주세요.")

    path = Path(path or db_path())
    if not path.exists():
        raise RebIndexError("R-ONE 지수 DB가 없어요.")
    with sqlite3.connect(path) as con:
        regions = [row[0] for row in con.execute("SELECT DISTINCT region FROM reb_index")]

    ranked = []
    for candidate in regions:
        parts = candidate.split(">")
        score = 0
        matched = True
        for token in tokens:
            if token in parts:
                score += 20
            elif any(token in part or part in token for part in parts):
                score += 5
            else:
                matched = False
                break
        if not matched:
            continue
        if parts[-1] == tokens[-1]:
            score += 100
        if parts[0] == tokens[0]:
            score += 40
        ranked.append((score, len(parts), candidate))

    if not ranked:
        raise RebIndexError(f"R-ONE에서 '{region}' 지역 지수를 찾지 못했어요.")
    ranked.sort(reverse=True)
    best_score = ranked[0][0]
    best = [row[2] for row in ranked if row[0] == best_score]
    if len(best) > 1:
        leaves = {value.split(">")[-1] for value in best}
        roots = {value.split(">")[0] for value in best}
        if len(leaves) > 1 or len(roots) > 1:
            raise AmbiguousRegionError(region, best[:8])
    return sorted(best, key=lambda value: (len(value.split(">")), value), reverse=True)[0]


def _period(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:6] if len(digits) >= 6 else ""


def _percentile(values, quantile):
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def adjust_price(price, base_index, current_index):
    """backtest_prototype.py와 같은 가격지수 비율 보정 순수 함수."""
    if not price or not base_index or not current_index:
        return None
    return float(price) * (float(current_index) / float(base_index))


def _series(resolved_region, path=None):
    path = Path(path or db_path())
    with sqlite3.connect(path) as con:
        rows = con.execute(
            "SELECT period, value FROM reb_index WHERE region = ? ORDER BY period",
            (resolved_region,),
        ).fetchall()
    if not rows:
        raise RebIndexError("선택한 지역의 R-ONE 지수가 비어 있어요.")
    return [(str(period), float(value)) for period, value in rows if value]


def _value_at_or_before(series, period):
    matches = [row for row in series if row[0] <= period]
    return matches[-1] if matches else None


def estimate_transactions(transactions, region, path=None, today=None):
    """거래별 지수 보정 후 대표 가격과 25~75백분위 범위를 반환한다."""
    resolved = resolve_region(region, path=path)
    series = _series(resolved, path=path)
    latest_period, latest_index = series[-1]
    adjusted = []
    newest_date = ""

    for row in transactions or []:
        try:
            price = float(row.get("dealAmountEok") or row.get("latestDealPriceEok") or 0)
        except (TypeError, ValueError):
            continue
        trade_date = str(row.get("dealDate") or row.get("latestDealDate") or "")
        trade_period = _period(trade_date)
        if price <= 0 or not trade_period:
            continue
        newest_date = max(newest_date, trade_date)
        if trade_period > latest_period:
            adjusted_price = price
            base_period = trade_period
            base_index = None
            factor = 1.0
            status_value = "지수 공표 이후 실거래"
        else:
            base = _value_at_or_before(series, trade_period)
            if not base:
                continue
            base_period, base_index = base
            adjusted_price = adjust_price(price, base_index, latest_index)
            factor = latest_index / base_index
            status_value = "R-ONE 지수보정"
        adjusted.append({
            "dealDate": trade_date,
            "originalPriceEok": round(price, 2),
            "adjustedPriceEok": round(adjusted_price, 2),
            "basePeriod": base_period,
            "baseIndex": base_index,
            "factor": round(factor, 6),
            "status": status_value,
        })

    if not adjusted:
        raise RebIndexError("지수보정에 사용할 실거래가 없어요.")

    adjusted.sort(key=lambda row: row["dealDate"], reverse=True)
    values = [row["adjustedPriceEok"] for row in adjusted]
    working = sorted(values)
    trimmed_count = 0
    if len(working) >= 10:
        trim_each_side = max(1, int(len(working) * 0.1))
        working = working[trim_each_side:-trim_each_side]
        trimmed_count = trim_each_side * 2

    if len(working) >= 3:
        low = _percentile(working, 0.25)
        mid = statistics.median(working)
        high = _percentile(working, 0.75)
        method = "거래별 R-ONE 지수보정 · 보정가 25~75백분위"
    else:
        low = min(working)
        mid = statistics.median(working)
        high = max(working)
        method = "거래별 R-ONE 지수보정 · 표본 전체 범위"

    today = today or dt.date.today()
    try:
        newest = dt.date.fromisoformat(newest_date[:10])
        age_days = max(0, (today - newest).days)
    except ValueError:
        age_days = None
    if len(adjusted) >= 5 and age_days is not None and age_days <= 180:
        confidence = "높음"
    elif len(adjusted) >= 3:
        confidence = "보통"
    else:
        confidence = "낮음"

    return {
        "estimate": {
            "minPriceEok": round(low, 2),
            "midPriceEok": round(mid, 2),
            "maxPriceEok": round(high, 2),
            "confidence": confidence,
            "sampleCount": len(adjusted),
            "trimmedCount": trimmed_count,
            "latestTradeDate": newest_date,
            "latestTradeAgeDays": age_days,
            "method": method,
        },
        "index": {
            "source": "한국부동산원 R-ONE 월간 아파트 매매가격지수",
            "region": resolved,
            "latestPeriod": latest_period,
            "latestValue": latest_index,
        },
        "adjustedTransactions": adjusted,
    }
