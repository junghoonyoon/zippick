"""Retire finished sites across source layers without deleting official evidence."""
import datetime as dt
import difflib
import json
import re

from pyproj import Transformer
from shapely import transform
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

import config
import redevelopment_occupancy as occupancy


def apartment_name(value):
    # Supply rounds are not separate buildings; phase and block numbers remain.
    text = re.sub(r'\(\s*\d+차\s*공급\s*\)', '', str(value or ''))
    text = re.sub(r'[\s*]+', '', text).lower().replace('sk뷰','skview')
    return re.sub(r'(?:아파트|주상복합)$', '', text)


def project_name(value):
    text=re.sub(r'\s+', '', str(value or ''))
    return re.sub(r'(?:주택)?(?:재개발|재건축)(?:정비)?(?:사업)?(?:구역)?$|주거환경개선사업지구$', '', text)


def completed_boundary_groups(rows,shapes,projects,project_points):
    """A published project may be split into several GIS records (e.g. 신흥)."""
    regions=json.loads((config.ROOT/'data/purchase_regions.json').read_text())['regions']
    region_codes={(r['province'],r['district'].replace('시 ','')):r['code'] for r in regions}
    groups={}
    for index,row in enumerate(rows):
        if row.get('sourceId')!='gg-plan-boundary' or not row.get('businessNameConfirmed'):continue
        if row.get('sourceLayer') not in (12,13,15):continue
        key=(row.get('districtCode'),row.get('sourceLayer'),project_name(row['sourceName']))
        groups.setdefault(key,[]).append(index)
    points={p['id']:pt for p,pt in project_points}
    result={}
    for (district,layer,name),indices in groups.items():
        area=sum(rows[i].get('siteAreaM2') or 0 for i in indices)
        if area<=0:continue
        geom=unary_union([shapes[i] for i in indices])
        matches=[]
        for p in projects:
            if project_name(p.get('name'))!=name:continue
            code=region_codes.get((p.get('province'),p.get('region')))
            if not code:
                raw=(p.get('point') or {}).get('rawAddress') or {}
                code=str(raw.get('b_code') or '')[:5]
            same_district=code and (code==district or (str(district).endswith('0') and code[:4]==district[:4]))
            size=p.get('siteAreaM2')
            if not same_district or not isinstance(size,(int,float)) or abs(size-area)/area>.01:continue
            # Full official name + district + published total area bind missing old lots.
            # If a coordinate exists, a clearly different location rejects the match.
            if p['id'] in points and geom.distance(points[p['id']])>500:continue
            matches.append(p)
        if len(matches)==1 and (matches[0].get('stage')=='completed' or occupancy.project_evidence(matches[0])):
            for index in indices:result[index]=matches[0]
    return result


def _area_project_name(value):
    """Normalize project names while preserving identifying words and numbers."""
    text = str(value or '').lower()
    text = text.replace('생활권', '')
    text = re.sub(r'[（(][^）)]*[）)]', '', text)
    text = re.sub(r'[^0-9a-z가-힣]', '', text)
    text = re.sub(r'^(?:경기도|경기|서울특별시|서울|인천광역시|인천|용인|김포|고양)', '', text)
    text = re.sub(r'(?:주택)?(?:재개발|재건축)(?:정비)?(?:사업)?(?:구역|단지)?$', '', text)
    return project_name(text)


def _generic_boundary_name(value):
    name = re.sub(r'[^0-9가-힣]', '', str(value or ''))
    return name in {
        '', '정비구역', '정비예정구역', '재개발구역', '재건축', '주택재건축정비구역',
        '주택재개발정비구역', '재정비촉진지구', '주거환경개선지구',
        '주거환경개선사업', '주거환경관리구역', '정비사업후보지행위제한지역',
    }


def _same_area_project_name(boundary_name, project):
    if _generic_boundary_name(boundary_name):
        return True
    left = _area_project_name(boundary_name)
    right = _area_project_name(project.get('name'))
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return min(len(left), len(right)) >= 5 and difflib.SequenceMatcher(None, left, right).ratio() >= .82


