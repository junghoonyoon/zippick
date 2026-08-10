#!/usr/bin/env python3
"""Nearby redevelopment influence for apartment purchase scoring."""

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "redevelopment_zones.geojson"
PROJECT_TYPES = (
    "재개발",
    "재건축",
    "뉴타운",
    "신속통합기획",
    "모아타운",
    "가로주택정비",
    "주거복합",
)
STAGES = (
    "검토·후보지",
    "정비구역 지정",
    "추진위원회",
    "조합설립인가",
    "건축심의",
    "사업시행인가",
    "관리처분인가",
    "이주·철거",
    "착공",
    "입주 예정",
    "완료",
)
STAGE_PROGRESS = {stage: index for index, stage in enumerate(STAGES)}

# 단계를 알 수 없는 구역에 쓰는 값. STAGES에 넣지 않아 가점·감점 계산에서 빠진다.
STAGE_UNKNOWN = "확인 필요"

# 관리처분인가를 받으면 통상 몇 달 안에 이주가 시작된다.
# 원본 공간정보에는 이주·철거 단계가 없어서, 이 단계부터 이주 임박으로 본다.
IMMINENT_MOVE_OUT_STAGES = ("관리처분인가", "이주·철거")

# 이 단계부터는 기존 주택이 이미 없어졌다고 본다.
DEMOLISHED_STAGES = ("이주·철거", "착공", "입주 예정")

COMPLETED_PROJECT_IDS = {
    # 새절역 두산위브 트레지움. 원본 공간정보에는 신사1/착공으로 남아 있어 영향 계산에서 제외한다.
    "11000UQ120PS202411014108",
}

# 이주 이야기를 꺼낼 거리 기준.
# 화면에 '이주를 앞두고 있어요'를 띄우는 기준과, 과거 사례를 세는 기준을
# 같은 값으로 맞춘다. 다르면 말만 꺼내고 근거는 못 보여주는 화면이 나온다.
MOVE_OUT_NEARBY_METERS = 500
_CACHE = {"mtime": None, "projects": []}


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact(value):
    return "".join(str(value or "").split())


def _coordinates(row, entity):
    for source in (row or {}, entity or {}):
        lat = _float(source.get("latitude") or source.get("lat") or source.get("y"))
        lng = _float(source.get("longitude") or source.get("lng") or source.get("x"))
        if lat is not None and lng is not None and 32 <= lat <= 39 and 124 <= lng <= 132:
            return {"latitude": lat, "longitude": lng}
    return None


def _project_type(raw):
    text = _compact(raw)
    # 존치구역은 정비를 하지 않는 곳이라 영향 계산에서 뺀다.
    if "존치" in text:
        return None
    # 청년안심·장기전세 같은 임대주택 중심 사업은 매매가 판단용 정비사업에서 뺀다.
    if any(keyword in text for keyword in (
        "청년안심",
        "역세권청년",
        "장기전세",
        "행복주택",
        "희망하우징",
        "공공임대",
        "국민임대",
        "영구임대",
        "임대주택",
        "미리내집",
    )):
        return None
    if "뉴타운" in text or "재정비촉진" in text:
        return "뉴타운"
    # 신속통합기획은 재개발·재건축을 빨리 진행하는 별도 트랙이라 유형을 따로 둔다.
    if "신속통합" in text:
        return "신속통합기획"
    if "재건축" in text:
        return "재건축"
    if "재개발" in text or "주택정비형" in text or "주거환경개선" in text:
        return "재개발"
    if "모아타운" in text or "소규모주택정비관리지역" in text:
        return "모아타운"
    if "가로주택" in text or "자율주택" in text:
        return "가로주택정비"
    if (
        "주거복합" in text
        or "복합개발" in text
        or "택지" in text
        or "공공주택" in text
        or "역세권활성화" in text
        or "시장정비" in text
        or "도시개발" in text
    ):
        return "주거복합"
    return None


