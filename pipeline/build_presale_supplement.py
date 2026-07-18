"""서울·경기 분양권/입주예정 단지 보강 CSV를 만든다.

청약홈의 APT 분양정보(입주예정)와 로컬에 저장된 국토부
분양권/입주권 실거래 캐시(현재 거래)를 합친다. 원본 공동주택
단지 식별정보는 사용승인 단지 위주라, 이 파일이 검색 인덱스의
신축 공백을 보완한다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import io
import json
import re
from collections import defaultdict
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
SEOUL_MASTER = (
    ROOT
    / "outputs"
    / "seoul_apartments_20260703"
    / "서울시_아파트_단지_목록_한국부동산원_20250918.csv"
)
GYEONGGI_MASTER = ROOT / "data" / "경기도_아파트_단지_목록_한국부동산원_20250918.csv"
SUPPLEMENT_PATH = ROOT / "data" / "분양권_입주예정_아파트_보강.csv"
MOLIT_CACHE_DIR = ROOT / "pipeline" / "cache" / "molit_transactions"

APPLYHOME_META_URL = "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do"
APPLYHOME_DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
APPLYHOME_META_PARAMS = {
    "recommendDataYn": "Y",
    "publicDataPk": "15101046",
    "publicDataDetailPk": "uddi:14a46595-03dd-47d3-a418-d64e52820598",
}
LH_LIST_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do"
LH_DETAIL_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"

OUTPUT_COLUMNS = [
    "시도",
    "자치구",
    "시군구",
    "법정동",
    "지번",
    "법정동코드",
    "주소",
    "대표단지명",
    "단지명_공시가격",
    "단지명_건축물대장",
    "단지명_도로명주소",
    "별칭",
    "단지종류명",
    "세대수",
    "상태",
    "입주예정월",
    "최근분양권거래일",
    "출처",
]

ANNOUNCEMENT_MARKERS = (
    "본청약",
    "사전청약",
    "무순위",
    "추가",
    "잔여",
    "계약취소",
    "취소후",
    "임의공급",
    "재공급",
    "입주자모집",
    "국민",
    "민영",
    "특별공급",
)

CURRENT_PROJECT_OVERRIDES = {
    compact_name: values
    for compact_name, values in (
        ("고양창릉s3", {
            "시도": "경기도",
            "시군구": "고양덕양구",
            "법정동": "도내동",
            "법정동코드": "41281",
            "세대수": "1282",
            "상태": "입주예정",
            "입주예정월": "2030-02",
            "출처": "LH 청약플러스",
        }),
        ("고양창릉s4", {
            "시도": "경기도",
            "시군구": "고양덕양구",
            "법정동": "도내동",
            "법정동코드": "41281",
            "세대수": "1024",
            "상태": "입주예정",
            "입주예정월": "2030-03",
            "출처": "LH 청약플러스",
        }),
        ("인덕원퍼스비엘", {
            "세대수": "2180",
        }),
        # 준공 후 분양 단지라 더 이상 분양권 배지를 붙이지 않는다.
        ("래미안원펜타스", {"상태": ""}),
    )
}

CURATED_EXISTING_NAME_KEYS = {
    "산성역헤리스톤",
    "올림픽파크포레온",
    "메이플자이",
    "디에이치방배",
    "래미안트리니원",
    "잠실르엘",
    "래미안원펜타스",
    "철산자이더헤리티지",
    "광명센트럴아이파크",
    "이문아이파크자이",
    "북서울자이폴라리스",
    "고양창릉s4",
    "고양창릉s3",
    "풍무역롯데캐슬시그니처",
}


def compact(value):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def clean_space(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def clean_complex_name(value):
    """청약 회차 문구를 걷고 실제 검색할 단지명을 남긴다."""
    name = clean_space(value)
    name = re.sub(r"^[★☆※\s]+", "", name)

    def strip_note(match):
        note = match.group(1)
        return "" if any(marker in note for marker in ANNOUNCEMENT_MARKERS) else match.group(0)

    previous = None
    while previous != name:
        previous = name
        name = re.sub(r"\(([^()]*)\)", strip_note, name)
    name = re.sub(
        r"\s*(?:추가\s*입주자|입주자|잔여세대|계약취소주택|취소후\s*재공급)"
        r"\s*(?:모집공고|모집)?\s*$",
        "",
        name,
    )
    name = re.sub(r"\s+", " ", name).strip(" ,-")
    return name


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return clean_space(html.unescape(text))


def clean_lh_title(value):
    title = clean_space(value)
    title = re.sub(r"(?:\s*\[정정공고\])+", "", title)
    title = re.sub(r"\s+\d+일전$", "", title)
    title = re.sub(
        r"\s*(?:입주자\s*)?모집\s*공고.*$"
        r"|\s*잔여세대.*$"
        r"|\s*추가\s*입주자.*$"
        r"|\s*공가세대.*$"
        r"|\s*일반매각.*$",
        "",
        title,
    )
    return clean_space(title)


def usable_name(value):
    name = clean_space(value)
    return bool(name) and len(compact(name)) >= 2 and not re.fullmatch(r"\(?[0-9-]+\)?", name)


def read_csv_rows(path):
    if not path or not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _nested_value(payload, key):
    if isinstance(payload, dict):
        if payload.get(key):
            return payload[key]
        for value in payload.values():
            found = _nested_value(value, key)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _nested_value(value, key)
            if found:
                return found
    return ""


def download_applyhome_rows(session=None):
    session = session or requests.Session()
    meta_response = session.get(
        APPLYHOME_META_URL,
        params=APPLYHOME_META_PARAMS,
        timeout=30,
    )
    meta_response.raise_for_status()
    metadata = meta_response.json()
    params = {
        "atchFileId": _nested_value(metadata, "atchFileId"),
        "fileDetailSn": _nested_value(metadata, "fileDetailSn"),
        "dataNm": _nested_value(metadata, "dataNm"),
    }
    if not all(params.values()):
        raise RuntimeError("청약홈 분양정보 다운로드 메타데이터를 찾지 못했습니다.")
    response = session.get(APPLYHOME_DOWNLOAD_URL, params=params, timeout=60)
    response.raise_for_status()
    for encoding in ("cp949", "utf-8-sig"):
        try:
            text = response.content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("청약홈 분양정보 CSV 인코딩을 해석하지 못했습니다.")
    return list(csv.DictReader(io.StringIO(text)))


def read_applyhome_rows(path=None):
    if not path:
        return download_applyhome_rows()
    raw = Path(path).read_bytes()
    for encoding in ("cp949", "utf-8-sig"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding))))
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"CSV 인코딩을 해석하지 못했습니다: {path}")


def download_lh_rows(as_of, session=None):
    """LH 청약플러스의 올해 서울·경기 분양 공고를 현재 시점까지 읽는다."""
    session = session or requests.Session()
    start_date = f"{as_of.year}-01-01"
    entries = []
    for region_code in ("11", "41"):
        response = session.post(
            LH_LIST_URL,
            data={
                "srchUppAisTpCd": "053954",
                "uppAisTpCd": "05",
                "mi": "1027",
                "currPage": "1",
                "srchY": "Y",
                "panSs": "",
                "schTy": "0",
                "startDt": start_date,
                "endDt": as_of.isoformat(),
                "listCo": "100",
                "cnpCd": region_code,
            },
            timeout=60,
        )
        response.raise_for_status()
        for table_row in re.findall(r"<tr>(.*?)</tr>", response.text, re.S):
            anchor = re.search(
                r'<a[^>]*data-id1="([^"]+)"[^>]*data-id2="([^"]+)"'
                r'[^>]*data-id3="([^"]+)"[^>]*data-id4="([^"]+)"'
                r'[^>]*class="wrtancInfoBtn"',
                table_row,
                re.S,
            )
            if not anchor:
                continue
            cells = [
                strip_html(value)
                for value in re.findall(r"<td[^>]*>(.*?)</td>", table_row, re.S)
            ]
            if len(cells) < 4 or cells[3] not in {"서울특별시", "경기도"}:
                continue
            entries.append({
                "ids": anchor.groups(),
                "title": clean_lh_title(cells[2]),
                "region": cells[3],
            })

    # 정정공고는 같은 사업의 새 panId로 반복된다. 목록의 최신 행만 상세 조회한다.
    unique_entries = []
    seen_titles = set()
    for entry in entries:
        title_key = compact(entry["title"])
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        unique_entries.append(entry)

    rows = []
    for entry in unique_entries:
        pan_id, connection_code, housing_type, upper_type = entry["ids"]
        response = session.get(
            LH_DETAIL_URL,
            params={
                "panId": pan_id,
                "ccrCnntSysDsCd": connection_code,
                "aisTpCd": housing_type,
                "uppAisTpCd": upper_type,
                "mi": "1027",
            },
            timeout=30,
        )
        response.raise_for_status()
        locations = re.findall(
            r"<li[^>]*>\s*소재지\s*:\s*(.*?)</li>",
            response.text,
            re.S,
        )
        households = re.findall(
            r"<li[^>]*>\s*총\s*세대수\s*:\s*([^<]+)</li>",
            response.text,
            re.S,
        )
        planned = re.findall(
            r"<li[^>]*>\s*입주예정(?:월|일)\s*:\s*([^<]+)</li>",
            response.text,
            re.S,
        )
        for index, location in enumerate(locations):
            planned_text = strip_html(planned[index] if index < len(planned) else "")
            planned_digits = month_key(planned_text)
            if not planned_digits:
                match = re.search(r"(\d{4})년\s*(\d{1,2})월", planned_text)
                planned_digits = f"{match.group(1)}{int(match.group(2)):02d}" if match else ""
            if not planned_digits or planned_digits < as_of.strftime("%Y%m"):
                continue
            rows.append({
                "주택명": entry["title"],
                "공급위치": strip_html(location),
                "세대수": re.sub(
                    r"\D",
                    "",
                    strip_html(households[index] if index < len(households) else ""),
                ),
                "입주예정월": planned_digits,
            })
    return rows


def build_region_index():
    """기존 단지 PNU로 주소 표기와 5자리 법정동코드를 연결한다."""
    label_by_lawd = {}
    lawd_by_label = {}
    for path in (SEOUL_MASTER, GYEONGGI_MASTER):
        for row in read_csv_rows(path):
            pnu = re.sub(r"\D", "", str(row.get("필지고유번호") or ""))
            if len(pnu) < 5:
                continue
            lawd = pnu[:5]
            province = row.get("시도") or ""
            city = row.get("시군구") or ""
            general_gu = row.get("일반구") or ""
            borough = row.get("자치구") or ""
            if province == "서울특별시":
                district = borough
                labels = [borough]
            else:
                district = f"{re.sub(r'시$', '', city)}{general_gu}" if general_gu else city
                labels = [city, general_gu, f"{city} {general_gu}".strip(), district]
                combined = re.fullmatch(
                    r"(수원|성남|안양|안산|고양|용인|부천)(.+구)",
                    district,
                )
                if combined:
                    base_city, gu = combined.groups()
                    labels.extend([f"{base_city}시 {gu}", gu])
            label_by_lawd.setdefault(lawd, {
                "시도": province,
                "자치구": borough if province == "서울특별시" else "",
                "시군구": district if province != "서울특별시" else "",
            })
            for label in labels:
                if label:
                    lawd_by_label.setdefault(compact(label), lawd)
    return label_by_lawd, lawd_by_label


def region_from_address(address, label_by_lawd, lawd_by_label):
    address = clean_space(address)
    lawd = ""
    labels = sorted(lawd_by_label, key=len, reverse=True)
    address_key = compact(address)
    for label in labels:
        if label and label in address_key:
            lawd = lawd_by_label[label]
            break
    if not lawd and "부천대장" in address_key:
        lawd = "41196"
    region = dict(label_by_lawd.get(lawd) or {})
    region.setdefault("시도", "서울특별시" if address.startswith("서울") else "경기도")
    region.setdefault("자치구", "")
    region.setdefault("시군구", "")

    place_names = re.findall(
        r"[가-힣0-9]+(?:동\d*가|동|읍|면|리)(?![가-힣0-9])",
        address,
    )
    legal_dong = place_names[0] if place_names else ""
    if not legal_dong and "부천대장" in address_key:
        legal_dong = "대장동"
    if legal_dong.endswith(("읍", "면")) and len(place_names) > 1 and place_names[1].endswith("리"):
        legal_dong = place_names[1]
    jibun_match = re.search(r"(?<![A-Za-z0-9])(\d+(?:-\d+)?)\s*(?:번지)?(?:\s|$|[,)])", address)
    return {
        **region,
        "법정동": legal_dong,
        "지번": jibun_match.group(1) if jibun_match else "",
        "법정동코드": lawd,
        "주소": address,
    }


def month_key(value):
    return re.sub(r"\D", "", str(value or ""))[:6]


def deal_date_cutoff(as_of, lookback_months):
    year = as_of.year
    month = as_of.month - lookback_months
    while month <= 0:
        year -= 1
        month += 12
    return dt.date(year, month, 1).isoformat()


def read_molit_cache(cache_dir, min_month):
    rows = []
    for path in sorted(Path(cache_dir).glob("presale_*.json")):
        match = re.search(r"presale_(\d{5})_(\d{6})\.json$", path.name)
        if not match or match.group(2) < min_month:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in payload.get("items") or []:
            row = dict(item)
            row["lawdCd"] = match.group(1)
            rows.append(row)
    return rows


def read_molit_exports(paths):
    rows = []
    for path in paths or []:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows.extend(payload.get("rows") or [])
    return rows


def source_names(row):
    return [
        row.get("대표단지명", ""),
        row.get("단지명_공시가격", ""),
        row.get("단지명_건축물대장", ""),
        row.get("단지명_도로명주소", ""),
        *((row.get("별칭") or "").split("|")),
    ]


def blank_candidate():
    return {column: "" for column in OUTPUT_COLUMNS}


def existing_candidates(path):
    candidates = []
    for row in read_csv_rows(path):
        source = row.get("출처") or ""
        if source and compact(row.get("대표단지명")) not in CURATED_EXISTING_NAME_KEYS:
            continue
        if not usable_name(row.get("대표단지명")):
            continue
        candidate = blank_candidate()
        candidate.update({column: clean_space(row.get(column)) for column in OUTPUT_COLUMNS})
        candidate["_aliases"] = {clean_space(value) for value in source_names(row) if usable_name(value)}
        candidate["_priority"] = 3
        candidate["_source_keys"] = {"기존 보강"}
        override = CURRENT_PROJECT_OVERRIDES.get(compact(candidate["대표단지명"]))
        if override is not None:
            candidate.update(override)
            candidate["_source_keys"].update(
                value for value in (override.get("출처"),) if value
            )
        candidates.append(candidate)
    return candidates


def applyhome_candidates(rows, as_of, label_by_lawd, lawd_by_label):
    current_month = as_of.strftime("%Y%m")
    deduped = {}
    for row in rows:
        if row.get("공급지역명") not in {"서울", "경기"}:
            continue
        planned_month = month_key(row.get("입주예정월"))
        if not planned_month or planned_month < current_month:
            continue
        name = clean_complex_name(row.get("주택명"))
        if not usable_name(name):
            continue
        if any(marker in compact(name) for marker in (
            "공공임대",
            "분양전환공공임대",
            "국민임대",
            "행복주택",
            "장기전세",
        )):
            continue
        location = region_from_address(
            row.get("공급위치"),
            label_by_lawd,
            lawd_by_label,
        )
        key = (
            compact(name),
            location.get("법정동코드", ""),
            compact(location.get("법정동")),
            compact(location.get("지번")),
        )
        candidate = deduped.get(key)
        if candidate is None:
            candidate = blank_candidate()
            candidate.update(location)
            candidate.update({
                "대표단지명": name,
                "단지명_공시가격": name,
                "단지종류명": "아파트",
                "상태": "입주예정",
                "입주예정월": f"{planned_month[:4]}-{planned_month[4:]}",
            })
            candidate["_aliases"] = {clean_space(row.get("주택명"))}
            candidate["_priority"] = 2
            candidate["_source_keys"] = {"청약홈 APT 분양정보"}
            deduped[key] = candidate
        else:
            candidate["_aliases"].add(clean_space(row.get("주택명")))
            if month_key(candidate.get("입주예정월")) < planned_month:
                candidate["입주예정월"] = f"{planned_month[:4]}-{planned_month[4:]}"
    return list(deduped.values())


def lh_candidates(rows, label_by_lawd, lawd_by_label):
    candidates = []
    for row in rows:
        name = clean_complex_name(row.get("주택명"))
        if not usable_name(name):
            continue
        location = region_from_address(
            row.get("공급위치"),
            label_by_lawd,
            lawd_by_label,
        )
        planned_month = month_key(row.get("입주예정월"))
        candidate = blank_candidate()
        candidate.update(location)
        candidate.update({
            "대표단지명": name,
            "단지명_공시가격": name,
            "단지종류명": "아파트",
            "세대수": row.get("세대수") or "",
            "상태": "입주예정",
            "입주예정월": (
                f"{planned_month[:4]}-{planned_month[4:]}"
                if planned_month
                else ""
            ),
        })
        candidate["_aliases"] = {clean_space(row.get("주택명"))}
        candidate["_priority"] = 2
        candidate["_source_keys"] = {"LH 청약플러스"}
        candidates.append(candidate)
    return candidates


def molit_candidates(rows, cutoff, label_by_lawd):
    grouped = {}
    for row in rows:
        if row.get("cancellationDate") or row.get("해제사유발생일"):
            continue
        deal_date = str(row.get("dealDate") or "")
        if not deal_date or deal_date < cutoff:
            continue
        name = clean_space(row.get("apartment") or row.get("아파트"))
        if not usable_name(name):
            continue
        lawd = str(row.get("lawdCd") or "")
        legal_dong = clean_space(row.get("legalDong") or row.get("법정동"))
        jibun = clean_space(row.get("jibun") or row.get("지번"))
        key = (lawd, compact(legal_dong), compact(jibun))
        candidate = grouped.get(key)
        if candidate is None:
            candidate = blank_candidate()
            candidate.update(label_by_lawd.get(lawd) or {})
            candidate.update({
                "법정동": legal_dong,
                "지번": jibun,
                "법정동코드": lawd,
                "대표단지명": name,
                "단지명_공시가격": name,
                "단지종류명": "아파트",
                "상태": "분양권",
                "최근분양권거래일": deal_date,
            })
            candidate["_aliases"] = {name}
            candidate["_priority"] = 1
            candidate["_source_keys"] = {"국토교통부 분양권/입주권 실거래"}
            grouped[key] = candidate
        else:
            candidate["_aliases"].add(name)
            if deal_date > candidate["최근분양권거래일"]:
                candidate["최근분양권거래일"] = deal_date
            current_name = candidate["대표단지명"]
            if (" " in name, len(name)) > (" " in current_name, len(current_name)):
                candidate["대표단지명"] = name
                candidate["단지명_공시가격"] = name
    return list(grouped.values())


def location_key(candidate):
    lawd = candidate.get("법정동코드", "")
    dong = compact(candidate.get("법정동"))
    jibun = compact(candidate.get("지번"))
    # 계획지구 주소는 한 읍·동만 적고 지번이 없는 경우가 많다. 그런 행을
    # 위치만으로 합치면 A1/B17처럼 서로 다른 블록이 하나가 된다.
    return (lawd, dong, jibun) if lawd and dong and jibun else None


def block_keys(candidate):
    values = candidate.get("_aliases", set()) | {candidate.get("대표단지명", "")}
    keys = set()
    for value in values:
        text = str(value or "").upper()
        keys.update(
            compact(match)
            for match in re.findall(r"(?:[A-Z]{0,2}-?\d+(?:BL|블록|단지))", text)
        )
    return keys


def names_overlap(left, right):
    left_keys = {compact(value) for value in left.get("_aliases", set()) | {left.get("대표단지명", "")}}
    right_keys = {compact(value) for value in right.get("_aliases", set()) | {right.get("대표단지명", "")}}
    left_keys.discard("")
    right_keys.discard("")
    left_blocks = block_keys(left)
    right_blocks = block_keys(right)
    if left_blocks and right_blocks and left_blocks.isdisjoint(right_blocks):
        return False
    if left_keys & right_keys:
        return True
    return any(
        min(len(a), len(b)) >= 5 and (a in b or b in a)
        for a in left_keys
        for b in right_keys
    )


def merge_candidates(candidates):
    merged = []
    for candidate in sorted(
        candidates,
        key=lambda value: (-value.get("_priority", 0), compact(value.get("대표단지명"))),
    ):
        target = None
        candidate_location = location_key(candidate)
        for existing in merged:
            same_location = candidate_location and candidate_location == location_key(existing)
            if same_location or names_overlap(candidate, existing):
                # 같은 이름이 다른 시군구에 반복되는 경우는 합치지 않는다.
                left_lawd = candidate.get("법정동코드", "")
                right_lawd = existing.get("법정동코드", "")
                if left_lawd and right_lawd and left_lawd != right_lawd:
                    continue
                target = existing
                break
        if target is None:
            merged.append(candidate)
            continue
        target_had_lawd = bool(target.get("법정동코드"))
        candidate_has_lawd = bool(candidate.get("법정동코드"))
        candidate_deal_date = candidate.get("최근분양권거래일")
        target["_aliases"].update(candidate["_aliases"])
        target["_source_keys"].update(candidate["_source_keys"])
        for column in OUTPUT_COLUMNS:
            if not target.get(column) and candidate.get(column):
                target[column] = candidate[column]
        if not target_had_lawd and candidate_has_lawd:
            for column in ("시도", "자치구", "시군구", "법정동", "지번", "법정동코드", "주소"):
                if candidate.get(column):
                    target[column] = candidate[column]
        if candidate_deal_date:
            if candidate_deal_date > target.get("최근분양권거래일"):
                target["최근분양권거래일"] = candidate_deal_date
            target["상태"] = "분양권"
        if month_key(candidate.get("입주예정월")) > month_key(target.get("입주예정월")):
            target["입주예정월"] = candidate["입주예정월"]
    return merged


def finalize(candidates):
    rows = []
    for candidate in candidates:
        override = CURRENT_PROJECT_OVERRIDES.get(compact(candidate.get("대표단지명")))
        if override is not None:
            candidate.update({key: value for key, value in override.items() if key != "출처"})
            if override.get("출처"):
                candidate["_source_keys"].add(override["출처"])
        name_key = compact(candidate.get("대표단지명"))
        aliases = sorted({
            clean_space(alias)
            for alias in candidate.pop("_aliases", set())
            if usable_name(alias) and compact(alias) != name_key
        }, key=lambda value: (len(compact(value)), value))
        sources = candidate.pop("_source_keys", set())
        candidate.pop("_priority", None)
        candidate["별칭"] = "|".join(aliases)
        candidate["출처"] = "|".join(sorted(sources))
        candidate["단지종류명"] = "아파트"
        rows.append({column: candidate.get(column, "") for column in OUTPUT_COLUMNS})
    rows.sort(key=lambda row: (
        0 if row["시도"] == "서울특별시" else 1,
        row["자치구"] or row["시군구"],
        row["법정동"],
        compact(row["대표단지명"]),
    ))
    return rows


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--applyhome-csv", help="생략하면 공공데이터포털 최신 파일 다운로드")
    parser.add_argument("--existing", default=str(SUPPLEMENT_PATH))
    parser.add_argument("--cache-dir", default=str(MOLIT_CACHE_DIR))
    parser.add_argument("--molit-json", action="append", default=[])
    parser.add_argument("--skip-lh", action="store_true")
    parser.add_argument("--output", default=str(SUPPLEMENT_PATH))
    parser.add_argument("--as-of", default=dt.date.today().isoformat())
    parser.add_argument("--lookback-months", type=int, default=12)
    return parser.parse_args()


def main():
    args = parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = deal_date_cutoff(as_of, args.lookback_months)
    min_month = re.sub(r"\D", "", cutoff)[:6]
    label_by_lawd, lawd_by_label = build_region_index()
    applyhome = read_applyhome_rows(args.applyhome_csv)
    lh_rows = [] if args.skip_lh else download_lh_rows(as_of)
    molit = read_molit_cache(args.cache_dir, min_month)
    molit.extend(read_molit_exports(args.molit_json))
    candidates = [
        *existing_candidates(args.existing),
        *applyhome_candidates(applyhome, as_of, label_by_lawd, lawd_by_label),
        *lh_candidates(lh_rows, label_by_lawd, lawd_by_label),
        *molit_candidates(molit, cutoff, label_by_lawd),
    ]
    rows = finalize(merge_candidates(candidates))
    write_csv(args.output, rows)
    status_counts = defaultdict(int)
    province_counts = defaultdict(int)
    for row in rows:
        status_counts[row["상태"]] += 1
        province_counts[row["시도"]] += 1
    print(json.dumps({
        "output": str(args.output),
        "count": len(rows),
        "byStatus": dict(status_counts),
        "byProvince": dict(province_counts),
        "dealCutoff": cutoff,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
