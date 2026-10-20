"""Shared Seoul/Gyeonggi plan coverage, exact address lookup and spatial joins.

Plan references remain separate from verified walking/direct-benefit metrics.
No region or apartment allowlist. Missing coverage never means zero development.
"""
import copy
import datetime as dt
import json
import re
import threading
from functools import lru_cache
from pathlib import Path
import config
import redevelopment_occupancy
import rail_station_mapping
import map_zone_policy
import map_zone_stage
import map_zone_context
import living_area_rail_policy
import project_official_links
import living_area_sources as sources
from living_area_scoring_policy import STAGES
from import_living_area_metro import stage, exact_point, OUT, GIS

def transform(fn, geometry):
    from shapely import transform as apply_transform
    return apply_transform(geometry,fn,interleaved=False)

LOCK=threading.RLock()
CENTER_PATH=config.ROOT/'pipeline/cache/living_area_centers.json'
AUDITED_CENTER_PATH=config.ROOT/'pipeline/cache/living_area_audited_centers.json'

@lru_cache(maxsize=2)
def _audited_centers(modified):
    return json.loads(AUDITED_CENTER_PATH.read_text())

def audited_center(identity,day):
    if not AUDITED_CENTER_PATH.exists():return None
    key=sources.digest(identity)
    item=_audited_centers(AUDITED_CENTER_PATH.stat().st_mtime_ns).get(key,{})
    checked=sources.date(item.get('day'))
    point=item.get('point')
    if not (item.get('identity')==identity and checked and 0<=(day-checked).days<=120
            and isinstance(point,dict) and point.get('coordinateBasis')=='address_geocode'):return None
    from living_area import distance
    return point if distance(point,point) is not None else None

@lru_cache(maxsize=2)
def _catalog(modified):
    data=json.loads(OUT.read_text())
    if sources.digest(data['projects'])!=data['projectsDigest']:raise ValueError('metro catalogue integrity')
    return data

def catalog():
    return _catalog(OUT.stat().st_mtime_ns) if OUT.exists() else {}

def station_visible(station,day):
    checked,published=sources.date(station.get('checkedAt')),sources.date(station.get('sourceDate'))
    return bool((station.get('stage') in STAGES or station.get('serviceStatus') == 'operating')
                and checked and published
                and 0<=(day-checked).days<=120 and published<=day)

def station_active(station,day):
    # Map visibility and eligibility for a future-rail bonus are separate.
    return station_visible(station,day) and station.get('serviceStatus') != 'operating'

def station_references(day):
    return rail_station_mapping.stations(day,catalog().get('railStations',[]))

def supported(identity):
    return identity.get('province') in ('서울특별시','경기도')

def active(p,day):
    if redevelopment_occupancy.project_evidence(p) or redevelopment_occupancy.completed_stage(p.get('stageLabel')):return False
    asof=sources.date(p.get('sourceDate'))
    checked=sources.date(p.get('checkedAt'))
    if p.get('projectType')=='new_supply':
        return bool(asof and asof<=day and checked and 0<=(day-checked).days<=120
                    and str(p.get('plannedMoveInMonth') or '')>=day.isoformat()[:7])
    return (p.get('stage') in STAGES and asof and checked and
            0<=(day-asof).days<=366 and 0<=(day-checked).days<=120)


def _plan_name(value):
    # The Gyeonggi boundary layer often leaves ALIAS blank and puts the
    # actual project name in REMARK. Punctuation differs from the quarterly
    # project list ("6,7단지" versus "6·7단지").
    name=str(value or '').lower().replace(',', '·').replace('ㆍ', '·').replace('・', '·')
    return re.sub(r'[^0-9a-z가-힣·]', '', name)


def _project_district_code(project):
    point=project.get('point') or {}
    raw=point.get('rawAddress') or {}
    code=str(project.get('districtCode') or raw.get('b_code') or '')
    return code[:5] if len(code)>=5 and code[:5].isdigit() else None

def _same_project_district(boundary_code, project):
    boundary = str(boundary_code or '')
    code = _project_district_code(project)
    # City boundaries can use the parent code (성남시 41130), while an
    # official address uses an administrative district (수정구 41131).
    return bool(code and (boundary == code or
                (len(boundary) == 5 and boundary.endswith('0') and boundary[:4] == code[:4])))