def _stage(raw):
    """원본 공간정보의 단계값을 집픽 단계로 옮긴다.

    원본에는 '이주·철거' 단계가 없다. 관리처분인가 뒤에 이주가 시작되므로
    이주 여부는 IMMINENT_MOVE_OUT_STAGES로 따로 판단한다.
    """
    text = _compact(raw)
    if not text:
        return STAGE_UNKNOWN
    if "확인필요" in text:
        return STAGE_UNKNOWN
    # 후보지로 뽑히기만 한 단계. 아래 '추진중' 규칙보다 먼저 걸러야 한다.
    if "대상지선정" in text or "후보지선정" in text or "입안제안" in text:
        return "검토·후보지"

    # 끝난 사업이 먼저다. '준공', '사용승인', '입주'가 여기 들어간다.
    if "준공" in text or "사용승인" in text or "사업완료" in text:
        return "완료"
    if "입주자모집" in text or "분양공고" in text:
        return "입주 예정"
    if "입주" in text:
        return "완료"
    if "착공" in text:
        return "착공"
    if "이주" in text or "철거" in text:
        return "이주·철거"
    if "관리처분" in text:
        return "관리처분인가"
    # 인가·승인·허가를 받은 단계는 모두 사업시행인가 수준으로 본다.
    if (
        "사업시행" in text
        or "사업계획승인" in text
        or "실시계획인가" in text
        or "건축허가" in text
        or "리모델링허가" in text
    ):
        return "사업시행인가"
    # 심의는 인가 직전 단계다. 인가와 같은 취급을 하지 않는다.
    if "심의" in text:
        return "건축심의"
    # '추진중'은 아직 인가를 받지 않았다는 뜻이라 조합설립인가로 올리지 않는다.
    if "추진중" in text or "추진위" in text or "추진계획" in text:
        return "추진위원회"
    if "조합설립" in text or "주민합의체" in text:
        return "조합설립인가"
    if (
        "정비구역" in text
        or "구역지정" in text
        or "지구지정" in text
        or "지구변경" in text
        or "지구계획승인" in text
        or "관리지역고시" in text
        or "정비계획수립" in text
        or "촉진계획수립" in text
        or "활성화계획수립" in text
    ):
        return "정비구역 지정"
    return "검토·후보지"


def _geometry_points(geometry):
    points = []

    def walk(value):
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            points.append((float(value[1]), float(value[0])))
            return
        for child in value:
            walk(child)

    walk((geometry or {}).get("coordinates"))
    return points


def _distance_meters(a, b):
    lat1 = math.radians(a["latitude"])
    lat2 = math.radians(b["latitude"])
    dlat = math.radians(b["latitude"] - a["latitude"])
    dlng = math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0, 1 - h)))


def _zone_distance(point, project):
    distances = [
        _distance_meters(point, {"latitude": lat, "longitude": lng})
        for lat, lng in project.get("_points", [])
    ]
    return min(distances) if distances else None


def _load_projects():
    try:
        mtime = DATA_PATH.stat().st_mtime
    except OSError:
        return []
    if _CACHE["mtime"] == mtime:
        return _CACHE["projects"]
    try:
        with DATA_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        _CACHE.update({"mtime": mtime, "projects": []})
        return []
    projects = []
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        project_id = str(feature.get("id") or properties.get("id") or "")
        if project_id in COMPLETED_PROJECT_IDS:
            continue
        project_type = _project_type(properties.get("projectType") or properties.get("type"))
        if project_type not in PROJECT_TYPES:
            continue
        stage = _stage(properties.get("stage"))
        if stage == "완료":
            continue
        points = _geometry_points(feature.get("geometry") or {})
        if not points:
            continue
        projects.append({
            "id": project_id,
            "name": str(properties.get("name") or "정비구역"),
            "type": project_type,
            "stage": stage,
            # 공식 공간정보에는 세대수가 없다. 값이 들어오면 그대로 쓰고,
            # 없으면 None으로 남겨 화면에서 '아직 몰라요'로 보여준다.
            "plannedHouseholds": _float(
                properties.get("plannedHouseholds") or properties.get("세대수")
            ),
            "areaSqm": _float(properties.get("areaSqm")),
            "expectedCompletionYear": properties.get("expectedCompletionYear") or properties.get("준공예정연도"),
            "sourceDate": properties.get("sourceDate") or "2026-02",
            "confidence": "high" if project_type in {"재개발", "재건축", "뉴타운"} else "medium",
            "_points": points,
        })
    _CACHE.update({"mtime": mtime, "projects": projects})
    return projects


