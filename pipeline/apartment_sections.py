"""Verified physical sections of source records that cover several complexes.

The source record remains untouched. Search and transaction loaders use the
same replacement rows; a shared Naver page is never a physical apartment id.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
import apartment_identity as identity

PATH = Path(__file__).resolve().parents[1] / 'data' / 'apartment_sections.json'

def compact(value):
    return re.sub(r'[^0-9a-z가-힣]', '', str(value or '').lower())

@lru_cache(maxsize=1)
def groups():
    return json.loads(PATH.read_text(encoding='utf-8'))['groups']

def source_rows(row):
    for group in groups():
        if (compact(row.get('대표단지명')) != compact(group['name'])
            or row.get('시도') != group['province']
            or (row.get('자치구') or row.get('시군구')) != group['district']
            or row.get('법정동') != group['legalDong']
            or identity.parcel_key(row.get('지번')) != identity.parcel_key(group['sourceJibun'])):
            continue
        return [{
            **row, '단지고유번호': section['apartmentId'],
            'kaptCode': section.get('kaptCode', ''), 'complexNo': '',
            '대표단지명': section['name'], '단지명_공시가격': section['name'],
            '단지명_건축물대장': '', '단지명_도로명주소': '',
            '별칭': group['name'], '주소': section['address'], '지번': section['jibun'],
            '필지고유번호': parcel_id(group['cortarNo'], section['jibun']),
            '세대수': section['households'], '사용승인일': section['approvedAt'],
            '상태': '준공', '입주예정월': '',
            'sectionIdentity': _section_identity(section, group), 'sectionSources': group['sources'],
            'transactionBuildingNumbers': section.get('buildingNumbers', []),
            'transactionScope': _transaction_scope_for_section(group, section),
        } for section in group['sections']]
    return [row]


def parcel_id(cortar_no, jibun):
    parcel = identity.parcel_key(jibun)
    main, _, sub = parcel.removeprefix('산').partition('-')
    return cortar_no + ('2' if parcel.startswith('산') else '1') + main.zfill(4) + (sub or '0').zfill(4)


def _transaction_scope_for_section(group, section):
    """Return an explicitly reviewed shared official-trade scope for a section."""
    apartment_id = str(section.get('apartmentId') or '').strip()
    for scope in group.get('transactionScopes', []):
        if apartment_id not in scope.get('memberApartmentIds', []):
            continue
        if identity.parcel_key(scope.get('jibun')) != identity.parcel_key(section.get('jibun')):
            continue
        return scope
    return None


def _section_identity(section, group):
    scope = _transaction_scope_for_section(group, section)
    return {**section, 'transactionScope': scope} if scope else section


def transaction_scope(entity):
    """Recover reviewed feed rules from a card's exact physical identity."""
    apartment_id = str((entity or {}).get('apartmentId') or '').strip()
    if not apartment_id:
        return None
    for group in groups():
        for section in group['sections']:
            if section['apartmentId'] != apartment_id:
                continue
            if not identity.satisfies(entity, {**group, **section}):
                return None
            return _transaction_scope_for_section(group, section)
    return None


def resolve(name, legal_dong='', jibun='', region='', apartment_id=''):
    matches = []
    for group in groups():
        if legal_dong and legal_dong != group['legalDong']:
            continue
        if region and not identity.region_matches(region, group):
            continue
        for section in group['sections']:
            if apartment_id and apartment_id != section['apartmentId']:
                continue
            if compact(name) not in {compact(section['name']), compact(group['legalDong'] + section['name'])}:
                continue
            if jibun and identity.parcel_key(jibun) != identity.parcel_key(section['jibun']):
                continue
            matches.append(section)
    return matches[0] if len(matches) == 1 else None
