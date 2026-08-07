#!/usr/bin/env python3
"""업무지구(여의도·광화문·강남)까지의 지하철 소요시간 추정.

왜 이 모듈이 필요한가
--------------------
기존 `budget_candidates.COMMUTE_AFFINITY`는 구 단위 하드코딩 점수표였다.
표에 없는 구(예: 구로구)는 모든 업무지구에서 0점이 되어, 실제로는 1호선으로
여의도·광화문이 연결되는 단지가 "직장권 접근성 없음"으로 표시됐다.

어떻게 계산하는가
----------------
`data/subway_station_codes.csv`의 역 코드(예: 143 개봉, D11 판교)는 노선별
역 순번을 담고 있다. 같은 노선에서 번호가 이어지는 역을 인접 간선으로 놓고,
같은 이름의 역을 환승 간선으로 이어 그래프를 만든 뒤 다익스트라를 돌린다.
런타임 외부 API 호출이 없다.

정확도에 대한 정직한 한계
------------------------
실제 시각표가 아니라 `역 수 × 노선별 평균 역간 시간`으로 만든 추정치다.
급행·직결 운행과 배차 간격은 반영하지 않아 실제와 5분 안팎 차이가 난다.
그래서 결과에는 항상 `estimated=True`를 붙이고, 화면에는 "지하철 역 수 기준
추정" 문구를 함께 노출해야 한다. 나중에 실제 경로 API로 바꾸더라도
`commute_profile()` 반환 형태만 유지하면 화면 코드는 손대지 않아도 된다.
"""

import csv
import heapq
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
STATION_CODE_PATH = os.path.join(DATA_DIR, "subway_station_codes.csv")
STATION_EXTRA_PATH = os.path.join(DATA_DIR, "subway_station_extras.csv")
STATION_CACHE_PATH = os.path.join(BASE_DIR, "cache", "apartment_station_distances.json")
MATRIX_PATH = os.path.join(DATA_DIR, "station_commute_times.json")

MATRIX_VERSION = "commute-subway-v2"
MATRIX_SOURCE = "지하철 역 수 기준 추정 (실제 시각표 아님)"

# 업무지구별 허브역 코드. 한 지구에 여러 역을 두고 그중 가장 빠른 값을 쓴다.
HUBS = {
    "여의도": ["526", "915"],            # 여의도역 5호선·9호선
    "광화문": ["533", "201", "132"],      # 광화문역 5호선, 시청역 2·1호선
    "강남": ["222", "D7"],               # 강남역 2호선·신분당선
}

# 노선별 평균 역간 소요시간(분). 정차·가감속을 포함한 실측 평균에 맞췄다.
LINE_HOP_MINUTES = {
    "공항철도": 4.5,
    "경춘선": 3.2,
    "경강선": 3.0,
    "신분당선": 3.0,
    "경의중앙선": 2.9,
    "수인분당선": 2.6,
    "서해선": 2.6,
    "에버라인": 1.8,
    "의정부경전철": 1.8,
    "우이신설선": 1.9,
    "김포골드라인": 2.2,
}
DEFAULT_HOP_MINUTES = 2.2   # 서울 1~9호선 평균
LONG_HAUL_HOP_MINUTES = 2.9  # 1호선 경부·경인·장항 등 광역 구간

TRANSFER_MINUTES = 4.0
WALK_METERS_PER_MIN = 67.0  # 도보 4km/h

# 배차 간격이 긴 노선은 갈아탈 때 기다리는 시간이 실제 통근시간을 좌우한다.
# 이 값을 넣지 않으면 GTX-A 같은 노선이 항상 최단 경로로 잡혀, 실제로는
# 20분에 한 대씩 오는 열차를 늘 바로 타는 것처럼 계산된다.
LINE_BOARDING_PENALTY = {
    "GTX-A": 10.0,
    "경강선": 5.0,
    "경춘선": 5.0,
    "서해선": 4.0,
    "경의중앙선": 3.0,
}
DEFAULT_BOARDING_PENALTY = 0.0

