#!/usr/bin/env python3
"""카카오 Local API로 아파트별 가장 가까운 지하철역 거리를 수집한다."""
import argparse
import datetime
import difflib
import hashlib
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config
import molit_transactions
import real_estate_search


API_BASE_URL = "https://dapi.kakao.com/v2/local"
CACHE_PATH = config.CACHE_DIR / "apartment_station_distances.json"
CACHE_VERSION = 1
SOURCE_NAME = "kakao-local-v2"
TERMINAL_STATUSES = {"ok", "no_address", "address_not_found", "station_not_found"}
_CACHE_LOCK = threading.RLock()
_CACHE_DATA = None
_CACHE_LOADED_PATH = None
_CACHE_LOADED_REVISION = None
_ACTIVE_BATCHES = 0
_STATION_QUERY_LOCK = threading.RLock()
_GEOCODE_LOCKS = tuple(threading.RLock() for _ in range(64))
SHARED_STATION_RADIUS_METERS = 500
STATION_TILE_DEGREES = 0.005
STATION_CERTAINTY_MARGIN_METERS = 25


class KakaoLocalError(RuntimeError):
    """카카오 Local API 설정 또는 호출 오류."""


def configured():
    return bool(str(config.KAKAO_REST_API_KEY or "").strip())


def entity_id(entity):
    material = "|".join(str(entity.get(key) or "").strip() for key in (
        "apartmentId", "kaptCode", "complexNo", "province", "district",
        "legalDong", "jibun", "name",
    ))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _legacy_entity_id(entity):
    material = entity.get("dedupeKey") or "|".join(
        str(entity.get(key) or "")
        for key in ("province", "district", "legalDong", "name")
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def entity_address(entity):
    address = " ".join(str(entity.get("address") or "").split())
    province = str(entity.get("province") or "").strip()
    district = str(entity.get("district") or "").strip()
    if address:
        prefix = " ".join(part for part in (province, district) if part)
        return address if not prefix or address.startswith(province) else f"{prefix} {address}"
    legal_dong = str(entity.get("legalDong") or "").strip()
    jibun = str(entity.get("jibun") or "").strip()
    if jibun and legal_dong and jibun.startswith(legal_dong):
        legal_dong = ""
    return " ".join(part for part in (province, district, legal_dong, jibun) if part)


def _empty_cache():
    return {
        "version": CACHE_VERSION,
        "source": SOURCE_NAME,
        "updatedAt": None,
        "records": {},
        "geocodes": {},
        "stationQueries": {},
    }


def reset_memory_cache():
    global _CACHE_DATA, _CACHE_LOADED_PATH, _CACHE_LOADED_REVISION
    with _CACHE_LOCK:
        _CACHE_DATA = None
        _CACHE_LOADED_PATH = None
        _CACHE_LOADED_REVISION = None


def _file_revision():
    try:
        stat = CACHE_PATH.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _load_cache():
    global _CACHE_DATA, _CACHE_LOADED_PATH, _CACHE_LOADED_REVISION
    path_key = os.fspath(CACHE_PATH)
    with _CACHE_LOCK:
        revision = _file_revision()
        if (
            _CACHE_DATA is not None
            and _CACHE_LOADED_PATH == path_key
            and _CACHE_LOADED_REVISION == revision
        ):
            return _CACHE_DATA
        payload = None
        if CACHE_PATH.exists():
            try:
                payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            payload = _empty_cache()
        if not isinstance(payload.get("records"), dict):
            payload["records"] = {}
        for key in ("geocodes", "stationQueries"):
            if not isinstance(payload.get(key), dict):
                payload[key] = {}
        _CACHE_DATA = payload
        _CACHE_LOADED_PATH = path_key
        _CACHE_LOADED_REVISION = revision
        return _CACHE_DATA


def _save_cache():
    global _CACHE_LOADED_REVISION
    with _CACHE_LOCK:
        payload = _load_cache()
        payload["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(CACHE_PATH)
        _CACHE_LOADED_REVISION = _file_revision()


def _save_if_not_batching():
    with _CACHE_LOCK:
        if _ACTIVE_BATCHES == 0:
            _save_cache()


def _merge_records(records):
    if not records:
        return
    with _CACHE_LOCK:
        payload = _load_cache()
        payload["records"].update({
            str(key): value
            for key, value in records.items()
            if isinstance(value, dict)
        })
        _save_cache()


def _coordinate_key(address):
    return hashlib.sha1(address.encode("utf-8")).hexdigest()[:20]


def _valid_coordinates(latitude, longitude):
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and 33 <= latitude <= 39 and 124 <= longitude <= 132):
        return None
    return latitude, longitude


def _coordinates_for_entity(entity, address):
    direct = _valid_coordinates(entity.get("latitude"), entity.get("longitude"))
    if direct:
        return {"latitude": direct[0], "longitude": direct[1], "matchedAddress": address,
                "coordinateMatchType": "entity"}
    key = _coordinate_key(address)
    with _GEOCODE_LOCKS[int(key[:4], 16) % len(_GEOCODE_LOCKS)]:
        cached = _load_cache()["geocodes"].get(key)
        if isinstance(cached, dict) and cached.get("address") == address:
            coordinates = _valid_coordinates(cached.get("latitude"), cached.get("longitude"))
            if coordinates:
                return {"latitude": coordinates[0], "longitude": coordinates[1],
                        "matchedAddress": cached.get("matchedAddress") or address,
                        "coordinateMatchType": "address_cache"}
        coordinates = geocode_address(address) or geocode_apartment_keyword(entity)
        if coordinates:
            with _CACHE_LOCK:
                _load_cache()["geocodes"][key] = {"address": address, **coordinates}
                _save_if_not_batching()
        return coordinates


def cache_revision():
    revision = _file_revision()
    if revision is None:
        return "none"
    modified_ns, size = revision
    return f"{modified_ns:x}-{size:x}"


def cached_record(entity):
    records = _load_cache().get("records", {})
    record = records.get(entity_id(entity))
    if not isinstance(record, dict):
        legacy = records.get(_legacy_entity_id(entity))
        if (isinstance(legacy, dict)
                and legacy.get("apartmentName") == str(entity.get("name") or "")
                and legacy.get("address") == entity_address(entity)
                and legacy.get("address")):
            record = legacy
    return dict(record) if isinstance(record, dict) else None


def cached_station(entity):
    record = cached_record(entity)
    if not record or record.get("status") not in {"ok", "station_not_found"}:
        return None
    lower_bound = record.get("stationDistanceLowerBound")
    if record.get("status") == "station_not_found" and lower_bound is None:
        lower_bound = config.KAKAO_STATION_RADIUS_METERS
    return {
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "nearestStationName": record.get("nearestStationName"),
        "nearestStationDistance": record.get("nearestStationDistance"),
        "nearestStationLatitude": record.get("nearestStationLatitude"),
        "nearestStationLongitude": record.get("nearestStationLongitude"),
        "stationDistanceLowerBound": lower_bound,
        "stationDistanceType": (
            record.get("stationDistanceType")
            or ("straight_line" if record.get("status") == "ok" else "straight_line_lower_bound")
        ),
        "stationDistanceSource": SOURCE_NAME,
        "stationDistanceUpdatedAt": record.get("fetchedAt"),
    }


def cache_stats(entities=None):
    payload = _load_cache()
    records = payload.get("records", {})
    if entities is not None:
        records = {
            entity_id(entity): record
            for entity in entities
            if (record := cached_record(entity)) is not None
        }
    ready = sum(1 for value in records.values() if value.get("status") == "ok")
    unavailable = sum(
        1 for value in records.values()
        if value.get("status") in TERMINAL_STATUSES and value.get("status") != "ok"
    )
    return {
        "configured": configured(),
        "recordCount": len(records),
        "readyCount": ready,
        "unavailableCount": unavailable,
        "geocodeCount": len(payload["geocodes"]),
        "stationQueryCount": sum(len(items) for items in payload["stationQueries"].values()),
        "updatedAt": payload.get("updatedAt"),
        "source": SOURCE_NAME,
        "distanceType": "straight_line",
    }


def _request_json(path, params):
    key = str(config.KAKAO_REST_API_KEY or "").strip()
    if not key:
        raise KakaoLocalError("카카오 REST API 키가 설정되어 있지 않습니다.")
    url = f"{API_BASE_URL}/{path.lstrip('/')}"
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"Authorization": f"KakaoAK {key}"},
                timeout=config.KAKAO_LOCAL_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (2 ** attempt))
                continue
            raise KakaoLocalError("카카오 Local API에 연결하지 못했습니다.") from exc
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise KakaoLocalError("카카오 Local API 응답 형식을 확인하지 못했습니다.") from exc
            if not isinstance(payload, dict):
                raise KakaoLocalError("카카오 Local API 응답 형식이 올바르지 않습니다.")
            return payload
        if response.status_code in {401, 403}:
            raise KakaoLocalError("카카오 REST API 키 또는 카카오맵 사용 설정을 확인해 주세요.")
        if response.status_code == 429 or response.status_code >= 500:
            last_error = KakaoLocalError(f"카카오 Local API 일시 오류({response.status_code})")
            if attempt < 2:
                time.sleep(0.4 * (2 ** attempt))
                continue
        raise KakaoLocalError(f"카카오 Local API 요청이 실패했습니다({response.status_code}).")
    raise KakaoLocalError("카카오 Local API 요청이 실패했습니다.") from last_error


