"""Regional rankings must open the very same physical complex in detail APIs."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import apartment_leaders as leaders
import budget_candidates as budget
import real_estate_search as search
import search_server

ROOT = Path(__file__).resolve().parents[1]


def ranked_item(entity):
    with mock.patch.object(leaders.kakao_station_distances, 'cached_station', return_value=None):
        return leaders._base_metrics(entity, [], '2026-11', '70-89')


def detail_target(item):
    return dict(name=item['apartmentName'], region=f"{item['sido']} {item['sigungu']}",
                legalDong=item['dong'], jibun=item.get('jibun', ''),
                **{key: item.get(key, '') for key in ('apartmentId', 'kaptCode', 'complexNo')})


def test_ranked_identity_resolves_to_the_registry_for_reported_and_other_regions():
    cases = [('서울숲리버뷰자이', '성동구'), ('래미안퍼스티지', '서초구'),
             ('판교푸르지오그랑블', '성남분당구')]
    for name, district in cases:
        matches = budget._find_entities(name, district)
        assert len(matches) == 1, (name, len(matches))
        entity = matches[0]
        item = ranked_item(entity)
        assert item['apartmentId'] == entity['apartmentId']
        assert item['jibun'] == budget._entity_jibun(entity)
        assert budget._price_lookup_entity(detail_target(item)) == entity


def test_missing_registry_id_never_becomes_a_synthetic_id_or_wrong_parcel():
    base = dict(name='현대', province='서울특별시', city='서울', district='서초구',
                legalDong='반포동', households=100)
    entities = [{**base, 'jibun':'1-11', 'dedupeKey':'first'},
                {**base, 'jibun':'11-1', 'dedupeKey':'second', 'kaptCode':'KAPT2', 'complexNo':'200'}]
    with mock.patch.object(search, 'APARTMENT_MASTER', entities), mock.patch.object(budget, '_ENTITY_LOOKUP', None):
        for entity in entities:
            item = ranked_item(entity)
            assert item['apartmentId'] == ''
            assert budget._price_lookup_entity(detail_target(item)) == entity
        wrong = {**detail_target(ranked_item(entities[1])), 'apartmentId':'wrong-id'}
        assert budget._price_lookup_entity(wrong) is None


def test_ranking_cache_does_not_reuse_legacy_hash_ids(tmp_path):
    with mock.patch.object(leaders, 'CACHE_DIR', tmp_path), \
         mock.patch.object(leaders.kakao_station_distances, 'cache_revision', return_value='station'), \
         mock.patch.object(leaders.kakao_station_distances.shared_data, 'revision', return_value='source'):
        old_material = '|'.join((leaders.CALCULATION_VERSION, '서울특별시', '성동구',
                                 '70-89', '2026-11', 'station', 'source'))
        old_path = tmp_path / (hashlib.sha256(old_material.encode()).hexdigest() + '.json')
        old_path.write_text(json.dumps({'rankings':{'price':[{'apartmentId':'old-hash'}]}}))
        fresh = {'rankings':{'price':[{'apartmentId':'11200120372630', 'jibun':'380'}]}}
        with mock.patch.object(leaders, 'calculate_rankings', return_value=fresh) as calculate:
            result = leaders.get_leaders('서울특별시', '성동구', reference_month='2026-11')
            assert result['items'] == fresh['rankings']['price']
            calculate.assert_called_once()
            again = leaders.get_leaders('서울특별시', '성동구', reference_month='2026-11')
            assert again['items'] == result['items']
            calculate.assert_called_once()


def test_leader_score_detail_keeps_legacy_links_without_using_them_as_registry_ids():
    item = {'apartmentId':'registry-id', 'leaderId':'old-ranking-hash', 'rank':1}
    payload = dict(rankings={'price':[item]}, region={}, referenceMonth='2026-11', areaBucket='70-89')
    with mock.patch.object(leaders, 'calculate_rankings', return_value=payload):
        for value in ['registry-id', 'old-ranking-hash']:
            assert leaders.apartment_detail(value, '서울특별시', '성동구', '70-89')['apartment'] == item
        assert leaders.apartment_detail('', '서울특별시', '성동구', '70-89') is None


def test_failed_identity_is_a_finished_retryable_state_and_never_calls_price_estimator():
    with mock.patch.object(budget, 'apartment_candidate_result', return_value=None), \
         mock.patch.object(budget, '_price_lookup_entity', return_value=None), \
         mock.patch.object(search_server.rone_estimates, 'estimate') as estimate:
        result, status = search_server._apartment_affordability(dict(
            name='서울숲리버뷰자이', region='성동구', apartment_id='wrong-id', area='84'))
        assert status == 200
        assert result['state'] == 'unavailable'
        assert result['priceStatus'] == 'identity_unverified'
        estimate.assert_not_called()


def test_leader_list_and_map_targets_enrich_search_with_canonical_metadata():
    entity = budget._find_entity('서울숲리버뷰자이', '성동구')
    item = ranked_item(entity)
    suggestion = next(row for row in search.suggest_apartments(entity['name'])
                      if row['apartmentId'] == entity['apartmentId'])
    html = (ROOT / '앱화면/real-estate-search.html').read_text()
    functions = []
    for name in ('aptSearchFallbackItem', 'aptSearchResultItems', 'leaderMapCandidate'):
        functions.append(re.search(r'^    function ' + name + r'\([^\n]*\) \{.*?^    \}', html, re.M | re.S).group())
    # Execute the actual attributes used by both the list and map, then follow
    # the same dataset -> selected item -> suggestion merge as a browser click.
    attrs = re.findall(r'const detailAttrs = (`data-leader-detail-name=.*?`);', html)
    assert len(attrs) == 2
    script = '''
const assert = require('node:assert/strict');
const esc = String, compactText = value => String(value || '').replace(/\\s+/g, '');
const leaderAreaProfile = () => ({label:'84㎡', target:84});
const currentLeaderPayload = {areaBucket:'70-89'};
const detailAreaTarget = 84;
'''
    script += 'const item = ' + json.dumps(item) + ';\nconst suggestion = ' + json.dumps(suggestion) + ';\n'
    for attr in attrs:
        script += '''{
const markup = ''' + attr + ''';
const values = Object.fromEntries([...markup.matchAll(/data-leader-detail-([a-z-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
const selected = {name:values.name,region:values.region,legalDong:values['legal-dong'],jibun:values.jibun,
apartmentId:values['apartment-id'],kaptCode:values['kapt-code'],complexNo:values['complex-no'],preferredArea:values['area-target']};
const result = aptSearchResultItems(item.apartmentName,[suggestion],selected)[0];
assert.equal(result.apartmentId,suggestion.apartmentId);
assert.equal(result.approvedAt,'2018-06-22');
assert.equal(result.jibun,'380');
assert.equal(result.households,858);
assert.equal(result.preferredArea,'84');
assert.match(selected.region,/서울특별시/);
assert.equal(values['kapt-code'],item.kaptCode);
assert.equal(values['complex-no'],item.complexNo);
}
'''
    script += '''
const map = leaderMapCandidate(item);
assert.equal(map.apartmentId, suggestion.apartmentId);
assert.equal(map.jibun, suggestion.jibun);
assert.match(map.region,/서울특별시/);
const wrong = aptSearchResultItems(item.apartmentName,[{...suggestion,apartmentId:'wrong-id',approvedAt:'WRONG'}],
{name:item.apartmentName,region:'성동구',apartmentId:item.apartmentId})[0];
assert.notEqual(wrong.approvedAt,'WRONG');
'''
    result = subprocess.run(['node'], input='\n'.join(functions) + '\n' + script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
