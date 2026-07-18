"""부동산 유튜브 검색 인덱스와 주문형 의견 분석."""
import csv
import datetime
import hashlib
import json
import re
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo

import requests

import config

if str(config.PARENT_PIPELINE_DIR) not in sys.path:
    sys.path.append(str(config.PARENT_PIPELINE_DIR))

import remote_cache  # noqa: E402
import youtube  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
_INDEX_VERSION = 1
_ANALYSIS_VERSION = 2
_REMOTE_INDEX_CHECK_INTERVAL_SECONDS = 60
_REMOTE_INDEX_CHECKED_AT = 0
REMOTE_PREFIX = "real_estate"
_POPULAR_ALIAS_INDEX_CACHE = {}
_AMBIGUOUS_APARTMENT_NAME_CACHE = {}

ENTITY_MASTER = [
    {"name": "강남", "category": "지역", "aliases": ["강남구", "강남권"], "keywords": ["대치", "개포", "압구정", "반포"]},
    {"name": "서초", "category": "지역", "aliases": ["서초구"], "keywords": ["반포", "잠원", "방배"]},
    {"name": "송파", "category": "지역", "aliases": ["송파구"], "keywords": ["잠실", "문정", "가락"]},
    {"name": "마포", "category": "지역", "aliases": ["마포구"], "keywords": ["아현", "공덕", "상암"]},
    {"name": "성수", "category": "지역", "aliases": ["성수동"], "keywords": ["서울숲", "한강변"]},
    {"name": "목동", "category": "지역", "aliases": ["양천구 목동"], "keywords": ["재건축", "학군"]},
    {"name": "분당", "category": "지역", "aliases": ["성남 분당"], "keywords": ["1기 신도시", "재건축"]},
    {"name": "판교", "category": "지역", "aliases": ["성남 판교"], "keywords": ["테크노밸리"]},
    {"name": "과천", "category": "지역", "aliases": ["과천시"], "keywords": ["지식정보타운", "재건축"]},
    {"name": "동탄", "category": "지역", "aliases": ["동탄신도시", "화성 동탄"], "keywords": ["GTX", "동탄역"]},
    {"name": "광명", "category": "지역", "aliases": ["광명시"], "keywords": ["철산", "하안", "재개발"]},
    {"name": "검단", "category": "지역", "aliases": ["검단신도시", "인천 검단"], "keywords": ["입주물량"]},
    {"name": "마곡", "category": "지역", "aliases": ["마곡지구"], "keywords": ["업무지구"]},
    {"name": "여의도", "category": "지역", "aliases": ["여의도동"], "keywords": ["재건축", "금융"]},
    {"name": "용산", "category": "지역", "aliases": ["용산구"], "keywords": ["국제업무지구", "한남"]},
    {"name": "잠실", "category": "지역", "aliases": ["잠실동"], "keywords": ["엘리트", "재건축"]},
    {"name": "올림픽파크포레온", "category": "단지", "aliases": ["둔촌주공", "올파포"], "keywords": ["강동", "입주"]},
    {"name": "헬리오시티", "category": "단지", "aliases": ["송파 헬리오시티"], "keywords": ["가락"]},
    {"name": "래미안 원베일리", "category": "단지", "aliases": ["원베일리", "반포 원베일리"], "keywords": ["반포"]},
    {"name": "은마아파트", "category": "단지", "aliases": ["대치 은마", "은마"], "keywords": ["재건축"]},
    {"name": "GTX", "category": "교통", "aliases": ["수도권광역급행철도", "GTX-A", "GTX-B", "GTX-C"], "keywords": ["역세권"]},
    {"name": "재건축", "category": "정책", "aliases": ["재건축 규제", "안전진단"], "keywords": ["초과이익환수", "정비사업"]},
    {"name": "전세", "category": "시장", "aliases": ["전세가", "전셋값", "전세시장"], "keywords": ["역전세", "전세사기"]},
    {"name": "분양", "category": "시장", "aliases": ["청약", "분양시장"], "keywords": ["분양가", "미분양"]},
    {"name": "미분양", "category": "시장", "aliases": ["악성 미분양", "준공 후 미분양"], "keywords": ["공급과잉"]},
]

MANUAL_APARTMENT_MASTER = [
    # lawdCd·legalDong·jibun까지 있으면 CSV에 없는 신축 단지도
    # molit_transactions가 합성 소스 행으로 실거래를 연결한다.
    {
        "name": "리버센SK뷰롯데캐슬", "category": "아파트",
        "aliases": ["리버센", "리버센 SK뷰", "리버센 SK VIEW 롯데캐슬", "리버센SKVIEW롯데캐슬", "중화동 리버센"],
        "province": "서울특별시", "district": "중랑구", "legalDong": "중화동",
        "jibun": "462", "lawdCd": "11260", "households": 1055,
    },
    {"name": "올림픽파크포레온", "category": "아파트", "aliases": ["둔촌주공", "올파포"]},
    {"name": "헬리오시티", "category": "아파트", "aliases": ["송파 헬리오시티"]},
    {"name": "래미안 원베일리", "category": "아파트", "aliases": ["래미안원베일리", "원베일리", "반포 원베일리"]},
    {"name": "은마아파트", "category": "아파트", "aliases": ["대치 은마", "은마"]},
    {"name": "반포자이", "category": "아파트", "aliases": []},
    {"name": "아크로리버파크", "category": "아파트", "aliases": ["아리팍"]},
    {"name": "잠실엘스", "category": "아파트", "aliases": ["엘스"]},
    {"name": "리센츠", "category": "아파트", "aliases": []},
    {"name": "트리지움", "category": "아파트", "aliases": []},
    {"name": "파크리오", "category": "아파트", "aliases": []},
    {"name": "잠실주공5단지", "category": "아파트", "aliases": ["주공5단지"]},
    {"name": "목동신시가지", "category": "아파트", "aliases": ["목동신시가지아파트"]},
    {"name": "마포래미안푸르지오", "category": "아파트", "aliases": ["마래푸"]},
    {"name": "서울숲 트리마제", "category": "아파트", "aliases": ["트리마제", "서울숲트리마제"]},
    {"name": "갤러리아포레", "category": "아파트", "aliases": []},
    {"name": "래미안대치팰리스", "category": "아파트", "aliases": []},
    {"name": "개포자이프레지던스", "category": "아파트", "aliases": []},
    {"name": "디에이치퍼스티어아이파크", "category": "아파트", "aliases": ["디퍼아"]},
    {"name": "한남더힐", "category": "아파트", "aliases": []},
    {"name": "나인원한남", "category": "아파트", "aliases": []},
    {"name": "아크로서울포레스트", "category": "아파트", "aliases": []},
    {"name": "과천푸르지오써밋", "category": "아파트", "aliases": []},
    {"name": "철산자이더헤리티지", "category": "아파트", "aliases": []},
    {"name": "광명센트럴아이파크", "category": "아파트", "aliases": []},
    {"name": "잠실르엘", "category": "아파트", "aliases": []},
    {"name": "메이플자이", "category": "아파트", "aliases": []},
    {"name": "고덕그라시움", "category": "아파트", "aliases": []},
    {"name": "동탄역 롯데캐슬", "category": "아파트", "aliases": ["동탄역롯데캐슬", "동탄롯데캐슬"]},
    {"name": "동탄역 시범단지", "category": "아파트", "aliases": ["동탄역시범단지", "동탄시범단지", "시범단지"]},
    {"name": "광교중흥S클래스", "category": "아파트", "aliases": ["광교중흥", "중흥S클래스"]},
    {"name": "판교푸르지오그랑블", "category": "아파트", "aliases": []},
    {"name": "백현마을", "category": "아파트", "aliases": []},
    {"name": "위례자이더시티", "category": "아파트", "aliases": []},
    {
        "name": "산성역 헤리스톤", "category": "성남수정구 아파트",
        "aliases": ["산성역헤리스톤", "헤리스톤", "헤리스톤아파트"],
        "province": "경기도", "city": "성남시", "district": "성남수정구",
        "legalDong": "산성동", "jibun": "1336", "lawdCd": "41131",
        "households": 3487, "status": "분양권",
    },
    {"name": "산성역 포레스티아", "category": "아파트", "aliases": ["산성역포레스티아", "산성역포레스티아아파트", "포레스티아"]},
    {"name": "산성역 자이푸르지오", "category": "아파트", "aliases": ["산자푸", "산성역자이푸르지오", "산성역자이푸르지오1단지", "산성역자이푸르지오 1단지", "산성역자이푸르지오2단지", "산성역자이푸르지오 2단지", "산성역자이푸르지오3단지", "산성역자이푸르지오 3단지", "산성역자이푸르지오4단지", "산성역자이푸르지오 4단지"]},
    {"name": "이문 아이파크 자이", "category": "아파트", "aliases": ["이문아이파크자이"]},
    {"name": "북서울자이 폴라리스", "category": "아파트", "aliases": ["북서울자이폴라리스"]},
    {"name": "자이퍼스틴", "category": "아파트", "aliases": []},
    {"name": "동탄 롯데캐슬 알바트로스", "category": "아파트", "aliases": ["동탄롯데캐슬알바트로스", "롯데캐슬알바트로스"]},
    {"name": "동탄역 시범 더샵 센트럴시티", "category": "아파트", "aliases": ["동탄역시범더샵센트럴시티", "더샵센트럴시티"]},
    {"name": "동탄 아이파크", "category": "아파트", "aliases": ["동탄아이파크"]},
    {"name": "동탄 푸른마을 포스코더샵2차", "category": "아파트", "aliases": ["푸른마을포스코더샵2차", "포스코더샵2차"]},
    {"name": "더샵 분당 센트로", "category": "아파트", "aliases": ["더샵분당센트로"]},
    {"name": "아이파크 삼성", "category": "아파트", "aliases": ["아이파크삼성"]},
    {"name": "아크로 삼성", "category": "아파트", "aliases": ["아크로삼성"]},
    {"name": "자연앤 힐스테이트", "category": "아파트", "aliases": ["자연앤힐스테이트"]},
    {"name": "더샵 스타시티", "category": "아파트", "aliases": ["더샵스타시티"]},
    {"name": "한신더휴 메가센텀", "category": "아파트", "aliases": ["한신더휴메가센텀", "한신더유메가센텀", "메가센텀"]},
    {"name": "센트럴 아이파크", "category": "아파트", "aliases": ["센트럴아이파크"]},
    {"name": "풍무역 롯데캐슬 시그니처", "category": "아파트", "aliases": ["풍무역롯데캐슬시그니처", "풍무현롯데캐슬시그니처"]},
    {"name": "힐스테이트 중앙", "category": "아파트", "aliases": ["힐스테이트중앙"]},
    {"name": "힐스테이트 하기", "category": "아파트", "aliases": ["힐스테이트하기"]},
    {"name": "고양 창릉 S4", "category": "아파트", "aliases": ["고양창릉S4", "창릉S4"]},
    {"name": "고양 창릉 S3", "category": "아파트", "aliases": ["고양창릉S3", "창릉S3"]},
    {"name": "e편한세상분당퍼스트빌리지", "category": "아파트", "aliases": ["이편한세상분당퍼스트빌리지", "분당퍼스트빌리지"]},
    {"name": "한신더휴 메가시티", "category": "아파트", "aliases": ["한신더휴메가시티", "창원메가시티"]},
    {"name": "래미안 퍼스티지", "category": "아파트", "aliases": ["반포래미안퍼스티지", "퍼스티지"]},
    {"name": "경희궁자이", "category": "아파트", "aliases": ["경희공자이"]},
]