# 코드 번호가 이어지지 않지만 실제로는 붙어 있는 구간.
# 노선 분기점, 2호선 순환 폐합, 지선 연결이 여기에 해당한다.
JUNCTIONS = [
    ("243", "201"),      # 2호선 순환 폐합: 충정로-시청
    ("141", "P142"),     # 1호선 경부선 분기: 구로-가산디지털단지
    ("548", "P549"),     # 5호선 마천지선 분기: 강동-둔촌동
    ("K312", "K826"),    # 경의중앙: 공덕-효창공원앞
    ("K826", "K110"),    # 경의중앙: 효창공원앞-용산
    ("K315", "P312"),    # 경의선 서울역지선: 가좌-신촌
    ("850", "701"),      # 서해선: 초지-원곡
    ("A04", "A042"),     # 공항철도 신설역
    ("A042", "A05"),
    ("A07", "A071"),
    ("A071", "A08"),
]

# 개통 후 이름이 바뀐 역. 캐시(카카오) 표기 → 역코드 데이터 표기.
STATION_ALIASES = {
    "불암산": "당고개",
    "4.19민주묘지": "419민주묘지",
    "평택지제": "지제",
    "총신대입구(이수)": "총신대입구",
}

_CODE_PATTERN = re.compile(r"^([A-Za-z]*)(\d+)(?:-(\d+))?$")
_MATRIX_CACHE = None
_EXTRA_LINES = {}
_EXTRA_HOPS = {}


# ── 코드 해석 ──────────────────────────────────────────────────────────

def parse_code(code):
    """'K217' → ('K', 217, None), '211-2' → ('', 211, 2)."""
    match = _CODE_PATTERN.match(str(code or "").strip())
    if not match:
        return None
    prefix, number, branch = match.groups()
    return prefix.upper(), int(number), int(branch) if branch else None


def line_for_code(code):
    """역 코드 → 앱에서 쓰는 노선 이름. 캐시의 '개봉역 1호선' 표기와 맞춘다."""
    if code in _EXTRA_LINES:
        return _EXTRA_LINES[code]
    parsed = parse_code(code)
    if not parsed:
        return ""
    prefix, number, _ = parsed
    if prefix == "":
        if 100 <= number <= 161:
            return "1호선"
        if 201 <= number <= 243:
            return "2호선"
        if 309 <= number <= 352:
            return "3호선"
        if 409 <= number <= 456:
            return "4호선"
        if 510 <= number <= 553:
            return "5호선"
        if 610 <= number <= 648:
            return "6호선"
        if 690 <= number <= 699:
            return "김포골드라인"
        if number in (701, 702) or 841 <= number <= 850:
            return "서해선"
        if 709 <= number <= 759:
            return "7호선"
        if 810 <= number <= 826:
            return "8호선"
        if 901 <= number <= 938:
            return "9호선"
        if 941 <= number <= 953:
            return "우이신설선"
        return ""
    if prefix == "K":
        if 110 <= number <= 138 or 312 <= number <= 336 or number == 826:
            return "경의중앙선"
        if 209 <= number <= 264:
            return "수인분당선"
        if 410 <= number <= 420:
            return "경강선"
        return ""
    if prefix == "P":
        if 116 <= number <= 140:
            return "경춘선"
        if 312 <= number <= 313:
            return "경의중앙선"
        if 540 <= number <= 560:
            return "5호선"      # 마천지선(둔촌동~마천)
        return "1호선"          # 경부선·경인선·장항선 구간
    if prefix == "A":
        return "공항철도"
    if prefix == "D":
        return "신분당선"
    if prefix == "U":
        return "의정부경전철"
    if prefix == "Y":
        return "에버라인"
    if prefix == "I":
        return "인천2호선" if 200 <= number <= 299 else "인천1호선"
    return ""


