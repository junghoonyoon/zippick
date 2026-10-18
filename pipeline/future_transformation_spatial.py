"""Optional, exact land intersections in Korea 2000 / Unified CS (EPSG:5179)."""
import datetime as dt
import math


def conversion(inputs, as_of, horizon, stage_weights, radius):
    try:
        from shapely.geometry import Point, shape
        from shapely.errors import GEOSException
        from shapely.ops import unary_union
        from shapely import transform
        from pyproj import Transformer
    except ImportError:
        return None, {'reason': '공간 계산 모듈이 없어 토지 면적을 계산하지 않았어요.'}
    try:
        center = inputs['center']
        if not (32 <= center['latitude'] <= 39 and 124 <= center['longitude'] <= 132):
            raise ValueError('invalid center')
        project = Transformer.from_crs('EPSG:4326', 'EPSG:5179', always_xy=True).transform
        def polygon(value):
            geometry = shape(value)
            if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
                raise ValueError('invalid land geometry')
            minx, miny, maxx, maxy = geometry.bounds
            if not all(math.isfinite(v) for v in geometry.bounds) or not (124 <= minx <= maxx <= 132 and 32 <= miny <= maxy <= 39):
                raise ValueError('geometry must use WGS84 in Korea')
            return transform(geometry, project, interleaved=False)
        buffer = transform(Point(center['longitude'], center['latitude']), project, interleaved=False).buffer(radius, quad_segs=64)
        lands = []
        for parcel in inputs['parcels']:
            approved = dt.date.fromisoformat(parcel['approvedAt'])
            age = as_of.year - approved.year - ((as_of.month, as_of.day) < (approved.month, approved.day))
            if parcel['use'] == 'residential' and age >= inputs.get('oldBuildingYears', 30):
                lands.append(polygon(parcel['geometry']).intersection(buffer))
        old_land = unary_union(lands)
        denominator = old_land.area
        if denominator <= 0:
            return None, {'reason': '확인 가능한 노후 주거용 토지 면적이 없어요.'}
        projects = []
        for item in inputs['projects']:
            end = dt.date.fromisoformat(item['expectedCompletionDate']) if item.get('expectedCompletionDate') else None
            stage = stage_weights.get(item['stage'])
            if item['stage'] in ('completed', 'cancelled'):
                continue
            intersection = polygon(item['geometry']).intersection(old_land)
            if intersection.is_empty:
                continue
            if not stage or not end or end < as_of:
                return None, {'reason': '겹치는 사업의 최신 단계와 공식 완료 일정이 필요해요.'}
            if end > horizon:
                continue
            projects.append((stage, item['id'], intersection))
        # Highest verified stage wins overlapping area; never double count land.
        occupied = unary_union([])
        weighted = raw = 0.0
        audit = []
        for weight, project_id, geometry in sorted(projects, key=lambda p: (-p[0], p[1])):
            unique = geometry.difference(occupied)
            occupied = occupied.union(geometry)
            raw += unique.area
            weighted += unique.area * weight
            audit.append({'projectId': project_id, 'landAreaM2': round(unique.area, 2), 'weightedAreaM2': round(unique.area * weight, 2)})
        return min(1, weighted / denominator), {
            'crs': 'EPSG:5179', 'eligibleOldResidentialLandAreaM2': round(denominator, 2),
            'unweightedConversionAreaM2': round(raw, 2), 'weightedConversionAreaM2': round(weighted, 2),
            'projects': audit,
        }
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, IndexError, GEOSException):
        return None, {'reason': '좌표·도형·토지 용도·사용승인일을 확인해야 면적을 계산할 수 있어요.'}