def _unnamed_boundary_project(row, geometry, points):
    if row.get('sourceLayer') not in (12, 13) or row.get('useCode') == 'UDT999':
        return None, None
    candidates = [(p, point) for p, point in points
                  if p.get('projectType') in ('redevelopment', 'reconstruction')
                  and _same_project_district(row.get('districtCode'), p)]
    inside = [p for p, point in candidates if geometry.covers(point)]
    if len(inside) == 1:
        area, project_area = row.get('siteAreaM2'), inside[0].get('siteAreaM2')
        if (isinstance(area, (float, int)) and area > 0
                and isinstance(project_area, (float, int))
                and abs(project_area - area) / area <= .01):
            return inside[0], 'official_address_and_area_inside_boundary'
        return None, None
    if inside:
        return None, None
    # A representative lot can be just outside an official reference polygon.
    # Require both proximity AND independently published matching land area.
    area = row.get('siteAreaM2')
    if not isinstance(area, (float, int)) or area <= 0:
        return None, None
    matched = [p for p, point in candidates
               if isinstance(p.get('siteAreaM2'), (float, int))
               and abs(p['siteAreaM2'] - area) / area <= .01
               and geometry.distance(point) <= 100]
    return (matched[0], 'official_address_and_area_match') if len(matched) == 1 else (None, None)


def _project_name_key(value):
    # Remove administrative suffixes only. Keep phases/numbers and place names.
    name = _plan_name(value)
    previous = None
    while previous != name:
        previous = name
        name = re.sub(r'(?:주택)?(?:재개발|재건축)(?:정비)?(?:사업|구역)?$|정비구역$|구역$', '', name)
    return name


def _named_boundary_project(row, geometry, points):
    """Match a full official name using district, area AND nearby exact address."""
    if row.get('sourceLayer') not in (12, 13) or row.get('useCode') not in ('UDR100', 'UDT100'):
        return None
    source = _project_name_key(row.get('sourceName'))
    area = row.get('siteAreaM2')
    if not source or not isinstance(area, (int, float)) or area <= 0:
        return None
    matches = []
    for project, point in points:
        if project.get('projectType') not in ('redevelopment', 'reconstruction'):
            continue
        if _project_name_key(project.get('name')) != source:
            continue
        original = row.get('sourceName', '')
        if ('재개발' in original and project['projectType'] != 'redevelopment'
                or '재건축' in original and project['projectType'] != 'reconstruction'):
            continue
        if (not _same_project_district(row.get('districtCode'), project)
                or geometry.distance(point) > 100):
            continue
        project_area = project.get('siteAreaM2')
        if not isinstance(project_area, (int, float)) or abs(project_area-area)/area > .01:
            continue
        matches.append(project)
    return matches[0] if len(matches) == 1 else None


def _center(apartment_id,province,district,dong,lot,day):
    identity={'apartmentId':apartment_id,'province':province,'district':district,'legalDong':dong,'jibun':lot}
    key=sources.digest(identity)
    with LOCK:
        cache=json.loads(CENTER_PATH.read_text()) if CENTER_PATH.exists() else {}
        item=cache.get(key)
    if item and item.get('day')==day:return item.get('point')
    try: point=exact_point({**identity,'region':district})
    except Exception: return None  # API failure is retried, never saved as a negative result.
    with LOCK:
        cache=json.loads(CENTER_PATH.read_text()) if CENTER_PATH.exists() else {}
        cache[key]={'identity':identity,'day':day,'point':point}
        CENTER_PATH.parent.mkdir(parents=True,exist_ok=True)
        tmp=CENTER_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(cache,ensure_ascii=False));tmp.replace(CENTER_PATH)
    return point

def center_for(identity,day):
    if not supported(identity) or not all(identity.get(k) for k in ('apartmentId','district','legalDong','jibun')):return None
    bound={k:identity.get(k) for k in ('apartmentId','province','district','legalDong','jibun')}
    bound['jibun']=str(bound['jibun'])
    reviewed=audited_center(bound,day)
    if reviewed:return reviewed
    return _center(identity['apartmentId'],identity['province'],identity['district'],identity['legalDong'],str(identity['jibun']),day.isoformat())