APARTMENT_CSV_PATHS = [
    config.ROOT / "outputs" / "seoul_apartments_20260703" / "서울시_아파트_단지_목록_한국부동산원_20250918.csv",
    config.ROOT / "data" / "경기도_아파트_단지_목록_한국부동산원_20250918.csv",
    config.ROOT / "data" / "분양권_입주예정_아파트_보강.csv",
]


def compact(text):
    return re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ]", "", str(text)).lower()


def _clean_entity_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_usable_apartment_name(value):
    name = _clean_entity_name(value)
    if not name:
        return False
    if re.fullmatch(r"\(?[0-9\-]+\)?", name):
        return False
    return len(compact(name)) >= 2


def _is_rental_row(row):
    text = " ".join(str(row.get(column, "") or "") for column in (
        "대표단지명",
        "단지명_공시가격",
        "단지명_건축물대장",
        "단지명_도로명주소",
        "상태",
    ))
    key = compact(text)
    rental_markers = (
        "영구임대",
        "공공임대",
        "국민임대",
        "행복주택",
        "장기전세",
        "공공전세",
        "매입임대",
        "전세임대",
        "임대아파트",
        "임대주택",
        "토지임대부",
        "사회주택",
    )
    public_housing_markers = (
        "엘에이치",
        "lh",
        "엔에이치에프",
        "nhf",
        "에스에이치",
        "휴먼시아",
    )
    return (
        any(marker in key for marker in rental_markers)
        or any(marker in key for marker in public_housing_markers)
    )


def _int_value(value):
    try:
        return int(str(value or "").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def _region_city(row):
    province = _clean_entity_name(row.get("시도"))
    district = _clean_entity_name(row.get("시군구") or row.get("자치구"))
    if province == "서울특별시":
        return "서울시"
    if district.endswith(("시", "군")):
        return district
    for city in ("성남", "수원", "용인", "고양", "안양", "안산", "부천"):
        if district.startswith(city):
            return f"{city}시"
    return district


def _has_building_dong_suffix(name):
    value = _clean_entity_name(name)
    return bool(re.search(r"(?:\(\s*\d+\s*동\s*\)|\d+\s*동)$", value))


def _strip_building_dong_suffix(name):
    value = _clean_entity_name(name)
    value = re.sub(r"\s*\(\s*아파트\s*\)", "", value)
    value = re.sub(r"\s*\(\s*\d+\s*동\s*\)\s*$", "", value)
    value = re.sub(r"\s*\d+\s*동\s*$", "", value)
    return value.strip()


def _apartment_display_name(row):
    name = _clean_entity_name(row.get("대표단지명") or row.get("단지명_도로명주소") or row.get("단지명_건축물대장") or row.get("단지명_공시가격"))
    official = _clean_entity_name(row.get("단지명_공시가격"))
    building_name = _clean_entity_name(row.get("단지명_건축물대장"))
    if _has_building_dong_suffix(name):
        for candidate in (building_name, official, _strip_building_dong_suffix(name)):
            if _is_usable_apartment_name(candidate) and not _has_building_dong_suffix(candidate):
                return candidate
    if name.endswith("아파트") and _is_usable_apartment_name(official):
        official_key = compact(official)
        name_key = compact(name)
        if name_key.startswith(official_key) and len(official_key) < len(name_key):
            return official
    return _strip_building_dong_suffix(name)


def _numbered_complex_base(name):
    match = re.match(r"^(.+?)\s*\d+\s*단지$", _clean_entity_name(name))
    if not match:
        return ""
    base = _clean_entity_name(match.group(1))
    return base if _is_usable_apartment_name(base) else ""


def _legal_dong_aliases(row):
    legal_dong = _clean_entity_name(row.get("법정동"))
    if not legal_dong:
        return []
    aliases = [legal_dong]
    shortened = re.sub(r"동\d+가$", "동", legal_dong)
    if shortened != legal_dong:
        aliases.append(shortened)
    return aliases


def _legal_dong_stems(dong):
    key = compact(dong)
    stems = {key}
    shortened = re.sub(r"동\d+가$", "동", key)
    stems.add(shortened)
    if key.endswith("동"):
        stems.add(key[:-1])
    if shortened.endswith("동"):
        stems.add(shortened[:-1])
    return {stem for stem in stems if stem}


def _is_redundant_generic_alias(name, alias):
    name_key = compact(name)
    alias_key = compact(alias)
    return len(name_key) <= 2 and alias_key == f"{name_key}아파트"


def _local_apartment_aliases(row, names):
    aliases = []
    seen = set()
    for dong in _legal_dong_aliases(row):
        dong_stems = _legal_dong_stems(dong)
        for name in names:
            clean_name = _clean_entity_name(name)
            if not _is_usable_apartment_name(clean_name):
                continue
            name_key = compact(clean_name)
            if any(name_key.startswith(stem) for stem in dong_stems):
                continue
            short_name = re.sub(r"\s*(?:아파트|단지)\s*$", "", clean_name).strip()
            candidates = [
                f"{dong} {clean_name}",
                f"{dong} {short_name}",
            ]
            for candidate in candidates:
                key = compact(candidate)
                if len(key) >= 4 and key not in seen:
                    seen.add(key)
                    aliases.append(candidate)
    return aliases


def _load_apartment_csv_entities(limit=None):
    entities = []
    numbered_groups = {}
    for path in APARTMENT_CSV_PATHS:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("단지종류명") and row.get("단지종류명") != "아파트":
                    continue
                if _is_rental_row(row):
                    continue
                name = _apartment_display_name(row)
                if not _is_usable_apartment_name(name):
                    continue
                aliases = []
                for column in ("단지명_공시가격", "단지명_건축물대장", "단지명_도로명주소"):
                    alias = _clean_entity_name(row.get(column))
                    if (
                        _is_usable_apartment_name(alias)
                        and compact(alias) != compact(name)
                        and not _is_redundant_generic_alias(name, alias)
                    ):
                        aliases.append(alias)
                for alias in re.split(r"[|,]", row.get("별칭") or row.get("aliases") or ""):
                    alias = _clean_entity_name(alias)
                    if (
                        _is_usable_apartment_name(alias)
                        and compact(alias) != compact(name)
                        and not _is_redundant_generic_alias(name, alias)
                    ):
                        aliases.append(alias)
                aliases.extend(_local_apartment_aliases(row, [name, *aliases]))
                district = row.get("자치구") or row.get("시군구") or ""
                legal_dong = _clean_entity_name(row.get("법정동"))
                pnu = re.sub(r"\D", "", str(row.get("필지고유번호") or ""))
                cortar_no = pnu[:10] if len(pnu) >= 10 else ""
                entities.append({
                    "name": name,
                    "category": f"{district} 아파트".strip(),
                    "aliases": aliases,
                    "province": row.get("시도") or "",
                    "city": _region_city(row),
                    "district": district,
                    "legalDong": legal_dong,
                    "jibun": str(row.get("지번") or "").strip(),
                    "cortarNo": cortar_no,
                    "address": str(row.get("주소") or "").strip(),
                    "dedupeKey": "|".join(compact(value) for value in (
                        name,
                        row.get("시도") or "",
                        district,
                        row.get("법정동") or "",
                    )),
                    "households": _int_value(row.get("세대수")),
                    "approvedAt": str(row.get("사용승인일") or "").strip(),
                    "lawdCd": str(row.get("법정동코드") or row.get("lawdCd") or "").strip(),
                    "status": str(row.get("상태") or "").strip(),
                })
                base = _numbered_complex_base(name)
                if base:
                    group = numbered_groups.setdefault(compact(base), {
                        "name": base,
                        "category": f"{district} 아파트".strip(),
                        "aggregate": True,
                        "aliases": [],
                        "province": row.get("시도") or "",
                        "city": _region_city(row),
                        "district": district,
                        "legalDong": legal_dong,
                        "jibun": str(row.get("지번") or "").strip(),
                        "cortarNo": cortar_no,
                        "address": str(row.get("주소") or "").strip(),
                        "households": 0,
                        "approvedAt": str(row.get("사용승인일") or "").strip(),
                        "lawdCd": str(row.get("법정동코드") or row.get("lawdCd") or "").strip(),
                        "status": str(row.get("상태") or "").strip(),
                    })
                    group["aliases"].extend([name, *aliases])
                    group["households"] += _int_value(row.get("세대수"))
                    approved_at = str(row.get("사용승인일") or "").strip()
                    if approved_at and (not group["approvedAt"] or approved_at < group["approvedAt"]):
                        group["approvedAt"] = approved_at
                if limit and len(entities) >= limit:
                    return _merge_entities(entities, numbered_groups.values())
    return _merge_entities(entities, numbered_groups.values())


def _merge_entities(*groups):
    merged = {}
    for group in groups:
        for entity in group:
            key = entity.get("dedupeKey") or compact(entity.get("name", ""))
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    "name": entity["name"],
                    "category": entity.get("category", ""),
                    "aliases": [],
                    "province": entity.get("province", ""),
                    "city": entity.get("city", ""),
                    "district": entity.get("district", ""),
                    "legalDong": entity.get("legalDong", ""),
                    "jibun": entity.get("jibun", ""),
                    "cortarNo": entity.get("cortarNo", ""),
                    "address": entity.get("address", ""),
                    "dedupeKey": entity.get("dedupeKey", ""),
                    "households": _int_value(entity.get("households")),
                    "approvedAt": entity.get("approvedAt", ""),
                    "aggregate": bool(entity.get("aggregate")),
                    "lawdCd": entity.get("lawdCd", ""),
                    "status": entity.get("status", ""),
                }
            else:
                for field in ("province", "city", "district", "legalDong", "jibun", "cortarNo", "address", "lawdCd", "status"):
                    if entity.get(field) and not merged[key].get(field):
                        merged[key][field] = entity.get(field)
                merged[key]["aggregate"] = bool(merged[key].get("aggregate") or entity.get("aggregate"))
                merged[key]["households"] = max(
                    _int_value(merged[key].get("households")),
                    _int_value(entity.get("households")),
                )
                candidate_date = str(entity.get("approvedAt") or "")
                current_date = str(merged[key].get("approvedAt") or "")
                if candidate_date and (not current_date or candidate_date < current_date):
                    merged[key]["approvedAt"] = candidate_date
            aliases = [*merged[key].get("aliases", []), *(entity.get("aliases") or [])]
            seen = {compact(merged[key]["name"])}
            deduped = []
            for alias in aliases:
                alias_key = compact(alias)
                if len(alias_key) >= 2 and alias_key not in seen:
                    seen.add(alias_key)
                    deduped.append(alias)
            merged[key]["aliases"] = deduped
    return list(merged.values())


