"""네이버부동산 단지 번호(complexNo)·표시명 리졸버.

공공데이터 단지명과 네이버 등록 단지명이 달라 텍스트 검색 링크가 실패하는
문제를 해결한다. 서버에서 단지 번호를 한 번 찾아 영구 캐시하고, 이후에는
단지 페이지로 직접 링크한다. 주소를 포함해 단지가 확정되면 네이버 등록
단지명을 후보 카드의 표시명으로도 사용한다. 실패 시 기존 단지명 검색 링크와
공공데이터 표시명을 유지한다.

주의: 비공식 엔드포인트라 상용 출시 전에는 네이버 약관·제휴 검토가 필요하다.
"""
import json
import re
import time
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import real_estate_search

SEARCH_ENDPOINT = "https://fin.land.naver.com/front-api/v1/search/autocomplete/complexes"
MOBILE_COMPLEX_LIST_ENDPOINT = "https://m.land.naver.com/complex/ajax/complexListByCortarNo"
CACHE_DIR = config.CACHE_DIR / "naver_complex"
CACHE_VERSION = "v5"
NEGATIVE_TTL_SECONDS = 60 * 60 * 24 * 7  # 못 찾은 단지는 7일 후 재시도
TIMEOUT_SECONDS = float(getattr(config, "NAVER_COMPLEX_TIMEOUT_SECONDS", 2))
MAX_WORKERS = int(getattr(config, "NAVER_COMPLEX_MAX_WORKERS", 2))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://fin.land.naver.com/",
}
_CACHE_LOCK = threading.Lock()
_CORTAR_CACHE_LOCK = threading.Lock()
_CORTAR_COMPLEX_CACHE = {}
_CORTAR_REQUEST_LOCKS = tuple(threading.Lock() for _ in range(32))
_DISABLED_LOCK = threading.Lock()
_DISABLED_UNTIL = 0
_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="naver-complex",
)

# 네이버 검색 API가 일시적으로 제한돼도 확실히 검증된 중복명 단지는
# 잘못된 오피스텔/지번 검색으로 보내지 않도록 직링크를 우선한다.
VERIFIED_COMPLEX_OVERRIDES = {
    ("마포한화오벨리스크", "도화동", "555"): {
        "complexNo": "12240",
        "complexName": "마포한화오벨리스크(주상복합)",
    },
    # 네이버 등록 단지명 확인: 길음동 1276, 684세대, 1998-02-02 사용승인.
    # 검색 API가 이 공공데이터명들에는 간헐적으로 빈 결과를 반환해, 확인된
    # 네이버 단지 번호와 표시명을 같은 주소의 두 원본명에 고정한다.
    ("돈암21삼부아파트", "길음동", "1276"): {
        "complexNo": "576",
        "complexName": "돈암삼부(삼부컨비니언)",
    },
    ("삼부컨비니언", "길음동", "1276"): {
        "complexNo": "576",
        "complexName": "돈암삼부(삼부컨비니언)",
    },
    # 공공데이터의 178세대·2006-11-30 사용승인 정보와 네이버 단지정보를
    # 대조해 1차로 확인했다. 2차는 139세대·2011-10-28 사용승인 단지다.
    ("은평신사두산위브", "신사동", "370"): {
        "complexNo": "25766",
        "complexName": "은평신사두산위브1차",
    },
}


def _cache_key(name, legal_dong, jibun):
    compact = real_estate_search.compact
    identity = f"{compact(name)}_{compact(legal_dong)}_{compact(jibun)}" or "unknown"
    return f"{CACHE_VERSION}_{identity}"


def _cache_path(key):
    safe = re.sub(r"[^0-9a-zA-Z가-힣_-]", "", key)[:120]
    return CACHE_DIR / f"{safe or 'unknown'}.json"


def _read_cache(key):
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    complex_no = cached.get("complexNo")
    if complex_no:
        return cached  # 성공 캐시는 영구
    if time.time() - float(cached.get("savedAt") or 0) > NEGATIVE_TTL_SECONDS:
        return None
    return cached


def _write_cache(key, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "savedAt": time.time()}
    path = _cache_path(key)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _temporarily_disabled():
    with _DISABLED_LOCK:
        return time.time() < _DISABLED_UNTIL


def _disable_temporarily(seconds=60 * 10):
    global _DISABLED_UNTIL
    with _DISABLED_LOCK:
        _DISABLED_UNTIL = max(_DISABLED_UNTIL, time.time() + seconds)