def _boundary_project(row, geom, points, projects):
    reviewed={'11000UQ120PS202411014521':'seoul-plan-renewal:7073','11000UQ120PS202411014176':'seoul-plan-renewal:7810'}
    inside=[p for p,pt in points if geom.covers(pt)]
    matches=[p for p in projects if p['id']==reviewed.get(row['id'])]
    method='reviewed_identity' if matches else None
    if not matches:
        exact=[p for p in inside if re.sub(r'\s+','',p['name'])==re.sub(r'\s+','',row['sourceName'])]
        matches=exact
        if len(matches)==1:method='exact_name_and_point_inside'
    if not matches and row['sourceId']=='gg-plan-boundary' and row['businessNameConfirmed']:
        # Name and district alone cannot identify separate nearby phases.
        # Outside representative lots also require matching area and proximity.
        area=row.get('siteAreaM2')
        exact=[p for p,pt in points if _plan_name(p.get('name'))==_plan_name(row['sourceName'])
               and _same_project_district(row['districtCode'],p)
               and isinstance(area,(int,float)) and area>0
               and isinstance(p.get('siteAreaM2'),(int,float))
               and abs(p['siteAreaM2']-area)/area<=.01 and geom.distance(pt)<=100]
        if len(exact)==1:matches=exact;method='official_name_district_area_and_proximity'
    if not matches and row['sourceId']=='gg-plan-boundary' and row['businessNameConfirmed']:
        matched = _named_boundary_project(row, geom, points)
        if matched:
            matches=[matched];method='official_name_address_and_area'
    if not matches and row['sourceId']=='gg-plan-boundary' and not row['businessNameConfirmed']:
        matched, matched_method = _unnamed_boundary_project(row, geom, points)
        if matched:
            matches=[matched];method=matched_method
    return (matches[0], method) if len(matches)==1 else (None, None)


@lru_cache(maxsize=2)
def _index(seoul_modified,metro_modified,scale_modified,occupancy_revision=None,stage_revision=None,apartment_revision=None):
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    from pyproj import Transformer
    forward=Transformer.from_crs(4326,5179,always_xy=True).transform
    original=json.loads((config.ROOT/'data/redevelopment_zones.geojson').read_text())['features']
    scale_path=config.ROOT/'data/redevelopment_project_scales.json'
    scale_refs={r['boundaryId']:r for r in json.loads(scale_path.read_text()).get('projects',[])} if scale_path.exists() else {}
    rows=[]; shapes=[]
    for f in original:
        props=f['properties']; label=props.get('stage','')
        stage_definition=map_zone_stage.definition(props)
        if stage_definition:label=stage_definition['label']
        scale=scale_refs.get(props['id'],{})
        if (scale.get('name')!=props['name'] or scale.get('districtCode')!=props.get('districtCode')
                or scale.get('siteAreaM2')!=props.get('areaSqm')):
            scale={}
        rows.append({'id':props['id'],'sourceName':props['name'],'name':props['name'],
                     'sourceNameField':'name','businessNameConfirmed':True,'stageLabel':label,
                     'stage':stage(label),'projectTypeLabel':props.get('projectType',''),
                     'stageDefinition':stage_definition,
                     'geometry':f['geometry'],'siteAreaM2':props.get('areaSqm'),
                     **{k:scale[k] for k in ('reportedHouseholds','reportedHouseholdsBasis',
                         'reportedHouseholdsSourceUrl','reportedHouseholdsSourceNote') if k in scale},
                     'sourceUrl':'https://data.seoul.go.kr/dataList/OA-22712/S/1/datasetView.do',
                     'sourceDate':props.get('sourceDate') or '2026-02',
                     'rawTypeCode':props.get('rawTypeCode'),'rawStageCode':props.get('rawStageCode'),
                     'sourceId':'seoul-plan-boundary','districtCode':props.get('districtCode')})
    for f in catalog().get('ggBoundaries',[]):
        p=f['properties'];alias=str(p.get('ALIAS') or '').strip();remark=str(p.get('REMARK') or '').strip();layer=p['sourceLayer']
        label={12:'재개발구역',13:'정비구역',14:'재정비촉진지구',15:'주거환경개선지구'}[layer]
        generic={'','정비구역','정비예정구역','재개발구역','재정비촉진지구','주거환경개선지구','주택재건축정비구역','주택재개발정비구역'}
        name=next((v for v in (alias,remark) if v and _plan_name(v) not in generic), alias or remark)
        named=bool(name and _plan_name(name) not in generic)
        rows.append({'id':'gg-zone:'+str(layer)+':'+str(p['OBJECTID']),'sourceName':name or label,
                     'sourceNameField':'ALIAS' if name and name == alias else 'REMARK' if remark else None,
                     'sourceAlias':alias,'sourceRemark':remark,'noticeDate':p.get('NTFDATE'),
                     'sourceLayer':layer,'useCode':p.get('USE_CD'),
                     'businessNameConfirmed':named,'name':name if named else label,
                     'stageLabel':'진행 단계 미확인','stage':'unknown',
                     'projectTypeLabel':label,'geometry':f['geometry'],'siteAreaM2':p.get('SHAPE.AREA'),
                     'sourceUrl':GIS+'bdsMap_Public/MapServer/'+str(layer),
                     'sourceDate':catalog().get('checkedAt'),'sourceId':'gg-plan-boundary',
                     'districtCode':p.get('STD_SGGCD')})
    good=[]
    for row in rows:
        try:
            geo=shape(row['geometry'])
            if geo.geom_type not in ('Polygon','MultiPolygon') or not geo.is_valid:continue
            projected=transform(forward,geo)
            good.append(row);shapes.append(projected)
        except (ValueError,TypeError):continue
    import redevelopment_completion
    good,shapes,audit=redevelopment_completion.filter_boundaries(good,shapes,catalog().get('projects',[]),_boundary_project)
    return good,shapes,STRtree(shapes),audit


