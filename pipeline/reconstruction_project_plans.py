"""Read exact-address reconstruction plans from the shared Seoul source."""
import datetime as dt
import json
from functools import lru_cache

import apartment_development as development
import apartment_identity as identity
import shared_data

FILE = 'seoul_reconstruction_plans.json'
SOURCE_URL = 'https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do'
MAX_AGE_DAYS = 120


def _stamp(path):
    try:
        info = path.stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


@lru_cache(maxsize=4)
def _index(path, stamp):
    if not stamp:
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
        raise ValueError('invalid Seoul reconstruction source')
    records = data['records']
    if any(not isinstance(row, dict) for row in records.values()):
        raise ValueError('invalid Seoul reconstruction record')
    if records and (data.get('totalCount') != len(records) or data.get('sourceUrl') != SOURCE_URL):
        raise ValueError('incomplete Seoul reconstruction source')
    by_address = {}
    for row in records.values():
        name = str(row.get('bsns_name') or '')
        district = str(row.get('site_code_nm') or '')
        dong, lot = development.address_parts(row.get('bsns_addr'))
        if not name or not district or not dong or not lot or '재건축' not in str(row.get('classify_l_nm') or ''):
            continue
        by_address.setdefault((district, dong, lot), []).append(row)
    return {'data': data, 'byAddress': by_address}


def _number(value, *, maximum=None):
    try:
        result = float(str(value).replace(',', ''))
        return result if 0 < result <= (maximum or 10**10) else None
    except (TypeError, ValueError, OverflowError):
        return None


def for_apartment(entity, *, day=None):
    day = day or dt.date.today()
    if entity.get('province') != '서울특별시':
        return {'status': 'out_of_coverage'}
    apartment_id = str(entity.get('apartmentId') or '')
    district, dong = (str(entity.get(k) or '') for k in ('district', 'legalDong'))
    lot = identity.entity_parcel(entity)
    if not all((apartment_id, district, dong, lot)) or entity.get('aggregate') or entity.get('sectionIdentity'):
        return {'status': 'identity_unverified'}
    path = shared_data.cache_path(FILE)
    try:
        index = _index(path, _stamp(path))
    except (ValueError, OSError, TypeError):
        return {'status': 'connection_error'}
    if not index:
        return {'status': 'not_collected'}
    data = index['data']
    if not data['records']:
        return {'status': data.get('status', 'not_collected')}
    keys = development.entity_keys(entity)
    matches = []
    for row in index['byAddress'].get((district, dong, lot), []):
        if not keys.intersection(development.name_keys(row.get('bsns_name'), dong)):
            continue
        if identity.phase_conflicts(entity.get('name'), row.get('bsns_name')):
            continue
        if development.terminal(row.get('propel_cd_nm')):
            continue
        matches.append(row)
    if not matches:
        return {'status': 'not_found', 'checkedAt': data.get('checkedAt'), 'sourceUrl': SOURCE_URL}
    # A common lot and name can belong to more than one project. Do not choose
    # one by price, capacity, or simply by having a populated ratio.
    if len(matches) != 1:
        return {'status': 'ambiguous', 'checkedAt': data.get('checkedAt'), 'sourceUrl': SOURCE_URL}
    row = matches[0]
    from living_area_sources import stage_date
    checked = development.date(str(data.get('checkedAt') or '')[:10])
    stale = (not checked or not 0 <= (day - checked).days <= MAX_AGE_DAYS or data.get('lastError')
             or (shared_data.read_only() and shared_data.status().get('status') == 'stale'))
    stage_as_of = stage_date(row.get('propel_dt'))
    if stage_as_of and stage_as_of > day.isoformat():
        stage_as_of = None
    return {'status': 'stale' if stale else 'ready', 'apartmentId': apartment_id,
            'projectId': str(row.get('basic_info_seq')), 'projectName': row.get('bsns_name'),
            'projectAddress': row.get('bsns_addr'), 'projectType': row.get('classify_l_nm'),
            'stageLabel': row.get('propel_cd_nm') or '단계 미확인', 'stageAsOf': stage_as_of,
            'plannedFloorAreaRatio': _number(row.get('flar_rt'), maximum=1500),
            'plannedBuildingCoverageRatio': _number(row.get('bldglnd_rt'), maximum=100),
            'plannedHouseholds': _number(row.get('suply_hshld')),
            'projectAreaSqm': _number(row.get('bsns_area')),
            'beforeZone': row.get('spfc_prev'), 'afterZone': row.get('spfc_after'),
            'checkedAt': str(data.get('checkedAt') or '')[:10], 'sourceUrl': SOURCE_URL,
            'scope': 'official_project_area', 'identityMatch': 'district_dong_parcel_and_name'}
