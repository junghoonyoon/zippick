"""브이월드 연속지적도를 시범 단지 반경으로 완전 수집한다.

원본 필지 도형만 보관한다. 건물 용도·사용승인일·사업 경계가 검증되기
전에는 이 자료를 노후 주거지 면적이나 생활권 변화 점수로 사용하지 않는다.
"""

import datetime as dt
import hashlib
import json
import math
import sqlite3
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely import transform
from shapely.errors import GEOSException
from shapely.geometry import Point, box, shape

import config
from building_hub import DB_PATH as BUILDING_DB_PATH, SOURCE_URL as BUILDING_SOURCE_URL


API_URL = "https://api.vworld.kr/req/data"
SOURCE_URL = "https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=cadastral"
DB_PATH = config.CACHE_DIR / "vworld_cadastral.sqlite3"
DATASET = "LP_PA_CBND_BUBUN"
PAGE_SIZE = 1000
TILE_METERS = 1000
TIMEOUT_SECONDS = 20


class CadastralError(RuntimeError):
    """공식 필지 자료를 완전하게 확인하지 못했다."""


def _center(latitude, longitude, radius_meters):
    values = (latitude, longitude, radius_meters)
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in values):
        raise ValueError("단지 좌표와 반경은 유한한 숫자여야 합니다.")
    if not (32 <= latitude <= 39 and 124 <= longitude <= 132 and 0 < radius_meters <= 3000):
        raise ValueError("단지 좌표 또는 반경이 범위를 벗어났습니다.")
    to_meters = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    return to_meters.transform(longitude, latitude)


def tile_boxes(latitude, longitude, radius_meters=1500):
    """2km² 요청 제한보다 작은 1km 격자로 반경을 덮는다."""
    cx, cy = _center(latitude, longitude, radius_meters)
    to_wgs84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    circle = Point(cx, cy).buffer(radius_meters, quad_segs=64)
    count = math.ceil(2 * radius_meters / TILE_METERS)
    tiles = []
    for row in range(count):
        for col in range(count):
            x0 = cx - radius_meters + col * TILE_METERS
            y0 = cy - radius_meters + row * TILE_METERS
            x1 = min(x0 + TILE_METERS, cx + radius_meters)
            y1 = min(y0 + TILE_METERS, cy + radius_meters)
            if not box(x0, y0, x1, y1).intersects(circle):
                continue
            # Edge samples enclose the projected tile after transforming to WGS84.
            corners = [to_wgs84.transform(x, y) for x in (x0, (x0+x1)/2, x1)
                       for y in (y0, (y0+y1)/2, y1)]
            west, east = min(p[0] for p in corners), max(p[0] for p in corners)
            south, north = min(p[1] for p in corners), max(p[1] for p in corners)
            # Bounding-box expansion from projection is tiny at the two pilot latitudes.
            area = transform(box(west, south, east, north),
                             Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform,
                             interleaved=False).area
            if area >= 2_000_000:
                raise CadastralError("지적도 요청 범위가 2km² 제한을 넘었습니다.")
            tiles.append((west, south, east, north))
    return tiles


def _response_page(payload, requested_page):
    try:
        response = payload["response"]
        status = response["status"]
        if status == "NOT_FOUND":
            return 0, []
        if status != "OK":
            raise CadastralError("브이월드가 지적도 요청을 거절했습니다. 키·호출 권한을 확인해 주세요.")
        page = response["page"]
        record = response["record"]
        total = int(record["total"])
        page_total = int(page["total"])
        page_current = int(page["current"])
        collection = response["result"]["featureCollection"]
        if isinstance(collection, str):
            collection = json.loads(collection)
        features = collection["features"]
        if (page_current != requested_page or total < 0 or page_total < 1
                or not isinstance(features, list) or len(features) > PAGE_SIZE
                or page_total != max(1, math.ceil(total / PAGE_SIZE))):
            raise ValueError("page totals")
        if len(features) != min(PAGE_SIZE, max(0, total - (requested_page - 1) * PAGE_SIZE)):
            raise ValueError("page size")
        return total, features
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CadastralError("브이월드의 페이지·총건수·도형을 확인할 수 없습니다.") from None