def spatial_index():
    seoul=config.ROOT/'data/redevelopment_zones.geojson'
    scales=config.ROOT/'data/redevelopment_project_scales.json'
    apartments=config.ROOT/'data/living_area_apartment_points.json'
    return _index(seoul.stat().st_mtime_ns,OUT.stat().st_mtime_ns,
                  scales.stat().st_mtime_ns if scales.exists() else 0,
                  redevelopment_occupancy.revision(),map_zone_stage.revision(),
                  apartments.stat().st_mtime_ns if apartments.exists() else 0)


def spatial(center,projects,day, *, bbox=None, include_routes=True):
    from shapely.geometry import Point,shape,box
    from shapely.ops import nearest_points
    from pyproj import Transformer
    rows,shapes,tree,_=spatial_index()
    development_contexts = map_zone_context.for_boundaries(rows, projects, day)
    forward=Transformer.from_crs(4326,5179,always_xy=True).transform
    inverse=Transformer.from_crs(5179,4326,always_xy=True).transform
    origin=transform(forward,Point(center['longitude'],center['latitude']))
    points=[]
    for p in projects:
        pt=p.get('point') or p
        if isinstance(pt.get('longitude'),(int,float)) and isinstance(pt.get('latitude'),(int,float)):
            points.append((p,transform(forward,Point(pt['longitude'],pt['latitude']))))
    zones=[]
    search_area = transform(forward, box(*bbox)) if bbox else origin.buffer(2000)
    for idx in tree.query(search_area):
        row=rows[int(idx)];geom=shapes[int(idx)];meters=origin.distance(geom)
        if bbox:
            if not geom.intersects(search_area):continue
        elif meters>2000:continue
        p,method=_boundary_project(row,geom,points,projects)
        if p and p.get('stage')=='completed':continue
        project_stage=stage(p.get('stageLabel')) if p else 'unknown'
        stage_conflict=bool(p and project_stage!='unknown'
                            and row['stage']!='unknown' and project_stage!=row['stage'])
        # A known original label (e.g. 건축심의) is useful even when it does
        # not fit the common redevelopment scoring stages.
        stage_source=p if p and (p.get('stageLabel') or '') not in map_zone_stage.MISSING else row
        selected_stage=project_stage if stage_source is p else row['stage']
        nearest=transform(inverse,nearest_points(origin,geom)[1]);label=shape(row['geometry']).representative_point()
        zones.append({**row, **project_official_links.for_boundary(row, p, day),
                      **({'developmentContext':development_contexts[row['id']]} if row['id'] in development_contexts else {}),
                      'projectId':p['id'] if p else 'boundary:'+row['id'],
                      'name':(row['name'] if row['businessNameConfirmed']
                              else p['name'] if p else row['name'] + ' · 사업명 미확인'),
                      **map_zone_policy.classify(row,p),
                      'boundaryStageLabel':row['stageLabel'],'projectStageLabel':p.get('stageLabel') if p else None,
                      'stageMismatch':stage_conflict,
                      **map_zone_stage.explanation(row,p,stage_conflict,stage_source,selected_stage),
                      'stageSourceUrl':None if stage_conflict else stage_source.get('sourceUrl'),
                      'stageSourceDate':None if stage_conflict else stage_source.get('sourceDate'),
                      'stageEvidence':[{'label':row['stageLabel'],'sourceUrl':row['sourceUrl'],'sourceDate':row['sourceDate']}]
                          + ([{'label':p['stageLabel'],'sourceUrl':p.get('sourceUrl'),'sourceDate':p.get('sourceDate')}] if p else []),
                      'stageLabel':'진행 단계 확인 중' if stage_conflict else stage_source['stageLabel'],
                      'stage':'unknown' if stage_conflict else selected_stage,
                      'projectType':p.get('projectType') if p else None,
                      'plannedHouseholds':p.get('plannedHouseholds') if p else None,
                      'matchMethod':method if p else 'boundary_only',
                      'businessNameConfirmed':bool(p) or row['businessNameConfirmed'],
                      'nameSourceUrl':p.get('sourceUrl') if p else row['sourceUrl'],
                      'nameSourceDate':p.get('sourceDate') if p else row['sourceDate'],
                      'nameCorrected':bool(p and not row['businessNameConfirmed'] and p['name'] != row['sourceName']),
                      'latitude':label.y,'longitude':label.x,'targetLatitude':nearest.y,'targetLongitude':nearest.x,
                      'distanceMeters':round(meters),'distanceLabel':'구역 경계까지 직선','containsSubject':geom.covers(origin),
                      'useContext':'noncommercial','commercialAllowed':False,'previewOnly':False,
                      'licenseStatus':'noncommercial_reference','note':'공식 지도 참고 경계 · 법적 경계 및 출입구 아님'})
    zones.sort(key=lambda z:(z['distanceMeters'],z.get('siteAreaM2') or 1e20,z['id']))
    routes=[]
    if not include_routes:return {'zones':zones,'routes':routes,'zoneCoverage':map_zone_policy.coverage()}
    for f in catalog().get('railRoutes',[]):
        p=f['properties']
        # Existing lines and partial openings are not promised new transport benefits.
        if p.get('FORM')=='개통' or not f.get('geometry'):continue
        geom=transform(forward,shape(f['geometry']));meters=origin.distance(geom)
        if meters>3000:continue
        nearest=transform(inverse,nearest_points(origin,geom)[1])
        route_coverage = rail_station_mapping.route_coverage('gg-rail:'+str(p['OBJECTID']),center,day)
        routes.append({**project_official_links.for_project({'id':'gg-rail:'+str(p['OBJECTID']),'name':p['LINE_NAME']}, day),
                       'id':'gg-rail:'+str(p['OBJECTID']),'name':p['LINE_NAME'],'stageLabel':p.get('PCST') or p.get('FORM'),
                       'geometry':f['geometry'],'distanceMeters':round(meters),'distanceLabel':'계획 노선까지 직선 · 역까지 거리 아님',
                       'latitude':nearest.y,'longitude':nearest.x,
                       'sourceUrl':GIS+'bdsMap_Monitoring/MapServer/7','sourceDate':catalog()['checkedAt'],
                       'geometryBasis':'official_reference_alignment','scoringEligible':False,
                       'stationCoverage':route_coverage,
                       **{k:route_coverage[k] for k in ('railReviewStatus','defaultVisible','reviewLabel','reviewReason')
                          if k in route_coverage}})
    return {'zones':zones,'routes':routes,'zoneCoverage':map_zone_policy.coverage()}