APARTMENT_MASTER = _merge_entities(MANUAL_APARTMENT_MASTER, _load_apartment_csv_entities())
APARTMENT_RANK_MASTER = MANUAL_APARTMENT_MASTER


def _region_search_entities():
    rows = []
    seen = set()
    for entity in APARTMENT_MASTER:
        for field in ("city", "district", "legalDong"):
            name = _clean_entity_name(entity.get(field))
            key = compact(name)
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            rows.append({
                "name": name,
                "category": "지역",
                "aliases": [name],
            })
    rows.sort(key=lambda row: (0 if row["name"].endswith(("구", "시", "군")) else 1, row["name"]))
    return rows


REGION_SEARCH_MASTER = _region_search_entities()

_GENERIC_APARTMENT_NAME_PARTS = (
    "주공",
    "현대",
    "삼성",
    "대림",
    "한신",
    "우성",
    "벽산",
    "동아",
    "대우",
    "롯데",
    "한양",
    "극동",
    "태영",
    "신동아",
    "쌍용",
    "두산",
    "동부",
    "효성",
    "럭키",
    "건영",
    "휴먼시아",
)


def _entity_aliases(entity):
    values = [entity["name"], *(entity.get("aliases") or []), *(entity.get("keywords") or [])]
    seen = set()
    out = []
    for value in values:
        key = compact(value)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _relaxed_alias_variants(alias):
    value = _clean_entity_name(alias)
    if not value:
        return []
    variants = []
    without_generic = re.sub(r"\s*(?:아파트|단지)\s*$", "", value).strip()
    if without_generic and without_generic != value:
        variants.append(without_generic)
    compacted = compact(without_generic or value)
    if len(compacted) >= 4:
        variants.append(compacted)
    without_dong = re.sub(r"동(?=[가-힣A-Za-z0-9]+$)", "", compacted)
    if len(without_dong) >= 4 and without_dong != compacted:
        variants.append(without_dong)
    return variants


def _is_ordered_subsequence(needle, haystack):
    if len(needle) < 4 or len(haystack) < len(needle):
        return False
    pos = 0
    for char in haystack:
        if pos < len(needle) and needle[pos] == char:
            pos += 1
    return pos == len(needle)


def _alias_match_score(query_key, alias_key):
    if not query_key or not alias_key:
        return None
    if alias_key == query_key:
        return 0
    if alias_key.startswith(query_key):
        return 20
    if query_key in alias_key:
        return 50
    if _is_ordered_subsequence(query_key, alias_key):
        return 80
    return None


def _search_entities():
    return [*REGION_SEARCH_MASTER, *ENTITY_MASTER, *APARTMENT_MASTER]


def query_aliases(query):
    query = query.strip()
    if not query:
        return []
    key = compact(query)
    aliases = [query]
    fuzzy_match = None
    for entity in _search_entities():
        names = _entity_aliases(entity)
        if key in {compact(name) for name in names}:
            aliases = [query, *names]
            break
        scores = [
            score
            for score in (_alias_match_score(key, compact(name)) for name in names)
            if score is not None
        ]
        if scores:
            score = min(scores)
            fuzzy_match = min(fuzzy_match or (score, names), (score, names), key=lambda item: item[0])
    else:
        if fuzzy_match:
            aliases = [query, *fuzzy_match[1]]
    aliases = [
        variant
        for alias in aliases
        for variant in [alias, *_relaxed_alias_variants(alias)]
    ]
    seen = set()
    seen_indexes = {}
    out = []
    for alias in aliases:
        alias_key = compact(alias)
        if len(alias_key) < 2:
            continue
        if alias_key != key and len(alias_key) < 3:
            continue
        if alias_key in seen:
            index = seen_indexes[alias_key]
            if " " in str(alias) and " " not in str(out[index]):
                out[index] = alias
            continue
        seen.add(alias_key)
        seen_indexes[alias_key] = len(out)
        out.append(alias)
    return out


def _fallback_search_terms(query, aliases):
    terms = []
    seen = set()
    for term in [query, *aliases]:
        value = _clean_entity_name(term)
        key = compact(value)
        if len(key) < 4 or key in seen:
            continue
        seen.add(key)
        terms.append(value)
        if len(terms) >= 4:
            break
    return terms or [query.strip()]


_UNIT_ALIAS_RE = re.compile(r"\d+\s*단지")


def _unit_alias_display(alias):
    return re.sub(r"\s+", " ", re.sub(r"[()]", " ", str(alias or ""))).strip()


