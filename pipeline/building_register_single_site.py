"""Use a title as site data only when it is the site's sole complete building.

This does not combine per-building ratios. A missing/conflicting recap never
allows a multi-building title snapshot to stand in for a whole-site register.
"""
import datetime as dt
import json
import math
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit

import shared_data

FILE = 'building_register_crosschecks.json'
VERSION = 'single-building-site-v1'


def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def _zero(value):
    try:
        return value is not None and value != '' and not isinstance(value, bool) and float(value) == 0
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _read(path, stamp):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not isinstance(value.get('records'), dict):
        raise ValueError('invalid title source')
    return value['records']


def for_entity(entity, parcel, *, day):
    path = shared_data.cache_path(FILE)
    try:
        stat = path.stat()
        entry = _read(str(path), (stat.st_mtime_ns, stat.st_size)).get(str(entity.get('apartmentId')))
    except (OSError, ValueError, TypeError):
        return None
    return profile(entity, parcel, entry, day=day)


def profile(entity, parcel, entry, *, day):
    if not isinstance(entry, dict) or entry.get('status') != 'ok' or entry.get('lastError'):
        return None
    identity = entry.get('identity') or {}
    if not isinstance(identity, dict) or not entity.get('apartmentId') or not parcel or any(
            str(identity.get(k) or '') != str(entity.get(k) or '')
            for k in ('apartmentId', 'province', 'district', 'legalDong', 'jibun', 'cortarNo')):
        return None
    snapshot = entry.get('snapshot') or {}
    if not isinstance(snapshot, dict):
        return None
    try:
        url = urlsplit(str(snapshot.get('sourceUrl') or ''))
    except ValueError:
        return None
    if url.scheme != 'https' or not (url.hostname or '').endswith('.go.kr'):
        return None
    try:
        collected = dt.date.fromisoformat(str(snapshot.get('fetchedAt') or '')[:10])
    except ValueError:
        return None
    if not 0 <= (day-collected).days <= 180 or snapshot.get('parcel') != parcel:
        return None
    if snapshot.get('referenceMonth'):
        try:
            reference = dt.date.fromisoformat(str(snapshot['referenceMonth'])+'-01')
        except ValueError:
            return None
        if not 0 <= (day-reference).days <= 180:
            return None
    rows = snapshot.get('records')
    if (snapshot.get('recordType') not in (None, 'title') or not isinstance(rows, list)
            or len(rows) != 1 or snapshot.get('totalCount') != 1 or not isinstance(rows[0], dict)):
        return None
    row = rows[0]
    if (not row.get('mgmBldrgstPk') or str(row.get('regstrKindCd')) not in ('2', '3')
            or str(row.get('mainAtchGbCd')) != '0' or row.get('mainPurpsCdNm') != '공동주택'
            or not all(_zero(row.get(k)) for k in ('bylotCnt', 'atchBldCnt', 'atchBldArea'))
            or any(str(row.get(k, '')).zfill(len(v)) != v for k,v in parcel.items())):
        return None
    canonical = lambda text: re.sub(r'[^0-9A-Za-z가-힣]', '', str(text or '')).removesuffix('아파트')
    names = {canonical(x) for x in (entity.get('name'), *(entity.get('aliases') or []))} - {''}
    if canonical(row.get('bldNm')) not in names:
        return None
    households = _number(entity.get('households'))
    if not households or _number(row.get('hhldCnt')) != households:
        return None
    land, footprint, area = map(_number, (row.get('platArea'), row.get('archArea'), row.get('vlRatEstmTotArea')))
    far, coverage = _number(row.get('vlRat')), _number(row.get('bcRat'))
    floors = _number(row.get('grndFlrCnt'))
    if (not all((land, footprint, area, far, coverage, floors)) or coverage > 100
            or not floors.is_integer() or floors > 200
            or abs(far-area/land*100) > 1 or abs(coverage-footprint/land*100) > 1):
        return None
    provenance = {'sourceUrl': snapshot['sourceUrl'], 'fetchedAt': snapshot['fetchedAt'],
                  'registerId': str(row['mgmBldrgstPk']), 'scope': 'sole_main_building_whole_site'}
    return {'status':'ready', 'scope':'whole_registered_site', 'recordType':'title',
            'scopeVerification':'sole_complete_title_exact_households_and_name',
            'floorAreaRatio':far, 'buildingCoverageRatio':coverage, 'landAreaSqm':land,
            'floorAreaForRatioSqm':area, 'households':households, 'mainBuildingCount':1,
            'residentialBuildingCount':1, 'minFloors':floors, 'maxFloors':floors,
            'floorScope':'all_residential_buildings', 'approvedAt':row.get('useAprDay'),
            'registerId':str(row['mgmBldrgstPk']), 'registerName':row.get('bldNm'),
            'source':snapshot.get('source'), 'sourceUrl':snapshot['sourceUrl'],
            'fetchedAt':snapshot['fetchedAt'], 'referenceMonth':snapshot.get('referenceMonth'),
            'fieldIssues':[], 'fieldSources':{k:dict(provenance) for k in ('floorAreaRatio','buildingCoverageRatio','landAreaSqm')},
            'reason':'전체 세대수를 포함하는 단일 건물의 공식 대장과 면적 계산이 일치해요.'}