def attach(result,identity,day):
    if not supported(identity) or not OUT.exists():return result
    bundle=catalog()
    checked=sources.date(bundle.get('checkedAt'))
    if not checked or not 0 <= (day-checked).days <= 120:return result
    result['metroIdentity']={k:identity.get(k) for k in ('province','district','legalDong','jibun')}
    result['metroCoverage']={**bundle['coverage'],'checkedAt':bundle['checkedAt'],'status':'partial'}
    mapping=rail_station_mapping.load()
    if rail_station_mapping.current(mapping,day):
        result['metroCoverage'].update(railStationMapping=mapping.get('coverage',{}),
            railStationReferences=mapping.get('coverage',{}).get('locatedStations',0),
            railStationCheckedAt=mapping.get('checkedAt'))
    center=result.get('center') or result.get('mapCenter') or center_for(identity,day)
    if center: result['mapCenter']=dict(center)
    # More recent reviewed notices override broad catalogues by source ID / exact full lot.
    retired=set(spatial_index()[3]['excludedProjectIds'])
    for field in ('projects','referenceProjects'):
        result[field]=[p for p in result.get(field,[]) if p['id'] not in retired
                       and p.get('stage')!='completed'
                       and not redevelopment_occupancy.completed_stage(p.get('stageLabel'))
                       and not redevelopment_occupancy.project_evidence(p)]
    existing=[*result.get('projects',[]),*result.get('referenceProjects',[])]
    curated_keys={(p.get('region'),p.get('legalDong'),p.get('jibun')) for p in existing if p.get('jibun')}
    candidates=[p for p in bundle['projects'] if p['id'] not in {x['id'] for x in existing}
                and (p.get('region'),p.get('legalDong'),p.get('jibun')) not in curated_keys]
    candidates+=existing
    candidates=[p for p in candidates if p['id'] not in retired
                and p.get('stage')!='completed' and not redevelopment_occupancy.completed_stage(p.get('stageLabel'))
                and not redevelopment_occupancy.project_evidence(p)]
    candidates=[{**p, **project_official_links.for_project(p, day)} for p in candidates]
    from living_area import distance
    near=[]
    for p in candidates:
        if p.get('stage') not in STAGES and p.get('projectType')!='new_supply':continue
        if p not in existing and not active(p,day):continue
        if (p.get('region'),p.get('legalDong'),p.get('jibun'))==(identity.get('district'),identity.get('legalDong'),identity.get('jibun')):continue
        pt=p.get('point') or p
        meters=distance(center,pt) if center else None
        if meters is None or meters>2000:continue
        near.append({**{k:v for k,v in p.items() if k!='point'},
            'latitude':pt['latitude'],'longitude':pt['longitude'],'geometryType':'point','distanceMeters':round(meters),
            'distanceLabel':'주소 대표점 직선거리','coordinateBasis':pt.get('coordinateBasis','address_geocode'),
            'coordinateSourceUrl':pt.get('sourceUrl'),'coordinateCheckedAt':pt.get('checkedAt'),
            'walkingMeters':None,'walkingMinutes':None,'benefitClass':'unverified','benefitLabel':'직접 수혜 미확인',
            'scopeLabel':'주변 사업 · 직선 2km 안','confidence':'plan_reference'})
    nearby_spatial=spatial(center,candidates,day) if center else {'zones':[],'routes':[]}
    # Route facts are useful even without a verified station. Publish them separately
    # from station-based scores, including already opened sections in the raw status.
    result['transportRoutes']=[{k:v for k,v in route.items() if k!='geometry'}
                               for route in nearby_spatial['routes']]
    zones=nearby_spatial['zones']
    by_id={p['id']:p for p in near}
    candidates_by_id={p['id']:p for p in candidates}
    for z in zones:
        if z['containsSubject']:continue # Do not count one's own redevelopment as a neighbouring benefit.
        if z['projectId'] in by_id:
            by_id[z['projectId']]['distanceMeters']=z['distanceMeters'];by_id[z['projectId']]['distanceLabel']='구역 경계까지 직선'
            continue
        if z['stage'] not in STAGES:continue
        kind=z.get('projectTypeLabel','')
        if not any(k in kind for k in ('재개발','재건축','주택정비','모아','가로주택','신속통합','주거환경')):continue
        by_id[z['projectId']]={'id':z['projectId'],'name':z['name'],'region':identity['district'],
            'projectType':'reconstruction' if '재건축' in kind else 'redevelopment',
            'stage':z['stage'],'stageLabel':z['stageLabel'],'siteAreaM2':z.get('siteAreaM2'),
            'sourceUrl':z['sourceUrl'],'sourceDate':z['sourceDate'],'checkedAt':bundle['checkedAt'],
            'geometryType':'point','latitude':z['latitude'],'longitude':z['longitude'],
            'distanceMeters':z['distanceMeters'],'distanceLabel':'구역 경계까지 직선','plannedHouseholds':None,
            'benefitClass':'unverified','benefitLabel':'직접 수혜 미확인','scopeLabel':'참고 경계 · 규모·단계 확인',
            'positionLabel':'공식 참고 경계 안의 표시 위치 · 출입구 아님'}
        by_id[z['projectId']].update({k:z[k] for k in ('reportedHouseholds','reportedHouseholdsBasis',
            'reportedHouseholdsSourceUrl','reportedHouseholdsSourceNote') if k in z})
        if source_project := candidates_by_id.get(z['projectId']):
            # Keep the authoritative supply/stage facts when a boundary supplies location.
            by_id[z['projectId']].update({k:v for k,v in source_project.items()
                if k not in ('point','latitude','longitude','geometryType','distanceMeters','distanceLabel')})
        by_id[z['projectId']].update(walkingMeters=None,walkingMinutes=None)
        by_id[z['projectId']].update({k:v for k,v in z.items() if k.startswith('officialDetail')})
    # Remove point references inside a containing own zone as well.
    own_ids={z['projectId'] for z in zones if z['containsSubject']}
    for pid in own_ids:by_id.pop(pid,None)
    # Keep a regional list even if location cannot be established. It never earns points.
    regional=[p for p in candidates if p.get('region')==identity.get('district') and p['id'] not in by_id and p.get('stage') in STAGES]
    result['metroCoverage'].update(nearbyProjects=len(by_id),regionalProjects=len(regional),
                                 mappedBoundaries=len(zones),railRoutesNearby=len(nearby_spatial['routes']),
                                 locationStatus='located' if center else 'unresolved')
    result['regionalProjects']=[{k:v for k,v in p.items() if k in ('id','name','stageLabel','plannedHouseholds','sourceUrl','sourceDate')
                                or k.startswith('officialDetail')} for p in regional]
    # Preserve curated rail/region facts, but never dump an entire city on the map.
    for p in existing:
        if p['id'] not in by_id and p['id'] not in own_ids and p.get('projectType')=='transport':by_id[p['id']]=p
    from living_area_context import recent
    references = sorted(station_references(day),
                        key=lambda station: distance(center, station) if center else float('inf'))
    for station in references:
        if station.get('scoringEligible') is False:continue
        meters=distance(center,station) if center and station_active(station,day) else None
        if meters is None or meters>2000:continue
        pid=station['projectId']
        if pid not in by_id:
            by_id[pid]={'id':pid,'name':station['lineName'],'projectType':'transport',
                'stage':station['stage'],'stageLabel':station['stageLabel'],'region':identity['district'],
                'sourceUrl':station['planSourceUrl'],'sourceDate':station['sourceDate'],
                'checkedAt':station['checkedAt'],'licenseVerifiedAt':station['checkedAt'],
                'nearestStationId':station['id'],
                'factSummary':station['name']+' 경유 계획 · '+station['stageLabel'],
                'planningNote':station.get('planningNote',''),
                'negativeFactors':[station['planningNote']] if station.get('planningNote') else [],
                'distanceMeters':round(meters),'distanceLabel':'계획역 참고 위치까지 직선거리',
                'benefitClass':'unverified','benefitLabel':'직접 수혜 미확인',
                'scopeLabel':'계획 경유역 · 출입구 미확정'}
    result['metroCoverage']['nearbyProjects']=len(by_id)
    for p in by_id.values():
        if p.get('projectType') == 'transport':
            p.update(living_area_rail_policy.annotate(p))
        p.update(project_official_links.for_project(p, day))
        p.setdefault('sourceRecordId',p['id'])
        p.setdefault('licenseVerifiedAt',bundle['checkedAt'])
        p.setdefault('licenseUrl',p.get('sourceUrl'))
    strict_ids={p['id'] for p in result.get('projects',[])}
    result['referenceProjects']=[p for p in by_id.values() if p['id'] not in strict_ids]
    if not by_id:
        result['headline']='주변 개발계획을 더 확인한 뒤 매수 가격을 판단하세요.'
        result['intro']='같은 지역의 공개 사업 목록은 아래에서 확인할 수 있어요. 단지 가까이 있는지 확인되지 않은 사업은 점수에 넣지 않아요.'
    result['snapshotId']=sources.digest({'previous':result['snapshotId'],'catalogue':bundle['projectsDigest'],
                                        'center':center,'projects':result['referenceProjects'],
                                        'transportRoutes':result['transportRoutes']})
    return result
