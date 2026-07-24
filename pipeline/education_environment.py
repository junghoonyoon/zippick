#!/usr/bin/env python3
"""서울·경기 아파트 교육환경 점수.

공식 학구도 원자료를 앱에서 쓰기 쉬운 JSON으로 변환한 뒤 사용한다. 학구도
원자료가 아직 비어 있으면 카카오 Local 장소 검색으로 주변 초·중학교와 학원
접근성을 보조 계산해 로컬 JSON에 캐시한다. 이 보조 계산값은 배정학교 확정이
아니므로 화면에도 주변 접근성 기준이라고 표시한다.
"""
import datetime
import json
import math
import os
import time

import config
import kakao_station_distances


DATA_PATH = config.ROOT / "data" / "education_environment_seoul_gyeonggi.json"
SCORE_FORMULA_VERSION = "education-env-v1"
SUPPORTED_REGIONS = {"서울특별시", "경기도"}
KAKAO_CATEGORY_RADIUS_METERS = 2000
KAKAO_ACADEMY_RADIUS_METERS = 1000
_DATASET = None


def reset_memory_cache():
    global _DATASET
    _DATASET = None


def _load_dataset():
    global _DATASET
    if _DATASET is not None:
        return _DATASET
    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    _DATASET = {
        "records": payload.get("records") if isinstance(payload.get("records"), dict) else {},
        "zones": payload.get("zones") if isinstance(payload.get("zones"), list) else [],
        "schools": {
            str(row.get("code") or row.get("schoolCode") or "").strip(): row
            for row in (payload.get("schools") if isinstance(payload.get("schools"), list) else [])
            if isinstance(row, dict)
        },
        "dataThrough": str(payload.get("dataThrough") or "").strip(),
        "source": str(payload.get("source") or "").strip(),
        "sourceUrl": str(payload.get("sourceUrl") or "").strip(),
    }
    return _DATASET


