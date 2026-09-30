"""한국부동산원 주간 아파트 매매가격지수를 지역별로 제공한다.

집픽 밴드는 이 지수로 과거 실거래를 오늘 기준에 맞춘다. 응답 경로에서는
저장된 자료만 읽고, 새 자료는 뒤에서 따로 받아 온다. 인증키가 없거나 자료를
받지 못하면 지수가 없다고 알려 호출부가 기존 계산을 그대로 쓰게 한다.
"""

import bisect
import datetime
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config


API_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
# (주) 아파트 매매가격지수. 시군구별 주간 값이 월요일 기준일로 들어 있다.
STATBL_ID = "T244183132827305"
SOURCE = "한국부동산원 주간 아파트가격동향 매매가격지수"
CACHE_PATH = config.CACHE_DIR / "regional_price_index.json"
CACHE_TTL_SECONDS = 60 * 60 * 12
# 새 자료를 받지 못해도 이 기간까지는 저장된 자료를 쓴다.
STALE_CACHE_LIMIT_SECONDS = 60 * 60 * 24 * 14
# 마지막 지수가 이보다 오래됐으면 오늘 기준으로 맞췄다고 말할 수 없다.
MAX_LATEST_POINT_AGE_DAYS = 21
LOOKBACK_WEEKS = 40
PAGE_SIZE = 1000
MAX_PAGES = 30
REQUEST_TIMEOUT_SECONDS = 8

PROVINCE_SHORT_NAMES = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북",
    "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}

_REFRESH_LOCK = threading.Lock()
_REFRESH_RUNNING = False
_MEMORY = {"loadedAt": 0.0, "mtime": None, "payload": None}


def configured():
    return bool(str(config.RONE_API_KEY or "").strip())


def _week_id(date):
    year, week, _ = date.isocalendar()
    return f"{year}{week:02d}"


def _parse_rows(rows):
    """Open API 행을 {지역 전체 이름: [[기준일, 지수], ...]}로 바꾼다."""
    regions = {}
    for row in rows or []:
        if not isinstance(row, dict) or str(row.get("ITM_NM") or "") != "지수":
            continue
        name = str(row.get("CLS_FULLNM") or "").strip()
        period = str(row.get("WRTTIME_DESC") or "").strip()[:10]
        try:
            datetime.date.fromisoformat(period)
            value = float(row.get("DTA_VAL"))
        except (TypeError, ValueError):
            continue
        if not name or value <= 0:
            continue
        regions.setdefault(name, {})[period] = value
    return {
        name: [[period, points[period]] for period in sorted(points)]
        for name, points in regions.items()
    }


def _fetch(today=None):
    api_key = str(config.RONE_API_KEY or "").strip()
    if not api_key:
        return None
    today = today or datetime.date.today()
    start = today - datetime.timedelta(weeks=LOOKBACK_WEEKS)
    rows = []
    for page in range(1, MAX_PAGES + 1):
        query = urlencode({
            "KEY": api_key, "Type": "json", "pIndex": page, "pSize": PAGE_SIZE,
            "STATBL_ID": STATBL_ID, "DTACYCLE_CD": "WK",
            "START_WRTTIME": _week_id(start), "END_WRTTIME": _week_id(today),
        })
        request = Request(
            f"{API_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": "zippick-regional-price-index/1.0"},
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        sections = payload.get("SttsApiTblData") if isinstance(payload, dict) else None
        if not isinstance(sections, list) or len(sections) < 2:
            break
        page_rows = sections[1].get("row") or []
        rows.extend(page_rows)
        total = 0
        for entry in sections[0].get("head") or []:
            if isinstance(entry, dict) and "list_total_count" in entry:
                total = int(entry.get("list_total_count") or 0)
        if not page_rows or len(rows) >= total:
            break
    regions = _parse_rows(rows)
    if not regions:
        return None
    return {
        "source": SOURCE,
        "sourceUrl": "https://www.reb.or.kr/r-one/portal/openapi/openApiIntroPage.do",
        "asOf": max(points[-1][0] for points in regions.values()),
        "regions": regions,
    }