def nearby_completed_boundary_groups(rows, shapes, projects, project_points, radius_m=250):
    """Recover completed Gyeonggi projects whose boundary record lost its name.

    A name-less or split GIS row is linked only when district, published site
    area, nearby official project address and (when present) project name all
    agree. A unique match is required; nearby apartments alone never retire a
    boundary.
    """
    result = {}
    regions=json.loads((config.ROOT/'data/purchase_regions.json').read_text())['regions']
    region_codes={(r['province'],r['district'].replace('시 ','')):r['code'] for r in regions}
    closed = []
    for project, point in project_points:
        label = re.sub(r'\s+', '', str(project.get('stageLabel') or ''))
        if (occupancy.project_evidence(project)
                or (project.get('stage') == 'completed'
                    and label not in {'해제', '폐지', '취소', '해산', '청산'})):
            closed.append((project, point))
    for index, (row, geometry) in enumerate(zip(rows, shapes)):
        if row.get('sourceId') != 'gg-plan-boundary' or row.get('sourceLayer') not in (12, 13, 15):
            continue
        area = row.get('siteAreaM2')
        if not isinstance(area, (int, float)) or area <= 0:
            continue
        boundary_name = row.get('sourceName') or row.get('name')
        matches = []
        for project, point in closed:
            if project.get('projectType') not in ('redevelopment', 'reconstruction'):
                continue
            code = region_codes.get((project.get('province'), str(project.get('region') or '').replace('시 ', '')))
            if not code:
                raw = (project.get('point') or {}).get('rawAddress') or {}
                code = str(raw.get('b_code') or '')[:5]
            district = str(row.get('districtCode') or '')
            same_district = code and (code == district or (district.endswith('0') and code[:4] == district[:4]))
            project_area = project.get('siteAreaM2')
            if not same_district or not isinstance(project_area, (int, float)) or abs(project_area-area)/area > .01:
                continue
            if geometry.distance(point) > radius_m or not _same_area_project_name(boundary_name, project):
                continue
            matches.append(project)
        if len(matches) == 1:
            result[index] = matches[0]
    return result


def unique_completed_area_boundary_groups(rows, projects, project_points, tolerance=0.0015):
    """Link Gyeonggi boundaries to one official completed project by name and area.

    This fallback is only used when the official project record has no usable
    coordinate. It requires a residential project with a completed status and
    known household count, the same district, and a one-to-one match in both
    directions. Generic labels need an area difference of at most 0.15%; a
    named boundary whose name matches the project can differ by up to 1%.
    """
    regions=json.loads((config.ROOT/'data/purchase_regions.json').read_text())['regions']
    region_codes={(r['province'],r['district'].replace('시 ','')):r['code'] for r in regions}
    projects_with_points={p['id'] for p,_ in project_points}
    candidates_by_boundary={}
    boundaries_by_project={}
    for index,row in enumerate(rows):
        if row.get('sourceId')!='gg-plan-boundary' or row.get('sourceLayer') not in (12,13,15):
            continue
        boundary_name=row.get('sourceName') or row.get('name')
        generic_name=_generic_boundary_name(boundary_name)
        area=row.get('siteAreaM2')
        if not isinstance(area,(int,float)) or area<=0:
            continue
        district=str(row.get('districtCode') or '')
        matches=[]
        for project in projects:
            if project.get('id') in projects_with_points:
                continue
            if project.get('projectType') not in ('redevelopment','reconstruction'):
                continue
            if project.get('stage')!='completed' or project.get('stageLabel') in {'해제','폐지','취소','청산','해산'}:
                continue
            households=project.get('plannedHouseholds')
            if not isinstance(households,(int,float)) or households<=0:
                continue
            name_match=_same_area_project_name(boundary_name,project)
            if not generic_name and not name_match:
                continue
            code=region_codes.get((project.get('province'),str(project.get('region') or '').replace('시 ','')))
            if not code:
                raw=(project.get('point') or {}).get('rawAddress') or {}
                code=str(raw.get('b_code') or '')[:5]
            same_district=code and (code==district or (district.endswith('0') and code[:4]==district[:4]))
            project_area=project.get('siteAreaM2')
            area_tolerance=0.01 if name_match and not generic_name else tolerance
            if not same_district or not isinstance(project_area,(int,float)) or abs(project_area-area)/area>area_tolerance:
                continue
            matches.append(project)
        if matches:
            candidates_by_boundary[index]=matches
            for project in matches:
                group=boundaries_by_project.setdefault(project['id'],{'named':set(),'generic':set()})
                group['generic' if generic_name else 'named'].add(index)
    result={}
    for index,matches in candidates_by_boundary.items():
        if len(matches)!=1:
            continue
        group=boundaries_by_project[matches[0]['id']]
        preferred=group['named'] or group['generic']
        if index in preferred and len(preferred)==1:
            result[index]=matches[0]
    return result


