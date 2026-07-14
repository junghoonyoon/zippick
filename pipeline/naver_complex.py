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
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import real_estate_search

SEARCH_ENDPOINT = "https://new.land.naver.com/api/search"
CACHE_DIR = config.CACHE_DIR / "naver_complex"
NEGATIVE_TTL_SECONDS = 60 * 60 * 24 * 7  # 못 찾은 단지는 7일 후 재시도
TIMEOUT_SECONDS = float(getattr(config, "NAVER_COMPLEX_TIMEOUT_SECONDS", 4))
MAX_WORKERS = int(getattr(config, "NAVER_COMPLEX_MAX_WORKERS", 6))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://new.land.naver.com/",
}
_CACHE_LOCK = threading.Lock()
_DISABLED_UNTIL = 0

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
}


def _cache_key(name, legal_dong, jibun):
    compact = real_estate_search.compact
    return f"{compact(name)}_{compact(legal_dong)}_{compact(jibun)}" or "unknown"


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


def _search(keyword):
    global _DISABLED_UNTIL
    if time.time() < _DISABLED_UNTIL:
        return []
    try:
        response = requests.get(
            SEARCH_ENDPOINT,
            params={"keyword": keyword},
            headers=HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        # 차단·형식 변경 시 잠시 끄고 폴백 링크로만 동작
        _DISABLED_UNTIL = time.time() + 60 * 10
        return []
    complexes = data.get("complexes") or data.get("complexList") or []
    return complexes if isinstance(complexes, list) else []


def _entry_complex_no(entry):
    for field in ("complexNo", "hscpNo", "complexNumber"):
        value = str(entry.get(field) or "").strip()
        if value.isdigit():
            return value
    return None


def _entry_name(entry):
    return str(entry.get("complexName") or entry.get("name") or "").strip()


def _entry_address(entry):
    return str(entry.get("cortarAddress") or entry.get("address") or "")


def _pick(complexes, name, legal_dong):
    compact = real_estate_search.compact
    name_key = compact(name)
    dong_key = compact(legal_dong)
    scored = []
    for entry in complexes:
        complex_no = _entry_complex_no(entry)
        if not complex_no:
            continue
        entry_name = compact(_entry_name(entry))
        if not entry_name:
            continue
        name_match = name_key == entry_name or name_key in entry_name or entry_name in name_key
        dong_match = bool(dong_key) and dong_key in compact(_entry_address(entry))
        if not name_match and not dong_match:
            continue
        scored.append((
            (2 if name_match else 0) + (1 if dong_match else 0),
            complex_no,
            _entry_name(entry),
        ))
    if not scored:
        return None
    scored.sort(reverse=True)
    top_score = scored[0][0]
    top = [item for item in scored if item[0] == top_score]
    # 동 정보 없이 이름만 걸린 후보가 여러 개면 오링크 위험 → 포기하고 폴백
    if len(top) > 1 and top_score < 3:
        return None
    return {"complexNo": top[0][1], "complexName": top[0][2]}


def resolve(name, legal_dong="", jibun="", region=""):
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
    queries = []
    if legal_dong:
        queries.append(f"{legal_dong} {name}")
    queries.append(name)
    if region and region != legal_dong:
        queries.append(f"{region} {name}")
    result = None
    for query in queries:
        picked = _pick(_search(query), name, legal_dong)
        if picked:
            result = picked
            break
    with _CACHE_LOCK:
        _write_cache(key, result or {"complexNo": None})
    return result


def complex_url(complex_no):
    return f"https://new.land.naver.com/complexes/{complex_no}"


def search_url(query):
    """현재 네이버페이 부동산의 단지 자동완성 검색 화면 URL."""
    from urllib.parse import quote

    return f"https://fin.land.naver.com/search?q={quote(str(query or '').strip(), safe='')}"


def attach_links(rows):
    """확정된 네이버 단지의 링크와 표시명을 후보 카드에 적용한다."""
    def _one(row):
        try:
            resolved = resolve(
                row.get("name", ""),
                legal_dong=row.get("legalDong", ""),
                jibun=row.get("jibun", ""),
                region=row.get("region", ""),
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
                row["displayName"] = complex_name
                row["displayNameSource"] = "naver_complex"
            return
        # 지번 검색은 네이버부동산에서 단지로 연결되지 않는 경우가 많다.
        # 후보 생성 단계에서 만든 단지명 검색어를 유지하고, 없는 경우에만
        # 표시용 검색어/단지명으로 새 이름 검색 링크를 만든다.
        query = str(
            row.get("naverPropertyQuery")
            or row.get("searchQuery")
            or row.get("displayName")
            or row.get("name")
            or ""
        ).strip()
        if query:
            row["naverPropertyQuery"] = query
            row["naverPropertyUrl"] = search_url(query)
        row["naverLinkKind"] = "name"

    targets = [row for row in rows if row.get("name")]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets))) as pool:
        list(pool.map(_one, targets))
