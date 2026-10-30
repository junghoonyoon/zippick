#!/usr/bin/env python3
"""서울·경기·인천 아파트 교육 접근성 점수.

서울·경기 공식 학구도와 역 거리 캐시를 사용한다. 학구도 자료가 없는 인천이나
기준 자료에 없는 지역은 카카오 Local 장소 검색으로 주변 초·중학교와 학원
접근성을 보조 계산해 공유 캐시에 저장한다. 이 값은 배정학교 확정이 아니므로
화면에도 주변 접근성 기준이라고 표시한다.
"""
import argparse
import datetime
import json
import math
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import config
import kakao_station_distances
import persistent_json_store


DATA_PATH = config.ROOT / "data" / "education_environment_seoul_gyeonggi.json"
OVERLAY_PATH = config.ROOT / "data" / "education_environment_extra_records.json"
RECORDS_PATH = config.CACHE_DIR / "education_environment_records.json"
SCORE_FORMULA_VERSION = "education-env-v1"
SUPPORTED_REGIONS = {"서울특별시", "경기도", "인천광역시"}
KAKAO_CATEGORY_RADIUS_METERS = 2000
KAKAO_ACADEMY_RADIUS_METERS = 1000
_DATASET = None
_DATASET_REVISION = None
_DATASET_LOCK = threading.RLock()
_LEGACY_MIGRATION_DONE = False


def reset_memory_cache():
    global _DATASET, _DATASET_REVISION, _LEGACY_MIGRATION_DONE
    with _DATASET_LOCK:
        _DATASET = None
        _DATASET_REVISION = None
        _LEGACY_MIGRATION_DONE = False