def _save_precomputed_record(apartment_id, record):
    global _DATASET
    if not apartment_id or not isinstance(record, dict):
        return
    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    records = payload.get("records")
    if not isinstance(records, dict):
        records = {}
    records[str(apartment_id)] = record
    payload["records"] = records
    payload.setdefault("schemaVersion", 1)
    payload["scoreFormulaVersion"] = SCORE_FORMULA_VERSION
    payload["dataThrough"] = datetime.date.today().isoformat()
    payload["source"] = "kakao-local-v2"
    payload["sourceUrl"] = "https://developers.kakao.com/docs/latest/ko/local/dev-guide"
    payload["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(DATA_PATH)
    _DATASET = None


def _region_supported(entity):
    province = str((entity or {}).get("province") or "").strip()
    return province in SUPPORTED_REGIONS


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distance_meters(left_lat, left_lon, right_lat, right_lon):
    values = [_float_or_none(value) for value in (left_lat, left_lon, right_lat, right_lon)]
    if any(value is None for value in values):
        return None
    lat1, lon1, lat2, lon2 = [math.radians(value) for value in values]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def elementary_distance_score(distance_meters):
    distance = _float_or_none(distance_meters)
    if distance is None:
        return None
    if distance <= 500:
        return 100.0
    if distance <= 700:
        return 88.0
    if distance <= 1000:
        return 68.0
    if distance <= 1500:
        return 38.0
    return 18.0


def academy_access_score(count_1km):
    count = _float_or_none(count_1km)
    if count is None:
        return None
    if count >= 80:
        return 100.0
    if count >= 40:
        return 85.0
    if count >= 20:
        return 65.0
    if count >= 10:
        return 45.0
    if count >= 3:
        return 25.0
    return 10.0


def middle_distance_score(distance_meters):
    distance = _float_or_none(distance_meters)
    if distance is None:
        return None
    if distance <= 800:
        return 100.0
    if distance <= 1200:
        return 86.0
    if distance <= 1600:
        return 68.0
    if distance <= 2200:
        return 42.0
    return 18.0


def _kakao_category_places(category_group_code, lat, lon, radius, max_pages=3):
    if not kakao_station_distances.configured():
        return []
    places = []
    seen = set()
    for page in range(1, max_pages + 1):
        payload = kakao_station_distances._request_json("search/category.json", {
            "category_group_code": category_group_code,
            "x": lon,
            "y": lat,
            "radius": radius,
            "sort": "distance",
            "page": page,
            "size": 15,
        })
        documents = payload.get("documents") or []
        for document in documents:
            place_id = str(document.get("id") or "") or "|".join((
                str(document.get("place_name") or ""),
                str(document.get("x") or ""),
                str(document.get("y") or ""),
            ))
            if place_id in seen:
                continue
            seen.add(place_id)
            places.append(document)
        if payload.get("meta", {}).get("is_end", True):
            break
        time.sleep(0.08)
    return places


def _place_distance(place):
    return _float_or_none(place.get("distance"))


def _place_name(place):
    return str(place.get("place_name") or "").strip()


def _school_level(place):
    name = _place_name(place)
    category = str(place.get("category_name") or "")
    text = f"{name} {category}"
    if "초등학교" in text or name.endswith("초"):
        return "elementary"
    if "중학교" in text or name.endswith("중"):
        return "middle"
    return ""


def _score_from_nearby_places(lat, lon):
    school_places = _kakao_category_places("SC4", lat, lon, KAKAO_CATEGORY_RADIUS_METERS, max_pages=3)
    academy_places = _kakao_category_places("AC5", lat, lon, KAKAO_ACADEMY_RADIUS_METERS, max_pages=3)
    elementary = [
        place for place in school_places
        if _school_level(place) == "elementary" and _place_distance(place) is not None
    ]
    middle = [
        place for place in school_places
        if _school_level(place) == "middle" and _place_distance(place) is not None
    ]
    elementary.sort(key=lambda place: _place_distance(place) or 10**9)
    middle.sort(key=lambda place: _place_distance(place) or 10**9)
    elementary_distance = _place_distance(elementary[0]) if elementary else None
    middle_distance = _place_distance(middle[0]) if middle else None
    elementary_score = elementary_distance_score(elementary_distance)
    middle_score = middle_distance_score(middle_distance)
    academy_score = academy_access_score(len(academy_places))
    confidence_score = 100.0 if elementary_score is not None or middle_score is not None else None
    score, coverage = _normalize_weighted_score((
        (elementary_score, 40),
        (middle_score, 25),
        (academy_score, 25),
        (confidence_score, 10),
    ))
    if score is None:
        return None
    return {
        "status": "ok",
        "basis": "nearby_school_access",
        "score": score,
        "coverage": coverage,
        "scoreFormulaVersion": SCORE_FORMULA_VERSION,
        "elementarySchoolNames": [_place_name(place) for place in elementary[:3] if _place_name(place)],
        "elementaryDistanceMeters": round(elementary_distance) if elementary_distance is not None else None,
        "middleSchoolNames": [_place_name(place) for place in middle[:3] if _place_name(place)],
        "middleDistanceMeters": round(middle_distance) if middle_distance is not None else None,
        "academyCount1km": len(academy_places),
    }


def _point_in_ring(lon, lat, ring):
    inside = False
    if len(ring) < 3:
        return False
    prev_lon, prev_lat = ring[-1][:2]
    for point in ring:
        curr_lon, curr_lat = point[:2]
        intersects = ((curr_lat > lat) != (prev_lat > lat)) and (
            lon < (prev_lon - curr_lon) * (lat - curr_lat) / ((prev_lat - curr_lat) or 1e-12) + curr_lon
        )
        if intersects:
            inside = not inside
        prev_lon, prev_lat = curr_lon, curr_lat
    return inside


def _point_in_polygon(lon, lat, polygon):
    if not polygon:
        return False
    if not _point_in_ring(lon, lat, polygon[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:])


def _contains_point(geometry, lon, lat):
    if not isinstance(geometry, dict):
        return False
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return _point_in_polygon(lon, lat, coordinates)
    if kind == "MultiPolygon":
        return any(_point_in_polygon(lon, lat, polygon) for polygon in coordinates)
    return False


def _matching_zones(dataset, level, lon, lat):
    matches = []
    for zone in dataset["zones"]:
        if not isinstance(zone, dict) or str(zone.get("level") or "") != level:
            continue
        if _contains_point(zone.get("geometry"), lon, lat):
            matches.append(zone)
    return matches


def _school_distance(dataset, zone, lat, lon):
    distances = []
    school_rows = []
    for code in zone.get("schoolCodes") or []:
        school = dataset["schools"].get(str(code))
        if not school:
            continue
        distance = _distance_meters(lat, lon, school.get("latitude"), school.get("longitude"))
        if distance is None:
            continue
        school_rows.append({
            "name": school.get("name") or school.get("schoolName") or "",
            "code": str(code),
            "distanceMeters": round(distance),
        })
        distances.append(distance)
    if not distances:
        return None, school_rows
    return min(distances), sorted(school_rows, key=lambda row: row["distanceMeters"])


def _normalize_weighted_score(parts):
    available = [
        (score, weight)
        for score, weight in parts
        if score is not None and weight > 0
    ]
    if not available:
        return None
    weighted = sum(score * weight for score, weight in available)
    total_weight = sum(weight for _score, weight in available)
    coverage = total_weight / sum(weight for _score, weight in parts if weight > 0)
    return round(weighted / total_weight), round(coverage, 2)


def _score_from_record(record):
    score = _float_or_none(record.get("score"))
    if score is not None:
        score = max(0, min(100, round(score)))
        coverage = _float_or_none(record.get("coverage"))
        return {
            **record,
            "status": "ok",
            "score": score,
            "coverage": coverage if coverage is not None else 1.0,
            "scoreFormulaVersion": SCORE_FORMULA_VERSION,
        }
    elementary_score = elementary_distance_score(record.get("elementaryDistanceMeters"))
    middle_score = 100.0 if record.get("middleZoneName") or record.get("middleSchoolNames") else None
    academy_score = academy_access_score(record.get("academyCount1km"))
    confidence_score = 100.0 if elementary_score is not None or middle_score is not None else None
    score, coverage = _normalize_weighted_score((
        (elementary_score, 40),
        (middle_score, 20),
        (academy_score, 30),
        (confidence_score, 10),
    ))
    if score is None:
        return None
    return {
        **record,
        "status": "ok",
        "score": score,
        "coverage": coverage,
        "scoreFormulaVersion": SCORE_FORMULA_VERSION,
    }


def education_environment_for_entity(entity):
    if not _region_supported(entity):
        return {"status": "unsupported_region", "score": None}
    dataset = _load_dataset()
    apartment_id = kakao_station_distances.entity_id(entity)
    record = dataset["records"].get(apartment_id)
    if isinstance(record, dict):
        scored = _score_from_record(record)
        if scored:
            return _with_metadata(scored, dataset)

    station_record = kakao_station_distances.cached_station(entity)
    lat = _float_or_none((station_record or {}).get("latitude"))
    lon = _float_or_none((station_record or {}).get("longitude"))
    if lat is None or lon is None:
        return _with_metadata({"status": "no_coordinates", "score": None}, dataset)

    elementary_zones = _matching_zones(dataset, "elementary", lon, lat)
    middle_zones = _matching_zones(dataset, "middle", lon, lat)
    if not elementary_zones and not middle_zones:
        try:
            nearby_record = _score_from_nearby_places(lat, lon)
        except Exception:
            nearby_record = None
        if nearby_record:
            nearby_record = _with_metadata(nearby_record, dataset)
            _save_precomputed_record(apartment_id, nearby_record)
            return nearby_record
        return _with_metadata({"status": "no_zone_match", "score": None}, dataset)

    elementary_zone = elementary_zones[0] if elementary_zones else {}
    middle_zone = middle_zones[0] if middle_zones else {}
    distance, schools = _school_distance(dataset, elementary_zone, lat, lon)
    record = {
        "elementaryZoneName": elementary_zone.get("name") or "",
        "elementarySchoolNames": [row["name"] for row in schools if row.get("name")],
        "elementaryDistanceMeters": round(distance) if distance is not None else None,
        "middleZoneName": middle_zone.get("name") or "",
        "middleSchoolNames": middle_zone.get("schoolNames") or [],
        "academyCount1km": None,
    }
    scored = _score_from_record(record)
    return _with_metadata(scored or {"status": "insufficient", "score": None}, dataset)


def _with_metadata(record, dataset):
    return {
        **record,
        "dataThrough": dataset.get("dataThrough", ""),
        "source": dataset.get("source", ""),
        "sourceUrl": dataset.get("sourceUrl", ""),
    }


def attach_education_environment(rows):
    for row in rows:
        try:
            entity = getattr(row, "_entity", None) or None
            if not entity:
                continue
            row["educationEnvironment"] = education_environment_for_entity(entity)
        except Exception:
            row["educationEnvironment"] = {"status": "error", "score": None}
    return rows