def hop_minutes(code):
    if code in _EXTRA_HOPS:
        return _EXTRA_HOPS[code]
    line = line_for_code(code)
    if line in LINE_HOP_MINUTES:
        return LINE_HOP_MINUTES[line]
    parsed = parse_code(code)
    if parsed and parsed[0] == "P" and line == "1호선":
        return LONG_HAUL_HOP_MINUTES
    if line == "1호선" and parsed and parsed[1] <= 115:
        return LONG_HAUL_HOP_MINUTES   # 소요산~의정부 구간
    return DEFAULT_HOP_MINUTES


# ── 그래프 구축 ────────────────────────────────────────────────────────

def load_station_codes(path=STATION_CODE_PATH):
    """{code: name} 사전. 출처는 서울교통공사 역코드 체계."""
    stations = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("code") or "").strip()
            name = (row.get("name") or "").strip()
            if code and name:
                stations[code] = name
    return stations


def load_station_extras(path=STATION_EXTRA_PATH):
    """역코드 데이터 이후 개통한 노선·연장 구간을 명시적으로 보탠다.

    (코드→이름) 사전과 (코드→연결 대상 코드 목록) 사전을 함께 돌려준다.
    이름이 겹쳐 그래프가 꼬이는 것을 막으려고 신림선 샛강처럼 중복되는
    역은 코드용 이름에 노선을 덧붙여 두고, 조회 시에는 이름만으로 찾는다.
    """
    names = {}
    links = {}
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return names, links
    with handle:
        for row in csv.DictReader(handle):
            code = (row.get("code") or "").strip()
            name = (row.get("name") or "").strip()
            if not code or not name:
                continue
            names[code] = name
            _EXTRA_LINES[code] = (row.get("line") or "").strip()
            try:
                _EXTRA_HOPS[code] = float(row.get("hop_minutes") or 0) or DEFAULT_HOP_MINUTES
            except ValueError:
                _EXTRA_HOPS[code] = DEFAULT_HOP_MINUTES
            links[code] = [
                item.strip()
                for item in str(row.get("connect_to") or "").split("|")
                if item.strip()
            ]
    return names, links


def build_graph(stations, extra_links=None):
    """노선 순번 인접 + 지선 연결 + 동명역 환승으로 그래프를 만든다."""
    graph = {code: [] for code in stations}

    def boarding_penalty(code):
        return LINE_BOARDING_PENALTY.get(line_for_code(code), DEFAULT_BOARDING_PENALTY)

    def connect(a, b, minutes, is_transfer):
        """양방향 간선. 환승은 도착 노선의 배차 대기까지 더한다."""
        if a not in graph or b not in graph:
            return
        to_b = minutes + (boarding_penalty(b) if is_transfer else 0)
        to_a = minutes + (boarding_penalty(a) if is_transfer else 0)
        graph[a].append((b, to_b, is_transfer))
        graph[b].append((a, to_a, is_transfer))

    # 1) 같은 노선에서 번호가 이어지는 역
    by_prefix = {}
    for code in stations:
        parsed = parse_code(code)
        if not parsed:
            continue
        prefix, number, branch = parsed
        if branch is not None:
            continue
        by_prefix.setdefault(prefix, []).append((number, code))
    for prefix, items in by_prefix.items():
        items.sort()
        for (number, code), (next_number, next_code) in zip(items, items[1:]):
            if line_for_code(code) != line_for_code(next_code):
                continue
            gap = next_number - number
            # 번호가 하나 비어 있는 경우(폐역·미개통)도 실제로는 붙어 있다.
            if gap > 2:
                continue
            connect(code, next_code, hop_minutes(code) * max(1, gap), False)

    # 2) 지선(211-1, 234-2, P157-1 …)은 본선 번호에서 갈라져 순서대로 이어진다
    branches = {}
    for code in stations:
        parsed = parse_code(code)
        if not parsed or parsed[2] is None:
            continue
        prefix, number, branch = parsed
        branches.setdefault(f"{prefix}{number}", []).append((branch, code))
    for trunk, items in branches.items():
        items.sort()
        previous = trunk
        for _, code in items:
            connect(previous, code, hop_minutes(code), False)
            previous = code

    # 3) 코드가 끊기지만 실제로는 이어진 구간
    for first, second in JUNCTIONS:
        connect(first, second, hop_minutes(first), False)

    # 3-1) 역코드 데이터 이후 개통한 구간
    for code, targets in (extra_links or {}).items():
        for target in targets:
            connect(code, target, hop_minutes(code), False)

    # 4) 같은 이름의 역 = 환승
    by_name = {}
    for code, name in stations.items():
        by_name.setdefault(name, []).append(code)
    for codes in by_name.values():
        for index, first in enumerate(codes):
            for second in codes[index + 1:]:
                connect(first, second, TRANSFER_MINUTES, True)

    return graph


