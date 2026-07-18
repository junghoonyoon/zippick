"""MOLIT apartment transaction price lookup."""
import csv
import datetime
import hashlib
import json
import os
import re
import statistics
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import real_estate_search

APARTMENT_ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
PRESALE_ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"
TRANSACTION_KIND_APARTMENT = "apartment"
TRANSACTION_KIND_PRESALE = "presale"
PRESALE_STATUSES = {"분양권", "입주권", "입주예정"}
TRANSACTION_CACHE_DIR = config.CACHE_DIR / "molit_transactions"
PRICE_BAND_CACHE_DIR = config.CACHE_DIR / "molit_price_bands"
MONTH_CACHE_TTL_SECONDS = 60 * 60 * 12
SETTLED_MONTH_CACHE_TTL_SECONDS = config.MOLIT_SETTLED_MONTH_CACHE_TTL_SECONDS
SETTLED_MONTH_RECENT_WINDOW_MONTHS = config.MOLIT_MONTH_CACHE_RECENT_WINDOW_MONTHS
PRICE_BAND_CACHE_TTL_SECONDS = 60 * 60 * 12
PRICE_BAND_CACHE_SCHEMA_VERSION = 7
RECENT_LOOKBACK_MONTHS = config.MOLIT_TRANSACTION_LOOKBACK_MONTHS
_CIRCUIT_STATE = {
    TRANSACTION_KIND_APARTMENT: {"disabledUntil": 0, "lastError": ""},
    TRANSACTION_KIND_PRESALE: {"disabledUntil": 0, "lastError": ""},
}
_PRICE_BAND_CACHE_LOCK = threading.Lock()
_MONTH_MEMORY_CACHE = {}
_MONTH_ADDRESS_INDEX = {}
_MONTH_MEMORY_CACHE_LOCK = threading.Lock()
_SOURCE_INDEX = None
_SOURCE_INDEX_SIGNATURE = None
_SOURCE_INDEX_LOCK = threading.Lock()
_PRESALE_ENTITY_INDEX = None
_PRESALE_ENTITY_INDEX_SIGNATURE = None


def _service_key(transaction_kind=TRANSACTION_KIND_APARTMENT):
    configured_key = (
        config.MOLIT_PRESALE_TRADE_API_KEY
        if transaction_kind == TRANSACTION_KIND_PRESALE
        else config.MOLIT_APARTMENT_TRADE_API_KEY
    )
    key = (configured_key or "").strip()
    return urllib.parse.unquote(key) if "%" in key else key


def configured(transaction_kind=TRANSACTION_KIND_APARTMENT):
    """인증키가 설정됐는지 반환한다.

    enabled()는 일시적인 회로 차단 상태까지 반영하므로, 디스크 캐시만으로도
    가능한 시그널 계산 여부를 판단할 때는 configured()를 사용해야 한다.
    """
    return bool(_service_key(transaction_kind))


def enabled(transaction_kind=TRANSACTION_KIND_APARTMENT):
    if not configured(transaction_kind):
        return False
    state = _circuit_state(transaction_kind)
    if time.time() < state["disabledUntil"]:
        return False
    # 대기 시간이 끝나면 회로와 경고를 함께 닫는다. 다음 조회는 새 요청 또는
    # 저장 데이터로 정상 진행되며, 과거 경고가 결과 캐시를 계속 막지 않는다.
    if state["disabledUntil"]:
        _mark_success(transaction_kind)
    return True


def _circuit_state(transaction_kind):
    return _CIRCUIT_STATE.setdefault(
        transaction_kind,
        {"disabledUntil": 0, "lastError": ""},
    )


def last_error(transaction_kind=TRANSACTION_KIND_APARTMENT):
    return _circuit_state(transaction_kind)["lastError"]


