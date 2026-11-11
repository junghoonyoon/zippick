"""Exact-address plans for the non-Seoul regions served by the product.

The whole published inventory is retained. A project name alone never attaches
its ratios to an apartment. Source dates and collection dates stay separate.
"""
import datetime as dt
import json
import re
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

import apartment_development as development
import apartment_identity as identity
import shared_data

FILE = 'regional_reconstruction_plans.json'
MAX_CHECK_AGE_DAYS = 90
MAX_PUBLICATION_AGE_DAYS = 366
SOURCES = {
    'gg-renewal': {'province': '경기도', 'name': '경기도 정비사업 추진현황',
                  'url': 'https://www.gg.go.kr/opendata/openDataBoard.do?decIdx=5318'},
    'incheon-renewal': {'province': '인천광역시', 'name': '인천시 정비사업 추진현황',
                        'url': 'https://www.data.go.kr/data/15055212/fileData.do'},
    'incheon-plan': {'province': '인천광역시', 'name': '인천시 정비사업 건축계획',
                     'url': 'https://www.data.go.kr/data/15080866/fileData.do'},
}
# The transaction master still includes the previous district names. Only
# published parent/successor pairs are aliases; two successor gu never merge.
# Dong, complete parcel and apartment name must still match independently.
DISTRICT_CHANGE_URL = 'https://www.incheon.go.kr/IC01070101'
DISTRICT_SUCCESSORS = {'서구': ('서해구', '검단구'), '중구': ('제물포구', '영종구'), '동구': ('제물포구',)}


def stamp():
    try:
        info = shared_data.cache_path(FILE).stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


def number(value, maximum=10**10):
    try:
        n = float(str(value).replace(',', '').strip().removesuffix('%'))
        return n if 0 < n <= maximum else None
    except (ValueError, TypeError, OverflowError):
        return None


def district_key(value):
    return re.sub(r'\s+', '', str(value or '')).removeprefix('인천').replace('시', '')


def district_matches(source, target, province):
    a, b = district_key(source), district_key(target)
    if a == b:
        return True
    return province == '인천광역시' and (a in DISTRICT_SUCCESSORS.get(b, ()) or b in DISTRICT_SUCCESSORS.get(a, ()))


def name_keys(value, dong=''):
    # The official Incheon inventory abbreviates 아파트 as A, including A2단지.
    value = re.sub(r'A(?=\s*(?:\d+단지|$|[,·]))', '아파트', str(value or ''))
    keys = development.name_keys(value, dong)
    # Quarterly inventories publish zone names as 영통3구역(원천주공).
    # The parenthesized complex is usable only with the same complete address.
    for alias in re.findall(r'[（(]([^）)]+)[）)]', value):
        if not re.search(r'제외|가칭|예정|미포함', alias):
            keys.update(development.name_keys(alias, dong))
    return keys


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('records'), dict):
        raise ValueError('invalid regional reconstruction source')
    for key, source in data['records'].items():
        if key not in SOURCES or not isinstance(source, dict) or source.get('sourceUrl') != SOURCES[key]['url']:
            raise ValueError('unrecognized regional reconstruction source')
        rows = source.get('records')
        if not isinstance(rows, dict) or len(rows) != source.get('totalCount'):
            raise ValueError('incomplete regional reconstruction source')
        for record_id, row in rows.items():
            if (not isinstance(row, dict) or row.get('id') != record_id or row.get('sourceId') != key
                    or row.get('province') != SOURCES[key]['province'] or not row.get('name')
                    or not row.get('district') or not isinstance(row.get('address'), str) or not row.get('projectTypeLabel')
                    or not row.get('stageLabel') or not development.date(row.get('sourceDate'))):
                raise ValueError('invalid regional reconstruction record')
            url = urlsplit(str(row.get('sourceUrl') or ''))
            if key == 'gg-renewal':
                query = parse_qs(url.query)
                official = (url.scheme == 'https' and url.hostname == 'www.gg.go.kr'
                            and url.path == '/opendata/openDataContent.do' and query.get('decodeIdx') == ['5318']
                            and len(query.get('gg_content_idx', [])) == 1 and query['gg_content_idx'][0].isdigit())
            else:
                official = row.get('sourceUrl') == SOURCES[key]['url']
            if not official or row['sourceDate'] != source.get('sourceDate'):
                raise ValueError('regional reconstruction provenance mismatch')
    return data


@lru_cache(maxsize=4)
def _read(path, revision):
    if revision is None:
        return {'version': 1, 'records': {}}
    return validate(json.loads(path.read_text(encoding='utf-8')))


def load():
    return _read(shared_data.cache_path(FILE), stamp())


def _fresh(source, day):
    checked = development.date(str(source.get('checkedAt') or '')[:10])
    published = development.date(source.get('sourceDate'))
    return (checked and published and not source.get('lastError')
            and 0 <= (day - checked).days <= MAX_CHECK_AGE_DAYS
            and 0 <= (day - published).days <= MAX_PUBLICATION_AGE_DAYS
            and not (shared_data.read_only() and shared_data.status().get('status') == 'stale'))


