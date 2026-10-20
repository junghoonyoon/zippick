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
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import apartment_identity
import apartment_sections
import real_estate_search

SEARCH_ENDPOINT = "https://fin.land.naver.com/front-api/v1/search/autocomplete/complexes"
MOBILE_COMPLEX_LIST_ENDPOINT = "https://m.land.naver.com/complex/ajax/complexListByCortarNo"
CACHE_DIR = config.CACHE_DIR / "naver_complex"
STATIC_OVERRIDES_PATH = config.ROOT / "data" / "naver_complex_overrides.json"
REVIEWS_PATH = config.ROOT / "data" / "naver_complex_reviews.json"
CACHE_VERSION = "v8"
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
_STATIC_OVERRIDES_LOCK = threading.Lock()
_STATIC_COMPLEX_OVERRIDES = None
_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="naver-complex",
)

# 네이버 검색 API가 일시적으로 제한돼도 확실히 검증된 중복명 단지는
# 잘못된 오피스텔/지번 검색으로 보내지 않도록 직링크를 우선한다.
VERIFIED_COMPLEX_OVERRIDES = {
    # 공공데이터의 별칭 '동성3'은 신내동 618의 800세대 단지를 뜻한다.
    # 네이버에는 '동성3차'로 등록돼 있으므로 단지번호를 주소와 함께 고정한다.
    ("동성3", "신내동", "618"): {
        "complexNo": "813",
        "complexName": "동성3차",
    },
    ("동성아파트", "신내동", "618"): {
        "complexNo": "813",
        "complexName": "동성3차",
    },
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
    # 네이버 모바일 단지목록 확인: 문정동 145, 문정시영, hscpNo 609.
    # 운영 서버에서 네이버 비공식 조회가 타임아웃될 때도 검색 결과가 아닌
    # 해당 단지 지도 화면으로 바로 보낸다.
    ("문정시영", "문정동", "145"): {
        "complexNo": "609",
        "complexName": "문정시영",
    },
    ("문정시영아파트", "문정동", "145"): {
        "complexNo": "609",
        "complexName": "문정시영",
    },
}


def _override_key(name, legal_dong="", jibun=""):
    return (
        real_estate_search.compact(name),
        real_estate_search.compact(legal_dong),
        apartment_identity.parcel_key(jibun, legal_dong),
    )


@lru_cache(maxsize=1)
def mapping_reviews():
    return json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))["entries"]


def rejected_mapping(complex_no, legal_dong, jibun, region=""):
    return any(str(complex_no) in review.get("rejectedComplexNos", [])
               and legal_dong == review["legalDong"]
               and apartment_identity.parcel_key(jibun) == apartment_identity.parcel_key(review["jibun"])
               and (not region or apartment_identity.region_matches(region, {"district": review["region"]}))
               for review in mapping_reviews())


def verified_phase_alias(name, entry):
    # Explicit, address-reviewed naming exceptions only. A different numbered
    # query must not borrow the exception through a generic alternate name.
    return (entry.get("phaseAliasVerified") is True
            and not apartment_identity.phase_conflicts(name, entry.get("name")))