def _read_cache():
    """Return (snapshot, age_seconds). 같은 파일은 다시 읽지 않는다."""
    try:
        mtime = CACHE_PATH.stat().st_mtime
    except OSError:
        return None, None
    if _MEMORY["mtime"] != mtime:
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        _MEMORY.update({"mtime": mtime, "payload": payload})
    payload = _MEMORY["payload"] or {}
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("regions"), dict):
        return None, None
    return snapshot, time.time() - float(payload.get("savedAt") or 0)


def _write_cache(snapshot):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix(f".{time.monotonic_ns()}.tmp")
        temporary.write_text(
            json.dumps({"savedAt": time.time(), "snapshot": snapshot}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(CACHE_PATH)
    except OSError:
        pass


def refresh(today=None):
    """지수를 새로 받아 저장한다. 실패하면 None을 돌려준다."""
    try:
        snapshot = _fetch(today=today)
    except Exception:
        snapshot = None
    if snapshot:
        _write_cache(snapshot)
    return snapshot


def _refresh_in_background():
    global _REFRESH_RUNNING
    with _REFRESH_LOCK:
        if _REFRESH_RUNNING:
            return
        _REFRESH_RUNNING = True

    def run():
        global _REFRESH_RUNNING
        try:
            refresh()
        finally:
            with _REFRESH_LOCK:
                _REFRESH_RUNNING = False

    threading.Thread(target=run, name="regional-price-index-refresh", daemon=True).start()


def latest_snapshot(allow_fetch=False):
    """저장된 지수를 돌려준다. 오래됐으면 뒤에서 새로 받는다."""
    snapshot, age = _read_cache()
    if snapshot and age is not None and age <= CACHE_TTL_SECONDS:
        return snapshot
    if configured():
        if allow_fetch:
            fresh = refresh()
            if fresh:
                return fresh
        else:
            _refresh_in_background()
    if snapshot and age is not None and age <= STALE_CACHE_LIMIT_SECONDS:
        return snapshot
    return None


def _region_tokens(region):
    tokens = str(region or "").split()
    if not tokens:
        return "", []
    province = PROVINCE_SHORT_NAMES.get(tokens[0], tokens[0])
    return province, tokens[1:]


def series_for_region(region, snapshot=None):
    """'서울특별시 종로구' 같은 지역의 주간 지수를 찾는다.

    시·도와 마지막 시군구 이름이 모두 맞아야 한다. '경기도 성남시 분당구'처럼
    시와 구가 함께 오면 시 이름도 확인해 다른 도시의 같은 구 이름과 섞지 않는다.
    """
    snapshot = snapshot if snapshot is not None else latest_snapshot()
    if not isinstance(snapshot, dict):
        return None
    province, districts = _region_tokens(region)
    if not province or not districts:
        return None
    for name, points in (snapshot.get("regions") or {}).items():
        parts = name.split(">")
        if len(parts) < 2 or parts[0] != province or parts[-1] != districts[-1]:
            continue
        if len(districts) >= 2 and districts[-2] not in parts[1:-1]:
            continue
        if len(points) < 2:
            return None
        return {"name": name, "label": " ".join([province, *districts]), "points": points}
    return None


def value_on(series, date_text):
    """그 날짜에 적용되던 지수. 그 주의 조사가 나오기 전이면 직전 주 값을 쓴다."""
    points = (series or {}).get("points") or []
    day = str(date_text or "")[:10]
    if not points or len(day) != 10:
        return None
    position = bisect.bisect_right([point[0] for point in points], day) - 1
    if position >= 0:
        return float(points[position][1])
    # 지수 시작일보다 조금 앞선 거래만 첫 값을 빌려 쓴다.
    try:
        gap = (datetime.date.fromisoformat(points[0][0]) - datetime.date.fromisoformat(day)).days
    except ValueError:
        return None
    return float(points[0][1]) if gap <= 14 else None


def latest_point(series, today=None):
    """가장 최근 지수. 너무 오래됐으면 None."""
    points = (series or {}).get("points") or []
    if not points:
        return None
    period, value = points[-1]
    try:
        age_days = ((today or datetime.date.today()) - datetime.date.fromisoformat(period)).days
    except ValueError:
        return None
    if age_days > MAX_LATEST_POINT_AGE_DAYS:
        return None
    return {"period": period, "value": float(value)}
