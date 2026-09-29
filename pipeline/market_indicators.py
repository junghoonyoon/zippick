"""한국은행 ECOS의 금리 자료를 집픽 가격 판단 입력 형식으로 제공한다."""

import datetime
import json
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import config


CACHE_PATH = config.CACHE_DIR / "market_indicators.json"
CACHE_TTL_SECONDS = 60 * 60 * 12
BASE_RATE_STAT_CODE = "722Y001"
BASE_RATE_ITEM_CODE = "0101000"
SOURCE = "한국은행 ECOS 한국은행 기준금리"


def _read_cache():
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(payload.get("savedAt") or 0) > CACHE_TTL_SECONDS:
        return None
    snapshot = payload.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else None


def _write_cache(snapshot):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"savedAt": time.time(), "snapshot": snapshot}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(CACHE_PATH)
    except OSError:
        pass


def _fetch_base_rate(today=None):
    today = today or datetime.date.today()
    api_key = str(config.ECOS_API_KEY or "").strip()
    if not api_key:
        return None
    start = today - datetime.timedelta(days=550)
    url = (
        "https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{quote(api_key, safe='')}/json/kr/1/100/{BASE_RATE_STAT_CODE}/D/"
        f"{start:%Y%m%d}/{today:%Y%m%d}/{BASE_RATE_ITEM_CODE}"
    )
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "zippick-market-indicators/1.0"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = ((payload.get("StatisticSearch") or {}).get("row") or []) if isinstance(payload, dict) else []
    values = []
    for row in rows:
        try:
            period = datetime.datetime.strptime(str(row.get("TIME") or ""), "%Y%m%d").date()
            value = float(row.get("DATA_VALUE"))
        except (TypeError, ValueError):
            continue
        values.append((period, value))
    if not values:
        return None
    values.sort()
    latest_date, latest_value = values[-1]
    prior_target = latest_date - datetime.timedelta(days=365)
    prior_date, prior_value = min(values, key=lambda item: abs((item[0] - prior_target).days))
    return {
        "status": "available",
        "asOf": latest_date.isoformat(),
        "baseRatePct": latest_value,
        "baseRateChangePp12m": round(latest_value - prior_value, 2),
        "baseRatePriorDate": prior_date.isoformat(),
        "source": SOURCE,
        "sourceUrl": "https://ecos.bok.or.kr/api/",
    }


def latest_snapshot(today=None, refresh=False):
    if not refresh:
        cached = _read_cache()
        if cached:
            return cached
    if not config.ECOS_API_KEY:
        return {"status": "unavailable", "reason": "ECOS API 키가 설정되지 않았어요.", "source": SOURCE}
    try:
        snapshot = _fetch_base_rate(today=today)
    except Exception:
        snapshot = None
    if not snapshot:
        cached = _read_cache()
        if cached:
            return {**cached, "stale": True}
        return {"status": "unavailable", "reason": "한국은행 금리 자료를 불러오지 못했어요.", "source": SOURCE}
    _write_cache(snapshot)
    return snapshot


def attach(candidates, today=None):
    snapshot = latest_snapshot(today=today)
    for row in candidates or []:
        row["marketIndicators"] = dict(snapshot)
