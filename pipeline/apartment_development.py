"""Exact physical-apartment to official renewal evidence, shared by all reports.

Names generate candidates. District/dong/parcel or a named official boundary
must confirm them. No remote calls, fuzzy scores, or per-apartment allowlist.
"""
import datetime as dt
import json
import re
from collections import defaultdict
from functools import lru_cache

import apartment_identity as identity
import config

VERSION = 'apartment-development-v1'
PATH = config.ROOT / 'data/apartment_development_sources.json'
POLICY = config.ROOT / 'data/apartment_development_policy.json'


def compact(value):
    return re.sub(r'[^0-9a-z가-힣]', '', identity.text(value).lower())


def name_keys(value, dong=''):
    """Normalize optional 차/단지 suffixes; keep the actual number (3 != 4)."""
    text = identity.text(value)
    members = re.findall(r'[（(]([^）)]+)[）)]', text)
    values = [text]
    if not any(re.search(r'\d+\s*(?:차|단지)', group) for group in members):
        values.append(re.sub(r'[（(][^）)]*[）)]', '', text))
    for group in members:
        if re.search(r'[,·ㆍ/]', group):
            values += re.split(r'[,·ㆍ/]', group)
    if re.search(r'[,·ㆍ/]', text):
        values += re.split(r'[,·ㆍ/]', text)
    # '하안주공6·7단지' and '극동·건영·벽산' are joint project names.
    for source in list(values):
        match = re.fullmatch(r'(.*?)(\d+(?:[,·ㆍ]\d+)+)(차|단지)?', re.sub(r'\s+', '', source))
        if match:
            values += [match[1] + n + (match[3] or '') for n in re.split(r'[,·ㆍ]', match[2])]
    keys = set()
    for value in values:
        value = compact(value)
        previous = None
        while previous != value:
            previous = value
            value = re.sub(r'(?:소규모)?(?:주택)?(?:재개발|재건축|리모델링)(?:정비)?(?:사업)?(?:조합)?$|정비사업(?:구역)?조합$|정비사업구역$|추진위원회$|조합$|일대$|일원$', '', value)
            value = re.sub(r'아파트|신시가지', '', value)
        # Remove administrative words first: 4차아파트 is not a middle phase.
        middle_phase = re.search(r'(\d+)차(?=[가-힣a-z])', value)
        if middle_phase:
            value = value[:middle_phase.start()] + value[middle_phase.end():] + middle_phase[1]
        for prefix in (compact(dong), compact(dong).removesuffix('동')):
            if prefix and value.startswith(prefix):
                rest = value[len(prefix):]
                if not re.fullmatch(r'\d+(?:차|단지)?', rest):
                    value = rest
                break
        value = re.sub(r'(\d+)(?:차|단지)$', r'\1', value)
        if len(value) >= 2 and not re.fullmatch(r'\d+|재건축|재개발|정비사업|정비구역|모아타운|신속통합기획', value):
            keys.add(value)
    return keys


def entity_keys(entity):
    return set().union(*(name_keys(value, entity.get('legalDong')) for value in
        [entity.get('name'), *(entity.get('aliases') or [])]))


def address_parts(value):
    text = identity.text(value)
    match = re.search(r'([가-힣0-9]+(?:동|가|리))\s*(산?\s*\d+(?:\s*-\s*\d+)?)', text)
    if not match:
        return '', ''
    return match[1], identity.parcel_key(match[2])


def address_lots(value):
    return [(m[1], identity.parcel_key(m[2])) for m in re.finditer(
        r'([가-힣0-9]+(?:동|가|리))\s*(산?\s*\d+(?:\s*-\s*\d+)?)', identity.text(value))]