def geocode_address(address):
    payload = _request_json("search/address.json", {"query": address, "size": 1})
    documents = payload.get("documents") or []
    if not documents:
        return None
    document = documents[0]
    try:
        longitude = float(document["x"])
        latitude = float(document["y"])
    except (KeyError, TypeError, ValueError):
        return None
    road_address = document.get("road_address") or {}
    return {
        "latitude": latitude,
        "longitude": longitude,
        "matchedAddress": (
            road_address.get("address_name")
            or document.get("address_name")
            or address
        ),
    }


def geocode_apartment_keyword(entity):
    """Resolve block-lot and stale jibun addresses by the apartment place name."""
    query_parts = []
    seen = set()
    for value in (
        entity.get("province"),
        entity.get("city"),
        entity.get("district"),
        entity.get("legalDong"),
        entity.get("name"),
    ):
        value = " ".join(str(value or "").split())
        key = real_estate_search.compact(value)
        if value and key not in seen:
            seen.add(key)
            query_parts.append(value)
    apartment_name = str(entity.get("name") or "").strip()
    if not apartment_name:
        return None
    region_parts = []
    seen_region = set()
    for value in (entity.get("province"), entity.get("city"), entity.get("district")):
        value = " ".join(str(value or "").split())
        key = real_estate_search.compact(value)
        if value and key not in seen_region:
            seen_region.add(key)
            region_parts.append(value)
    queries = [
        " ".join(query_parts),
        " ".join([*region_parts, apartment_name]),
    ]
    normalized_block_name = re.sub(
        r"\bA?(\d+)BL\b",
        r"\1단지",
        apartment_name,
        flags=re.IGNORECASE,
    )
    if normalized_block_name != apartment_name:
        queries.extend((
            " ".join([*query_parts[:-1], normalized_block_name]),
            " ".join([*region_parts, normalized_block_name]),
        ))
    queries = list(dict.fromkeys(query for query in queries if query))
    documents = []
    seen_places = set()
    for query in queries:
        payload = _request_json("search/keyword.json", {"query": query, "size": 15})
        for document in payload.get("documents") or []:
            place_id = str(document.get("id") or "") or "|".join((
                str(document.get("place_name") or ""),
                str(document.get("x") or ""),
                str(document.get("y") or ""),
            ))
            if place_id not in seen_places:
                seen_places.add(place_id)
                documents.append(document)
    name_key = real_estate_search.compact(apartment_name)
    legal_dong_key = real_estate_search.compact(entity.get("legalDong"))
    jibun_numbers = set(
        part for part in re.findall(r"\d+(?:-\d+)?", str(entity.get("jibun") or ""))
        if part
    )
    candidates = []
    for order, document in enumerate(documents):
        category = str(document.get("category_name") or "")
        if not any(
            label in category
            for label in ("아파트", "도시형생활주택", "빌라,주택")
        ):
            continue
        place_name = str(document.get("place_name") or "")
        place_key = real_estate_search.compact(place_name)
        address_name = str(document.get("address_name") or "")
        address_key = real_estate_search.compact(address_name)
        normalized_place = place_key.replace("아파트", "")
        normalized_name = real_estate_search.compact(normalized_block_name).replace("아파트", "")
        score = 0
        if normalized_place == normalized_name:
            score += 1000
        elif (
            len(normalized_name) >= 4
            and (normalized_name in normalized_place or normalized_place in normalized_name)
        ):
            score += 600
        elif difflib.SequenceMatcher(None, normalized_name, normalized_place).ratio() >= 0.68:
            score += 600
        if legal_dong_key and legal_dong_key in address_key:
            score += 150
        address_numbers = set(re.findall(r"\d+(?:-\d+)?", address_name))
        if jibun_numbers and jibun_numbers & address_numbers:
            score += 400
        try:
            longitude = float(document["x"])
            latitude = float(document["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if score < 500:
            continue
        candidates.append((score, -order, {
            "latitude": latitude,
            "longitude": longitude,
            "matchedAddress": (
                document.get("road_address_name")
                or address_name
                or apartment_name
            ),
            "coordinateMatchType": "apartment_keyword",
        }))
    return max(candidates, default=(None, None, None), key=lambda item: item[:2])[2]


def nearest_subway_station(longitude, latitude):
    payload = _request_json(
        "search/category.json",
        {
            "category_group_code": "SW8",
            "x": f"{float(longitude):.12f}",
            "y": f"{float(latitude):.12f}",
            "radius": config.KAKAO_STATION_RADIUS_METERS,
            "sort": "distance",
            "size": 1,
        },
    )
    documents = payload.get("documents") or []
    if not documents:
        return None
    document = documents[0]
    try:
        distance = float(document["distance"])
        station_longitude = float(document["x"])
        station_latitude = float(document["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "nearestStationName": str(document.get("place_name") or "").strip(),
        "nearestStationDistance": round(distance, 1),
        "nearestStationLatitude": station_latitude,
        "nearestStationLongitude": station_longitude,
        "nearestStationKakaoPlaceId": str(document.get("id") or "").strip() or None,
    }


def _distance_meters(latitude_a, longitude_a, latitude_b, longitude_b):
    latitude_a, longitude_a, latitude_b, longitude_b = map(
        math.radians, (latitude_a, longitude_a, latitude_b, longitude_b)
    )
    return 6371000 * 2 * math.asin(math.sqrt(
        math.sin((latitude_b - latitude_a) / 2) ** 2
        + math.cos(latitude_a) * math.cos(latitude_b)
        * math.sin((longitude_b - longitude_a) / 2) ** 2
    ))


def _station_from_query(query, longitude, latitude):
    center = _valid_coordinates(query.get("latitude"), query.get("longitude"))
    if not center:
        return None
    center_gap = _distance_meters(latitude, longitude, *center)
    if center_gap > SHARED_STATION_RADIUS_METERS:
        return None
    stations = []
    for document in query.get("documents") or []:
        point = _valid_coordinates(document.get("latitude"), document.get("longitude"))
        if point:
            stations.append((_distance_meters(latitude, longitude, *point), document))
    if not stations:
        return None
    distance, nearest = min(stations, key=lambda item: item[0])
    # An omitted station is at least this far from the query center. The
    # triangle inequality proves it cannot be nearer to this apartment.
    boundary = (config.KAKAO_STATION_RADIUS_METERS if query.get("isEnd")
                else query.get("lastCenterDistance"))
    if boundary is None or distance >= float(boundary) - center_gap - STATION_CERTAINTY_MARGIN_METERS:
        return None
    return {
        "nearestStationName": nearest["name"],
        "nearestStationDistance": round(distance, 1),
        "nearestStationLatitude": nearest["latitude"],
        "nearestStationLongitude": nearest["longitude"],
        "nearestStationKakaoPlaceId": nearest.get("id"),
    }


def _station_tile(latitude, longitude):
    return (math.floor(latitude / STATION_TILE_DEGREES),
            math.floor(longitude / STATION_TILE_DEGREES))


def nearest_subway_station_shared(longitude, latitude):
    # Serialize only station queries, so concurrent apartments in one area
    # reuse the first result instead of sending duplicate Kakao requests.
    with _STATION_QUERY_LOCK:
        queries = _load_cache()["stationQueries"]
        tile_lat, tile_lon = _station_tile(latitude, longitude)
        for lat_index in range(tile_lat - 1, tile_lat + 2):
            for lon_index in range(tile_lon - 1, tile_lon + 2):
                for query in queries.get(f"{lat_index},{lon_index}", []):
                    station = _station_from_query(query, longitude, latitude)
                    if station:
                        return station
        payload = _request_json("search/category.json", {
            "category_group_code": "SW8",
            "x": f"{float(longitude):.12f}",
            "y": f"{float(latitude):.12f}",
            "radius": config.KAKAO_STATION_RADIUS_METERS,
            "sort": "distance",
            "size": 15,
        })
        raw_documents = payload.get("documents") or []
        documents = []
        for document in raw_documents:
            point = _valid_coordinates(document.get("y"), document.get("x"))
            name = str(document.get("place_name") or "").strip()
            if point and name:
                documents.append({
                    "id": str(document.get("id") or "").strip() or None,
                    "name": name,
                    "latitude": point[0], "longitude": point[1],
                })
        if len(documents) != len(raw_documents):
            return nearest_subway_station(longitude, latitude)
        if not documents:
            return None
        last_center_distance = max(
            _distance_meters(latitude, longitude, item["latitude"], item["longitude"])
            for item in documents
        )
        query = {
            "latitude": latitude, "longitude": longitude,
            "documents": documents,
            "isEnd": (payload.get("meta") or {}).get("is_end") is True,
            "lastCenterDistance": last_center_distance,
        }
        station = _station_from_query(query, longitude, latitude)
        if station:
            key = f"{tile_lat},{tile_lon}"
            with _CACHE_LOCK:
                _load_cache()["stationQueries"].setdefault(key, []).append(query)
                _save_if_not_batching()
            return station
        # Malformed or incomplete category response: retain the established
        # single-result lookup rather than guessing which station is nearest.
        return nearest_subway_station(longitude, latitude)


def _base_record(entity, status, address, **extra):
    return {
        "apartmentId": entity_id(entity),
        "apartmentName": str(entity.get("name") or ""),
        "address": address,
        "status": status,
        "source": SOURCE_NAME,
        "fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **extra,
    }


def enrich_entity(entity):
    address = entity_address(entity)
    if not address and not _valid_coordinates(entity.get("latitude"), entity.get("longitude")):
        return _base_record(entity, "no_address", "")
    coordinates = _coordinates_for_entity(entity, address)
    if not coordinates:
        return _base_record(entity, "address_not_found", address)
    station = nearest_subway_station_shared(
        coordinates["longitude"],
        coordinates["latitude"],
    )
    if not station:
        return _base_record(
            entity,
            "station_not_found",
            address,
            **coordinates,
            stationDistanceLowerBound=config.KAKAO_STATION_RADIUS_METERS,
            stationDistanceType="straight_line_lower_bound",
        )
    return _base_record(
        entity,
        "ok",
        address,
        **coordinates,
        **station,
        stationDistanceType="straight_line",
    )


def _region_matches(value, target):
    value_key = real_estate_search.compact(value)
    target_key = real_estate_search.compact(target)
    aliases = {
        "서울": "서울특별시",
        "서울시": "서울특별시",
        "경기": "경기도",
    }
    target_key = real_estate_search.compact(aliases.get(str(target).strip(), target))
    if not value_key:
        return False
    if value_key == target_key:
        return True
    return bool(
        target_key.endswith(("구", "군"))
        and len(target_key) >= 3
        and value_key.endswith(target_key)
    )


def entities_for_region(sido="", sigungu=""):
    rows = []
    seen = set()
    for entity in real_estate_search.APARTMENT_MASTER:
        status = str(entity.get("status") or "").strip()
        if entity.get("aggregate") or (
            status and status not in molit_transactions.PRESALE_STATUSES
        ):
            continue
        if sido and not _region_matches(entity.get("province"), sido):
            continue
        if sigungu and not _region_matches(entity.get("district"), sigungu):
            continue
        key = entity_id(entity)
        if key in seen:
            continue
        seen.add(key)
        rows.append(entity)
    return rows


def enrich_entities(
    entities,
    *,
    force=False,
    retry_unavailable=False,
    limit=None,
    workers=None,
    dry_run=False,
):
    entities = list(entities)
    if limit is not None:
        entities = entities[:max(0, int(limit))]
    cached = []
    pending = []
    for entity in entities:
        record = cached_record(entity)
        if (
            not force
            and isinstance(record, dict)
            and record.get("status") in TERMINAL_STATUSES
            and not (retry_unavailable and record.get("status") != "ok")
        ):
            cached.append(record)
        else:
            pending.append(entity)
    summary = {
        "configured": configured(),
        "source": SOURCE_NAME,
        "distanceType": "straight_line",
        "requestedCount": len(entities),
        "cachedCount": len(cached),
        "pendingCount": len(pending),
        "processedCount": 0,
        "readyCount": sum(1 for record in cached if record.get("status") == "ok"),
        "unavailableCount": sum(1 for record in cached if record.get("status") != "ok"),
        "failedCount": 0,
        "failures": [],
        "dryRun": bool(dry_run),
    }
    if dry_run or not pending:
        return summary
    if not configured():
        raise KakaoLocalError("KAKAO_REST_API_KEY 또는 카카오REST키를 설정해 주세요.")
    global _ACTIVE_BATCHES
    max_workers = max(1, min(int(workers or config.KAKAO_STATION_MAX_WORKERS), 16))
    updates = {}
    with _CACHE_LOCK:
        _ACTIVE_BATCHES += 1
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_entities = {
                pool.submit(enrich_entity, entity): entity
                for entity in pending
            }
            for future in as_completed(future_entities):
                entity = future_entities[future]
                summary["processedCount"] += 1
                try:
                    record = future.result()
                except KakaoLocalError as exc:
                    summary["failedCount"] += 1
                    if len(summary["failures"]) < 20:
                        summary["failures"].append({
                            "apartmentName": entity.get("name"),
                            "error": str(exc),
                        })
                    continue
                updates[entity_id(entity)] = record
                if record.get("status") == "ok":
                    summary["readyCount"] += 1
                else:
                    summary["unavailableCount"] += 1
                if len(updates) >= 250:
                    _merge_records(updates)
                    updates.clear()
        _merge_records(updates)
    finally:
        with _CACHE_LOCK:
            _ACTIVE_BATCHES -= 1
            if _ACTIVE_BATCHES == 0:
                _save_cache()
    summary["cache"] = cache_stats(entities)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="카카오 Local API로 아파트별 가장 가까운 지하철역 거리를 저장합니다.",
    )
    parser.add_argument("--sido", default="")
    parser.add_argument("--sigungu", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--retry-unavailable",
        action="store_true",
        help="주소 또는 역을 찾지 못했던 단지만 다시 확인합니다.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.all and (not args.sido or not args.sigungu):
        parser.error("지역 단위 실행에는 --sido와 --sigungu가 필요합니다. 전체 수집은 --all을 사용하세요.")
    entities = entities_for_region(
        "" if args.all else args.sido,
        "" if args.all else args.sigungu,
    )
    try:
        payload = enrich_entities(
            entities,
            force=args.force,
            retry_unavailable=args.retry_unavailable,
            limit=args.limit,
            workers=args.workers,
            dry_run=args.dry_run,
        )
    except KakaoLocalError as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