def development_records(*, day=None):
    """The same checked source drives the existing per-complex stage matcher."""
    day = day or dt.date.today()
    try:
        sources = load()['records']
    except (OSError, ValueError, TypeError):
        return []
    result = []
    for key, source in sources.items():
        if not _fresh(source, day):
            continue
        for row in source['records'].values():
            if row.get('sourceDate') > day.isoformat():
                continue
            aliases = ([old for old, current in DISTRICT_SUCCESSORS.items() if row['district'] in current]
                       if row['province'] == '인천광역시' else [])
            result.append({**row, 'name': re.sub(r'A(?=\s*(?:\d+단지|$|[,·]))', '아파트', row['name']),
                           'districtAliases': aliases,
                           'checkedAt': str(source['checkedAt'])[:10], 'sourcePriority': 80})
    return result


def for_apartment(entity, *, day=None):
    day = day or dt.date.today()
    province = entity.get('province')
    if province not in {s['province'] for s in SOURCES.values()}:
        return {'status': 'out_of_coverage'}
    apartment_id = str(entity.get('apartmentId') or '')
    dong, lot = entity.get('legalDong'), identity.entity_parcel(entity)
    if not apartment_id or not dong or not lot or entity.get('aggregate') or entity.get('sectionIdentity'):
        return {'status': 'identity_unverified'}
    try:
        sources = load()['records']
    except (OSError, ValueError, TypeError):
        return {'status': 'connection_error'}
    expected = {key for key, source in SOURCES.items() if source['province'] == province}
    checks, matches = [], []
    keys = development.entity_keys(entity)
    for key in sorted(expected):
        source = sources.get(key)
        status = 'not_collected' if source is None else 'ready' if _fresh(source, day) else 'stale'
        checks.append({'sourceId': key, 'status': status, 'sourceUrl': SOURCES[key]['url'],
                       'sourceLabel': SOURCES[key]['name'],
                       'sourceDate': source.get('sourceDate') if source else None,
                       'checkedAt': source.get('checkedAt') if source else None})
        if source is None:
            continue
        for row in source['records'].values():
            if ('재건축' not in row['projectTypeLabel']
                    or not district_matches(row['district'], entity.get('district'), province)
                    or row.get('legalDong') != dong or identity.parcel_key(row.get('jibun')) != lot
                    or not keys.intersection(name_keys(row['name'], dong))
                    or development.excluded_member(row['name'], entity)
                    or identity.phase_conflicts(entity.get('name'), row['name'])):
                continue
            matches.append((row, source, status))
    base = {'sourceChecks': checks, 'coverageComplete': False}
    if not matches:
        statuses = {c['status'] for c in checks}
        status = ('not_collected' if statuses == {'not_collected'} else 'stale' if 'stale' in statuses
                  else 'not_collected' if 'not_collected' in statuses else 'not_found')
        return {**base, 'status': status}
    latest = max(row['sourceDate'] for row, _, _ in matches)
    current = [item for item in matches if item[0]['sourceDate'] == latest]
    # Do not combine two distinct named projects sharing an address.
    if len({development.compact(row['name']).replace('아파트', '').replace('a', '') for row, _, _ in current}) != 1:
        return {**base, 'status': 'ambiguous'}
    if len({row['stageLabel'] for row, _, _ in current}) != 1:
        return {**base, 'status': 'ambiguous'}
    row, source, status = current[0]
    if development.terminal(row['stageLabel']):
        return {**base, 'status': 'completed', 'stageLabel': row['stageLabel'], 'sourceDate': latest,
                'sourceUrl': row['sourceUrl']}
    plan_candidates = [(r, s, st) for r, s, st in matches if number(r.get('plannedFloorAreaRatio'), 1500)]
    selected = max(plan_candidates, key=lambda item: item[0]['sourceDate']) if plan_candidates else current[0]
    plan, plan_source, plan_status = selected
    if any(r['sourceDate'] == plan['sourceDate'] and r.get('plannedFloorAreaRatio') != plan.get('plannedFloorAreaRatio')
           for r, _, _ in plan_candidates):
        return {**base, 'status': 'ambiguous'}
    result = {**base, 'status': 'ready' if status == plan_status == 'ready' else 'stale',
              'apartmentId': apartment_id, 'projectId': row['id'], 'projectName': row['name'],
              'projectAddress': row['address'], 'projectType': row['projectTypeLabel'],
              'stageLabel': row['stageLabel'], 'stageAsOf': None, 'stageSourceDate': latest,
              'stageSourceUrl': row['sourceUrl'], 'sourceDate': plan['sourceDate'],
              'sourceUrl': plan['sourceUrl'], 'sourceLabel': SOURCES[plan['sourceId']]['name'],
              'checkedAt': str(plan_source.get('checkedAt') or '')[:10],
              'scope': 'official_project_area', 'identityMatch': 'district_dong_parcel_and_name'}
    if district_key(row['district']) != district_key(entity.get('district')):
        result.update(districtMatchMethod='official_administrative_successor',
                      sourceDistrict=row['district'], apartmentDistrict=entity.get('district'),
                      districtMatchSourceUrl=DISTRICT_CHANGE_URL)
    for field in ('plannedFloorAreaRatio', 'plannedBuildingCoverageRatio', 'plannedHouseholds', 'projectAreaSqm',
                  'existingFloorAreaRatio', 'existingHouseholds'):
        result[field] = plan.get(field)
    result['subjectHouseholdsMatch'] = (number(entity.get('households')) is not None
                                       and number(entity.get('households')) == number(result.get('existingHouseholds')))
    result['missingFields'] = [field for field in ('plannedFloorAreaRatio', 'plannedBuildingCoverageRatio') if not result[field]]
    return result
