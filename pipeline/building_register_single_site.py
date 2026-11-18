"""Use a sole complete registered title with exact parcel and total households.

This does not combine per-building ratios. A missing/conflicting recap never
allows a multi-building title snapshot to stand in for a whole-site register.
"""
import datetime as dt
import json
import math
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs

import shared_data
import apartment_identity
import building_register_identity

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


def entry_for(entity):
    """Read the common immutable title/corroboration store once per version."""
    path = shared_data.cache_path(FILE)
    try:
        stat = path.stat()
    except OSError:
        return None
    return _read(str(path), (stat.st_mtime_ns, stat.st_size)).get(str(entity.get('apartmentId')))


def for_entity(entity, parcel, *, day, parcel_reference=None):
    try:
        entry = entry_for(entity)
    except (OSError, ValueError, TypeError):
        return None
    return profile(entity, parcel, entry, day=day, parcel_reference=parcel_reference)


def _basic_identity(entity, parcel, entry, households, day):
    source=entry.get('officialBasic') or {}
    if not isinstance(source,dict):return False
    record=source.get('record') or {}
    if not isinstance(record,dict) or source.get('sourceUrl')!='https://www.data.go.kr/data/15106861/fileData.do':return False
    try:date=dt.date.fromisoformat(str(source.get('sourceDate')))
    except ValueError:return False
    if not 0<=(day-date).days<=180 or not re.fullmatch(r'[0-9a-f]{64}',str(source.get('sourceSha256') or '')):return False
    if (record.get('단지고유번호')!=str(entity.get('apartmentId'))
        or record.get('필지고유번호') not in building_register_identity.pnu_variants(entity,parcel,day=day)
        or _number(record.get('세대수'))!=households):return False
    canonical=lambda text:re.sub(r'[^0-9A-Za-z가-힣]','',str(text or '')).removesuffix('아파트')
    names={canonical(record.get(k)) for k in ('단지명_공시가격','단지명_건축물대장','단지명_도로명주소')}-{''}
    aliases={canonical(v) for v in (entity.get('name'),*(entity.get('aliases') or [])) if not apartment_identity.phase_conflicts(entity.get('name'),v)}-{''}
    return bool(names & aliases)


def _single_parcel_land(entity,parcel,reference,day):
    if not isinstance(reference,dict) or reference.get('kind')!='parcel_zoning' or reference.get('zoneCoverageVerified') is not False:return None
    url=urlsplit(str(reference.get('sourceUrl') or ''))
    if (url.scheme!='https' or url.hostname not in ('www.eum.go.kr','eum.go.kr') or url.path!='/web/ar/lu/luLandDet.jsp'
        or reference.get('pnu') not in building_register_identity.pnu_variants(entity,parcel,day=day)
        or parse_qs(url.query).get('pnu')!=[reference.get('pnu')]):return None
    try:checked=dt.date.fromisoformat(str(reference.get('checkedAt')))
    except ValueError:return None
    return _number(reference.get('parcelAreaSqm')) if 0<=(day-checked).days<=180 else None


def profile(entity, parcel, entry, *, day, parcel_reference=None):
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
    if not 0 <= (day-collected).days <= 180 or snapshot.get('parcel') not in building_register_identity.variants(entity, parcel, day=day):
        return None
    if snapshot.get('referenceMonth'):
        try:
            reference = dt.date.fromisoformat(str(snapshot['referenceMonth'])+'-01')
        except ValueError:
            return None
        if not 0 <= (day-reference).days <= 180:
            return None
    original_parcel = parcel
    parcel = snapshot['parcel']
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
    households = _number(entity.get('households'))
    if canonical(row.get('bldNm')) not in names:
        if str(row.get('bldNm') or '').strip() or not households or not _basic_identity(entity,original_parcel,entry,households,day):return None
    if not households or _number(row.get('hhldCnt')) != households:
        return None
    land, footprint, area = map(_number, (row.get('platArea'), row.get('archArea'), row.get('vlRatEstmTotArea')))
    independent_land=False
    if land is None:
        land=_single_parcel_land(entity,original_parcel,parcel_reference,day)
        independent_land=land is not None
    far, coverage = _number(row.get('vlRat')), _number(row.get('bcRat'))
    floors = _number(row.get('grndFlrCnt'))
    if (not all((land, footprint, area, far, coverage, floors)) or coverage > 100
            or not floors.is_integer() or floors > 200
            or abs(far-area/land*100) > 1 or abs(coverage-footprint/land*100) > 1):
        return None
    provenance = {'sourceUrl': snapshot['sourceUrl'], 'fetchedAt': snapshot['fetchedAt'],
                  'registerId': str(row['mgmBldrgstPk']), 'scope': 'sole_main_building_whole_site'}
    field_sources={k:dict(provenance) for k in ('floorAreaRatio','buildingCoverageRatio','landAreaSqm')}
    if independent_land:
        field_sources['landAreaSqm']={'sourceUrl':parcel_reference['sourceUrl'],'checkedAt':parcel_reference['checkedAt'],'pnu':parcel_reference['pnu'],'scope':'whole_site_single_parcel_confirmed_by_title','method':'independent_official_parcel_area'}
    return {'status':'ready', 'scope':'whole_registered_site', 'recordType':'title',
            'scopeVerification':'sole_complete_title_exact_households_and_name',
            'floorAreaRatio':far, 'buildingCoverageRatio':coverage, 'landAreaSqm':land,
            'floorAreaForRatioSqm':area, 'households':households, 'registeredTitleCount':1,
            'registeredGroundFloors':floors, 'approvedAt':row.get('useAprDay'),
            'registerId':str(row['mgmBldrgstPk']), 'registerName':row.get('bldNm'),
            'source':snapshot.get('source'), 'sourceUrl':snapshot['sourceUrl'],
            'fetchedAt':snapshot['fetchedAt'], 'referenceMonth':snapshot.get('referenceMonth'),
            'fieldIssues':[], 'fieldSources':field_sources,
            'reason':'전체 세대수를 포함하는 공식 표제부와 대지·면적 계산이 일치해요. 대장 건수를 실제 동수로 대신 쓰지 않아요.'}