def _validate_feature(feature):
    try:
        pnu = feature["properties"]["pnu"]
        geometry = feature["geometry"]
        if (not isinstance(pnu, str) or len(pnu) != 19 or not pnu.isdecimal()
                or geometry["type"] not in ("Polygon", "MultiPolygon")):
            raise ValueError("parcel identifier or geometry")
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError("invalid polygon")
        west, south, east, north = polygon.bounds
        if not (124 <= west <= east <= 132 and 32 <= south <= north <= 39):
            raise ValueError("out of Korea")
        return pnu, polygon
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, GEOSException):
        raise CadastralError("지적도 필지번호 또는 경계를 확인할 수 없습니다.") from None


def _request_json(request, opener, retry_wait_seconds):
    for attempt in range(3):
        try:
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                break
        except OSError:
            if attempt == 2:
                break
        except (ValueError, UnicodeError):
            break
        time.sleep(retry_wait_seconds * (2 ** attempt))
    # URL에 키가 있으므로 원래 예외(URL)를 연결하거나 출력하지 않는다.
    raise CadastralError("브이월드 지적도를 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from None


def fetch_radius(apartment_id, latitude, longitude, *, radius_meters=1500,
                 api_key=None, domain=None, opener=urlopen, pause_seconds=0.12,
                 retry_wait_seconds=0.5):
    """모든 타일과 페이지를 받은 경우에만 스냅샷을 돌려준다."""
    key = str(api_key if api_key is not None else config.VWORLD_API_KEY).strip()
    if not key:
        raise CadastralError("브이월드 인증키가 없습니다. VWORLD_API_KEY를 설정해 주세요.")
    if not isinstance(apartment_id, str) or not apartment_id.strip():
        raise ValueError("단지 ID가 필요합니다.")
    tiles = tile_boxes(latitude, longitude, radius_meters)
    to_meters = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    circle = Point(*_center(latitude, longitude, radius_meters)).buffer(radius_meters, quad_segs=64)
    features_by_pnu = {}
    tile_counts = []
    for west, south, east, north in tiles:
        total_for_tile = None
        for page_no in range(1, 101):
            query = {"service": "data", "request": "GetFeature", "data": DATASET,
                     "key": key, "geomFilter": "BOX(" + ",".join(f"{v:.9f}" for v in (west, south, east, north)) + ")",
                     "geometry": "true", "attribute": "true", "crs": "EPSG:4326",
                     "size": PAGE_SIZE, "page": page_no}
            if domain:
                query["domain"] = domain
            request = Request(f"{API_URL}?{urlencode(query)}", headers={
                "Accept": "application/json", "User-Agent": "zippick-cadastral/1.0"})
            payload = _request_json(request, opener, retry_wait_seconds)
            total, features = _response_page(payload, page_no)
            if total_for_tile is not None and total != total_for_tile:
                raise CadastralError("조회 도중 필지 총건수가 바뀌었습니다. 저장하지 않았습니다.")
            total_for_tile = total
            for feature in features:
                pnu, polygon = _validate_feature(feature)
                previous = features_by_pnu.get(pnu)
                if previous is not None:
                    if not shape(previous["geometry"]).equals(polygon):
                        raise CadastralError("같은 필지번호의 경계가 서로 다릅니다. 저장하지 않았습니다.")
                elif transform(polygon, to_meters.transform, interleaved=False).intersects(circle):
                    features_by_pnu[pnu] = feature
            if page_no * PAGE_SIZE >= total:
                break
            if pause_seconds:
                time.sleep(pause_seconds)
        else:
            raise CadastralError("브이월드 페이지 제한으로 전체 필지를 받지 못했습니다.")
        tile_counts.append(total_for_tile)
        if pause_seconds:
            time.sleep(pause_seconds)
    return {"apartmentId": apartment_id, "center": {"latitude": latitude, "longitude": longitude},
            "radiusMeters": radius_meters, "dataset": DATASET, "sourceUrl": SOURCE_URL,
            "crs": "EPSG:4326", "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tileCounts": tile_counts, "queryComplete": True,
            "features": [features_by_pnu[pnu] for pnu in sorted(features_by_pnu)]}


def store_snapshot(snapshot, path=DB_PATH):
    """완전 수집 결과만 원자적으로 보관한다. 인증키와 호출 URL은 저장하지 않는다."""
    center = snapshot.get("center") or {}
    if (snapshot.get("dataset") != DATASET or snapshot.get("queryComplete") is not True
            or snapshot.get("sourceUrl") != SOURCE_URL
            or len(snapshot.get("tileCounts") or []) != len(tile_boxes(
                center.get("latitude"), center.get("longitude"), snapshot.get("radiusMeters")))
            or any(not isinstance(n, int) or n < 0 for n in snapshot["tileCounts"])):
        raise ValueError("검증된 지적도 스냅샷이 아닙니다.")
    ids = [_validate_feature(feature)[0] for feature in snapshot["features"]]
    if len(ids) != len(set(ids)):
        raise ValueError("중복 필지번호가 있습니다.")
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS cadastral_snapshots (
            id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL, fetched_at TEXT NOT NULL,
            radius_meters REAL NOT NULL, parcel_count INTEGER NOT NULL, source_url TEXT NOT NULL,
            payload_json TEXT NOT NULL)""")
        db.execute("INSERT OR IGNORE INTO cadastral_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (digest, snapshot["apartmentId"], snapshot["fetchedAt"],
                    snapshot["radiusMeters"], len(ids), SOURCE_URL, raw))
    return digest


def audit_building_join(snapshot, building_db_path=BUILDING_DB_PATH):
    """PNU로 건축HUB 범위와 연결 건수를 확인한다. 용도/연식 점수는 만들지 않는다."""
    pnus = {_validate_feature(feature)[0] for feature in snapshot["features"]}
    required = {pnu[:10] for pnu in pnus}
    latest = {}
    if building_db_path.exists():
        with sqlite3.connect(building_db_path) as db:
            table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dong_snapshots'").fetchone()
            if table:
                for dong, fetched_at, source_url, total, payload in db.execute(
                        "SELECT dong_id, fetched_at, source_url, total_count, payload FROM dong_snapshots"):
                    if dong in required and (dong not in latest or fetched_at > latest[dong][0]):
                        latest[dong] = (fetched_at, source_url, total, payload)
    covered = set()
    matched = set()
    rows_in_radius = 0
    for dong, (_fetched_at, source_url, total, payload) in latest.items():
        try:
            data = json.loads(payload)
            records = data["records"]
            if (source_url != BUILDING_SOURCE_URL or data["totalCount"] != total
                    or len(records) != total):
                continue
            parcel_ids = []
            for record in records:
                code = "".join(str(record[field]) for field in
                               ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"))
                if len(code) != 19 or not code.isdecimal() or not code.startswith(dong):
                    raise ValueError("invalid building parcel ID")
                parcel_ids.append(code)
        except (KeyError, TypeError, ValueError):
            continue
        covered.add(dong)
        for pnu in parcel_ids:
            if pnu in pnus:
                matched.add(pnu)
                rows_in_radius += 1
    return {"scope": "radius_1500m" if snapshot["radiusMeters"] == 1500 else "radius",
            "parcelCount": len(pnus), "requiredDongCodes": sorted(required),
            "coveredDongCodes": sorted(covered), "missingDongCodes": sorted(required - covered),
            "matchedParcelCount": len(matched), "buildingRecordCountOnMatchedParcels": rows_in_radius,
            "fullBuildingDongCoverage": required <= covered,
            "scoreReady": False}