def shortest_times(graph, sources):
    """허브역들에서 출발하는 다중 시작점 다익스트라. {코드: (분, 환승수)}"""
    best = {}
    queue = [(0.0, 0, source) for source in sources if source in graph]
    heapq.heapify(queue)
    while queue:
        minutes, transfers, node = heapq.heappop(queue)
        if node in best:
            continue
        best[node] = (minutes, transfers)
        for neighbor, cost, is_transfer in graph[node]:
            if neighbor in best:
                continue
            heapq.heappush(
                queue,
                (minutes + cost, transfers + (1 if is_transfer else 0), neighbor),
            )
    return best


def build_matrix(code_path=STATION_CODE_PATH, extra_path=STATION_EXTRA_PATH):
    stations = load_station_codes(code_path)
    extra_names, extra_links = load_station_extras(extra_path)
    stations.update(extra_names)
    graph = build_graph(stations, extra_links)

    records = {}
    fallback = {}

    def put(bucket, key, hub_name, minutes, transfers):
        entry = bucket.setdefault(key, {})
        existing = entry.get(hub_name)
        if existing and existing["minutes"] <= minutes:
            return
        entry[hub_name] = {"minutes": minutes, "transfers": transfers}

    for hub_name, hub_codes in HUBS.items():
        for code, (raw_minutes, transfers) in shortest_times(graph, hub_codes).items():
            minutes = round(raw_minutes)
            name = stations[code]
            # '서울역'처럼 이름 자체에 '역'이 붙은 곳은 두 번 붙이지 않는다.
            display = name if name.endswith("역") else f"{name}역"
            put(records, f"{display} {line_for_code(code)}".strip(), hub_name, minutes, transfers)
            # 노선 표기가 달라도 찾을 수 있게 역 이름만으로도 남긴다.
            put(fallback, name, hub_name, minutes, transfers)

    return {
        "version": MATRIX_VERSION,
        "source": MATRIX_SOURCE,
        "hubs": list(HUBS),
        "stationCount": len(records),
        "records": records,
        "byStationName": fallback,
    }