def suggest_apartments(query, limit=8):
    """단지 자동완성. 묶음(aggregate)이 아닌 개별 단지만 주소와 함께 반환한다.

    '한솔주공' 같은 축약 검색어도 순서 유지 부분 일치로 개별 단지에 매칭한다.
    로딩 시 이름 정규화로 별칭에 흡수된 'N단지' 개별 단지(예:
    '한솔마을(4단지)(주공)')는 검색 단위로 되살려 따로 보여준다.
    세대수 큰 단지를 먼저 보여준다.
    """
    key = compact(query)
    if not key or len(key) < 2:
        return []
    rows = []
    for order, entity in enumerate(APARTMENT_MASTER):
        if entity.get("aggregate"):
            continue
        aliases = entity.get("aliases") or []
        unit_aliases = []
        base_aliases = []
        seen_units = set()
        for alias in aliases:
            if _UNIT_ALIAS_RE.search(str(alias or "")):
                unit_key = compact(alias)
                if unit_key and unit_key not in seen_units:
                    seen_units.add(unit_key)
                    unit_aliases.append(alias)
            else:
                base_aliases.append(alias)
        unit_matches = [
            (score, alias)
            for alias in unit_aliases
            for score in [_alias_match_score(key, compact(alias))]
            if score is not None
        ]
        base_best = None
        for alias in [entity.get("name", ""), *base_aliases]:
            score = _alias_match_score(key, compact(alias))
            if score is not None:
                base_best = score if base_best is None else min(base_best, score)
                if base_best == 0:
                    break
        if unit_matches:
            # 개별 단지가 검색어에 맞으면 묶인 대표 이름 대신 단지별로 보여준다.
            for score, alias in unit_matches:
                virtual = dict(entity)
                virtual["name"] = _unit_alias_display(alias)
                virtual["households"] = 0  # 병합 합계 세대수를 개별 단지에 붙이지 않는다
                virtual["aliases"] = [alias]
                rows.append((score, 0, order, virtual))
            continue
        if base_best is not None and unit_aliases:
            # '상계주공아파트'처럼 묶인 대표 이름으로 검색해도 개별 단지로 펼친다.
            for alias in unit_aliases:
                virtual = dict(entity)
                virtual["name"] = _unit_alias_display(alias)
                virtual["households"] = 0
                virtual["aliases"] = [alias]
                rows.append((base_best, 0, order, virtual))
            continue
        if base_best is None:
            continue
        rows.append((base_best, -_int_value(entity.get("households")), order, entity))
    rows.sort(key=lambda row: row[:3])

    # 같은 단지가 마스터 CSV·수동 등록마다 다른 표기(자치구 vs 법정동, 세대수
    # 개정, 필드 공백)로 등재된 중복을 병합한다. 이름이 같고 시도·시·법정동이
    # 서로 충돌하지 않으면(비어 있으면 호환) 같은 단지로 본다. 세대수는 둘 다
    # 있고 30% 넘게 차이날 때만 다른 단지로 판정한다.
    def _cluster_compatible(entity, cluster):
        for field in ("province", "city", "legalDong"):
            value_a = compact(entity.get(field, ""))
            value_b = compact(cluster.get(field, ""))
            if value_a and value_b and value_a != value_b:
                return False
        households_a = _int_value(entity.get("households"))
        households_b = _int_value(cluster.get("households"))
        if households_a and households_b:
            larger = max(households_a, households_b)
            if (larger - min(households_a, households_b)) / larger > 0.3:
                return False
        return True

    clusters = []
    buckets = {}
    for _best, _households, _order, entity in rows:
        name_key = compact(entity.get("name", ""))
        bucket = buckets.setdefault(name_key, [])
        target = next((cluster for cluster in bucket if _cluster_compatible(entity, cluster)), None)
        if target is None:
            cluster = dict(entity)
            bucket.append(cluster)
            clusters.append(cluster)
            continue
        for field in (
            "province",
            "city",
            "district",
            "legalDong",
            "jibun",
            "cortarNo",
            "lawdCd",
            "address",
            "status",
        ):
            if not str(target.get(field) or "").strip() and str(entity.get(field) or "").strip():
                target[field] = entity[field]
        target["households"] = max(
            _int_value(target.get("households")), _int_value(entity.get("households")),
        )

    suggestions = []
    for entity in clusters[:limit * 3]:
        city = str(entity.get("city") or "").strip()
        district = str(entity.get("district") or "").strip()
        # '성남수정구'처럼 시 이름이 접두사로 붙은 자치구 표기는 '수정구'로 정리한다.
        # 남는 부분이 구/군으로 끝나는 두 글자 이상일 때만 잘라 '군포시'→'시' 오류를 막는다.
        city_stem = re.sub(r"시$", "", city)
        district_display = district
        if city_stem and district.startswith(city_stem):
            remainder = district[len(city_stem):]
            if len(remainder) >= 2 and re.search(r"[구군]$", remainder):
                district_display = remainder
        address_parts = []
        stripped_parts = []
        for part in (entity.get("province"), city, district_display, entity.get("legalDong")):
            part = str(part or "").strip()
            if not part:
                continue
            # '서울특별시'와 '서울시'처럼 접미사만 다른 중복 표기를 제거한다.
            stripped = re.sub(r"(특별자치시|특별자치도|특별시|광역시|시|도|구|군|동)$", "", part)
            if stripped and stripped in stripped_parts:
                continue
            address_parts.append(part)
            stripped_parts.append(stripped)
        suggestions.append({
            "name": entity.get("name", ""),
            # 일부 공공 원본은 자치구가 비어 있고 시·법정동만 있다. 검색 결과가
            # 빈 지역으로 넘어가면 전용면적 API가 단지를 식별하지 못하므로 가장
            # 구체적으로 남아 있는 지역값을 순서대로 사용한다.
            "region": district or city or str(entity.get("legalDong") or "").strip(),
            "address": " ".join(address_parts) or str(entity.get("address") or "").strip(),
            "legalDong": str(entity.get("legalDong") or "").strip(),
            "jibun": str(entity.get("jibun") or "").strip(),
            "cortarNo": str(entity.get("cortarNo") or "").strip(),
            "lawdCd": str(entity.get("lawdCd") or "").strip(),
            "households": _int_value(entity.get("households")),
            "status": str(entity.get("status") or "").strip(),
            "category": "아파트",
        })
    # 주소 없는 항목이 주소 있는 동명 단지와 겹치면 중복이므로 제거한다.
    named_with_address = {compact(item["name"]) for item in suggestions if item["address"]}
    suggestions = [
        item for item in suggestions
        if item["address"] or compact(item["name"]) not in named_with_address
    ]
    # '상계주공아파트'처럼 단지 번호 없는 묶음 이름은, 같은 지역에 번호 붙은
    # 형제 단지가 2곳 이상 함께 검색되면 숨긴다. 묶음 이름의 결과값은 여러
    # 단지 실거래가 섞여 단지별 리포트와 1:1이 되지 않기 때문이다.
    def _base_stem(value):
        return re.sub(r"(아파트|단지)+$", "", compact(value))

    def _has_unit_number(value):
        return bool(re.search(r"\d+\s*단지", str(value or "")) or _UNIT_ALIAS_RE.search(str(value or "")))

    filtered = []
    for item in suggestions:
        if not _has_unit_number(item["name"]):
            stem = _base_stem(item["name"])
            siblings = [
                other for other in suggestions
                if other is not item
                and _has_unit_number(other["name"])
                and other["region"] == item["region"]
                and stem and compact(other["name"]).startswith(stem)
            ]
            if len(siblings) >= 2:
                continue
        filtered.append(item)
    return filtered[:limit]


def suggest_entities(query, limit=12):
    key = compact(query)
    if not key:
        return []
    suggestions = []
    covered = set()
    split_query = _split_region_apartment_query(query)
    if split_query:
        search_region, apartment_key = split_query
        scoped_apartments = [
            entity for entity in APARTMENT_MASTER
            if _entity_matches_region(entity, search_region) and _apartment_matches_query_key(entity, apartment_key)
        ]
        scoped_apartments.sort(key=lambda entity: -_int_value(entity.get("households")))
        for entity in scoped_apartments:
            name = _region_apartment_search_query(entity, search_region)
            name_key = compact(name)
            if not name_key or name_key in covered:
                continue
            suggestions.append({
                "name": name,
                "category": entity.get("category", "아파트"),
                "matched": query,
                "aliases": _entity_aliases(entity),
            })
            covered.add(name_key)
            if len(suggestions) >= limit:
                return suggestions
    rows = []
    for order, entity in enumerate(_search_entities()):
        matched = None
        for alias in _entity_aliases(entity):
            alias_key = compact(alias)
            score = _alias_match_score(key, alias_key)
            if score is None:
                continue
            matched = min(matched or (score, alias), (score, alias))
            if score == 0:
                break
        if matched:
            rows.append((matched[0], order, {
                "name": entity["name"],
                "category": entity.get("category", ""),
                "matched": matched[1],
                "aliases": _entity_aliases(entity),
            }))
    rows.sort(key=lambda row: (row[0], row[1]))
    for _, _, suggestion in rows:
        name_key = compact(suggestion["name"])
        if name_key in covered:
            continue
        suggestions.append(suggestion)
        covered.update(compact(alias) for alias in suggestion.get("aliases") or [])
        if len(suggestions) >= limit:
            break
    return suggestions