def approved_apartments():
    path = config.ROOT / 'data/living_area_apartment_points.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    today = dt.date.today()
    output = []
    for row in data.get('rows', []):
        try:
            approval = dt.datetime.fromtimestamp(row['use_aprv_ymd']/1000,
                dt.timezone(dt.timedelta(hours=9))).date()
            if approval > today or not all(row.get(k) for k in ('apt_cd','apt_nm','sgg_addr','emd_addr','apt_rdn_addr')):
                continue
            point = Point(float(row['xcrd']), float(row['ycrd']))
            if not (124 < point.x < 132 and 33 < point.y < 39):continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        output.append((row, point, approval.isoformat()))
    return output


def filter_boundaries(rows, shapes, projects, match_project):
    forward = Transformer.from_crs(4326, 5179, always_xy=True).transform
    project_points = []
    for p in projects:
        pt = p.get('point') or p
        if isinstance(pt.get('longitude'),(int,float)) and isinstance(pt.get('latitude'),(int,float)):
            project_points.append((p, transform(Point(pt['longitude'],pt['latitude']),forward,interleaved=False)))
    project_tree=STRtree([pt for _,pt in project_points])
    def match(row,geometry):
        nearby=[project_points[int(i)] for i in project_tree.query(geometry.buffer(100))]
        return match_project(row,geometry,nearby,projects)
    apartments = [(a,transform(pt,forward,interleaved=False),approved)
                  for a,pt,approved in approved_apartments()]
    by_name = {}
    for a,pt,approved in apartments:
        by_name.setdefault(apartment_name(a['apt_nm']),[]).append((a,pt,approved))
    excluded = {}
    retired_projects = {p['id'] for p in projects if p.get('stage')=='completed'
                        or occupancy.completed_stage(p.get('stageLabel')) or occupancy.project_evidence(p)}
    completed_groups=completed_boundary_groups(rows,shapes,projects,project_points)
    completed_area_groups=nearby_completed_boundary_groups(rows,shapes,projects,project_points)
    completed_unique_area_groups=unique_completed_area_boundary_groups(rows,projects,project_points)
    for index,(row,geometry) in enumerate(zip(rows,shapes)):
        evidence = occupancy.occupancy_evidence({**row,'projectType':row.get('projectTypeLabel')})
        project,method = match(row,geometry)
        if not project and index in completed_groups:
            project=completed_groups[index];method='official_name_district_and_combined_site_area'
        if not project and index in completed_area_groups:
            project=completed_area_groups[index];method='official_district_site_area_and_nearby_project_address'
        if not project and index in completed_unique_area_groups:
            project=completed_unique_area_groups[index];method='official_district_and_unique_site_area_without_project_coordinates'
        reason = None
        if evidence:
            reason = 'reviewed_completion'
        elif row.get('stage')=='completed' or occupancy.completed_stage(row.get('stageLabel')):
            reason = 'official_completed_stage'
        elif project and project['id'] in retired_projects:
            reason = 'completed_project_identity'
            evidence = {'projectId':project['id'],'sourceUrl':project.get('sourceUrl'),
                        'sourceDate':project.get('sourceDate'),'projectName':project.get('name'),
                        'projectStageLabel':project.get('stageLabel'),
                        'projectSiteAreaM2':project.get('siteAreaM2'),
                        'boundaryAreaM2':row.get('siteAreaM2'),'matchMethod':method}
        # Recruitment on an existing complex cannot describe a future construction site.
        # Apply only to supply/reference records, never to a new reconstruction project.
        if not reason and row.get('projectTypeLabel') in ('미리내집','장기전세주택','청년안심주택'):
            hits=[(a,approved) for a,pt,approved in by_name.get(apartment_name(row['name']),[])
                  if geometry.distance(pt)<=50]
            addresses={(a['emd_addr'],a['apt_rdn_addr'],approved) for a,approved in hits}
            if hits and len(addresses)==1:
                a,approved=hits[0]
                reason='existing_apartment_supply'
                evidence={'kaptCode':a['apt_cd'],'apartmentName':a['apt_nm'],
                          'legalDong':a['emd_addr'],'roadAddress':a['apt_rdn_addr'],
                          'useApprovalDate':approved,
                          'sourceUrl':'https://data.seoul.go.kr/dataList/OA-15818/A/1/datasetView.do',
                          'matchMethod':'exact_apartment_name_and_address_within_50m'}
        if not reason and row.get('projectTypeLabel')=='미리내집':
            # This layer describes rental supply rounds, not construction work.
            # A future construction site's own redevelopment record remains separate.
            reason='housing_supply_notice'
            evidence={'sourceUrl':row.get('sourceUrl'),'sourceDate':row.get('sourceDate'),
                      'note':'임대주택 공급 안내는 개발사업 경계에서 제외. 준공 여부를 추정한 것이 아님.'}
        if reason:
            if project:retired_projects.add(project['id'])
            excluded[index]={'id':row['id'],'name':row['name'],'reason':reason,'evidence':evidence,
                             'sourceUrl':row.get('sourceUrl'),'stageLabel':row.get('stageLabel')}
    # The same finished site can survive under a different source ID or supply round.
    # Require almost identical footprints; a neighbouring phase or broad district stays.
    closed_indices=[i for i in excluded if excluded[i]['reason']!='housing_supply_notice']
    closed_shapes=[shapes[i] for i in closed_indices]
    tree=STRtree(closed_shapes)
    for index,(row,geometry) in enumerate(zip(rows,shapes)):
        if index in excluded or geometry.area<=0:continue
        for hit in tree.query(geometry):
            other_index=closed_indices[int(hit)]
            other=rows[other_index]; finished=shapes[other_index]
            if row.get('districtCode')!=other.get('districtCode'):continue
            ratio=geometry.area/finished.area if finished.area else 0
            if not .9 <= ratio <= 1.1:continue
            # Do not treat a cancelled plan as proof that an apartment was completed.
            if other.get('stageLabel') in ('해제','폐지','취소','청산','해산'):continue
            label=row.get('projectTypeLabel','')
            same_project=apartment_name(row['name'])==apartment_name(other['name'])
            source_variant=(label=='재정비촉진구역' or other.get('projectTypeLabel')=='재정비촉진구역')
            supply=label in ('미리내집','장기전세주택','청년안심주택')
            if not (same_project or source_variant or supply):continue
            if geometry.intersection(finished).area / max(geometry.area,finished.area)<.97:continue
            excluded[index]={'id':row['id'],'name':row['name'],'reason':'same_completed_site',
                             'evidence':{'completedBoundaryId':other['id'],'overlapMinimum':.97},
                             'sourceUrl':row.get('sourceUrl'),'stageLabel':row.get('stageLabel')}
            project,_=match(row,geometry)
            if project:retired_projects.add(project['id'])
            break
    keep=[i for i in range(len(rows)) if i not in excluded]
    return ([rows[i] for i in keep],[shapes[i] for i in keep],
            {'excludedBoundaries':list(excluded.values()),'excludedProjectIds':sorted(retired_projects)})
