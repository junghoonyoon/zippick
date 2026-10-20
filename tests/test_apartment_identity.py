"""Regressions for parcel collisions across search, transactions, links and Jev."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import apartment_identity as identity
import budget_candidates as budget
import molit_transactions as molit
import real_estate_search as search
import naver_complex
import typesafe_jev as jev

PARCELS = ['1', '18-1', '1341', '1-11', '11-1', '111', '산1', '산1-11']
BASE = {'name': '현대', 'province': '서울특별시', 'district': '서초구', 'legalDong': '반포동'}


@pytest.mark.parametrize('parcel', PARCELS)
def test_parcel_identity_is_lossless_through_lookup_and_transactions(parcel):
    entities = [{**BASE, 'jibun': value, 'address': '서울특별시 서초구 반포동 ' + value} for value in PARCELS]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        matches = budget._find_entities('현대', '서초구', '반포동', parcel)
        assert [e['jibun'] for e in matches] == [parcel]
        assert budget._find_entity('현대', '서초구') is None
        selected = budget._price_lookup_entity({'name': '현대', 'region': '서초구', 'legalDong': '반포동', 'jibun': parcel})
        assert selected['jibun'] == parcel
    rows = [{'대표단지명': '현대', '법정동': '반포동', '지번': value} for value in PARCELS]
    assert [r['지번'] for r in rows if molit._row_matches_entity(r, selected)] == [parcel]
    items = [{'apartment': '현대', 'legalDong': '반포동', 'jibun': value} for value in PARCELS]
    source = next(r for r in rows if r['지번'] == parcel)
    assert [v['jibun'] for v in items if molit._matches_transaction(source, v, '현대')] == [parcel]
    assert len({naver_complex._cache_key('현대', '반포동', p) for p in PARCELS}) == len(PARCELS)


@pytest.mark.parametrize('raw,expected', [('001-011', '1-11'), ('산 01–011', '산1-11'), ('반포동 001-0', '1'), (None, ''), ('지구BL 3-11', '지구bl3-11')])
def test_only_formatting_is_normalized(raw, expected):
    assert identity.parcel_key(raw, '반포동') == expected


def test_address_fallback_requires_a_complete_parcel_and_never_a_road_number():
    assert identity.entity_parcel({**BASE, 'address': '서울특별시 서초구 반포동 18-1'}) == '18-1'
    assert identity.entity_parcel({**BASE, 'address': '서울특별시 서초구 반포대로 18-1'}) == ''
    assert identity.entity_parcel({**BASE, 'address': '서울특별시 서초구 반포동 18-1 101동'}) == ''
    assert not molit._row_matches_entity({'법정동': '반포동', '지번': '1'}, {**BASE, 'address': '서울특별시 서초구 반포동 18-1'})


def test_same_name_and_legacy_dedupe_key_never_merge_different_parcels():
    entities = [{**BASE, 'jibun': p, 'dedupeKey': 'legacy-same', 'households': 100} for p in ['1-11', '11-1']]
    assert len(search._merge_entities(entities)) == 2
    assert not budget._same_apartment_entity(*entities)
    with mock.patch.object(search, 'APARTMENT_MASTER', entities):
        suggestions = search.suggest_apartments('현대')
    assert {s['jibun'] for s in suggestions} == {'1-11', '11-1'}


def test_ids_survive_master_and_suggestions_and_prevent_merging():
    entities = [{**BASE, 'jibun': '1', 'apartmentId': value, 'households': 100} for value in ['A', 'B']]
    merged = search._merge_entities(entities)
    assert {e['apartmentId'] for e in merged} == {'A', 'B'}
    with mock.patch.object(search, 'APARTMENT_MASTER', merged), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        assert budget._find_entity('현대', '서초구', '반포동', '1') is None
        assert {s['apartmentId'] for s in search.suggest_apartments('현대')} == {'A', 'B'}


def test_numbered_name_does_not_override_parcel_or_dong():
    row = {'대표단지명': '현대1단지', '법정동': '중동', '지번': '1-11'}
    for dong, parcel in [('상중동', '1-11'), ('중동', '11-1')]:
        assert not molit._matches_transaction(row, {'apartment': '현대1단지', 'legalDong': dong, 'jibun': parcel}, '현대1단지')


def test_jev_is_never_called_when_supplied_parcel_or_id_conflicts():
    candidates = [{**BASE, 'jibun': '11-1', 'apartmentId': 'B'}]
    with mock.patch.object(jev, 'configured', return_value=True), mock.patch.object(jev.requests, 'post') as post:
        for query in [{**BASE, 'jibun': '1-11'}, {**BASE, 'apartmentId': 'A'}]:
            assert jev.choose_apartment_identity(query, candidates)['selectedIndex'] is None
        post.assert_not_called()
    with mock.patch.object(search, 'APARTMENT_MASTER', candidates), mock.patch.object(budget, '_ENTITY_LOOKUP', None), mock.patch.object(jev, 'choose_apartment_identity') as choose:
        result = budget.resolve_apartment_identity('현대', '서초구', '반포동', '1-11')
        assert result['entity'] is None
        choose.assert_not_called()
        assert budget._price_lookup_entity({'name': '현대', 'region': '서초구', 'legalDong': '반포동', 'jibun': '1-11'}) is None


def test_jev_filtered_indices_and_cache_keep_original_candidate_order():
    candidates = [{**BASE, 'jibun': p} for p in ['11-1', '1-11']]
    response = mock.Mock()
    response.json.return_value = {'answers': {'apartment_identity': {'choice': 'candidate_0', 'probabilities': {'candidate_0': .99, 'no_match': .01}, 'confidence': .99}}}
    jev._CACHE.clear()
    with mock.patch.object(jev, 'configured', return_value=True), mock.patch.object(jev.requests, 'post', return_value=response):
        result = jev.choose_apartment_identity({**BASE, 'jibun': '1-11'}, candidates)
        assert result['selectedIndex'] == 1
        result = jev.choose_apartment_identity({**BASE, 'jibun': '1-11'}, list(reversed(candidates)))
        assert result['selectedIndex'] == 0


@pytest.mark.skipif(not shutil.which('node'), reason='node required')
def test_frontend_identity_matches_server_parcels_and_rejects_id_conflicts():
    html = (ROOT / '앱화면/real-estate-search.html').read_text()
    funcs = '\n'.join(re.search(r'    function ' + name + r'\(.*?\n    \}', html, re.S).group() for name in ['parcelIdentityKey', 'candidateIdentityKey', 'sameCandidateIdentity', 'candidateMapEntryForApartment', 'aptSearchMapSelectionKey'])
    script = funcs + '''
const assert = require('node:assert/strict');
const compactText = v => String(v || '').replace(/[^0-9A-Za-z가-힣]/g, '').toLowerCase();
const candidateDisplayName = v => v.name;
const base = {name:'현대',region:'서초구',legalDong:'반포동'};
const a = {...base,jibun:'1-11'}, b = {...base,jibun:'11-1'};
assert.equal(sameCandidateIdentity(a,b),false);
assert.equal(sameCandidateIdentity(a,{...a,jibun:'001-011'}),true);
assert.equal(sameCandidateIdentity({...a,apartmentId:'A'},{...a,apartmentId:'B'}),false);
assert.equal(sameCandidateIdentity({...a,region:'서울 서초구'},{...a,region:'서울특별시 서초구'}),true);
assert.notEqual(candidateIdentityKey({...a,apartmentId:'A',complexNo:'1'}),candidateIdentityKey({...a,apartmentId:'A',complexNo:'2'}));
let candidateMapEntries = [{item:a},{item:b}];
assert.equal(candidateMapEntryForApartment(base),null);
assert.equal(candidateMapEntryForApartment({...base,jibun:'001-011'}).item,a);
const currentAptSearchItems = [{...a,areaLabel:'전용 59㎡'}];
const button = {dataset:{candidateMapKey:'stale-before-area-selection'},closest:() => ({dataset:{aptCardIndex:'0'}})};
assert.equal(aptSearchMapSelectionKey(button),candidateIdentityKey(currentAptSearchItems[0]));
currentAptSearchItems[0] = {...a,areaLabel:'전용 84㎡'};
assert.equal(aptSearchMapSelectionKey(button),candidateIdentityKey(currentAptSearchItems[0]));
'''
    script += 'console.log(JSON.stringify(' + json.dumps(PARCELS) + '.map(parcelIdentityKey)));'
    # map passes index as second argument; explicitly use the single-value wrapper.
    script = script.replace('.map(parcelIdentityKey)', '.map(value => parcelIdentityKey(value))')
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [identity.parcel_key(p) for p in PARCELS]


def test_region_province_is_not_discarded_when_district_names_repeat():
    entities = [
        {'name': '현대', 'province': province, 'district': '중구', 'legalDong': '중앙동', 'jibun': '1'}
        for province in ['서울특별시', '부산광역시']
    ]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        assert budget._find_entities('현대', '서울 중구', '중앙동', '1') == [entities[0]]
        assert not identity.satisfies({'region': '서울 중구'}, entities[1])


def test_alias_family_cannot_choose_a_child_by_alias_order():
    manual = {'name': '햇살마을', 'aliases': ['햇살마을1단지', '햇살마을2단지']}
    sources = [{**BASE, 'name': '햇살마을' + str(n) + '단지', 'jibun': str(n), 'dedupeKey': str(n)} for n in (1, 2)]
    for ordered in [sources, list(reversed(sources))]:
        linked = search._link_manual_apartments_to_source([manual], ordered)[0]
        assert not linked.get('jibun')
        assert not linked.get('dedupeKey')


def test_candidate_deduplication_keeps_different_parcels_with_same_legacy_key():
    entities = [{**BASE, 'jibun': p, 'dedupeKey': 'legacy-same'} for p in ['1-11', '11-1']]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        rows = [{**e, 'region': '서초구'} for e in entities]
        assert len(budget._dedupe_candidate_rows(rows)) == 2


def test_price_api_does_not_fallback_to_generic_estimate_for_ambiguous_or_wrong_id():
    import search_server
    entities = [{**BASE, 'jibun': p, 'apartmentId': str(n)} for n, p in enumerate(['1-11', '11-1'])]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None), mock.patch.object(budget, 'apartment_candidate_result', return_value=None), mock.patch.object(search_server.rone_estimates, 'estimate') as estimate:
        for extra in [{}, {'legal_dong': '반포동', 'jibun': '1-11', 'apartment_id': 'wrong-id'}]:
            result, status = search_server._apartment_affordability({'name': '현대', 'region': '서초구', **extra})
            assert status == 200
            assert result['state'] == 'unavailable'
        estimate.assert_not_called()


def test_known_name_cannot_switch_to_another_known_complex_at_supplied_address():
    entities = [{**BASE, 'name': '원베일리', 'jibun': '1'},
                {**BASE, 'name': '퍼스티지', 'jibun': '18-1'}]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        assert budget._price_lookup_entity({'name': '원베일리', 'region': '서초구', 'legalDong': '반포동', 'jibun': '18-1'}) is None
        assert budget._price_lookup_entity({'name': '퍼스티지', 'region': '서초구', 'legalDong': '반포동', 'jibun': '18-1'}) == entities[1]
        with mock.patch.object(jev, 'choose_apartment_identity') as choose:
            assert budget.resolve_apartment_identity('원베일리', '서초구', '반포동', '18-1')['entity'] is None
            choose.assert_not_called()