def _parse_index_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _popular_alias_index(entities):
    cache_key = "apartments" if entities is APARTMENT_MASTER else "all"
    if cache_key in _POPULAR_ALIAS_INDEX_CACHE:
        return _POPULAR_ALIAS_INDEX_CACHE[cache_key]
    alias_to_orders = {}
    for order, entity in enumerate(entities):
        aliases = [compact(alias) for alias in [entity["name"], *(entity.get("aliases") or [])]]
        aliases = [alias for alias in aliases if len(alias) >= 2]
        for alias in aliases:
            alias_to_orders.setdefault(alias, set()).add(order)
    pattern = None
    if alias_to_orders:
        terms = sorted(alias_to_orders.keys(), key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(term) for term in terms))
    indexed = (pattern, {alias: tuple(orders) for alias, orders in alias_to_orders.items()})
    _POPULAR_ALIAS_INDEX_CACHE[cache_key] = indexed
    return indexed


def _popular_rows_regex(entities, videos, limit=10):
    pattern, alias_to_orders = _popular_alias_index(entities)
    if not pattern:
        return []
    stats = {}
    for video in videos:
        text = video.get("searchText") or _index_search_text(video.get("title", ""), "")
        video_orders = set()
        for match in pattern.finditer(text):
            for order in alias_to_orders.get(match.group(0), ()):
                row = stats.setdefault(order, {"mentionVideos": 0, "occurrences": 0})
                row["occurrences"] += 1
                video_orders.add(order)
        for order in video_orders:
            stats[order]["mentionVideos"] += 1
    rows = []
    for order, stat in stats.items():
        entity = entities[order]
        rows.append((
            -stat["mentionVideos"],
            -stat["occurrences"],
            order,
            {
                "name": entity["name"],
                "category": entity["category"],
                "mentionCount": stat["mentionVideos"],
                "occurrenceCount": stat["occurrences"],
                "lookbackDays": config.POPULAR_CHIPS_LOOKBACK_DAYS,
            },
        ))
    rows.sort()
    return rows


def _popular_rows(entities, limit=10):
    cutoff = datetime.datetime.now(KST) - datetime.timedelta(days=config.POPULAR_CHIPS_LOOKBACK_DAYS)
    videos = []
    for video in load_index().get("videos", []):
        published_at = _parse_index_datetime(video.get("publishedAt"))
        if published_at and published_at < cutoff:
            continue
        videos.append(video)
    if len(entities) > 400:
        return _popular_rows_regex(entities, videos, limit=limit)
    rows = []
    for order, entity in enumerate(entities):
        aliases = [compact(alias) for alias in [entity["name"], *(entity.get("aliases") or [])]]
        aliases = [alias for alias in aliases if len(alias) >= 2]
        mention_videos = 0
        occurrence_count = 0
        for video in videos:
            text = video.get("searchText") or _index_search_text(video.get("title", ""), "")
            count = sum(text.count(alias) for alias in aliases)
            if count:
                mention_videos += 1
                occurrence_count += count
        if mention_videos:
            rows.append((
                -mention_videos,
                -occurrence_count,
                order,
                {
                    "name": entity["name"],
                    "category": entity["category"],
                    "mentionCount": mention_videos,
                    "occurrenceCount": occurrence_count,
                    "lookbackDays": config.POPULAR_CHIPS_LOOKBACK_DAYS,
                },
            ))
    rows.sort()
    return rows


def popular_chips(limit=10, kind="all"):
    entities = APARTMENT_RANK_MASTER if kind == "apartments" else ENTITY_MASTER
    rows = _popular_rows(entities, limit=limit)
    if not rows:
        return [
            {"name": entity["name"], "category": entity["category"], "mentionCount": 0}
            for entity in entities[:limit]
        ]
    return [row[3] for row in rows[:limit]]


def _entity_matches_region(entity, region):
    key = compact(region)
    if not key:
        return False
    candidates = [
        entity.get("province", ""),
        entity.get("city", ""),
        entity.get("district", ""),
        entity.get("legalDong", ""),
        entity.get("category", "").replace(" 아파트", ""),
        entity.get("name", ""),
        *(entity.get("aliases") or []),
    ]
    for candidate in candidates:
        candidate_key = compact(candidate)
        if not candidate_key:
            continue
        if candidate_key == key:
            return True
        if len(key) >= 2 and key in candidate_key:
            return True
    return False


def _display_subdistrict(city, district):
    district = str(district or "").strip()
    city = str(city or "").strip()
    if city and district.startswith(city):
        district = district[len(city):]
    elif city.endswith("시") and district.startswith(city[:-1]):
        district = district[len(city[:-1]):]
    return district or city


def _region_parent_city(region):
    region_key = compact(region)
    for entity in APARTMENT_MASTER:
        city = entity.get("city", "")
        if compact(city) == region_key:
            return city
    for entity in APARTMENT_MASTER:
        if compact(entity.get("district", "")) == region_key:
            return entity.get("city", "")
    for entity in APARTMENT_MASTER:
        if compact(entity.get("legalDong", "")) == region_key:
            return entity.get("city", "")
    return ""


def region_display_name(region):
    region_key = compact(region)
    for entity in APARTMENT_MASTER:
        if compact(entity.get("district", "")) == region_key:
            return _display_subdistrict(entity.get("city", ""), entity.get("district", ""))
    for entity in APARTMENT_MASTER:
        if compact(entity.get("legalDong", "")) == region_key:
            return entity.get("legalDong", "")
    return region


def region_subdistricts(region):
    parent_city = _region_parent_city(region) or region
    region_key = compact(parent_city)
    active_key = compact(region)
    rows = []
    seen = set()
    for entity in APARTMENT_MASTER:
        if compact(entity.get("city", "")) != region_key:
            continue
        district = entity.get("district", "")
        label = _display_subdistrict(entity.get("city", ""), district)
        if not label or compact(label) == region_key or compact(label) in seen:
            continue
        seen.add(compact(label))
        rows.append({
            "label": label,
            "query": district,
            "active": compact(district) == active_key,
        })
    rows.sort(key=lambda row: row["label"])
    return rows


def _region_key_variants(region_entity):
    variants = set()
    for alias in _entity_aliases(region_entity):
        key = compact(alias)
        if len(key) < 2:
            continue
        variants.add(key)
        if key.endswith(("시", "구", "군", "동")) and len(key) > 2:
            variants.add(key[:-1])
    return sorted(variants, key=len, reverse=True)


def _split_region_apartment_query(query):
    query_key = compact(query)
    if len(query_key) < 4:
        return None
    matches = []
    for region_entity in REGION_SEARCH_MASTER:
        for region_key in _region_key_variants(region_entity):
            position = query_key.find(region_key)
            if position < 0:
                continue
            apartment_key = query_key[:position] + query_key[position + len(region_key):]
            if len(apartment_key) < 2:
                continue
            region_level = 0 if region_entity["name"].endswith(("시", "구", "군")) else 1
            matches.append((
                -len(region_key),
                0 if position == 0 else 1,
                region_level,
                region_entity["name"],
                apartment_key,
            ))
    if not matches:
        return None
    matches.sort()
    return matches[0][3], matches[0][4]


def region_query_scope(query):
    split_query = _split_region_apartment_query(query)
    if split_query:
        return split_query[0]
    return query


def _apartment_alias_keys(entity):
    keys = set()
    for alias in _entity_aliases(entity):
        key = compact(alias)
        if len(key) < 2 or key in {"아파트", "단지"}:
            continue
        keys.add(key)
        stripped = re.sub(r"(?:아파트|단지)$", "", key)
        if len(stripped) >= 2:
            keys.add(stripped)
    return keys


def _apartment_matches_query_key(entity, query_key):
    if not query_key:
        return True
    query_variants = {query_key}
    stripped = re.sub(r"(?:아파트|단지)$", "", query_key)
    if len(stripped) >= 2:
        query_variants.add(stripped)
    for key in _apartment_alias_keys(entity):
        for variant in query_variants:
            if key == variant:
                return True
            if len(variant) >= 2 and variant in key:
                return True
            if len(key) >= 3 and key not in {"아파트", "단지"} and key in variant:
                return True
    return False