def _path_revision(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _dataset_revision():
    return tuple(_path_revision(path) for path in (DATA_PATH, OVERLAY_PATH, RECORDS_PATH))


def _read_dataset_file(path):
    if path == RECORDS_PATH:
        return persistent_json_store.read_json_object(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _migrate_legacy_release_records(releases_root=None, current_release=None):
    """Move records saved inside old release folders into the shared cache once."""
    global _LEGACY_MIGRATION_DONE
    if _LEGACY_MIGRATION_DONE:
        return
    if releases_root is None:
        releases_root = config.ROOT.parent
        if releases_root.name != "releases":
            return
    releases_root = releases_root.resolve()
    current_release = Path(current_release or config.ROOT).resolve()
    legacy_files = []
    try:
        for release in releases_root.iterdir():
            if not release.is_dir() or release.resolve() == current_release:
                continue
            legacy_path = release / "data" / DATA_PATH.name
            try:
                revision = legacy_path.stat().st_mtime_ns
            except OSError:
                continue
            legacy_files.append((revision, legacy_path))
    except OSError:
        _LEGACY_MIGRATION_DONE = True
        return
    legacy_files.sort(key=lambda item: item[0])
    if not legacy_files:
        _LEGACY_MIGRATION_DONE = True
        return

    with _DATASET_LOCK, persistent_json_store.exclusive_file_lock(RECORDS_PATH):
        payload = persistent_json_store.read_json_object(RECORDS_PATH)
        records = payload.get("records")
        if isinstance(records, dict) and records:
            _LEGACY_MIGRATION_DONE = True
            return
        merged = {}
        latest_data_through = ""
        for _revision, legacy_path in legacy_files:
            legacy = _read_dataset_file(legacy_path)
            rows = legacy.get("records")
            if not isinstance(rows, dict):
                continue
            formula_version = legacy.get("scoreFormulaVersion") or SCORE_FORMULA_VERSION
            for apartment_id, record in rows.items():
                if isinstance(record, dict):
                    merged[str(apartment_id)] = {
                        **record,
                        "scoreFormulaVersion": record.get("scoreFormulaVersion") or formula_version,
                    }
            latest_data_through = max(
                latest_data_through,
                str(legacy.get("dataThrough") or "").strip(),
            )
        if merged:
            payload.update({
                "schemaVersion": 1,
                "scoreFormulaVersion": SCORE_FORMULA_VERSION,
                "dataThrough": latest_data_through or datetime.date.today().isoformat(),
                "source": "legacy-release-migration",
                "sourceUrl": "https://developers.kakao.com/docs/latest/ko/local/dev-guide",
                "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "records": merged,
            })
            persistent_json_store.write_json_atomically(RECORDS_PATH, payload)
        _LEGACY_MIGRATION_DONE = True


def _load_dataset():
    global _DATASET, _DATASET_REVISION
    with _DATASET_LOCK:
        _migrate_legacy_release_records()
        revision = _dataset_revision()
        if _DATASET is not None and revision == _DATASET_REVISION:
            return _DATASET
        base = _read_dataset_file(DATA_PATH)
        overlay = _read_dataset_file(OVERLAY_PATH)
        cached = _read_dataset_file(RECORDS_PATH)
        records = {}
        for payload in (base, overlay, cached):
            rows = payload.get("records")
            if isinstance(rows, dict):
                records.update(rows)
        data_through = max(
            (str(payload.get("dataThrough") or "").strip()
             for payload in (base, overlay, cached)),
            default="",
        )
        _DATASET = {
            "records": records,
            "zones": base.get("zones") if isinstance(base.get("zones"), list) else [],
            "schools": {
                str(row.get("code") or row.get("schoolCode") or "").strip(): row
                for row in (base.get("schools") if isinstance(base.get("schools"), list) else [])
                if isinstance(row, dict)
            },
            "dataThrough": data_through,
            "source": str(base.get("source") or "").strip(),
            "sourceUrl": str(base.get("sourceUrl") or "").strip(),
        }
        _DATASET_REVISION = revision
        return _DATASET


def _save_precomputed_records(records):
    global _DATASET, _DATASET_REVISION
    updates = {
        str(apartment_id): {
            **record,
            "scoreFormulaVersion": SCORE_FORMULA_VERSION,
            "source": record.get("source") or "kakao-local-v2",
            "sourceUrl": record.get("sourceUrl") or "https://developers.kakao.com/docs/latest/ko/local/dev-guide",
        }
        for apartment_id, record in (records or {}).items()
        if apartment_id and isinstance(record, dict)
    }
    if not updates:
        return
    with _DATASET_LOCK, persistent_json_store.exclusive_file_lock(RECORDS_PATH):
        payload = persistent_json_store.read_json_object(RECORDS_PATH)
        current = payload.get("records")
        if not isinstance(current, dict):
            current = {}
        current.update(updates)
        payload.update({
            "schemaVersion": 1,
            "scoreFormulaVersion": SCORE_FORMULA_VERSION,
            "dataThrough": datetime.date.today().isoformat(),
            "source": "kakao-local-v2",
            "sourceUrl": "https://developers.kakao.com/docs/latest/ko/local/dev-guide",
            "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "records": current,
        })
        persistent_json_store.write_json_atomically(RECORDS_PATH, payload)
        _DATASET = None
        _DATASET_REVISION = None


def _save_precomputed_record(apartment_id, record):
    _save_precomputed_records({apartment_id: record})


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
        raise kakao_station_distances.KakaoLocalError(
            "카카오 REST API 키가 설정되어 있지 않습니다."
        )
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


def education_environment_for_entity(entity, allow_remote_lookup=True):
    if not _region_supported(entity):
        return {"status": "unsupported_region", "score": None}
    dataset = _load_dataset()
    apartment_id = kakao_station_distances.entity_id(entity)
    record = dataset["records"].get(apartment_id)
    if isinstance(record, dict):
        if (
            record.get("status") == "no_places"
            and record.get("scoreFormulaVersion") == SCORE_FORMULA_VERSION
        ):
            return _with_metadata(record, dataset)
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
        if not allow_remote_lookup:
            return _with_metadata({"status": "not_precomputed", "score": None}, dataset)
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
        "basis": "official_school_zone",
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
        "source": record.get("source") or dataset.get("source", ""),
        "sourceUrl": record.get("sourceUrl") or dataset.get("sourceUrl", ""),
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


def _entity_coordinates(entity):
    station = kakao_station_distances.cached_station(entity) or {}
    lat = _float_or_none(station.get("latitude"))
    lon = _float_or_none(station.get("longitude"))
    if lat is None or lon is None:
        return None
    return lat, lon


def _collect_batch_targets(entities, retry_unavailable=False):
    pending = []
    summary = {
        "requestedCount": len(entities),
        "pendingCount": 0,
        "skippedScoredCount": 0,
        "skippedZoneCount": 0,
        "noCoordinatesCount": 0,
        "noSchoolCount": 0,
        "unsupportedRegionCount": 0,
        "failedCount": 0,
        "apiRequestCount": 0,
        "failures": [],
    }
    for entity in entities:
        if not _region_supported(entity):
            summary["unsupportedRegionCount"] += 1
            continue
        record = education_environment_for_entity(entity, allow_remote_lookup=False)
        if record.get("score") is not None:
            summary["skippedScoredCount"] += 1
            if record.get("basis") == "official_school_zone":
                summary["skippedZoneCount"] += 1
            continue
        if record.get("status") == "no_coordinates" or _entity_coordinates(entity) is None:
            summary["noCoordinatesCount"] += 1
            continue
        if record.get("status") == "no_places" and not retry_unavailable:
            summary["noSchoolCount"] += 1
            continue
        pending.append(entity)
    summary["pendingCount"] = len(pending)
    return pending, summary


def enrich_entities(
    entities,
    *,
    retry_unavailable=False,
    limit=None,
    workers=None,
    dry_run=False,
):
    entities = list(entities)
    if limit is not None:
        entities = entities[:max(0, int(limit))]
    pending, summary = _collect_batch_targets(entities, retry_unavailable)
    summary.update({
        "configured": kakao_station_distances.configured(),
        "source": "kakao-local-v2",
        "distanceType": "straight_line",
        "savedCount": 0,
        "readyCount": summary["skippedScoredCount"],
        "dryRun": bool(dry_run),
    })
    if dry_run or not pending:
        summary["cacheRecordCount"] = len(_load_dataset()["records"])
        return summary
    if not kakao_station_distances.configured():
        summary["haltedReason"] = "configuration"
        summary["failedCount"] = len(pending)
        summary["failures"].append({"error": "카카오 REST API 키가 설정되어 있지 않습니다."})
        return summary

    max_workers = max(1, min(int(workers or config.KAKAO_STATION_MAX_WORKERS), 16))
    updates = {}
    api_request_counter = [0]
    api_request_counter_lock = threading.Lock()
    pending_iter = iter(pending)
    pool = ThreadPoolExecutor(max_workers=max_workers)
    future_entities = {}
    processed_futures = set()
    halted_error = None

    def submit_next():
        try:
            entity = next(pending_iter)
        except StopIteration:
            return False
        future_entities[pool.submit(
            kakao_station_distances.run_counted_api_call,
            _score_from_nearby_places,
            *_entity_coordinates(entity),
            counter=api_request_counter,
            counter_lock=api_request_counter_lock,
        )] = entity
        return True

    def collect(future):
        nonlocal halted_error
        if future.cancelled() or future in processed_futures:
            return
        processed_futures.add(future)
        entity = future_entities[future]
        try:
            record = future.result()
        except Exception as exc:
            summary["failedCount"] += 1
            if len(summary["failures"]) < 20:
                summary["failures"].append({
                    "apartmentName": entity.get("name"),
                    "error": str(exc),
                })
            if isinstance(exc, (
                kakao_station_distances.KakaoAuthenticationError,
                kakao_station_distances.KakaoQuotaError,
                kakao_station_distances.KakaoNetworkError,
            )):
                halted_error = exc
            return
        if record is None:
            record = {
                "status": "no_places",
                "score": None,
                "basis": "nearby_school_access",
                "scoreFormulaVersion": SCORE_FORMULA_VERSION,
                "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source": "kakao-local-v2",
                "sourceUrl": "https://developers.kakao.com/docs/latest/ko/local/dev-guide",
            }
            summary["noSchoolCount"] += 1
        else:
            record = {
                **record,
                "scoreFormulaVersion": SCORE_FORMULA_VERSION,
                "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source": "kakao-local-v2",
                "sourceUrl": "https://developers.kakao.com/docs/latest/ko/local/dev-guide",
            }
            summary["readyCount"] += 1
        updates[kakao_station_distances.entity_id(entity)] = record
        summary["savedCount"] += 1
        if len(updates) >= 250:
            _save_precomputed_records(updates)
            updates.clear()

    try:
        for _ in range(min(max_workers, len(pending))):
            submit_next()
        while future_entities:
            completed, _ = wait(future_entities, return_when=FIRST_COMPLETED)
            for future in completed:
                collect(future)
                future_entities.pop(future, None)
            if halted_error:
                remaining = tuple(future_entities)
                for future in remaining:
                    future.cancel()
                pool.shutdown(wait=True, cancel_futures=True)
                for future in remaining:
                    collect(future)
                future_entities.clear()
                summary["haltedReason"] = (
                    "quota"
                    if isinstance(halted_error, kakao_station_distances.KakaoQuotaError)
                    else "authentication"
                    if isinstance(halted_error, kakao_station_distances.KakaoAuthenticationError)
                    else "network"
                )
                break
            for _ in range(len(completed)):
                if not submit_next():
                    break
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        _save_precomputed_records(updates)
    summary["cacheRecordCount"] = len(_load_dataset()["records"])
    summary["apiRequestCount"] = api_request_counter[0]
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="역 거리 캐시 좌표와 카카오 Local API로 주변 학교 점수를 저장합니다."
    )
    parser.add_argument("--sido", default="")
    parser.add_argument("--sigungu", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--retry-unavailable", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.all and (not args.sido or not args.sigungu):
        parser.error("지역 단위 실행에는 --sido와 --sigungu가 필요합니다. 전체 수집은 --all을 사용하세요.")
    entities = kakao_station_distances.entities_for_region(
        "" if args.all else args.sido,
        "" if args.all else args.sigungu,
    )
    summary = enrich_entities(
        entities,
        retry_unavailable=args.retry_unavailable,
        limit=args.limit,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("haltedReason") or summary.get("failedCount"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