def save_matrix(path=MATRIX_PATH, code_path=STATION_CODE_PATH):
    payload = build_matrix(code_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    return payload


# ── 조회 ───────────────────────────────────────────────────────────────

def load_matrix(path=MATRIX_PATH):
    global _MATRIX_CACHE
    if _MATRIX_CACHE is not None:
        return _MATRIX_CACHE
    try:
        with open(path, encoding="utf-8") as handle:
            _MATRIX_CACHE = json.load(handle)
    except (OSError, ValueError):
        _MATRIX_CACHE = {"records": {}, "version": MATRIX_VERSION, "source": MATRIX_SOURCE}
    return _MATRIX_CACHE


def reset_cache():
    global _MATRIX_CACHE
    _MATRIX_CACHE = None


def _walk_minutes(distance_m):
    try:
        distance = float(distance_m)
    except (TypeError, ValueError):
        return None
    if distance <= 0:
        return None
    return max(1, round(distance / WALK_METERS_PER_MIN))


def commute_profile(station_name, station_distance_m=None, path=MATRIX_PATH):
    """단지 하나의 업무지구별 소요시간.

    `station_name`은 캐시 표기 그대로 '개봉역 1호선' 형태를 받는다.
    반환 형태를 고정해 두면 나중에 실제 경로 API로 바꿔도 화면은 그대로다.
    """
    matrix = load_matrix(path)
    key = str(station_name or "").strip()
    parts = key.split()
    base = parts[0][:-1] if parts and parts[0].endswith("역") else (parts[0] if parts else "")
    base = STATION_ALIASES.get(base, base)
    line = " ".join(parts[1:]) if len(parts) > 1 else ""

    record = (matrix.get("records") or {}).get(key)
    if not record:
        # 노선 표기가 캐시와 다를 수 있어(안산선→수인분당선 등) 역 이름으로 되찾는다.
        by_name = matrix.get("byStationName") or {}
        record = by_name.get(base) or by_name.get(f"{base}역")
    if not record:
        return None
    walk = _walk_minutes(station_distance_m)
    hubs = {}
    for hub_name, value in record.items():
        ride = value.get("minutes")
        if ride is None:
            continue
        transfers = value.get("transfers", 0)
        total = ride + (walk or 0)
        hubs[hub_name] = {
            "rideMinutes": ride,
            "walkMinutes": walk,
            "totalMinutes": total,
            "transfers": transfers,
            "label": _hub_label(hub_name, total, transfers),
        }
    if not hubs:
        return None
    fastest = min(hubs.items(), key=lambda item: item[1]["totalMinutes"])
    return {
        "station": base,
        "line": line,
        "walkMinutes": walk,
        "hubs": hubs,
        "fastestHub": fastest[0],
        "fastestMinutes": fastest[1]["totalMinutes"],
        "estimated": True,
        "source": matrix.get("source", MATRIX_SOURCE),
    }


def _hub_label(hub_name, total_minutes, transfers):
    transfer_text = "환승 없이" if transfers == 0 else f"{transfers}번 갈아타고"
    return f"{hub_name}까지 {transfer_text} 약 {total_minutes}분"


def profile_for_apartment(record, path=MATRIX_PATH):
    """apartment_station_distances.json의 레코드 한 건을 그대로 받는다."""
    if not record:
        return None
    return commute_profile(
        record.get("nearestStationName"),
        record.get("nearestStationDistance"),
        path=path,
    )


# ── 점수화 ─────────────────────────────────────────────────────────────

# 40분 부근을 기준선으로 둔다. 수도권 직장인 평균 편도 통근시간이 대략
# 이 부근이라 "평균보다 가까운가"를 그대로 점수로 옮길 수 있다.
COMMUTE_SCORE_BANDS = (
    (25, 100.0, "25분 이내"),
    (35, 85.0, "35분 이내"),
    (45, 68.0, "45분 이내"),
    (60, 48.0, "1시간 이내"),
    (75, 30.0, "1시간 15분 이내"),
)


def commute_access_score(profile, targets=None):
    """직장권 접근성 점수(0~100)와 근거 문장.

    targets가 있으면 사용자가 고른 업무지구만 본다. 없으면 세 곳 중 가장
    빠른 곳을 기준으로 한다. 사용자가 직장권을 입력하지 않아도 점수가
    나오게 하려는 의도다.
    """
    if not profile:
        return None, "지하철 노선 데이터를 찾지 못함"
    hubs = profile.get("hubs") or {}
    picked = {name: value for name, value in hubs.items() if not targets or name in targets}
    if not picked:
        picked = hubs
    name, value = min(picked.items(), key=lambda item: item[1]["totalMinutes"])
    total = value["totalMinutes"]
    station = profile.get("station")
    for limit, score, band in COMMUTE_SCORE_BANDS:
        if total <= limit:
            return score, f"{station} 기준 {name} {band}(약 {total}분) · 역 수 기준 추정"
    return 12.0, f"{station} 기준 {name}까지 약 {total}분 · 역 수 기준 추정"


if __name__ == "__main__":
    payload = save_matrix()
    print(f"{payload['stationCount']}개 역 저장 · {MATRIX_PATH}")