def _disable_temporarily(
    message,
    seconds=60 * 10,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    state = _circuit_state(transaction_kind)
    state["disabledUntil"] = time.time() + seconds
    state["lastError"] = message


def _mark_success(transaction_kind=TRANSACTION_KIND_APARTMENT):
    state = _circuit_state(transaction_kind)
    state["disabledUntil"] = 0
    state["lastError"] = ""


def compact(text):
    return real_estate_search.compact(text)


def _clean_money(value):
    text = str(value or "").replace(",", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0


def _float_value(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _deal_months(months=RECENT_LOOKBACK_MONTHS):
    today = datetime.date.today()
    year = today.year
    month = today.month
    values = []
    for _ in range(months):
        values.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return values


def _cache_path(lawd_cd, deal_ymd, transaction_kind=TRANSACTION_KIND_APARTMENT):
    prefix = "presale_" if transaction_kind == TRANSACTION_KIND_PRESALE else ""
    return TRANSACTION_CACHE_DIR / f"{prefix}{lawd_cd}_{deal_ymd}.json"


def _month_cache_ttl(deal_ymd):
    """최근 월은 짧은 TTL, 신고 기한이 지난 과거 월은 긴 TTL을 쓴다.

    실거래 신고는 계약 후 30일 이내라 과거 월 데이터는 사실상 확정된다.
    해제(취소) 신고 반영을 위해 확정 월도 긴 주기로는 다시 받는다.
    매일 전체 월을 다시 받던 API 호출 폭주를 막는 것이 목적이다.
    """
    if str(deal_ymd) in _deal_months(SETTLED_MONTH_RECENT_WINDOW_MONTHS):
        return MONTH_CACHE_TTL_SECONDS
    return SETTLED_MONTH_CACHE_TTL_SECONDS


def _read_cached_month(
    lawd_cd,
    deal_ymd,
    allow_stale=False,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    path = _cache_path(lawd_cd, deal_ymd, transaction_kind)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fetched_at = float(payload.get("fetchedAt") or 0)
    if not allow_stale and time.time() - fetched_at > _month_cache_ttl(deal_ymd):
        return None
    return payload.get("items") or []


def _write_cached_month(
    lawd_cd,
    deal_ymd,
    items,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    TRANSACTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(lawd_cd, deal_ymd, transaction_kind)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({
        "fetchedAt": time.time(),
        "lawdCd": lawd_cd,
        "dealYmd": deal_ymd,
        "transactionKind": transaction_kind,
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_cached_month_memory(
    lawd_cd,
    deal_ymd,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    """Read a fresh month cache and reuse it across cache-only lookups."""
    memory_key = (transaction_kind, str(lawd_cd), str(deal_ymd))
    with _MONTH_MEMORY_CACHE_LOCK:
        memory_cached = _MONTH_MEMORY_CACHE.get(memory_key)
        if memory_cached and time.time() - memory_cached[0] <= _month_cache_ttl(deal_ymd):
            return memory_cached[1]
    cached = _read_cached_month(
        lawd_cd,
        deal_ymd,
        transaction_kind=transaction_kind,
    )
    if cached is not None:
        with _MONTH_MEMORY_CACHE_LOCK:
            _MONTH_MEMORY_CACHE[memory_key] = (time.time(), cached)
    return cached


def _price_band_cache_key(name, region, area_label, lookback_months):
    tracked_files = [__file__, *real_estate_search.APARTMENT_CSV_PATHS]
    revisions = {}
    for path in tracked_files:
        try:
            revisions[str(path)] = os.path.getmtime(path)
        except OSError:
            revisions[str(path)] = 0
    material = {
        "schema": PRICE_BAND_CACHE_SCHEMA_VERSION,
        "date": datetime.date.today().isoformat(),
        "name": str(name or "").strip(),
        "region": str(region or "").strip(),
        "areaLabel": str(area_label or "").strip(),
        "lookbackMonths": int(lookback_months or RECENT_LOOKBACK_MONTHS),
        "transactionKind": transaction_kind_for_apartment(name, region),
        "dealMonths": _deal_months(int(lookback_months or RECENT_LOOKBACK_MONTHS)),
        "revisions": revisions,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _price_band_cache_path(cache_key):
    return PRICE_BAND_CACHE_DIR / f"{cache_key}.json"


def _read_cached_price_band(cache_key):
    path = _price_band_cache_path(cache_key)
    if not path.exists():
        return False, None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    fetched_at = float(cached.get("fetchedAt") or 0)
    if time.time() - fetched_at > PRICE_BAND_CACHE_TTL_SECONDS:
        try:
            path.unlink()
        except OSError:
            pass
        return False, None
    return True, cached.get("band")


def _write_cached_price_band(cache_key, band):
    PRICE_BAND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _price_band_cache_path(cache_key)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({
        "fetchedAt": time.time(),
        "band": band,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _xml_text(item, names):
    for name in names:
        child = item.find(name)
        if child is not None and child.text is not None:
            return child.text.strip()
    return ""


def _parse_items(xml_text, transaction_kind=TRANSACTION_KIND_APARTMENT):
    root = ET.fromstring(xml_text)
    result_code = _xml_text(root.find("header") or root, ["resultCode"])
    result_message = _xml_text(root.find("header") or root, ["resultMsg"])
    if result_code and result_code not in {"00", "000"}:
        raise RuntimeError(result_message or f"국토부 API 오류: {result_code}")
    rows = []
    for item in root.findall(".//item"):
        amount_manwon = _clean_money(_xml_text(item, ["거래금액", "dealAmount"]))
        if amount_manwon <= 0:
            continue
        year = _xml_text(item, ["년", "dealYear"])
        month = _xml_text(item, ["월", "dealMonth"])
        day = _xml_text(item, ["일", "dealDay"])
        deal_date = ""
        if year and month and day:
            deal_date = f"{year}-{int(month):02d}-{int(day):02d}"
        rows.append({
            "apartment": _xml_text(item, ["아파트", "aptNm"]),
            "legalDong": _xml_text(item, ["법정동", "umdNm"]),
            "jibun": _xml_text(item, ["지번", "jibun"]),
            "exclusiveArea": _float_value(_xml_text(item, ["전용면적", "excluUseAr"])),
            "floor": _xml_text(item, ["층", "floor"]),
            "dealDate": deal_date,
            "dealAmountManwon": amount_manwon,
            "dealAmountEok": round(amount_manwon / 10000, 4),
            "dealType": _xml_text(item, ["거래유형", "dealingGbn"]),
            "estateAgentRegion": _xml_text(item, ["중개사소재지", "estateAgentSggNm"]),
            "cancellationDate": _xml_text(item, ["해제사유발생일", "cdealDay"]),
            "cancellationType": _xml_text(item, ["해제여부", "cdealType"]),
            "transactionKind": transaction_kind,
        })
    return rows


def fetch_month(
    lawd_cd,
    deal_ymd,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    memory_key = (transaction_kind, str(lawd_cd), str(deal_ymd))
    with _MONTH_MEMORY_CACHE_LOCK:
        memory_cached = _MONTH_MEMORY_CACHE.get(memory_key)
        if memory_cached and time.time() - memory_cached[0] <= _month_cache_ttl(deal_ymd):
            return memory_cached[1]
    cached = _read_cached_month(
        lawd_cd,
        deal_ymd,
        transaction_kind=transaction_kind,
    )
    if cached is not None:
        with _MONTH_MEMORY_CACHE_LOCK:
            _MONTH_MEMORY_CACHE[memory_key] = (time.time(), cached)
        return cached
    # 국토부 API의 순간 지연 때문에 이미 확보한 실거래 데이터까지 버리지 않는다.
    # 새 요청이 실패하거나 회로가 잠시 열린 경우에만 이 만료 캐시를 사용한다.
    stale_cached = _read_cached_month(
        lawd_cd,
        deal_ymd,
        allow_stale=True,
        transaction_kind=transaction_kind,
    )
    if not enabled(transaction_kind):
        if stale_cached is not None:
            return stale_cached
        raise RuntimeError(
            last_error(transaction_kind)
            or "공공데이터키가 설정되어 있지 않아요."
        )
    try:
        response = requests.get(
            (
                PRESALE_ENDPOINT
                if transaction_kind == TRANSACTION_KIND_PRESALE
                else APARTMENT_ENDPOINT
            ),
            params={
                "serviceKey": _service_key(transaction_kind),
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ymd,
                "numOfRows": 1000,
                "pageNo": 1,
            },
            timeout=config.MOLIT_TRANSACTION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = _parse_items(response.text, transaction_kind)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status in {401, 403}:
            _disable_temporarily(
                "국토부 실거래가 API 권한이 없거나 인증키가 승인되지 않았어요.",
                transaction_kind=transaction_kind,
            )
        if stale_cached is not None:
            return stale_cached
        raise
    except requests.RequestException:
        # 긴 전역 차단은 정상 단지의 시그널까지 누락시킨다. 짧은 회로 차단으로
        # 동시 요청 폭주만 막고, 그동안에는 위의 만료 캐시를 계속 사용한다.
        _disable_temporarily(
            "국토부 실거래가 API 응답이 지연되어 저장된 데이터로 계산합니다.",
            seconds=15,
            transaction_kind=transaction_kind,
        )
        if stale_cached is not None:
            return stale_cached
        raise
    except (ET.ParseError, RuntimeError, ValueError):
        _disable_temporarily(
            "국토부 실거래가 응답을 해석하지 못해 저장된 데이터로 계산합니다.",
            seconds=15,
            transaction_kind=transaction_kind,
        )
        if stale_cached is not None:
            return stale_cached
        raise
    _mark_success(transaction_kind)
    _write_cached_month(
        lawd_cd,
        deal_ymd,
        items,
        transaction_kind=transaction_kind,
    )
    with _MONTH_MEMORY_CACHE_LOCK:
        _MONTH_MEMORY_CACHE[memory_key] = (time.time(), items)
    return items


def prefetch_months(
    pairs,
    max_workers=None,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    """(lawd_cd, deal_ymd) 쌍을 병렬로 받아 월별 캐시를 미리 채운다.

    이미 캐시된 쌍은 fetch_month가 즉시 반환하므로 중복 제출 비용이 거의 없다.
    실패한 쌍은 조용히 건너뛰고, 이후 개별 조회 경로가 기존 방식대로 처리한다.
    """
    pending = []
    seen = set()
    for lawd_cd, deal_ymd in pairs:
        key = (str(lawd_cd), str(deal_ymd))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        pending.append(key)
    if not pending or not enabled(transaction_kind):
        return 0
    workers = max(1, min(max_workers or config.MOLIT_PREFETCH_MAX_WORKERS, len(pending)))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(fetch_month, lawd_cd, deal_ymd, transaction_kind)
            for lawd_cd, deal_ymd in pending
        ]
        for future in futures:
            try:
                future.result()
                done += 1
            except Exception:
                continue
    return done


def _items_for_source_row(lawd_cd, deal_ymd, items, row, dong_only=False):
    """Narrow a district-month payload by parcel before matching names.

    dong_only=True면 지번 좁히기를 건너뛴다. 'N단지' 조회처럼 마스터 지번
    표기가 틀려도 이름의 단지 번호로 정확히 귀속할 수 있는 경우에 쓴다.
    """
    transaction_kind = (
        str(items[0].get("transactionKind") or TRANSACTION_KIND_APARTMENT)
        if items
        else TRANSACTION_KIND_APARTMENT
    )
    memory_key = (transaction_kind, str(lawd_cd), str(deal_ymd))
    with _MONTH_MEMORY_CACHE_LOCK:
        cached_index = _MONTH_ADDRESS_INDEX.get(memory_key)
        if cached_index is None or cached_index[0] != id(items):
            address_index = {}
            for item in items:
                key = (compact(item.get("legalDong")), compact(item.get("jibun")))
                address_index.setdefault(key, []).append(item)
            _MONTH_ADDRESS_INDEX[memory_key] = (id(items), address_index)
        else:
            address_index = cached_index[1]
    dong = compact(row.get("법정동") or row.get("읍면동"))
    jibun = compact(row.get("지번"))
    if dong and jibun and not dong_only:
        return address_index.get((dong, jibun), [])
    if dong:
        return [item for (item_dong, _), values in address_index.items() if item_dong == dong for item in values]
    return items


def _row_lawd_cd(row):
    parcel_id = str(row.get("필지고유번호") or "").strip()
    if len(parcel_id) >= 5 and parcel_id[:5].isdigit():
        return parcel_id[:5]
    for column in ("법정동코드", "lawdCd"):
        value = re.sub(r"\D", "", str(row.get(column) or ""))
        if len(value) >= 5:
            return value[:5]
    return ""


def _row_region_values(row):
    return [
        row.get("시도", ""),
        row.get("자치구", ""),
        row.get("시군구", ""),
        row.get("일반구", ""),
        row.get("읍면동", ""),
        row.get("법정동", ""),
        row.get("주소", ""),
    ]


def _row_name_values(row):
    return [
        row.get("대표단지명", ""),
        row.get("단지명_공시가격", ""),
        row.get("단지명_건축물대장", ""),
        row.get("단지명_도로명주소", ""),
    ]


def _matches_region(row, region):
    if not region:
        return True
    region_key = compact(region)
    return any(
        value_key and (region_key in value_key or value_key in region_key)
        for value_key in (compact(value) for value in _row_region_values(row))
    )


def _matches_name(row, name):
    name_key = compact(name)
    if not name_key:
        return False
    for value in _row_name_values(row):
        value_key = compact(value)
        if value_key and (name_key == value_key or name_key in value_key or value_key in name_key):
            return True
    return False


def _entity_region_matches(entity, region):
    if not region:
        return True
    region_key = compact(region)
    values = [
        entity.get("province", ""),
        entity.get("city", ""),
        entity.get("district", ""),
        entity.get("legalDong", ""),
        entity.get("category", ""),
        entity.get("address", ""),
    ]
    return any(
        value_key and (region_key in value_key or value_key in region_key)
        for value_key in (compact(value) for value in values)
    )


def _entity_alias_values(entity):
    return [entity.get("name", ""), *(entity.get("aliases") or [])]


def _matching_master_entities(name, region):
    name_key = compact(name)
    if not name_key:
        return []
    matches = []
    for entity in real_estate_search.APARTMENT_MASTER:
        if not _entity_region_matches(entity, region):
            continue
        alias_keys = {compact(value) for value in _entity_alias_values(entity) if compact(value)}
        if name_key in alias_keys:
            matches.append(entity)
    return matches


def _presale_entity_index():
    global _PRESALE_ENTITY_INDEX, _PRESALE_ENTITY_INDEX_SIGNATURE
    master = real_estate_search.APARTMENT_MASTER
    signature = (id(master), len(master))
    if _PRESALE_ENTITY_INDEX is not None and _PRESALE_ENTITY_INDEX_SIGNATURE == signature:
        return _PRESALE_ENTITY_INDEX
    index = {}
    for entity in master:
        if str(entity.get("status") or "").strip() not in PRESALE_STATUSES:
            continue
        for value in _entity_alias_values(entity):
            key = compact(value)
            if key:
                index.setdefault(key, []).append(entity)
    _PRESALE_ENTITY_INDEX = index
    _PRESALE_ENTITY_INDEX_SIGNATURE = signature
    return index


def transaction_kind_for_apartment(name, region=""):
    """Select the official transaction feed for a known complex.

    Pre-construction complexes must use the presale/occupancy-right feed.
    Unknown or completed complexes keep the standard apartment trade feed.
    """
    entities = _presale_entity_index().get(compact(name), [])
    return (
        TRANSACTION_KIND_PRESALE
        if any(_entity_region_matches(entity, region) for entity in entities)
        else TRANSACTION_KIND_APARTMENT
    )


def _row_matches_entity(row, entity):
    dong_key = compact(entity.get("legalDong"))
    address_key = compact(entity.get("address"))
    row_dong = compact(row.get("법정동") or row.get("읍면동"))
    row_jibun = compact(row.get("지번"))
    if dong_key and row_dong and dong_key != row_dong:
        return False
    if address_key and row_jibun and not address_key.endswith(row_jibun):
        return False
    return True


def _dedupe_rows(rows):
    deduped = []
    seen = set()
    for row in rows:
        key = (
            _row_lawd_cd(row),
            compact(row.get("법정동") or row.get("읍면동")),
            compact(row.get("지번")),
            compact(row.get("대표단지명")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _source_row_index():
    global _SOURCE_INDEX, _SOURCE_INDEX_SIGNATURE
    signature = tuple(str(path) for path in real_estate_search.APARTMENT_CSV_PATHS)
    if _SOURCE_INDEX is not None and _SOURCE_INDEX_SIGNATURE == signature:
        return _SOURCE_INDEX
    with _SOURCE_INDEX_LOCK:
        if _SOURCE_INDEX is not None and _SOURCE_INDEX_SIGNATURE == signature:
            return _SOURCE_INDEX
        all_rows = []
        exact = {}
        seen = set()
        for path in real_estate_search.APARTMENT_CSV_PATHS:
            if not path.exists():
                continue
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("단지종류명") and row.get("단지종류명") != "아파트":
                        continue
                    lawd_cd = _row_lawd_cd(row)
                    if not lawd_cd:
                        continue
                    key = (
                        lawd_cd,
                        compact(row.get("법정동") or row.get("읍면동")),
                        compact(row.get("지번")),
                        compact(row.get("대표단지명")),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    all_rows.append(row)
                    for value in _row_name_values(row):
                        value_key = compact(value)
                        if value_key:
                            exact.setdefault(value_key, []).append(row)
        # CSV 스냅샷에 없는 신축 단지: 수동 마스터에 필지 정보(lawdCd·법정동·지번)가
        # 있으면 합성 소스 행을 만들어 실거래를 정확히 연결한다. 필지 정보가 없으면
        # 퍼지 매칭이 다른 지역 유사 이름 거래를 물어오므로 등록하지 않는다.
        for entity in real_estate_search.MANUAL_APARTMENT_MASTER:
            lawd_cd = str(entity.get("lawdCd") or "").strip()
            dong = str(entity.get("legalDong") or "").strip()
            jibun = str(entity.get("jibun") or "").strip()
            if not (lawd_cd and dong and jibun):
                continue
            aliases = [str(alias or "").strip() for alias in (entity.get("aliases") or []) if str(alias or "").strip()]
            row = {
                "대표단지명": entity.get("name", ""),
                "단지명_공시가격": aliases[0] if aliases else "",
                "단지명_건축물대장": aliases[1] if len(aliases) > 1 else "",
                "단지명_도로명주소": aliases[2] if len(aliases) > 2 else "",
                "시도": entity.get("province", ""),
                "시군구": entity.get("district", ""),
                "읍면동": dong,
                "법정동": dong,
                "지번": jibun,
                "필지고유번호": f"{lawd_cd}{'0' * 14}",
            }
            key = (lawd_cd, compact(dong), compact(jibun), compact(row["대표단지명"]))
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
            for value in [entity.get("name", ""), *aliases]:
                value_key = compact(value)
                if value_key:
                    exact.setdefault(value_key, []).append(row)
        _SOURCE_INDEX = (all_rows, exact)
        _SOURCE_INDEX_SIGNATURE = signature
        return _SOURCE_INDEX


def source_rows(name, region=""):
    all_rows, exact_index = _source_row_index()
    entities = _matching_master_entities(name, region)
    search_names = [name]
    for entity in entities:
        search_names.extend(_entity_alias_values(entity))
    search_keys = []
    seen_keys = set()
    for value in search_names:
        value_key = compact(value)
        if value_key and value_key not in seen_keys:
            seen_keys.add(value_key)
            search_keys.append(value_key)
    exact_rows = [
        row
        for key in search_keys
        for row in exact_index.get(key, [])
        if _matches_region(row, region)
        and (not entities or any(_row_matches_entity(row, entity) for entity in entities))
    ]
    if exact_rows:
        return _dedupe_rows(exact_rows)
    rows = []
    # Fuzzy fallback for names that have no exact public-data alias. The
    # indexed exact path above handles normal complexes without reopening and
    # rescanning every CSV for every candidate.
    for row in all_rows:
        if (
            any(_matches_name(row, value) for value in search_names)
            and _matches_region(row, region)
            and (not entities or any(_row_matches_entity(row, entity) for entity in entities))
        ):
            rows.append(row)
    # A generic substring such as "동아" can occur in several unrelated
    # complexes in the same district. When the requested complex has an exact
    # public-data alias, do not mix those fuzzy matches into its transactions.
    return _dedupe_rows(exact_rows or rows)


def source_rows_for_entity(entity, region=""):
    """Resolve public source rows for a known master entity without rescanning masters."""
    entity = entity or {}
    name = str(entity.get("name") or "").strip()
    region = region or entity.get("district") or entity.get("city") or ""
    all_rows, exact_index = _source_row_index()
    search_names = [name, *_entity_alias_values(entity)]
    search_keys = []
    seen_keys = set()
    for value in search_names:
        value_key = compact(value)
        if value_key and value_key not in seen_keys:
            seen_keys.add(value_key)
            search_keys.append(value_key)
    exact_rows = [
        row
        for key in search_keys
        for row in exact_index.get(key, [])
        if _matches_region(row, region) and _row_matches_entity(row, entity)
    ]
    if exact_rows:
        return _dedupe_rows(exact_rows)
    rows = [
        row
        for row in all_rows
        if any(_matches_name(row, value) for value in search_names)
        and _matches_region(row, region)
        and _row_matches_entity(row, entity)
    ]
    return _dedupe_rows(rows)


def _minimum_area_transactions(transactions, min_area):
    minimum = float(min_area or 0)
    eligible = [
        item for item in transactions
        if float(item.get("exclusiveArea") or 0) >= max(0, minimum - 0.05)
    ]
    if not eligible:
        return []
    area_type = lambda item: max(int(minimum), int(float(item.get("exclusiveArea") or 0)))
    smallest_type = min(area_type(item) for item in eligible)
    matches = [
        item for item in eligible
        if area_type(item) == smallest_type
    ]
    matches.sort(key=lambda row: row.get("dealDate", ""), reverse=True)
    return matches


def _area_target(area_label):
    text = str(area_label or "")
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
    if values:
        low = min(values)
        high = max(values)
        # Official exclusive areas commonly differ from the rounded display
        # label by a few hundredths (for example 59.98㎡ shown as 60㎡).
        return (max(0, low - 0.75), high + 0.75)
    if "84" in text:
        return (75, 95)
    if "59" in text:
        return (50, 70)
    if "49" in text:
        return (40, 58)
    return None


def _matches_area(item, area_label):
    target = _area_target(area_label)
    if not target:
        return True
    area = float(item.get("exclusiveArea") or 0)
    return target[0] <= area <= target[1]


def _is_market_transaction(item):
    """Exclude direct and cancelled deals from market-price calculations."""
    if compact(item.get("dealType")) == compact("직거래"):
        return False
    # 해제 신고: 해제사유발생일이 있거나, 날짜 없이 해제여부(O)만 찍힌 건 모두 제외
    if str(item.get("cancellationDate") or "").strip():
        return False
    return str(item.get("cancellationType") or "").strip().upper() != "O"


def _transaction_recency_weight(item):
    """Give recent contracts more influence without pretending to know asking prices."""
    try:
        deal_date = datetime.date.fromisoformat(str(item.get("dealDate") or "")[:10])
    except ValueError:
        return 0.4
    age_days = max(0, (datetime.date.today() - deal_date).days)
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.7
    return 0.4


def _weighted_price_quantile(rows, quantile):
    ordered = sorted(rows, key=lambda row: float(row.get("dealAmountEok") or 0))
    total_weight = sum(_transaction_recency_weight(row) for row in ordered)
    if not ordered or total_weight <= 0:
        return 0.0
    target = total_weight * max(0, min(1, float(quantile)))
    cumulative = 0.0
    for row in ordered:
        cumulative += _transaction_recency_weight(row)
        if cumulative >= target:
            return float(row.get("dealAmountEok") or 0)
    return float(ordered[-1].get("dealAmountEok") or 0)


def _current_price_estimate(transactions):
    """Estimate today's likely transaction band from detailed recent contracts.

    The outer 10% of prices are removed when the sample is large enough, then
    the latest contracts receive more weight. The weighted 25th/50th/75th
    percentiles form the estimate, keeping it distinct from the raw min/max
    range shown as factual recent trades.
    """
    priced = [row for row in transactions if float(row.get("dealAmountEok") or 0) > 0]
    if len(priced) < 3:
        return None
    ordered = sorted(priced, key=lambda row: float(row.get("dealAmountEok") or 0))
    trimmed_count = 0
    if len(ordered) >= 10:
        trim_each_side = max(1, int(len(ordered) * 0.1))
        ordered = ordered[trim_each_side:-trim_each_side]
        trimmed_count = trim_each_side * 2
    low = _weighted_price_quantile(ordered, 0.25)
    middle = _weighted_price_quantile(ordered, 0.5)
    high = _weighted_price_quantile(ordered, 0.75)
    if not low or not middle or not high:
        return None
    return {
        "minPriceEok": round(min(low, high), 2),
        "midPriceEok": round(middle, 2),
        "maxPriceEok": round(max(low, high), 2),
        "sampleCount": len(priced),
        "trimmedCount": trimmed_count,
        "method": "최근 거래 가중 중앙값 · 가중 25~75백분위",
    }


def _shift_month(period, offset):
    value = str(period or "")
    if not re.fullmatch(r"\d{6}", value):
        return ""
    year = int(value[:4])
    month = int(value[4:]) - 1 + int(offset)
    year += month // 12
    month %= 12
    return f"{year}{month + 1:02d}"


def _exclude_price_outliers(prices):
    """Remove isolated prices without erasing a genuinely wide market range."""
    values = [_float_value(value) for value in prices if _float_value(value) > 0]
    if len(values) < 3:
        return values, 0
    middle = statistics.median(values)
    deviations = [abs(value - middle) for value in values]
    median_deviation = statistics.median(deviations)
    tolerance = max(middle * 0.2, median_deviation * 3)
    typical = [value for value in values if abs(value - middle) <= tolerance]
    if len(typical) < 2:
        return values, 0
    return typical, len(values) - len(typical)


def _quarter_trade_stats(transactions):
    trades = [
        row for row in transactions
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("dealDate") or ""))
        and _float_value(row.get("dealAmountEok")) > 0
    ]
    if not trades:
        return {
            "statsThrough": "",
            "recent3AveragePriceEok": 0,
            "recent3TradeCount": 0,
            "recent3AdjustedAveragePriceEok": 0,
            "recent3AdjustedTradeCount": 0,
            "recent3ExcludedTradeCount": 0,
            "previous3AveragePriceEok": 0,
            "previous3TradeCount": 0,
        }
    stats_through = max(str(row["dealDate"]) for row in trades)
    end_period = stats_through[:7].replace("-", "")
    recent_periods = {_shift_month(end_period, offset) for offset in (-2, -1, 0)}
    previous_periods = {_shift_month(end_period, offset) for offset in (-5, -4, -3)}

    def prices_for(periods):
        return [
            _float_value(row.get("dealAmountEok"))
            for row in trades
            if str(row.get("dealDate") or "")[:7].replace("-", "") in periods
        ]

    recent_prices = prices_for(recent_periods)
    previous_prices = prices_for(previous_periods)
    adjusted_recent_prices, excluded_recent_count = _exclude_price_outliers(recent_prices)
    return {
        "statsThrough": stats_through,
        "recent3AveragePriceEok": round(statistics.mean(recent_prices), 2) if recent_prices else 0,
        "recent3TradeCount": len(recent_prices),
        "recent3AdjustedAveragePriceEok": (
            round(statistics.mean(adjusted_recent_prices), 2)
            if adjusted_recent_prices
            else 0
        ),
        "recent3AdjustedTradeCount": len(adjusted_recent_prices),
        "recent3ExcludedTradeCount": excluded_recent_count,
        "previous3AveragePriceEok": round(statistics.mean(previous_prices), 2) if previous_prices else 0,
        "previous3TradeCount": len(previous_prices),
    }


def quarter_trade_stats(transactions):
    """Return the shared recent/previous three-month trade summary."""
    return _quarter_trade_stats(transactions)


def _half_year_trade_stats(transactions):
    """최근 거래월 기준 최근 6개월과 직전 6개월의 평균·표본 수."""
    trades = [
        row for row in transactions
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("dealDate") or ""))
        and _float_value(row.get("dealAmountEok")) > 0
    ]
    if not trades:
        return {
            "recent6AveragePriceEok": 0,
            "recent6TradeCount": 0,
            "previous6AveragePriceEok": 0,
            "previous6TradeCount": 0,
        }
    end_period = max(str(row["dealDate"]) for row in trades)[:7].replace("-", "")
    recent_periods = {_shift_month(end_period, offset) for offset in range(-5, 1)}
    previous_periods = {_shift_month(end_period, offset) for offset in range(-11, -5)}

    def prices_for(periods):
        return [
            _float_value(row.get("dealAmountEok"))
            for row in trades
            if str(row.get("dealDate") or "")[:7].replace("-", "") in periods
        ]

    recent_prices = prices_for(recent_periods)
    previous_prices = prices_for(previous_periods)
    return {
        "recent6AveragePriceEok": round(statistics.mean(recent_prices), 2) if recent_prices else 0,
        "recent6TradeCount": len(recent_prices),
        "previous6AveragePriceEok": round(statistics.mean(previous_prices), 2) if previous_prices else 0,
        "previous6TradeCount": len(previous_prices),
    }


_UNIT_NUMBER_RE = re.compile(r"(\d+)\s*단지")


def _unit_number(value):
    match = _UNIT_NUMBER_RE.search(str(value or ""))
    if not match:
        return ""
    return match.group(1).lstrip("0") or match.group(1)


def _matches_transaction(row, item, name):
    item_name = compact(item.get("apartment"))
    if not item_name:
        return False
    names = [name, *_row_name_values(row)]
    name_match = any(compact(value) and (compact(value) == item_name or compact(value) in item_name or item_name in compact(value)) for value in names)
    if not name_match:
        return False
    row_dong = compact(row.get("법정동") or row.get("읍면동"))
    item_dong = compact(item.get("legalDong"))
    if row_dong and item_dong and row_dong not in item_dong and item_dong not in row_dong:
        return False
    # 'N단지'가 조회명과 실거래명 양쪽에 있으면 번호 일치가 최우선 기준이다.
    # 마스터의 지번 표기 오류가 있어도 다른 단지 거래가 섞이지 않도록,
    # 번호가 다르면 제외하고 번호가 같으면 지번 검사 없이 인정한다.
    query_unit = _unit_number(name)
    item_unit = _unit_number(item.get("apartment"))
    if query_unit and item_unit:
        return query_unit == item_unit
    row_jibun = compact(row.get("지번"))
    item_jibun = compact(item.get("jibun"))
    if row_jibun and item_jibun and row_jibun != item_jibun:
        return False
    return True


def _matching_transactions(rows, name, area_label, lookback_months, monthly):
    matches = []
    seen = set()
    unit_query = bool(_unit_number(name))
    for row in rows:
        lawd_cd = _row_lawd_cd(row)
        for deal_ymd in _deal_months(lookback_months):
            items = monthly.get((lawd_cd, deal_ymd), [])
            for item in _items_for_source_row(lawd_cd, deal_ymd, items, row, dong_only=unit_query):
                if not _is_market_transaction(item):
                    continue
                if not _matches_area(item, area_label):
                    continue
                if not _matches_transaction(row, item, name):
                    continue
                key = (
                    item.get("apartment"),
                    item.get("dealDate"),
                    item.get("dealAmountManwon"),
                    item.get("exclusiveArea"),
                    item.get("floor"),
                )
                if key in seen:
                    continue
                seen.add(key)
                matches.append(item)
    matches.sort(key=lambda row: row.get("dealDate", ""), reverse=True)
    return matches


def transactions_for_apartment(name, region="", area_label="", lookback_months=RECENT_LOOKBACK_MONTHS):
    rows = source_rows(name, region)
    if not rows:
        return []
    transaction_kind = transaction_kind_for_apartment(name, region)
    lawd_cds = sorted({_row_lawd_cd(row) for row in rows if _row_lawd_cd(row)})
    month_values = _deal_months(lookback_months)
    prefetch_months(
        ((lawd_cd, deal_ymd) for lawd_cd in lawd_cds for deal_ymd in month_values),
        transaction_kind=transaction_kind,
    )
    monthly = {}
    for lawd_cd in lawd_cds:
        for deal_ymd in month_values:
            try:
                monthly[(lawd_cd, deal_ymd)] = (
                    fetch_month(
                        lawd_cd,
                        deal_ymd,
                        transaction_kind=transaction_kind,
                    )
                    if transaction_kind == TRANSACTION_KIND_PRESALE
                    else fetch_month(lawd_cd, deal_ymd)
                )
            except Exception:
                continue
    return _matching_transactions(rows, name, area_label, lookback_months, monthly)


def transactions_for_apartment_cached(
    name,
    region="",
    area_label="",
    lookback_months=RECENT_LOOKBACK_MONTHS,
    entity=None,
):
    """Return matching transactions using only fresh local month caches.

    Empty-state nearby suggestions must not fan out into additional public API
    requests. This mirrors transactions_for_apartment's matching rules while
    deliberately skipping both prefetch_months and fetch_month.
    """
    rows = source_rows_for_entity(entity, region) if entity else source_rows(name, region)
    if not rows:
        return []
    transaction_kind = transaction_kind_for_apartment(name, region)
    monthly = {}
    month_values = _deal_months(lookback_months)
    lawd_cds = sorted({_row_lawd_cd(row) for row in rows if _row_lawd_cd(row)})
    for lawd_cd in lawd_cds:
        for deal_ymd in month_values:
            items = _read_cached_month_memory(
                lawd_cd,
                deal_ymd,
                transaction_kind=transaction_kind,
            )
            if items is not None:
                monthly[(lawd_cd, deal_ymd)] = items
    return _matching_transactions(rows, name, area_label, lookback_months, monthly)


def area_options_for_apartment(name, region="", lookback_months=RECENT_LOOKBACK_MONTHS):
    """Return recently traded exclusive-area types for a complex.

    Public transaction records often express the same marketed unit type with
    slightly different decimals (for example 59.82㎡ and 59.98㎡). Nearby
    values are grouped so the UI presents useful choices instead of a long list
    of nearly identical buttons.
    """
    transactions = transactions_for_apartment(
        name,
        region=region,
        area_label="",
        lookback_months=lookback_months,
    )
    clusters = []
    for transaction in sorted(
        transactions,
        key=lambda item: float(item.get("exclusiveArea") or 0),
    ):
        area = float(transaction.get("exclusiveArea") or 0)
        if area <= 0:
            continue
        cluster = next(
            (
                candidate
                for candidate in clusters
                if abs(area - candidate["representative"]) <= 1.25
            ),
            None,
        )
        if cluster is None:
            cluster = {
                "areas": [],
                "transactions": [],
                "representative": area,
            }
            clusters.append(cluster)
        cluster["areas"].append(area)
        cluster["transactions"].append(transaction)
        ordered_areas = sorted(cluster["areas"])
        cluster["representative"] = ordered_areas[len(ordered_areas) // 2]

    options = []
    for cluster in clusters:
        areas = cluster["areas"]
        representative = float(cluster["representative"])
        low_label = int(min(areas))
        high_label = int(max(areas))
        label = (
            f"전용 {low_label}㎡"
            if low_label == high_label
            else f"전용 {low_label}~{high_label}㎡"
        )
        options.append({
            "value": f"{representative:.2f}".rstrip("0").rstrip("."),
            "label": label,
            "transactionCount": len(cluster["transactions"]),
            "latestDealDate": max(
                str(item.get("dealDate") or "")
                for item in cluster["transactions"]
            ),
        })
    return options


def latest_transaction_for_apartment(
    name,
    region="",
    area_label="",
    lookback_months=None,
    skip_months=RECENT_LOOKBACK_MONTHS,
):
    lookback_months = int(lookback_months or config.MOLIT_STALE_TRANSACTION_LOOKBACK_MONTHS)
    skip_months = max(0, int(skip_months or 0))
    rows = source_rows(name, region)
    if not rows:
        return None
    transaction_kind = transaction_kind_for_apartment(name, region)
    lawd_cds = sorted({_row_lawd_cd(row) for row in rows if _row_lawd_cd(row)})
    month_values = _deal_months(lookback_months)[skip_months:]
    batch_size = max(1, config.MOLIT_STALE_PREFETCH_BATCH_MONTHS)
    for batch_start in range(0, len(month_values), batch_size):
        month_batch = month_values[batch_start:batch_start + batch_size]
        # 최신 월부터 순서대로 훑되, 배치 단위로 병렬 프리페치해서
        # 거래가 뜸한 단지의 한 달씩 순차 조회(최대 수십 회)를 제거한다.
        prefetch_months(
            ((lawd_cd, deal_ymd) for lawd_cd in lawd_cds for deal_ymd in month_batch),
            transaction_kind=transaction_kind,
        )
        matched = _scan_months_for_latest(
            month_batch,
            lawd_cds,
            rows,
            name,
            area_label,
            transaction_kind=transaction_kind,
        )
        if matched:
            return {
                "name": name,
                "region": region,
                "areaLabel": area_label,
                "latestDealPriceEok": round(float(matched.get("dealAmountEok") or 0), 2),
                "latestDealExclusiveArea": matched.get("exclusiveArea"),
                "latestDealFloor": matched.get("floor", ""),
                "latestDealDate": matched.get("dealDate", ""),
                "sourceNote": f"국토부 실거래가 최근 {lookback_months}개월 확장 조회",
            }
    return None


def _scan_months_for_latest(
    month_values,
    lawd_cds,
    rows,
    name,
    area_label,
    transaction_kind=TRANSACTION_KIND_APARTMENT,
):
    for deal_ymd in month_values:
        month_matches = []
        for lawd_cd in lawd_cds:
            try:
                items = (
                    fetch_month(
                        lawd_cd,
                        deal_ymd,
                        transaction_kind=transaction_kind,
                    )
                    if transaction_kind == TRANSACTION_KIND_PRESALE
                    else fetch_month(lawd_cd, deal_ymd)
                )
            except Exception:
                continue
            for source_row in rows:
                if _row_lawd_cd(source_row) != lawd_cd:
                    continue
                for item in _items_for_source_row(lawd_cd, deal_ymd, items, source_row, dong_only=bool(_unit_number(name))):
                    if not _is_market_transaction(item):
                        continue
                    if not _matches_area(item, area_label):
                        continue
                    if not _matches_transaction(source_row, item, name):
                        continue
                    month_matches.append(item)
        if month_matches:
            month_matches.sort(key=lambda row: row.get("dealDate", ""), reverse=True)
            return month_matches[0]
    return None


def _price_band_payload(name, region, area_label, lookback_months, transactions):
    prices = sorted(float(row.get("dealAmountEok") or 0) for row in transactions if row.get("dealAmountEok"))
    if not prices:
        return None
    latest = next((row for row in transactions if row.get("dealAmountEok")), {})
    previous = next((row for row in transactions[1:] if row.get("dealAmountEok")), {})
    estimate = _current_price_estimate(transactions)
    return {
        "name": name,
        "region": region,
        "areaLabel": area_label,
        "lookbackMonths": lookback_months,
        "minPriceEok": round(min(prices), 2),
        "midPriceEok": round(statistics.median(prices), 2),
        "averagePriceEok": round(statistics.mean(prices), 2),
        "maxPriceEok": round(max(prices), 2),
        "latestDealPriceEok": round(float(latest.get("dealAmountEok") or 0), 2),
        "latestDealExclusiveArea": latest.get("exclusiveArea"),
        "latestDealFloor": latest.get("floor", ""),
        "previousDealPriceEok": round(float(previous.get("dealAmountEok") or 0), 2),
        "previousDealDate": previous.get("dealDate", ""),
        "transactionCount": len(prices),
        "latestDealDate": latest.get("dealDate", ""),
        "sourceNote": f"국토부 실거래가 최근 {lookback_months}개월",
        "currentEstimateMinPriceEok": (estimate or {}).get("minPriceEok"),
        "currentEstimateMidPriceEok": (estimate or {}).get("midPriceEok"),
        "currentEstimateMaxPriceEok": (estimate or {}).get("maxPriceEok"),
        "currentEstimateSampleCount": (estimate or {}).get("sampleCount", 0),
        "currentEstimateTrimmedCount": (estimate or {}).get("trimmedCount", 0),
        "currentEstimateMethod": (estimate or {}).get("method", ""),
        **_quarter_trade_stats(transactions),
        **_half_year_trade_stats(transactions),
    }


def price_band_for_apartment(name, region="", area_label="", lookback_months=RECENT_LOOKBACK_MONTHS):
    lookback_months = int(lookback_months or RECENT_LOOKBACK_MONTHS)
    cache_key = _price_band_cache_key(name, region, area_label, lookback_months)
    with _PRICE_BAND_CACHE_LOCK:
        cache_hit, cached_band = _read_cached_price_band(cache_key)
    if cache_hit:
        return cached_band

    band = _price_band_payload(
        name,
        region,
        area_label,
        lookback_months,
        transactions_for_apartment(
            name,
            region=region,
            area_label=area_label,
            lookback_months=lookback_months,
        ),
    )
    with _PRICE_BAND_CACHE_LOCK:
        _write_cached_price_band(cache_key, band)
    return band


def cached_price_band_for_apartment(
    name,
    region="",
    area_label="",
    lookback_months=RECENT_LOOKBACK_MONTHS,
    entity=None,
):
    """Return a price band without making any network request."""
    lookback_months = int(lookback_months or RECENT_LOOKBACK_MONTHS)
    cache_key = _price_band_cache_key(name, region, area_label, lookback_months)
    with _PRICE_BAND_CACHE_LOCK:
        cache_hit, cached_band = _read_cached_price_band(cache_key)
    if cache_hit:
        return cached_band
    return _price_band_payload(
        name,
        region,
        area_label,
        lookback_months,
        transactions_for_apartment_cached(
            name,
            region=region,
            area_label=area_label,
            lookback_months=lookback_months,
            entity=entity,
        ),
    )


def _minimum_area_price_band_payload(name, region, minimum, lookback_months, transactions):
    minimum = float(minimum or 0)
    transactions = _minimum_area_transactions(
        transactions,
        minimum,
    )
    prices = sorted(float(row.get("dealAmountEok") or 0) for row in transactions if row.get("dealAmountEok"))
    if not prices:
        return None
    latest = transactions[0]
    previous = next((row for row in transactions[1:] if row.get("dealAmountEok")), {})
    estimate = _current_price_estimate(transactions)
    display_area = max(int(minimum), int(float(latest.get("exclusiveArea") or 0)))
    return {
        "name": name,
        "region": region,
        "areaLabel": f"전용 {display_area}㎡",
        "lookbackMonths": lookback_months,
        "minPriceEok": round(min(prices), 2),
        "midPriceEok": round(statistics.median(prices), 2),
        "averagePriceEok": round(statistics.mean(prices), 2),
        "maxPriceEok": round(max(prices), 2),
        "latestDealPriceEok": round(float(latest.get("dealAmountEok") or 0), 2),
        "latestDealExclusiveArea": latest.get("exclusiveArea"),
        "latestDealFloor": latest.get("floor", ""),
        "previousDealPriceEok": round(float(previous.get("dealAmountEok") or 0), 2),
        "previousDealDate": previous.get("dealDate", ""),
        "transactionCount": len(prices),
        "latestDealDate": latest.get("dealDate", ""),
        "sourceNote": f"국토부 실거래가 최근 {lookback_months}개월 · 최소 {minimum:g}㎡ 이상 중 확인된 최소 평형",
        "currentEstimateMinPriceEok": (estimate or {}).get("minPriceEok"),
        "currentEstimateMidPriceEok": (estimate or {}).get("midPriceEok"),
        "currentEstimateMaxPriceEok": (estimate or {}).get("maxPriceEok"),
        "currentEstimateSampleCount": (estimate or {}).get("sampleCount", 0),
        "currentEstimateTrimmedCount": (estimate or {}).get("trimmedCount", 0),
        "currentEstimateMethod": (estimate or {}).get("method", ""),
        **_quarter_trade_stats(transactions),
        **_half_year_trade_stats(transactions),
    }


def price_band_for_apartment_min_area(name, region="", min_area=0, lookback_months=RECENT_LOOKBACK_MONTHS):
    """Return the smallest actually traded unit type at or above min_area."""
    minimum = float(min_area or 0)
    cache_label = f"최소 전용 {minimum:g}㎡"
    lookback_months = int(lookback_months or RECENT_LOOKBACK_MONTHS)
    cache_key = _price_band_cache_key(name, region, cache_label, lookback_months)
    with _PRICE_BAND_CACHE_LOCK:
        cache_hit, cached_band = _read_cached_price_band(cache_key)
    if cache_hit:
        return cached_band

    band = _minimum_area_price_band_payload(
        name,
        region,
        minimum,
        lookback_months,
        transactions_for_apartment(
            name,
            region=region,
            area_label="",
            lookback_months=lookback_months,
        ),
    )
    with _PRICE_BAND_CACHE_LOCK:
        _write_cached_price_band(cache_key, band)
    return band


def cached_price_band_for_apartment_min_area(
    name,
    region="",
    min_area=0,
    lookback_months=RECENT_LOOKBACK_MONTHS,
    entity=None,
):
    """Return a minimum-area price band using only local caches."""
    minimum = float(min_area or 0)
    cache_label = f"최소 전용 {minimum:g}㎡"
    lookback_months = int(lookback_months or RECENT_LOOKBACK_MONTHS)
    cache_key = _price_band_cache_key(name, region, cache_label, lookback_months)
    with _PRICE_BAND_CACHE_LOCK:
        cache_hit, cached_band = _read_cached_price_band(cache_key)
    if cache_hit:
        return cached_band
    return _minimum_area_price_band_payload(
        name,
        region,
        minimum,
        lookback_months,
        transactions_for_apartment_cached(
            name,
            region=region,
            area_label="",
            lookback_months=lookback_months,
            entity=entity,
        ),
    )