def _is_ambiguous_apartment_name(name):
    key = compact(name)
    if not key:
        return False
    if key in _AMBIGUOUS_APARTMENT_NAME_CACHE:
        return _AMBIGUOUS_APARTMENT_NAME_CACHE[key]
    generic = (
        key.endswith("아파트") and len(key) <= 7
    ) or any(part in key and len(key) <= 8 for part in _GENERIC_APARTMENT_NAME_PARTS)
    locations = set()
    if not generic:
        for entity in APARTMENT_MASTER:
            if compact(entity.get("name", "")) != key:
                continue
            locations.add((
                compact(entity.get("city", "")),
                compact(entity.get("district", "")),
                compact(entity.get("legalDong", "")),
            ))
            if len(locations) > 1:
                generic = True
                break
    _AMBIGUOUS_APARTMENT_NAME_CACHE[key] = generic
    return generic


def _region_search_scope(entity, region):
    legal_dong = entity.get("legalDong", "")
    if legal_dong:
        return legal_dong
    region_key = compact(region)
    district = entity.get("district", "")
    city = entity.get("city", "")
    if district and compact(district) != region_key:
        return district
    if city:
        return city
    return region


def _region_apartment_search_query(entity, region):
    region_key = compact(region)
    aliases = _entity_aliases(entity)
    region_matches = [
        alias for alias in aliases
        if region_key and region_key in compact(alias) and compact(alias) != region_key
    ]
    if region_matches:
        return min(region_matches, key=lambda alias: (len(compact(alias)), " " not in alias))

    legal_dong = entity.get("legalDong", "")
    legal_stems = _legal_dong_stems(legal_dong) if legal_dong else set()
    local_matches = [
        alias for alias in aliases
        if any(stem in compact(alias) for stem in legal_stems)
    ]
    if local_matches:
        return min(local_matches, key=lambda alias: (len(compact(alias)), " " not in alias))

    name = entity["name"]
    if len(compact(name)) <= 2 or _is_ambiguous_apartment_name(name):
        scope = _region_search_scope(entity, region)
        if scope and compact(scope) not in compact(name):
            return f"{scope} {name}"
    return name


def region_apartments(region, limit=20):
    split_query = _split_region_apartment_query(region)
    search_region, apartment_key = split_query if split_query else (region, "")
    entities = [entity for entity in APARTMENT_MASTER if _entity_matches_region(entity, search_region)]
    if apartment_key:
        entities = [entity for entity in entities if _apartment_matches_query_key(entity, apartment_key)]
    ranked = []
    for order, entity in enumerate(entities):
        households = _int_value(entity.get("households"))
        if households <= 0:
            continue
        ranked.append((
            -households,
            order,
            {
                "name": entity["name"],
                "category": entity.get("category", "아파트"),
                "mentionCount": 0,
                "occurrenceCount": 0,
                "households": households,
                "city": entity.get("city", ""),
                "district": entity.get("district", ""),
                "legalDong": entity.get("legalDong", ""),
                "searchQuery": _region_apartment_search_query(entity, search_region),
            },
            {compact(entity["name"]), *(compact(alias) for alias in entity.get("aliases") or [])},
        ))
    ranked.sort()
    rows = []
    covered = set()
    for _, _, item, alias_keys in ranked:
        if compact(item["name"]) in covered:
            continue
        rows.append(item)
        covered.update(key for key in alias_keys if key)
        if len(rows) >= limit:
            break
    return rows


def _remote_path(name):
    return f"{REMOTE_PREFIX}/{name}"


def _sync_remote_index_if_needed(force=False):
    global _REMOTE_INDEX_CHECKED_AT
    now = time.monotonic()
    if not force and now - _REMOTE_INDEX_CHECKED_AT < _REMOTE_INDEX_CHECK_INTERVAL_SECONDS:
        return
    _REMOTE_INDEX_CHECKED_AT = now
    remote_index = remote_cache.download_json(_remote_path("search_index.json"))
    if not remote_index:
        return
    local_updated = None
    if config.SEARCH_INDEX_JSON.exists():
        try:
            local_updated = json.loads(config.SEARCH_INDEX_JSON.read_text(encoding="utf-8")).get("updatedAt")
        except (OSError, ValueError):
            local_updated = None
    if remote_index.get("updatedAt") and remote_index.get("updatedAt") > str(local_updated or ""):
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config.SEARCH_INDEX_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(remote_index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(config.SEARCH_INDEX_JSON)


def load_index():
    _sync_remote_index_if_needed()
    if not config.SEARCH_INDEX_JSON.exists():
        return {"version": _INDEX_VERSION, "updatedAt": None, "videos": []}
    try:
        return json.loads(config.SEARCH_INDEX_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": _INDEX_VERSION, "updatedAt": None, "videos": []}


def save_index(videos):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _INDEX_VERSION,
        "updatedAt": datetime.datetime.now(KST).isoformat(),
        "lookbackDays": config.SEARCH_LOOKBACK_DAYS,
        "maxVideosPerChannel": config.SEARCH_MAX_VIDEOS_PER_CHANNEL,
        "videos": videos,
    }
    tmp = config.SEARCH_INDEX_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config.SEARCH_INDEX_JSON)
    remote_cache.upload_json(_remote_path("search_index.json"), payload)
    return payload


def _index_search_text(title, transcript):
    return compact(f"{title or ''} {transcript or ''}")


def sync_index(channels=None):
    channels = channels if channels is not None else config.ready_channels()
    videos = []
    for channel in channels:
        try:
            recent = youtube.recent_uploads(
                channel,
                lookback_days=config.SEARCH_LOOKBACK_DAYS,
                max_results=max(12, config.SEARCH_MAX_VIDEOS_PER_CHANNEL),
            )[:config.SEARCH_MAX_VIDEOS_PER_CHANNEL]
        except Exception as exc:
            print(f"  - {channel['name']}: {str(exc)[:100]}")
            continue
        print(f"  - {channel['name']}: 후보 {len(recent)}개")
        for video in recent:
            text = youtube.fetch_transcript(video["videoId"])
            videos.append(_index_video_row(video, text=text, channel_type=channel.get("type")))
    videos.sort(key=lambda row: (row["publishedAt"], row.get("transcriptStatus") == "ok"), reverse=True)
    payload = save_index(videos)
    print(f"검색 인덱스 생성: 영상 {len(videos)}개 · 최근 {config.SEARCH_LOOKBACK_DAYS}일")
    return payload


def _index_video_row(video, text="", channel_type=None, fallback=False):
    published_at = video["publishedAt"].isoformat() if hasattr(video.get("publishedAt"), "isoformat") else (video.get("publishedAt") or "")
    return {
        "videoId": video["videoId"],
        "channel": video.get("channel", ""),
        "channelId": video.get("channelId", ""),
        "channelType": channel_type,
        "categories": video.get("categories") or [],
        "title": video.get("title", ""),
        "publishedAt": published_at,
        "publishedText": video.get("publishedText", ""),
        "publishedAgeMonths": video.get("publishedAgeMonths"),
        "views": int(video.get("views") or 0),
        "durationSec": int(video.get("durationSec") or 0),
        "url": video.get("url") or f"https://www.youtube.com/watch?v={video['videoId']}",
        "titleSearchText": compact(video.get("title", "")),
        "searchText": _index_search_text(video.get("title", ""), text),
        "transcriptChars": len(text or ""),
        "transcriptStatus": "ok" if text else "missing",
        "transcriptError": "" if text else (youtube.LAST_TRANSCRIPT_ERROR or ""),
        "fallback": fallback,
    }


def transcript_text(video_id):
    path = config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json"
    if not path.exists():
        remote_cache.download_to_file(f"transcripts/{video_id}.json", path)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return data.get("text", "") if data.get("status") == "ok" else ""