def _search(keyword):
    if _temporarily_disabled():
        return None
    try:
        response = requests.get(
            SEARCH_ENDPOINT,
            params={"keyword": keyword, "size": 20, "page": 0},
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        # 조회 제한을 '검색 결과 없음'으로 캐시하면 이후 정상화돼도 일주일간
        # 검색창 링크만 남는다. 장애는 None으로 구분해 캐시하지 않는다.
        _disable_temporarily()
        return None
    result = data.get("result") if isinstance(data, dict) else None
    complexes = (
        (result.get("list") if isinstance(result, dict) else None)
        or data.get("complexes")
        or data.get("complexList")
        or []
    )
    return complexes if isinstance(complexes, list) else []


def _search_by_cortar(cortar_no):
    """법정동 코드로 해당 동의 네이버 단지 목록을 조회한다."""
    cortar_no = re.sub(r"\D", "", str(cortar_no or ""))[:10]
    if len(cortar_no) != 10:
        return None
    if _temporarily_disabled():
        return None
    with _CORTAR_CACHE_LOCK:
        if cortar_no in _CORTAR_COMPLEX_CACHE:
            return _CORTAR_COMPLEX_CACHE[cortar_no]
    # 같은 동만 한 번 호출하되 서로 다른 동의 조회는 병렬로 진행한다.
    # 네트워크 대기 중 전역 캐시 잠금을 잡지 않는다.
    request_lock = _CORTAR_REQUEST_LOCKS[
        hash(cortar_no) % len(_CORTAR_REQUEST_LOCKS)
    ]
    with request_lock:
        if _temporarily_disabled():
            return None
        with _CORTAR_CACHE_LOCK:
            if cortar_no in _CORTAR_COMPLEX_CACHE:
                return _CORTAR_COMPLEX_CACHE[cortar_no]
        try:
            response = requests.get(
                MOBILE_COMPLEX_LIST_ENDPOINT,
                params={"cortarNo": cortar_no},
                headers={**HEADERS, "Referer": "https://m.land.naver.com/"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            _disable_temporarily()
            return None
        complexes = data.get("result") if isinstance(data, dict) else None
        if not isinstance(complexes, list):
            return None
        with _CORTAR_CACHE_LOCK:
            _CORTAR_COMPLEX_CACHE[cortar_no] = complexes
        return complexes


def _entry_complex_no(entry):
    for field in ("complexNumber", "complexNo", "hscpNo"):
        value = str(entry.get(field) or "").strip()
        if value.isdigit():
            return value
    return None


def _entry_name(entry):
    return str(
        entry.get("complexName")
        or entry.get("hscpNm")
        or entry.get("name")
        or ""
    ).strip()


def _entry_address(entry):
    address = entry.get("address")
    if isinstance(address, dict):
        address = " ".join(
            str(value or "").strip()
            for value in (
                address.get("roadAddress"),
                address.get("jibunAddress"),
            )
            if str(value or "").strip()
        )
    return str(
        entry.get("legalDivisionName")
        or entry.get("cortarAddress")
        or address
        or ""
    )


def _name_variants(value, legal_dong=""):
    key = real_estate_search.compact(value)
    variants = [key] if key else []
    without_apartment = re.sub(r"아파트$", "", key)
    if without_apartment and without_apartment not in variants:
        variants.append(without_apartment)
    dong_key = real_estate_search.compact(legal_dong)
    if dong_key.endswith("동"):
        for candidate in list(variants):
            if candidate.startswith(dong_key):
                without_dong_suffix = dong_key[:-1] + candidate[len(dong_key):]
                if without_dong_suffix and without_dong_suffix not in variants:
                    variants.append(without_dong_suffix)
    return variants


def _character_similarity(left, right):
    """단어 순서만 바뀐 네이버 등록명까지 잡는 문자 구성 유사도."""
    if len(left) < 5 or len(right) < 5:
        return 0
    overlap = sum((Counter(left) & Counter(right)).values())
    return (2 * overlap) / (len(left) + len(right))


def _name_match_score(query, entry_name, legal_dong=""):
    best = 0
    for name_key in _name_variants(query, legal_dong):
        for entry_key in _name_variants(entry_name):
            if name_key == entry_key:
                best = max(best, 4)
                continue
            if name_key in entry_key or entry_key in name_key:
                shorter = name_key if len(name_key) <= len(entry_key) else entry_key
                longer = entry_key if shorter == name_key else name_key
                if len(shorter) >= 5:
                    best = max(best, 3)
                elif len(shorter) >= 4 and longer.startswith(shorter):
                    best = max(best, 2)
                continue
            similarity = _character_similarity(name_key, entry_key)
            if similarity >= 0.82:
                best = max(best, 1 + similarity)
    return best


def _pick(complexes, name, legal_dong, alternate_names=()):
    compact = real_estate_search.compact
    query_names = []
    seen_names = set()
    for value in (name, *alternate_names):
        key = compact(value)
        if key and key not in seen_names:
            seen_names.add(key)
            query_names.append(value)
    dong_key = compact(legal_dong)
    scored = []
    for entry in complexes:
        complex_no = _entry_complex_no(entry)
        if not complex_no:
            continue
        entry_name = compact(_entry_name(entry))
        if not entry_name:
            continue
        name_score = max(
            (
                _name_match_score(query, entry_name, legal_dong)
                for query in query_names
            ),
            default=0,
        )
        dong_match = bool(dong_key) and dong_key in compact(_entry_address(entry))
        if not name_score and not dong_match:
            continue
        scored.append((
            name_score + (1 if dong_match else 0),
            complex_no,
            _entry_name(entry),
        ))
    if not scored:
        return None
    scored.sort(reverse=True)
    top_score = scored[0][0]
    top = [item for item in scored if item[0] == top_score]
    # 같은 점수의 후보가 여러 개면 오링크 위험 → 포기하고 폴백
    if len(top) > 1:
        return None
    return {"complexNo": top[0][1], "complexName": top[0][2]}


def resolve(
    name,
    legal_dong="",
    jibun="",
    region="",
    cortar_no="",
    alternate_names=(),
):
    """단지 번호 조회. 실패 시 None (호출부가 주소 검색으로 폴백)."""
    name = str(name or "").strip()
    if not name:
        return None
    override_key = (
        real_estate_search.compact(name),
        real_estate_search.compact(legal_dong),
        real_estate_search.compact(jibun),
    )
    override = VERIFIED_COMPLEX_OVERRIDES.get(override_key)
    if override:
        return dict(override)
    key = _cache_key(name, legal_dong, jibun)
    with _CACHE_LOCK:
        cached = _read_cache(key)
    if cached is not None:
        return cached if cached.get("complexNo") else None
    cortar_complexes = _search_by_cortar(cortar_no)
    if cortar_complexes is not None:
        result = _pick(
            cortar_complexes,
            name,
            legal_dong,
            alternate_names=alternate_names,
        )
        if result:
            with _CACHE_LOCK:
                _write_cache(key, result)
            return result
    queries = []
    if legal_dong:
        queries.append(f"{legal_dong} {name}")
    queries.append(name)
    if region and region != legal_dong:
        queries.append(f"{region} {name}")
    result = None
    search_available = True
    for query in queries:
        complexes = _search(query)
        if complexes is None:
            search_available = False
            break
        picked = _pick(
            complexes,
            name,
            legal_dong,
            alternate_names=alternate_names,
        )
        if picked:
            result = picked
            break
    if result or search_available:
        with _CACHE_LOCK:
            _write_cache(key, result or {"complexNo": None})
    return result


def complex_url(complex_no):
    """네이버페이 부동산에서 해당 단지의 매물 지도를 바로 여는 URL."""
    return f"https://fin.land.naver.com/complexes/{complex_no}?tab=article"


def search_url(query):
    """현재 네이버페이 부동산의 단지 자동완성 검색 화면 URL."""
    from urllib.parse import quote

    return f"https://fin.land.naver.com/search?q={quote(str(query or '').strip(), safe='')}"


def attach_links(rows, update_display_name=True):
    """확정된 네이버 단지의 링크와 표시명을 후보 카드에 적용한다."""
    def _one(row):
        try:
            resolved = resolve(
                row.get("name", ""),
                legal_dong=row.get("legalDong", ""),
                jibun=row.get("jibun", ""),
                region=row.get("region", ""),
                cortar_no=row.get("cortarNo", ""),
                alternate_names=(
                    row.get("displayName", ""),
                    row.get("searchQuery", ""),
                    row.get("naverPropertyQuery", ""),
                ),
            )
        except Exception:
            resolved = None
        if resolved and resolved.get("complexNo"):
            row["naverComplexNo"] = resolved["complexNo"]
            row["naverPropertyUrl"] = complex_url(resolved["complexNo"])
            row["naverLinkKind"] = "complex"
            complex_name = str(resolved.get("complexName") or "").strip()
            if complex_name:
                row["naverComplexName"] = complex_name
                if update_display_name:
                    row["displayName"] = complex_name
                    row["displayNameSource"] = "naver_complex"
            return
        # 확정되지 않은 단지를 검색 화면으로 보내면 네이버페이 오류 화면이
        # 열리거나 동명이인 단지로 연결될 수 있으므로 링크를 비활성화한다.
        query = str(
            row.get("naverPropertyQuery")
            or row.get("searchQuery")
            or row.get("displayName")
            or row.get("name")
            or ""
        ).strip()
        if query:
            row["naverPropertyQuery"] = query
        row["naverComplexNo"] = None
        row["naverPropertyUrl"] = ""
        row["naverLinkKind"] = "unresolved"

    targets = [row for row in rows if row.get("name")]
    if not targets:
        return
    # 요청마다 별도 풀을 만들면 동시 검색 수만큼 네이버 호출이 늘어난다.
    # 프로세스 공용 풀로 전체 호출량을 제한한다.
    list(_EXECUTOR.map(_one, targets))
