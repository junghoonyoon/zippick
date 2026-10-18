"""건축HUB 표제부를 법정동 또는 정확한 지번으로 수집해 원본 속성만 보관한다.

건물의 연면적은 토지 면적이 아니다. 이 자료만으로 생활권 변화 점수를 만들지 않는다.
"""

import datetime as dt
import json
import re
import sqlite3
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

import config


API_URL = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
SOURCE_URL = "https://www.data.go.kr/data/15134735/openapi.do"
DB_PATH = config.CACHE_DIR / "building_hub.sqlite3"
PAGE_SIZE = 100
MAX_PAGES = 50
TIMEOUT_SECONDS = 15


class BuildingHubError(RuntimeError):
    """조회가 실패했거나 완전한 결과인지 확인할 수 없다."""


def _code(value, length, label):
    value = str(value).strip()
    if not re.fullmatch(rf"\d{{{length}}}", value):
        raise ValueError(f"{label}는 {length}자리 숫자여야 합니다.")
    return value


def _parcel(sigungu_cd, bjdong_cd, bun, ji, plat_gb_cd):
    return {
        "sigunguCd": _code(sigungu_cd, 5, "시군구 코드"),
        "bjdongCd": _code(bjdong_cd, 5, "법정동 코드"),
        "bun": _code(bun, 4, "본번"),
        "ji": _code(ji, 4, "부번"),
        "platGbCd": _code(plat_gb_cd, 1, "대지 구분"),
    }


def _parse_page(payload, parcel):
    try:
        response = payload["response"]
        header = response["header"]
        if str(header["resultCode"]).strip() not in ("00", "000", "0"):
            raise BuildingHubError("건축HUB가 요청을 거절했습니다. 활용신청과 인증키를 확인해 주세요.")
        body = response["body"]
        total = int(body["totalCount"])
        items = body.get("items") or {}
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if total < 0 or not isinstance(items, list):
            raise ValueError("invalid page")
        for item in items:
            if not isinstance(item, dict) or not item.get("mgmBldrgstPk"):
                raise ValueError("missing building ID")
            for field, expected in parcel.items():
                actual = item.get(field)
                if actual is not None and str(actual).zfill(len(expected)) != expected:
                    raise ValueError("wrong parcel")
        return total, items
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildingHubError("건축HUB 응답의 건물 ID·지번·총건수를 확인할 수 없습니다.") from exc


def fetch_title_records(sigungu_cd, bjdong_cd, bun, ji, *, plat_gb_cd="0", api_key=None,
                        page_size=PAGE_SIZE, max_pages=MAX_PAGES, opener=urlopen):
    """한 필지의 전체 페이지를 받는다. 불완전한 응답은 저장할 수 없게 오류로 끝낸다."""
    parcel = _parcel(sigungu_cd, bjdong_cd, bun, ji, plat_gb_cd)
    result = _fetch_records(parcel, api_key=api_key, page_size=page_size,
                            max_pages=max_pages, opener=opener)
    return {"parcel": parcel, **result}


def fetch_dong_records(sigungu_cd, bjdong_cd, *, api_key=None, page_size=1000,
                       max_pages=MAX_PAGES, opener=urlopen):
    """시범 법정동의 표제부 전체를 받는다. 반경 1.5km 완전성은 뜻하지 않는다."""
    dong = {"sigunguCd": _code(sigungu_cd, 5, "시군구 코드"),
            "bjdongCd": _code(bjdong_cd, 5, "법정동 코드")}
    result = _fetch_records(dong, api_key=api_key, page_size=page_size,
                            max_pages=max_pages, opener=opener)
    return {"dong": dong, **result}


def _fetch_records(filters, *, api_key, page_size, max_pages, opener):
    key = str(api_key if api_key is not None else config.BUILDING_HUB_API_KEY).strip()
    if not key:
        raise BuildingHubError("건축HUB 인증키가 없습니다. BUILDING_HUB_API_KEY를 설정해 주세요.")
    if not 1 <= page_size <= 1000 or not 1 <= max_pages <= 100:
        raise ValueError("페이지 크기 또는 최대 페이지 수가 범위를 벗어났습니다.")
    rows = []
    expected_total = None
    for page_no in range(1, max_pages + 1):
        query = urlencode({"serviceKey": unquote(key), **filters, "_type": "json",
                           "numOfRows": page_size, "pageNo": page_no})
        request = Request(f"{API_URL}?{query}", headers={
            "Accept": "application/json", "User-Agent": "zippick-building-hub/1.0"})
        try:
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            # URL에 인증키가 있으므로 하위 예외 문자열을 사용자에게 보여주지 않는다.
            raise BuildingHubError("건축HUB에서 자료를 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from exc
        total, items = _parse_page(payload, filters)
        if expected_total is not None and total != expected_total:
            raise BuildingHubError("조회 도중 총건수가 바뀌었습니다. 다시 받아 주세요.")
        expected_total = total
        rows.extend(items)
        if len(rows) >= total:
            break
        if not items:
            raise BuildingHubError("건축HUB가 일부 페이지만 보냈습니다. 저장하지 않았습니다.")
    if expected_total is None or len(rows) < expected_total:
        raise BuildingHubError("건축HUB 페이지 제한으로 전체 자료를 받지 못했습니다. 저장하지 않았습니다.")
    ids = [str(row["mgmBldrgstPk"]) for row in rows]
    if len(set(ids)) != len(ids):
        raise BuildingHubError("건축HUB 응답에 중복 건물 ID가 있습니다. 저장하지 않았습니다.")
    return {"source": "국토교통부 건축HUB 건축물대장 표제부",
            "sourceUrl": SOURCE_URL, "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "totalCount": expected_total, "records": rows}


def store_snapshot(snapshot, path=DB_PATH):
    """검증된 한 필지의 조회 이력을 SQLite에 원자적으로 보관한다."""
    if len(snapshot["records"]) != snapshot["totalCount"]:
        raise ValueError("건축HUB 전체 건수를 확인할 수 없습니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    parcel = snapshot["parcel"]
    parcel_id = "".join(parcel[field] for field in ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"))
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS snapshots (parcel_id TEXT NOT NULL, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL, total_count INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(parcel_id, fetched_at))")
        db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                   (parcel_id, snapshot["fetchedAt"], snapshot["sourceUrl"],
                    snapshot["totalCount"], json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))))
    return parcel_id


def store_dong_snapshot(snapshot, path=DB_PATH):
    """법정동 단위의 완전한 API 응답을 별도 테이블에 원자적으로 저장한다."""
    if len(snapshot["records"]) != snapshot["totalCount"]:
        raise ValueError("건축HUB 전체 건수를 확인할 수 없습니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    dong = snapshot["dong"]
    dong_id = dong["sigunguCd"] + dong["bjdongCd"]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS dong_snapshots (dong_id TEXT NOT NULL, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL, total_count INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(dong_id, fetched_at))")
        db.execute("INSERT INTO dong_snapshots VALUES (?, ?, ?, ?, ?)",
                   (dong_id, snapshot["fetchedAt"], snapshot["sourceUrl"],
                    snapshot["totalCount"], json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))))
    return dong_id