def nearby_projects(row, entity, radius_meters=3000, limit=8):
    point = _coordinates(row, entity)
    if not point:
        return [], "no_coordinates"
    projects = []
    for project in _load_projects():
        distance = _zone_distance(point, project)
        if distance is None or distance > radius_meters:
            continue
        item = {key: value for key, value in project.items() if not key.startswith("_")}
        item["distanceMeters"] = int(round(distance))
        projects.append(item)
    projects.sort(key=lambda item: (0 if item["distanceMeters"] <= 1000 else 1, item["distanceMeters"]))
    return projects[:limit], "ok"


def influence_score(row, entity):
    projects, status = nearby_projects(row, entity)
    if status != "ok":
        return 50, "좌표가 없어 중립점수로 계산했어요", {
            "status": "missing",
            "projects": [],
            "reason": status,
            "neutralPoints": 2,
        }
    if not projects:
        return 50, "반경 3km 안 공식 정비사업 데이터가 없어 중립점수로 계산했어요", {
            "status": "missing",
            "projects": [],
            "reason": "no_projects",
            "neutralPoints": 2,
        }

    # 단계를 모르는 구역은 가점도 감점도 하지 않는다.
    staged = [project for project in projects if project["stage"] in STAGE_PROGRESS]
    direct = [project for project in projects if project["distanceMeters"] <= 1000]
    later = [
        project for project in staged
        if STAGE_PROGRESS[project["stage"]] >= STAGE_PROGRESS["사업시행인가"]
    ]
    early = [
        project for project in staged
        if STAGE_PROGRESS[project["stage"]] <= STAGE_PROGRESS["추진위원회"]
    ]
    known_supply = [
        int(project["plannedHouseholds"])
        for project in projects
        if project.get("plannedHouseholds")
    ]
    large_supply = sum(known_supply)
    # 세대수는 구역 면적으로 대신 세지 않는다. 값이 없으면 공급 감점을 건너뛴다.
    supply_known = bool(known_supply)

    score = 50
    score += min(20, len(direct) * 8 + max(0, len(projects) - len(direct)) * 3)
    score += min(18, len(later) * 9)
    score -= min(16, len(early) * 5)
    if supply_known and large_supply >= 3000:
        score -= 12
    elif len(projects) >= 4:
        score -= 6
    if any(project["distanceMeters"] <= 400 and project["stage"] in IMMINENT_MOVE_OUT_STAGES for project in projects):
        score -= 6
    if any(project["stage"] in DEMOLISHED_STAGES for project in direct):
        score -= 5

    score = max(20, min(88, score))
    closest = projects[0]
    scope = "직접 영향권" if closest["distanceMeters"] <= 1000 else "생활권 영향권"
    reason = f"{scope} {closest['name']} · {closest['stage']} 단계"
    move_out = [
        project for project in projects
        if project["distanceMeters"] <= MOVE_OUT_NEARBY_METERS
        and project["stage"] in IMMINENT_MOVE_OUT_STAGES
    ]
    return round(score), reason, {
        "status": "ok",
        "projects": projects,
        "directCount": len(direct),
        "lifestyleCount": len(projects) - len(direct),
        "laterStageCount": len(later),
        "earlyStageCount": len(early),
        "supplyHouseholds": large_supply if supply_known else None,
        "supplyHouseholdsKnown": supply_known,
        "moveOutNearby": [
            {
                "name": project["name"],
                "stage": project["stage"],
                "distanceMeters": project["distanceMeters"],
            }
            for project in move_out
        ],
        "checks": [
            "주거환경 개선 가능성",
            "새 아파트 공급 부담",
            "사업 진행 가능성",
            "가격에 먼저 반영됐을 가능성",
        ],
    }
