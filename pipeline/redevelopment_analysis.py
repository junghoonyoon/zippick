#!/usr/bin/env python3
"""Nearby redevelopment influence for apartment purchase scoring."""

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "redevelopment_zones.geojson"
PROJECT_TYPES = ("재개발", "재건축", "뉴타운", "모아타운", "가로주택정비", "주거복합")
STAGES = (
    "검토·후보지",
    "정비구역 지정",
    "추진위원회",
    "조합설립인가",
    "사업시행인가",
    "관리처분인가",
    "이주·철거",
    "착공",
    "입주 예정",
    "완료",
)
STAGE_PROGRESS = {stage: index for index, stage in enumerate(STAGES)}
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
    text = str(raw or "")
    if "뉴타운" in text or "재정비촉진" in text:
        return "뉴타운"
    if "재건축" in text:
        return "재건축"
    if "재개발" in text or "주택정비형" in text:
        return "재개발"
    if "모아타운" in text or "소규모주택정비 관리지역" in text:
        return "모아타운"
    if "가로주택" in text:
        return "가로주택정비"
    if "주거복합" in text or "복합개발" in text or "택지" in text or "공공주택" in text:
        return "주거복합"
    return None


def _stage(raw):
    text = str(raw or "")
    if "입주 예정" in text:
        return "입주 예정"
    if "입주" in text or "준공" in text:
        return "완료"
    if "착공" in text:
        return "착공"
    if "이주" in text or "철거" in text:
        return "이주·철거"
    if "관리처분" in text:
        return "관리처분인가"
    if "사업시행" in text:
        return "사업시행인가"
    if "조합설립" in text:
        return "조합설립인가"
    if "추진위원" in text:
        return "추진위원회"
    if "정비구역" in text or "구역지정" in text:
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
        project_type = _project_type(properties.get("projectType") or properties.get("type"))
        if project_type not in PROJECT_TYPES:
            continue
        points = _geometry_points(feature.get("geometry") or {})
        if not points:
            continue
        projects.append({
            "id": str(feature.get("id") or properties.get("id") or ""),
            "name": str(properties.get("name") or "정비구역"),
            "type": project_type,
            "stage": _stage(properties.get("stage")),
            "plannedHouseholds": properties.get("plannedHouseholds") or properties.get("세대수"),
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

    direct = [project for project in projects if project["distanceMeters"] <= 1000]
    later = [project for project in projects if STAGE_PROGRESS.get(project["stage"], 0) >= STAGE_PROGRESS["사업시행인가"]]
    early = [project for project in projects if STAGE_PROGRESS.get(project["stage"], 0) <= STAGE_PROGRESS["추진위원회"]]
    large_supply = sum(int(_float(project.get("plannedHouseholds")) or 0) for project in projects)

    score = 50
    score += min(20, len(direct) * 8 + max(0, len(projects) - len(direct)) * 3)
    score += min(18, len(later) * 9)
    score -= min(16, len(early) * 5)
    if large_supply >= 3000:
        score -= 12
    elif len(projects) >= 4:
        score -= 6
    if any(project["distanceMeters"] <= 400 and project["stage"] in {"관리처분인가", "이주·철거", "착공"} for project in projects):
        score -= 6
    if any(project["stage"] in {"관리처분인가", "이주·철거", "착공", "입주 예정"} for project in direct):
        score -= 5

    score = max(20, min(88, score))
    closest = projects[0]
    scope = "직접 영향권" if closest["distanceMeters"] <= 1000 else "생활권 영향권"
    reason = f"{scope} {closest['name']} · {closest['stage']} 단계"
    return round(score), reason, {
        "status": "ok",
        "projects": projects,
        "directCount": len(direct),
        "lifestyleCount": len(projects) - len(direct),
        "laterStageCount": len(later),
        "earlyStageCount": len(early),
        "supplyHouseholds": large_supply or None,
        "checks": [
            "주거환경 개선 가능성",
            "새 아파트 공급 부담",
            "사업 진행 가능성",
            "가격에 먼저 반영됐을 가능성",
        ],
    }
