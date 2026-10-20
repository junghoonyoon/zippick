"""Map references are independent of benefit scores and verified walking routes.

OA-22712 geometry is displayed for the user-confirmed noncommercial use.
Original geometry, license and source date are retained; map references do not
become verified benefit-score inputs.
"""
import math

import config
from living_area_rail_policy import annotate
import project_official_links
from living_area_context import read

ZONE_BINDINGS = {
    'seoul-plan-renewal:7073': ('11000UQ120PS202411014521', '장안동 134-15 일대', '134-15'),
    'seoul-plan-renewal:7810': ('11000UQ120PS202411014176', '장안현대', '95-1'),
}


def _positive_scale(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 else None


def _featured_developments(zones, projects, limit=3):
    """Rank measurable renewal projects within 2 km for map labels only."""
    own_ids = {zone['projectId'] for zone in zones if zone.get('containsSubject')}
    candidates = {}
    for zone in zones:
        kind = zone.get('projectTypeLabel') or ''
        if (zone.get('containsSubject') or not zone.get('businessNameConfirmed')
                or (zone.get('zoneKind') is not None and zone['zoneKind'] != 'renewal')
                or not (zone.get('zoneKind') == 'renewal' or zone.get('projectType') in ('redevelopment', 'reconstruction')
                        or any(word in kind for word in ('재개발', '재건축', '주택정비', '가로주택', '소규모', '신속통합기획')))):
            continue
        candidates[zone['projectId']] = {
            'projectId': zone['projectId'], 'distanceMeters': zone['distanceMeters'],
            'plannedHouseholds': _positive_scale(zone.get('plannedHouseholds')),
            'reportedHouseholds': _positive_scale(zone.get('reportedHouseholds')),
            'siteAreaM2': _positive_scale(zone.get('siteAreaM2')),
        }
    for project in projects:
        if (project.get('id') in own_ids or project.get('projectType') not in ('redevelopment', 'reconstruction')
                or project.get('geometryType') != 'point' or not project.get('licenseVerifiedAt')):
            continue
        lat, lon = project.get('latitude'), project.get('longitude')
        if (not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lon) or not (33 < lat < 39 and 124 < lon < 132)):
            continue
        distance = project.get('distanceMeters')
        if not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance > 2000:
            continue
        row = candidates.setdefault(project['id'], {'projectId': project['id'], 'distanceMeters': distance})
        row['distanceMeters'] = min(row['distanceMeters'], distance)
        for key in ('plannedHouseholds', 'reportedHouseholds', 'siteAreaM2'):
            row[key] = _positive_scale(project.get(key)) or row.get(key)
    measurable = [row for row in candidates.values() if any(row.get(key) for key in
                  ('plannedHouseholds', 'reportedHouseholds', 'siteAreaM2'))]
    def scale(row):
        for basis in ('plannedHouseholds', 'reportedHouseholds', 'siteAreaM2'):
            if row.get(basis):
                return basis, row[basis]
        return None, None
    # Household counts and land area have different units. Rank known household
    # counts together, then use official area to fill any remaining label slots.
    ranked = sorted((row for row in measurable if row['distanceMeters'] <= 2000),
                    key=lambda row: (0 if scale(row)[0] != 'siteAreaM2' else 1,
                                     -scale(row)[1], row['distanceMeters'], row['projectId']))
    return [{'projectId': row['projectId'], 'scaleBasis': scale(row)[0],
             'scaleValue': scale(row)[1], 'selectionRadiusMeters': 2000}
            for row in ranked[:limit]]