def transcript_segments(video_id):
    path = config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json"
    if not path.exists():
        remote_cache.download_to_file(f"transcripts/{video_id}.json", path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data.get("segments", []) if data.get("status") == "ok" else []


def match_count(text, aliases):
    normalized = compact(text)
    count = 0
    for alias in aliases:
        key = compact(alias)
        if len(key) >= 2:
            count += normalized.count(key)
    return count


def extract_context(text, aliases):
    window = config.SEARCH_CONTEXT_WINDOW
    max_chars = config.SEARCH_CONTEXT_MAX_CHARS
    max_spans = config.SEARCH_CONTEXT_MAX_SPANS
    lowered = text.lower()
    spans = []
    for alias in aliases:
        needle = str(alias).lower().strip()
        if not needle:
            continue
        start = 0
        while len(spans) < max_spans:
            at = lowered.find(needle, start)
            if at < 0:
                break
            spans.append((max(0, at - window), min(len(text), at + len(needle) + window)))
            start = at + len(needle)
    if not spans:
        return text[:max_chars]
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return "\n\n[...중략...]\n\n".join(text[start:end] for start, end in merged)[:max_chars]


def _video_match_row(video, aliases):
    text = None
    search_text = video.get("searchText")
    if search_text is None:
        text = transcript_text(video["videoId"])
        search_text = _index_search_text(video.get("title", ""), text)
    title_text = video.get("titleSearchText") or compact(video.get("title", ""))
    count = match_count(search_text, aliases)
    title_count = match_count(title_text, aliases)
    if count <= 0 and title_count <= 0:
        return None
    row = dict(video)
    if text is not None:
        row["_text"] = text
    row["matchCount"] = count
    row["titleMatch"] = bool(title_count)
    row["hasTranscriptText"] = video.get("transcriptStatus") == "ok" or bool((text or "").strip())
    return row


_NON_MARKET_TOPIC_TERMS = (
    "창호", "샷시", "새시", "윈도우", "시공", "인테리어", "리모델링 시공", "리모델링공사",
    "도배", "장판", "싱크대", "욕실", "가구", "가전", "자재", "제품", "견적", "공사",
    "홈씨씨", "kcc", "lx지인", "하우시스", "커튼", "블라인드", "타일", "필름",
)

_MARKET_OPINION_TERMS = (
    "시세", "전망", "가격", "매매", "거래", "실거래", "호가", "분양", "청약", "재건축",
    "재개발", "입지", "학군", "교통", "공급", "수요", "전세", "월세", "금리", "정책",
    "투자", "매수", "매도", "상승", "하락", "리스크", "저평가", "고평가", "호재",
    "악재", "거래량", "입주", "입주물량", "개발", "역세권",
)

_NO_OPINION_PHRASES = (
    "부동산 관련 의견은 제시하지",
    "부동산관련의견은제시하지",
    "아파트 단지 자체에 대한 부동산 관련 의견은",
    "제품을 소개",
    "제품의 특징과 장점",
    "시공된 창호",
)


def _has_any_term(text, terms):
    key = compact(text)
    return any(compact(term) in key for term in terms)


def _is_likely_non_market_video(video):
    text = " ".join(str(video.get(field, "") or "") for field in ("channel", "title"))
    return _has_any_term(text, _NON_MARKET_TOPIC_TERMS) and not _has_any_term(text, _MARKET_OPINION_TERMS)


def _fallback_queries(query, aliases=None):
    rows = []
    seen = set()
    for term in _fallback_search_terms(query, aliases or []):
        for suffix in ("부동산 아파트", "임장", "분양권", "매매", "시세"):
            value = f"{term} {suffix}"
            key = compact(value)
            if key not in seen:
                seen.add(key)
                rows.append(value)
    return rows


def _relative_published_at(text):
    now = datetime.datetime.now(KST)
    value = str(text or "")
    match = re.search(r"(\d+)\s*(분|시간|일|주|개월|년)\s*전", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "분":
        return now - datetime.timedelta(minutes=amount)
    if unit == "시간":
        return now - datetime.timedelta(hours=amount)
    if unit == "일":
        return now - datetime.timedelta(days=amount)
    if unit == "주":
        return now - datetime.timedelta(weeks=amount)
    if unit == "개월":
        return now - datetime.timedelta(days=amount * 30)
    if unit == "년":
        return now - datetime.timedelta(days=amount * 365)
    return now


def _relative_age_months(text):
    value = str(text or "")
    match = re.search(r"(\d+)\s*(분|시간|일|주|개월|년)\s*전", value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit in ("분", "시간", "일", "주"):
        return 0
    if unit == "개월":
        return amount
    if unit == "년":
        return amount * 12
    return None


def _view_count(text):
    value = str(text or "").replace(",", "")
    match = re.search(r"([\d.]+)\s*(만|천)?", value)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "만":
        number *= 10000
    elif unit == "천":
        number *= 1000
    return int(number)


def _youtube_web_search_videos(query, max_results=8, lookback_months=None):
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    match = re.search(r"var ytInitialData = (\{.*?\});</script>", response.text)
    if not match:
        return []
    data = json.loads(match.group(1))
    rows = []
    seen = set()

    def walk(value):
        if len(rows) >= max_results:
            return
        if isinstance(value, dict):
            renderer = value.get("videoRenderer")
            if renderer:
                video_id = renderer.get("videoId")
                title_runs = (renderer.get("title") or {}).get("runs") or []
                owner_runs = (renderer.get("ownerText") or {}).get("runs") or []
                title = "".join(run.get("text", "") for run in title_runs) or (renderer.get("title") or {}).get("simpleText") or ""
                channel = "".join(run.get("text", "") for run in owner_runs)
                published = ((renderer.get("publishedTimeText") or {}).get("simpleText") or "")
                views = ((renderer.get("viewCountText") or {}).get("simpleText") or "")
                age_months = _relative_age_months(published)
                if age_months is not None and age_months > lookback_months:
                    return
                if video_id and title and video_id not in seen:
                    seen.add(video_id)
                    rows.append({
                        "channel": channel,
                        "channelId": "",
                        "videoId": video_id,
                        "title": title,
                        "publishedAt": _relative_published_at(published),
                        "publishedText": published,
                        "publishedAgeMonths": age_months,
                        "views": _view_count(views),
                        "durationSec": 0,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                    })
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return rows


def _fallback_search_matches(query, aliases, existing_ids, lookback_months=None):
    if not config.SEARCH_FALLBACK_ENABLED or not config.YOUTUBE_API_KEY:
        return []
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    rows = []
    videos = []
    fallback_queries = _fallback_queries(query, aliases)
    try:
        videos = youtube.search_videos(
            fallback_queries[0],
            lookback_days=lookback_months * 31,
            max_results=config.SEARCH_FALLBACK_MAX_RESULTS,
            order=config.SEARCH_FALLBACK_ORDER,
        )
    except Exception as exc:
        print(f"  - YouTube API 검색 보강 실패: {str(exc)[:120]}")
    if len(videos) < config.SEARCH_FALLBACK_MAX_RESULTS:
        seen_video_ids = {video.get("videoId") for video in videos}
        for fallback_query in fallback_queries:
            if len(videos) >= config.SEARCH_FALLBACK_MAX_RESULTS:
                break
            try:
                web_videos = _youtube_web_search_videos(fallback_query, max_results=config.SEARCH_FALLBACK_MAX_RESULTS, lookback_months=lookback_months)
                for video in web_videos:
                    video_id = video.get("videoId")
                    if video_id and video_id not in seen_video_ids:
                        seen_video_ids.add(video_id)
                        videos.append(video)
                        if len(videos) >= config.SEARCH_FALLBACK_MAX_RESULTS:
                            break
            except Exception as exc:
                print(f"  - YouTube 웹 검색 보강 실패({fallback_query}): {str(exc)[:120]}")
    for video in videos:
        if video["videoId"] in existing_ids:
            continue
        if _is_likely_non_market_video(video):
            continue
        if int(video.get("views") or 0) < config.SEARCH_FALLBACK_MIN_VIEWS:
            continue
        text = youtube.fetch_transcript(video["videoId"])
        if not text:
            continue
        row = _index_video_row(video, text=text, fallback=True)
        match = _video_match_row(row, aliases)
        if match:
            rows.append(match)
            existing_ids.add(video["videoId"])
    return rows


def _within_lookback_months(video, lookback_months):
    if not lookback_months:
        return True
    age_months = video.get("publishedAgeMonths")
    if age_months is not None:
        try:
            return int(age_months) <= lookback_months
        except (TypeError, ValueError):
            pass
    published_at = _parse_index_datetime(video.get("publishedAt"))
    if not published_at:
        return True
    cutoff = datetime.datetime.now(KST) - datetime.timedelta(days=lookback_months * 31)
    return published_at >= cutoff


def _sort_and_limit_matches(matches, max_youtubers=None):
    matches.sort(
        key=lambda row: (
            row.get("hasTranscriptText", False),
            row.get("titleMatch", False),
            row.get("matchCount", 0),
            row.get("publishedAt") or "",
            row.get("views", 0),
        ),
        reverse=True,
    )
    limit = max_youtubers or config.SEARCH_MAX_YOUTUBERS
    best = {}
    for row in matches:
        best.setdefault(row.get("channel", ""), row)
        if len(best) >= limit:
            break
    return list(best.values())


def _matching_videos(query, include_fallback=True, lookback_months=None):
    aliases = query_aliases(query)
    if not aliases:
        return []
    matches = []
    for video in load_index().get("videos", []):
        if not _within_lookback_months(video, lookback_months):
            continue
        if _is_likely_non_market_video(video):
            continue
        row = _video_match_row(video, aliases)
        if row:
            matches.append(row)
    if include_fallback:
        existing_ids = {row["videoId"] for row in matches}
        matches.extend(_fallback_search_matches(query, aliases, existing_ids, lookback_months=lookback_months))
    return matches


def match_stats(matches, visible_matches):
    return {
        "mentionedVideoCount": len(matches),
        "candidateYoutuberCount": len({row.get("channel", "") for row in matches}),
        "shownYoutuberCount": len({row.get("channel", "") for row in visible_matches}),
    }


def find_videos_with_stats(query, max_youtubers=None, include_fallback=True, lookback_months=None):
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    matches = _matching_videos(query, include_fallback=include_fallback, lookback_months=lookback_months)
    visible = _sort_and_limit_matches(list(matches), max_youtubers=max_youtubers)
    return visible, match_stats(matches, visible)


def _cache_path(video_id, query):
    digest = hashlib.sha256(compact(query).encode("utf-8")).hexdigest()[:16]
    return config.REAL_ESTATE_ANALYSIS_CACHE_DIR / f"{video_id}-{digest}.json"


def _analysis_inputs(video, query):
    aliases = query_aliases(query)
    if "_text" not in video:
        video["_text"] = transcript_text(video["videoId"])
    context = extract_context(video["_text"], aliases)
    context_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    return aliases, context, context_hash, _cache_path(video["videoId"], query)


def _read_cached_analysis(path, context_hash):
    if not path.exists() and not config.FORCE_ANALYSIS_REFRESH:
        remote_cache.download_to_file(_remote_path(f"analysis/{path.name}"), path)
    if path.exists() and not config.FORCE_ANALYSIS_REFRESH:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("version") == _ANALYSIS_VERSION and cached.get("contextHash") == context_hash:
                return cached["data"], True
        except (OSError, ValueError, KeyError):
            pass
    return None, False


def _evidence_terms(evidence):
    terms = set()
    for term in re.findall(r"[0-9A-Za-z가-힣]{2,}", evidence or ""):
        key = compact(term)
        if len(key) >= 2 and key not in {"있습니다", "것으로", "대한", "또한", "때문입니다"}:
            terms.add(key)
    return terms


def source_time_sec(video_id, aliases, evidence):
    segments = transcript_segments(video_id)
    if not segments:
        return None
    alias_keys = [compact(alias) for alias in aliases if compact(alias)]
    terms = _evidence_terms(evidence)
    best = None
    for order, segment in enumerate(segments):
        text = segment.get("text", "")
        key = compact(text)
        if not key or not any(alias in key for alias in alias_keys):
            continue
        overlap = sum(1 for term in terms if term in key)
        try:
            start_sec = float(segment.get("startSec"))
        except (TypeError, ValueError):
            continue
        candidate = (overlap * 10 + min(len(key), 80) / 80, -order, start_sec)
        if best is None or candidate > best:
            best = candidate
    return round(best[2]) if best else None


def cached_match(video, query):
    _, _, context_hash, path = _analysis_inputs(video, query)
    return _read_cached_analysis(path, context_hash)


def analyze_match(video, query):
    import analyze_real_estate

    aliases, context, context_hash, path = _analysis_inputs(video, query)
    if not context.strip():
        return {"mentioned": False, "stance": "단순언급", "summary": "", "evidence": "", "sourceTimeSec": None}, False
    cached_data, cached = _read_cached_analysis(path, context_hash)
    if cached:
        return cached_data, True
    data = analyze_real_estate.analyze_opinion(query, aliases, context)
    data["sourceTimeSec"] = source_time_sec(video["videoId"], aliases, data.get("evidence", ""))
    config.REAL_ESTATE_ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({
        "version": _ANALYSIS_VERSION,
        "contextHash": context_hash,
        "provider": analyze_real_estate.LAST_GENERATION_PROVIDER,
        "data": data,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    remote_cache.upload_file(_remote_path(f"analysis/{path.name}"), path)
    return data, False


def mood_from_counts(counts):
    up = int(counts.get("상승기대") or 0)
    wait = int(counts.get("관망") or 0)
    risk = int(counts.get("주의") or 0)
    mention = int(counts.get("단순언급") or 0)
    judged = up + wait + risk
    score = up * 1.0 + wait * -0.2 + risk * -1.3
    score_ratio = round(score / judged, 2) if judged else 0.0
    up_share = up / judged if judged else 0
    wait_share = wait / judged if judged else 0
    risk_share = risk / judged if judged else 0

    if judged < 3:
        label = "판단 보류"
    elif up_share >= 0.55 and risk_share < 0.25:
        label = "상승 기대 우세"
    elif risk_share >= 0.3 or score_ratio <= -0.35:
        label = "주의 우세"
    elif wait_share >= 0.45:
        label = "관망 우세"
    else:
        label = "의견 갈림"

    summaries = {
        "상승 기대 우세": "유튜버들은 수요·입지·호재를 더 강하게 봤어요.",
        "관망 우세": "유튜버들은 가격과 거래량을 더 확인하자는 쪽이에요.",
        "주의 우세": "유튜버들은 가격 부담이나 공급 리스크를 반복해서 언급했어요.",
        "의견 갈림": "유튜버 의견이 아직 한쪽 방향으로 모이지 않았어요.",
        "판단 보류": "판단하기엔 아직 명확한 의견 표본이 적어요.",
    }
    return {
        "label": label,
        "summary": summaries[label],
        "judgedCount": judged,
        "mentionOnlyCount": mention,
        "scoreRatio": score_ratio,
    }


def base_search_result(query, videos, stats=None, lookback_months=None):
    stats = stats or match_stats(videos, videos)
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    counts = {stance: 0 for stance in config.STANCES}
    return {
        "query": query.strip(),
        "aliases": query_aliases(query),
        "matchedVideos": stats["mentionedVideoCount"],
        "mentionedVideoCount": stats["mentionedVideoCount"],
        "candidateYoutuberCount": stats["candidateYoutuberCount"],
        "shownYoutuberCount": stats["shownYoutuberCount"],
        "lookbackMonths": lookback_months,
        "processedVideos": 0,
        "analyzedVideos": 0,
        "analysisLimit": max(1, min(len(videos), config.SEARCH_MAX_ANALYZED_VIDEOS)),
        "opinions": [],
        "counts": counts,
        "marketMood": mood_from_counts(counts),
        "errors": [],
        "indexUpdatedAt": load_index().get("updatedAt"),
    }


def _is_non_market_opinion(video, result):
    if not result.get("mentioned"):
        return True
    combined = " ".join(str(value or "") for value in (
        video.get("channel", ""),
        video.get("title", ""),
        result.get("summary", ""),
        result.get("evidence", ""),
    ))
    explicit_no_opinion = _has_any_term(combined, _NO_OPINION_PHRASES)
    non_market_topic = _has_any_term(combined, _NON_MARKET_TOPIC_TERMS)
    market_context = _has_any_term(combined, _MARKET_OPINION_TERMS)
    if explicit_no_opinion:
        return True
    if non_market_topic and (result.get("stance") == "단순언급" or not market_context):
        return True
    if result.get("stance") == "단순언급" and not market_context:
        return True
    return False


def opinion_from_result(video, result, cached):
    if _is_non_market_opinion(video, result):
        return None
    return {
        "videoId": video.get("videoId", ""),
        "channel": video.get("channel", ""),
        "title": video.get("title", ""),
        "publishedAt": video.get("publishedAt", ""),
        "publishedText": video.get("publishedText", ""),
        "publishedAgeMonths": video.get("publishedAgeMonths"),
        "views": video.get("views", 0),
        "url": video.get("url", ""),
        "stance": result.get("stance", "단순언급"),
        "summary": result.get("summary", ""),
        "evidence": result.get("evidence", ""),
        "sourceTimeSec": result.get("sourceTimeSec"),
        "cached": cached,
    }


def add_opinion(search_result, opinion):
    if not opinion:
        return
    opinion["_order"] = len(search_result["opinions"])
    search_result["opinions"].append(opinion)
    search_result["counts"][opinion["stance"]] += 1
    search_result["marketMood"] = mood_from_counts(search_result["counts"])


def _published_sort_value(opinion):
    try:
        return datetime.datetime.fromisoformat(opinion.get("publishedAt", "")).timestamp()
    except (TypeError, ValueError):
        return 0


def opinion_sort_key(opinion):
    mention_rank = 1 if opinion.get("stance") == "단순언급" else 0
    return (-_published_sort_value(opinion), mention_rank, -int(opinion.get("views") or 0), opinion.get("_order", 0))


def sort_opinions(search_result):
    search_result["opinions"].sort(key=opinion_sort_key)
    for opinion in search_result["opinions"]:
        opinion.pop("_order", None)


def search_real_estate(query, include_fallback=True, lookback_months=None):
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    videos, stats = find_videos_with_stats(query, include_fallback=include_fallback, lookback_months=lookback_months)
    result = base_search_result(query, videos, stats, lookback_months=lookback_months)
    for idx, video in enumerate(videos):
        try:
            if idx < result["analysisLimit"]:
                opinion_result, cached = analyze_match(video, query)
                result["analyzedVideos"] += 1
            else:
                opinion_result, cached = cached_match(video, query)
                if not cached:
                    result["processedVideos"] += 1
                    continue
        except Exception as exc:
            result["errors"].append(f"{video.get('channel', '')}: {str(exc)[:120]}")
            result["processedVideos"] += 1
            continue
        add_opinion(result, opinion_from_result(video, opinion_result, cached))
        result["processedVideos"] += 1
    sort_opinions(result)
    result["done"] = True
    return result