def date(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _age(entity, day):
    years = []
    if isinstance(entity.get('buildingAge'), (int, float)):
        years.append(entity['buildingAge'])
    for key in ('approvedAt', 'buildYear'):
        match = re.match(r'^(\d{4})(?:\D|$)', str(entity.get(key) or ''))
        if match and 1900 <= int(match[1]) <= day.year:
            years.append(day.year - int(match[1]))
    return min(years) if years else None


def stage_rating(label):
    text = re.sub(r'\s+', '', str(label or ''))
    # Only a completed procedural step earns its published weight.
    for row in policy()['stages']:
        if text in row['stages']:
            return row
    return None


def terminal(label):
    text = re.sub(r'\s+', '', str(label or ''))
    return text in {'completed', 'cancelled', '준공', '준공인가', '준공완료', '입주', '입주완료',
                    '사용승인', '이전고시', '조합해산', '조합청산', '청산및조합해산', '해제', '폐지', '취소'}


def excluded_member(name, entity):
    groups = re.findall(r'[（(]([^）)]*제외[^）)]*)[）)]', str(name or ''))
    if not groups:
        return False
    numbers = set(re.findall(r'\d+', entity.get('name') or ''))
    for group in groups:
        excluded = set(re.findall(r'\d+', group))
        for first,last in re.findall(r'(\d+)\s*[~∼-]\s*(\d+)', group):
            if 0 <= int(last)-int(first) <= 30:
                excluded.update(str(i) for i in range(int(first),int(last)+1))
        if not numbers or numbers & excluded:
            return True
    return False


@lru_cache(maxsize=2)
def _policy(modified):
    return json.loads(POLICY.read_text())


def policy():
    return _policy(POLICY.stat().st_mtime_ns)


def revision():
    paths = [PATH, POLICY, config.ROOT/'data/living_area_metro_catalog.json',
             config.ROOT/'data/redevelopment_zones.geojson', config.ROOT/'data/map_zone_stage_codes.json',
             config.ROOT/'data/redevelopment_occupancy_overrides.json',
             config.ROOT/'data/living_area_apartment_points.json']
    return tuple(p.stat().st_mtime_ns if p.exists() else None for p in paths)


@lru_cache(maxsize=2)
def _index(revisions):
    import living_area_metro as metro
    from pyproj import Transformer
    rows = []
    if PATH.exists():
        rows.extend(json.loads(PATH.read_text())['projects'])
    for project in metro.catalog().get('projects', []):
        if project.get('sourceId') not in ('seoul-plan-renewal', 'gg-quarter'):
            continue
        rows.append({**{k: v for k, v in project.items() if k != 'point'},
            'district': project.get('region'), 'sourcePriority': 60,
            'projectTypeLabel': project.get('projectTypeLabel') or
                ('재건축' if project.get('projectType') == 'reconstruction' else
                 '재개발' if project.get('projectType') == 'redevelopment' else '정비사업'),
            'checkedAt': project.get('checkedAt')})
    by_address, by_district = defaultdict(list), defaultdict(list)
    codes = {(r['province'], r['district'].replace('시 ', '')):r['code']
             for r in json.loads((config.ROOT/'data/purchase_regions.json').read_text())['regions']}
    for row in rows:
        dong, parcel = address_parts(row.get('address'))
        row['legalDong'] = row.get('legalDong') or dong
        row['jibun'] = identity.parcel_key(row.get('jibun') or parcel)
        row['keys'] = name_keys(row['name'], row['legalDong'])
        if not re.search(r'재건축|재개발|리모델링|가로주택|자율주택|소규모|신속통합|정비사업', row.get('projectTypeLabel') or ''):
            continue
        lots = address_lots(row.get('address')) or [(row['legalDong'], row['jibun'])]
        row['addressLots'] = lots
        if row.get('province') and row.get('district'):
            for district in {row['district'], *(row.get('districtAliases') or [])}:
                by_district[(row['province'], district)].append(row)
                for dong, parcel in lots:
                    if dong and parcel:
                        by_address[(row['province'], district, dong, parcel)].append(row)
    boundaries, shapes, tree, _ = metro.spatial_index()
    forward = Transformer.from_crs(4326, 5179, always_xy=True).transform
    points = defaultdict(list)
    source = json.loads((config.ROOT/'data/living_area_apartment_points.json').read_text())
    for row in source.get('rows', []):
        points[(row.get('sgg_addr'), row.get('emd_addr'))].append(row)
    cached = {}
    if metro.CENTER_PATH.exists():
        for value in json.loads(metro.CENTER_PATH.read_text()).values():
            if value.get('identity', {}).get('apartmentId') and value.get('point'):
                cached[value['identity']['apartmentId']] = value
    return {'rows':rows, 'byAddress':by_address, 'byDistrict':by_district, 'codes':codes,
            'boundaries':boundaries, 'shapes':shapes, 'tree':tree, 'forward':forward,
            'points':points, 'pointCheckedAt':source.get('checkedAt'), 'cached':cached}


def index():
    return _index(revision())


def offline_center(entity, day, registry=None):
    data = registry or index()
    cached = data['cached'].get(str(entity.get('apartmentId') or ''))
    if cached and all(str(cached['identity'].get(k) or '') == str(entity.get(k) or '')
                      for k in ('province', 'district', 'legalDong', 'jibun')):
        checked = date(cached.get('day'))
        if checked and 0 <= (day - checked).days <= 120:
            return cached['point']
    checked = date(data['pointCheckedAt'])
    if not checked or not 0 <= (day - checked).days <= 120:
        return None
    keys = entity_keys(entity)
    candidates = []
    for row in data['points'].get((entity.get('district'), entity.get('legalDong')), []):
        code = bool(entity.get('kaptCode') and entity['kaptCode'] == row.get('apt_cd'))
        named = bool(keys & name_keys(row.get('apt_nm'), entity.get('legalDong')))
        households = entity.get('households') and entity['households'] == row.get('tnohsh')
        lot = identity.parcel_key(row.get('daddr'))
        if code or named and (households or lot and lot == identity.entity_parcel(entity)):
            try:
                candidates.append({'latitude':float(row['ycrd']), 'longitude':float(row['xcrd']),
                                   'coordinateBasis':'official_point_identity_match'})
            except (KeyError, ValueError, TypeError):
                pass
    return candidates[0] if len(candidates) == 1 else None


def _same_code(code, wanted):
    return bool(code and wanted and (str(code) == str(wanted) or
        str(code).endswith('0') and str(code)[:4] == str(wanted)[:4]))


def for_apartment(entity, *, day=None, center=None, registry=None):
    day = day or dt.date.today()
    apartment_id = str(entity.get('apartmentId') or '')
    result = {'version':VERSION, 'apartmentId':apartment_id,
        'identity':{k:entity.get(k) for k in ('name', 'province', 'district', 'legalDong', 'jibun')},
        'checkedAt':day.isoformat(), 'status':'not_found', 'projects':[], 'unresolvedProjects':[],
        'coverageComplete':False,
        'coverageNote':'연결한 공식 자료에서 확인한 결과예요. 자료가 없다고 정비사업이 없다는 뜻은 아니에요.'}
    age = _age(entity, day)
    if not apartment_id or entity.get('aggregate'):
        result['status'] = 'identity_unresolved'
        return result
    if age is not None and age < policy()['minimumBuildingAge'] or re.search(r'분양권|입주예정|미준공', str(entity.get('status') or '')):
        result['status'] = 'not_applicable'
        return result
    data = registry or index()
    province, district, dong = (entity.get(k) for k in ('province', 'district', 'legalDong'))
    parcel, keys = identity.entity_parcel(entity), entity_keys(entity)
    code = str(entity.get('lawdCd') or entity.get('cortarNo') or data['codes'].get((province, district)) or '')[:5]
    point = center or offline_center(entity, day, data)
    located = None
    if point:
        from shapely.geometry import Point
        try:
            x, y = data['forward'](point['longitude'], point['latitude'])
            located = Point(x, y)
        except (KeyError, TypeError, ValueError):
            pass
    matched_boundaries = []
    if located is not None:
        for i in data['tree'].query(located.buffer(50)):
            row, geometry = data['boundaries'][int(i)], data['shapes'][int(i)]
            if not _same_code(row.get('districtCode'), code):
                continue
            import map_zone_policy
            if map_zone_policy.classify(row)['zoneKind'] != 'renewal':
                continue
            boundary_keys = name_keys(row.get('sourceName'), dong)
            if excluded_member(row.get('sourceName'), entity):
                continue
            if not keys.intersection(boundary_keys):
                continue
            if geometry.distance(located) > 50:
                continue
            match = {**row, 'matchMethod':'name_district_and_official_boundary',
                     'matchedSubjectApartmentId':apartment_id, 'containsSubject':geometry.covers(located),
                     'distanceMeters':round(geometry.distance(located)), 'sourcePriority':40,
                     'checkedAt':day.isoformat(), 'keys':boundary_keys,
                     'projectTypeLabel':row.get('projectTypeLabel'), 'district':district, 'province':province}
            match.pop('geometry', None)
            matched_boundaries.append(match)
    matches = []
    address_candidates = data['byAddress'].get((province, district, dong, parcel), []) if parcel else []
    address_groups = [row for row in address_candidates if keys & row['keys'] and len(row['keys']) > 1]
    for row in data['byDistrict'].get((province, district), []):
        if excluded_member(row['name'], entity):
            continue
        if row.get('addressLots') and dong not in {d for d,p in row['addressLots']}:
            continue
        checked = date(row.get('checkedAt'))
        if not checked or not 0 <= (day - checked).days <= policy()['maxSourceAgeDays']:
            continue
        published = date(row.get('sourceDate'))
        if published and published > day:
            continue
        name_match = bool(keys & row['keys'])
        address_match = row in address_candidates
        if not name_match and address_match:
            # Joined names such as 극동건영벽산 need the same complete parcel.
            # A numeric phase mismatch (주공1 vs 주공12) still rejects it.
            name_match = any(a in b and len(a) >= 2 and
                set(re.findall(r'\d+', a)) == set(re.findall(r'\d+', b))
                for a in keys for b in row['keys'])
        group_match = address_match and any(
            len(boundary['keys']) > 1 and any(len(key) >= 2 and key in compact(row['name'])
                for key in boundary['keys'] if key not in keys)
            for boundary in matched_boundaries)
        group_match = group_match or address_match and any(
            any(len(key) >= 2 and key in compact(row['name']) for key in group['keys'] if key not in keys)
            for group in address_groups)
        if not name_match and not group_match:
            continue
        if not address_match:
            # A different representative lot is accepted only for a containing,
            # named joint boundary. A same-name neighbour is never enough.
            linked = [b for b in matched_boundaries if b['containsSubject'] and b['keys'] & row['keys']]
            if not linked:
                result['unresolvedProjects'].append({k:row.get(k) for k in ('id','name','address','stageLabel','sourceUrl')})
                continue
        matches.append({**row, 'matchMethod':'exact_district_dong_parcel_and_name' if name_match and address_match
                        else 'joint_name_and_containing_boundary', 'matchedSubjectApartmentId':apartment_id})
    matches += matched_boundaries
    if not matches:
        result['status'] = 'unresolved' if result['unresolvedProjects'] else 'not_found'
        if age is None:
            result['status'] = 'building_age_unresolved'
        return result
    # A specific current business disclosure outranks an older map category.
    # Preserve all original evidence and make the precedence reviewable.
    best_priority = max(row['sourcePriority'] for row in matches)
    selected = [row for row in matches if row['sourcePriority'] == best_priority]
    latest = max(str(row.get('sourceDate') or row.get('checkedAt') or '') for row in selected)
    selected = [row for row in selected if str(row.get('sourceDate') or row.get('checkedAt') or '') == latest]
    unique = {row['id']:row for row in selected}
    selected = list(unique.values())
    evidence = [{k:row.get(k) for k in ('id','name','address','stageLabel','sourceUrl','sourceDate','checkedAt','sourcePriority')}
                for row in matches]
    for row in selected:
        result['projects'].append({k:v for k,v in row.items() if k not in ('keys','geometry','point')})
    result['evidence'] = evidence
    result['stageSelectionBasis'] = 'official_business_disclosure_then_published_inventory_then_reference_boundary'
    if all(terminal(row.get('stageLabel')) for row in selected):
        result['status'] = 'completed_or_cancelled'
        result['projects'] = []
        return result
    if age is None:
        result['status'] = 'building_age_unresolved'
        result['projects'] = []
        return result
    result['status'] = 'confirmed'
    ratings = [stage_rating(row.get('stageLabel')) for row in selected]
    if any(not r for r in ratings) or len({r['points'] for r in ratings if r}) != 1:
        result['rating'] = {'state':'missing', 'points':None, 'scoreText':'평가 보류',
                            'reason':'공식 자료의 현재 단계를 더 확인해야 해요.'}
    else:
        stage, row = ratings[0], selected[0]
        result['rating'] = {'state':'ready', 'points':stage['points'], 'ratio':stage['points']/5,
            'stars':f"{stage['points']:.1f}", 'scoreText':f"{stage['points']:.1f}/5",
            'stageLabel':stage['label'], 'sourceStage':row.get('stageLabel'),
            'sourceDate':row.get('sourceDate'), 'checkedAt':row.get('checkedAt'),
            'sourceUrl':row['sourceUrl'], 'version':policy()['version']}
    return result


def attach(result, entity, day):
    if result.get('apartmentId') == entity.get('apartmentId'):
        try:
            result['ownDevelopment'] = for_apartment(entity, day=day,
                center=result.get('center') or result.get('mapCenter'))
        except (ValueError, OSError, TypeError, KeyError):
            result['ownDevelopment'] = {'version':VERSION, 'apartmentId':entity.get('apartmentId'),
                'status':'error', 'projects':[], 'coverageComplete':False,
                'errorReason':'단지 정비사업 자료를 불러오지 못했어요. 잠시 뒤 리포트를 다시 열어 주세요.'}
        if result.get('snapshotId'):
            import living_area_sources
            result['snapshotId'] = living_area_sources.digest({
                'livingAreaSnapshot':result['snapshotId'], 'ownDevelopment':result['ownDevelopment'],
                'policy':policy()['version']})
    return result