def _static_complex_overrides():
    """Load preverified ZipPick-to-Naver complex mappings bundled with deploys."""
    global _STATIC_COMPLEX_OVERRIDES
    with _STATIC_OVERRIDES_LOCK:
        if _STATIC_COMPLEX_OVERRIDES is not None:
            return _STATIC_COMPLEX_OVERRIDES
        overrides = {}
        try:
            payload = json.loads(STATIC_OVERRIDES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _STATIC_COMPLEX_OVERRIDES = overrides
            return overrides
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            _STATIC_COMPLEX_OVERRIDES = overrides
            return overrides
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            complex_no = str(entry.get("complexNo") or "").strip()
            name = str(entry.get("name") or "").strip()
            if not complex_no.isdigit() or not name:
                continue
            key = _override_key(
                name,
                entry.get("legalDong", ""),
                entry.get("jibun", ""),
            )
            value = {
                "name": name,
                "phaseAliasVerified": entry.get("phaseAliasVerified", False),
                "complexNo": complex_no,
                "complexName": str(entry.get("complexName") or "").strip(),
                "region": str(entry.get("region") or "").strip(),
            }
            overrides.setdefault(key, []).append(value)
        _STATIC_COMPLEX_OVERRIDES = overrides
        return overrides


def _verified_override(name, legal_dong="", jibun="", alternate_names=(), region=""):
    names = []
    seen = set()
    for value in (name, *alternate_names):
        key = real_estate_search.compact(value)
        if key and key not in seen:
            seen.add(key)
            names.append(value)
    for value in names:
        override = VERIFIED_COMPLEX_OVERRIDES.get(
            _override_key(value, legal_dong, jibun)
        )
        if override and not apartment_identity.phase_conflicts(name, override.get('complexName')):
            return {
                **override,
                # 화면의 단지명은 검수된 네이버 단지명으로 통일한다. 원본명은
                # row["name"]에 그대로 남아 실거래 조회 식별값으로 사용한다.
                "displayName": str(override.get("complexName") or "").strip(),
                "displayNameSource": "naver_verified_mapping",
            }
    static_overrides = _static_complex_overrides()
    for value in names:
        candidates = static_overrides.get(_override_key(value, legal_dong, jibun), [])
        candidates = [entry for entry in candidates
                      if (not apartment_identity.phase_conflicts(name, entry.get('complexName'))
                          or verified_phase_alias(name, entry))
                      and not rejected_mapping(entry['complexNo'], legal_dong, jibun, region)
                      and (not region or not entry.get('region') or
                           apartment_identity.region_matches(region, {'district': entry['region'], 'legalDong': legal_dong}))]
        if len({entry['complexNo'] for entry in candidates}) == 1:
            selected = candidates[0]
            return {
                "complexNo": selected["complexNo"],
                "complexName": selected["complexName"],
                "displayName": selected["complexName"],
                "displayNameSource": "naver_verified_mapping",
            }
    return None


def resolve_static(name, legal_dong="", jibun="", alternate_names=(), region=""):
    """Return only a bundled, address-verified Naver mapping without I/O."""
    section = apartment_sections.resolve(name, legal_dong, jibun, region)
    if section:
        return {'complexNo': section['naverComplexNo'], 'complexName': section['naverComplexName'],
                'displayName': section['naverComplexName'],
                'displayNameSource': 'naver_verified_mapping',
                'scope': section['naverScope']}
    return _verified_override(name, legal_dong, jibun, alternate_names, region)


def _cache_key(name, legal_dong, jibun, region=""):
    compact = real_estate_search.compact
    identity = f"{compact(region)}_{compact(name)}_{compact(legal_dong)}_{apartment_identity.parcel_key(jibun, legal_dong)}" or "unknown"
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


def _pick(complexes, name, legal_dong, alternate_names=(), jibun="", region=""):
    known_section = apartment_sections.resolve(name)
    if known_section and not apartment_sections.resolve(name, legal_dong, jibun, region):
        return None
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
        if known_section and complex_no != known_section['naverComplexNo']:
            continue
        entry_name = compact(_entry_name(entry))
        if not entry_name:
            continue
        if entry.get('hscpTypeCd') and entry['hscpTypeCd'] not in {'A01', 'A03', 'A04'}:
            continue
        if rejected_mapping(complex_no, legal_dong, jibun, region):
            continue
        if apartment_identity.phase_conflicts(name, _entry_name(entry)):
            continue
        entry_address = _entry_address(entry)
        if legal_dong and entry_address and compact(legal_dong) not in compact(entry_address):
            continue
        if region and entry_address and not apartment_identity.region_matches(region, {'address': entry_address}):
            continue
        entry_parcel = apartment_identity.entity_parcel({'address': entry_address, 'legalDong': legal_dong,
                                                       'jibun': entry.get('jibun', '')})
        if jibun and entry_parcel and apartment_identity.parcel_key(jibun) != entry_parcel:
            continue
        name_score = max(
            (
                _name_match_score(query, entry_name, legal_dong)
                for query in query_names if not apartment_identity.phase_conflicts(query, _entry_name(entry))
            ),
            default=0,
        )
        dong_match = bool(dong_key) and dong_key in compact(_entry_address(entry))
        if not name_score:
            continue
        # A numbered child cannot be selected just because it is the only
        # partial family-name hit. Exact aliases or a parcel must corroborate it.
        if (apartment_identity.phase_numbers(_entry_name(entry))
                and not any(apartment_identity.phase_numbers(query) for query in query_names)
                and not (jibun and entry_parcel == apartment_identity.parcel_key(jibun))):
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
    if apartment_sections.resolve(name) and not apartment_sections.resolve(name, legal_dong, jibun, region):
        return None
    override = resolve_static(
        name,
        legal_dong,
        jibun,
        alternate_names=alternate_names,
        region=region,
    )
    if override:
        return dict(override)
    key = _cache_key(name, legal_dong, jibun, region)
    with _CACHE_LOCK:
        cached = _read_cache(key)
    if cached is not None and not rejected_mapping(cached.get('complexNo'), legal_dong, jibun, region):
        return cached if cached.get("complexNo") else None
    cortar_complexes = _search_by_cortar(cortar_no)
    if cortar_complexes is not None:
        result = _pick(
            cortar_complexes,
            name,
            legal_dong,
            alternate_names=alternate_names,
            jibun=jibun, region=region,
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
            jibun=jibun, region=region,
        )
        if picked:
            result = picked
            break
    if result or search_available:
        with _CACHE_LOCK:
            _write_cache(key, result or {"complexNo": None})
    return result


def complex_url(complex_no):
    """네이버페이 부동산에서 해당 단지의 기본 시세 화면을 바로 연다.

    네이버의 ``tab=article``은 매물 탭을 강제로 열기 때문에, 카드의
    '시세보기' 동작과 맞지 않는다. 단지번호만 넘기면 네이버가 시세 탭을
    기본으로 표시한다.
    """
    return f"https://fin.land.naver.com/complexes/{complex_no}"


def search_url(query):
    """현재 네이버페이 부동산의 단지 자동완성 검색 화면 URL."""
    from urllib.parse import quote

    return f"https://fin.land.naver.com/search?q={quote(str(query or '').strip(), safe='')}"


def _apply_resolved_mapping(row, resolved, update_display_name=True):
    """Apply one already-verified mapping without touching search identity."""
    row["naverComplexNo"] = resolved["complexNo"]
    row["naverPropertyUrl"] = complex_url(resolved["complexNo"])
    row["naverLinkKind"] = "complex"
    complex_name = str(resolved.get("complexName") or "").strip()
    if not complex_name:
        return
    row["naverComplexName"] = complex_name
    if not update_display_name:
        return
    source_name = row.get("displayName") or row.get("name") or ""
    # A bundled mapping has passed the address/parcel check, so its exact
    # NAVER label is safe even when the public source name has a phase number.
    verified_display_name = str(resolved.get("displayName") or "").strip()
    if verified_display_name:
        row["displayName"] = verified_display_name
        row["displayNameSource"] = resolved.get("displayNameSource") or "naver_verified_mapping"
        return
    # A live lookup has no durable display-name review. Preserve a numbered
    # public source name rather than making 1·2단지 look like one guessed row.
    preserve_source = bool(apartment_identity.phase_numbers(source_name))
    row["displayName"] = source_name if preserve_source else complex_name
    row["displayNameSource"] = "apartment_identity" if preserve_source else "naver_complex"


def attach_static_links(rows, update_display_name=True):
    """Apply bundled address-verified NAVER labels without a network lookup.

    This is used on every first paint. A timeout or a changed autocomplete
    response must never make a card name or a price card disappear.
    """
    for row in rows:
        if not row.get("name"):
            continue
        resolved = resolve_static(
            row.get("name", ""),
            legal_dong=row.get("legalDong", ""),
            jibun=row.get("jibun", ""),
            region=row.get("region", ""),
            alternate_names=(
                row.get("displayName", ""),
                row.get("searchQuery", ""),
                row.get("naverPropertyQuery", ""),
            ),
        )
        if resolved and resolved.get("complexNo"):
            _apply_resolved_mapping(row, resolved, update_display_name)


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
            _apply_resolved_mapping(row, resolved, update_display_name)
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