def map_context(entity, analysis):
    from future_transformation import apartment_key
    result = {'zones': [], 'stations': [], 'connections': [], 'featuredDevelopment': None,
              'featuredDevelopments': [],
              'useContext': 'noncommercial',
              'distanceBasis': '단지 대표점 기준 직선거리 · 도보거리 아님'}
    # GIS is optional in installations that serve search only.
    try:
        from pyproj import Transformer
        from shapely.geometry import Point, shape, mapping
        from shapely.ops import nearest_points
        from shapely import transform as transform_geometry
    except ImportError:
        return {**result, 'status': 'geometry_unavailable'}
    def transform(fn, geometry):
        return transform_geometry(geometry, fn, interleaved=False)
    FORWARD = Transformer.from_crs(4326, 5179, always_xy=True).transform
    INVERSE = Transformer.from_crs(5179, 4326, always_xy=True).transform
    center = analysis.get('center') or analysis.get('mapCenter') or {}
    lat, lon = center.get('latitude'), center.get('longitude')
    if (analysis.get('modelVersion') != 'living-area-v2-beta'
            or analysis.get('apartmentId') != apartment_key(entity)
            or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lat, lon))
            or not (33 < lat < 39 and 124 < lon < 132)):
        return result
    import datetime as dt
    import living_area_metro as metro
    from living_area_context import recent
    day = dt.date.fromisoformat(analysis.get('asOfDate') or dt.date.today().isoformat())
    if analysis.get('metroIdentity') and any(entity.get(k) != analysis['metroIdentity'].get(k)
            for k in ('province','district','legalDong','jibun')):
        return result
    origin = transform(FORWARD, Point(lon, lat))
    if analysis.get('metroCoverage') or (metro.supported(entity) and metro.catalog()):
        candidates = {p['id']:p for p in metro.catalog().get('projects', [])}
        # Use the same canonical projects as the viewport API. Cached display
        # rows can include derived boundary:* entries, which duplicate real
        # projects and make an otherwise exact spatial match ambiguous.
        spatial = metro.spatial(center,list(candidates.values()),day)
        result.update(spatial)
        from living_area import distance
        from living_area_context import recent
        for station in metro.station_references(day):
            meters=distance(center,station)
            if meters is not None and meters <= 3000 and metro.station_visible(station,day):
                row = {k:v for k,v in station.items() if k!='rawPlace'} | {'distanceMeters':round(meters)}
                row.update(project_official_links.for_project(station, day))
                if station.get('serviceStatus') == 'operating':
                    row.update(stage='completed', stageLabel='운행 중', scoringEligible=False,
                               positionLabel='기존역 대표점 · 실제 출입구와 다를 수 있어요.')
                # Link by reviewed route IDs, never by a similar line/station name.
                station_point = transform(FORWARD, Point(station['longitude'], station['latitude']))
                routes = [route for route in result.get('routes', []) if route['id'] in station.get('routeIds', [])]
                if routes:
                    route = min(routes, key=lambda route: station_point.distance(transform(FORWARD, shape(route['geometry']))))
                    row['routeId'] = route['id']
                result['stations'].append(row)
        # Match named planned stations only to the same official railway route.
        # Kakao's planned-station place points can be offset from the public
        # reference alignment, so keep both positions and expose the gap.
        reference_path = config.ROOT / 'data/living_area_rail_station_references.json'
        references = read(reference_path) if reference_path.exists() else {}
        if recent(references.get('checkedAt'),day):
            for station in references.get('stations',[]):
                # A reviewed station registry supersedes the old map-only point.
                if any(s.get('coordinateSourceUrl') == station.get('coordinateSourceUrl')
                       for s in result['stations']):continue
                if station.get('sourceDate','9999-12-31') > day.isoformat():
                    continue
                route = next((route for route in result.get('routes',[])
                              if route['name'] == station['lineName']),None)
                if not route:
                    continue
                station_point = transform(FORWARD,Point(station['longitude'],station['latitude']))
                meters = origin.distance(station_point)
                if meters > 3000:
                    continue
                route_point = nearest_points(station_point,transform(FORWARD,shape(route['geometry'])))[1]
                gap = station_point.distance(route_point)
                if gap > 500:
                    continue  # Do not draw an arbitrary connection to a distant line.
                anchor = transform(INVERSE,route_point)
                result['stations'].append({**station,'distanceMeters':round(meters),
                    'routeId':route['id'],'routeAnchor':{'latitude':anchor.y,'longitude':anchor.x},
                    'routeLinkMeters':round(gap),'routeLinkBasis':'reference_point_to_official_alignment',
                    'scoringEligible':False,
                    'stationEntranceVerified':False,'walkingMeters':None,'walkingMinutes':None,
                    'checkedAt':references['checkedAt'],
                    'coordinateSource':references['coordinateSource']})
    elif metro.OUT.exists():
        # Historical reports retain only associations reviewed at that date.
        projects = analysis.get('displayProjects', analysis.get('projects', []))
        valid_ids = {p['id'] for p in projects if p['id'] in ZONE_BINDINGS
                     and p.get('region') == '동대문구' and p.get('legalDong') == '장안동'
                     and p.get('jibun') == ZONE_BINDINGS[p['id']][2]}
        result['zones'] = [z for z in metro.spatial(center,projects,day)['zones'] if z['projectId'] in valid_ids]
    featured = _featured_developments(result['zones'], analysis.get('displayProjects', []))
    result['featuredDevelopments'] = featured
    result['featuredDevelopment'] = featured[0] if featured else None
    # Apply a regional filter as well as distance. Never attach a pilot's routes by name alone.
    if entity.get('district') == '동대문구':
        bundle = read(config.ROOT / 'data/living_area_map_references.json')
        if not recent(bundle.get('checkedAt'),day):return result
        for station in bundle['stations']:
            # Current metro reports use the shared reviewed registry. Retain
            # pilot anchors only for historical reports without that coverage.
            if analysis.get('metroCoverage') and metro.rail_station_mapping.current(metro.rail_station_mapping.load(), day):
                continue
            point = transform(FORWARD, Point(station['longitude'], station['latitude']))
            distance = origin.distance(point)
            if distance <= 3000:
                result['stations'].append({**station, 'distanceMeters': round(distance),
                    'stationEntranceVerified': False, 'walkingMeters': None, 'walkingMinutes': None,
                    'checkedAt': bundle['checkedAt'], 'coordinateSource': bundle['coordinateSource']})
        ids = {s['id'] for s in result['stations']}
        result['connections'] = [c for c in bundle['connections'] if set(c['stationIds']) <= ids]
    result['stations'] = [annotate(station) for station in result['stations']]
    return result
