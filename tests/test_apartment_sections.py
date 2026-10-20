"""Real catalog and regression checks for section identity across app surfaces."""
import json
import sys
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import apartment_identity as identity
import apartment_sections as sections
import budget_candidates as budget
import molit_transactions as trades
import momentum_signals
import naver_complex as naver
import real_estate_search as search
import search_server as server
import typesafe_jev as jev


def imun():
    return sorted(search.suggest_apartments('이문아이파크자이'), key=lambda x: x['name'])


def test_imun_has_three_physical_sections_and_two_external_pages():
    rows = imun()
    assert [r['name'] for r in rows] == [f'이문아이파크자이 {n}단지' for n in (1, 2, 3)]
    assert len({r['apartmentId'] for r in rows}) == 3
    assert len({r['address'] for r in rows}) == 3
    assert len({(r['latitude'], r['longitude']) for r in rows}) == 3
    assert rows[0]['address'].endswith('이문로 120')
    assert rows[1]['address'].endswith('이문로 150')
    assert rows[2]['address'].endswith('천장산로13길 15')
    assert rows[2]['latitude'] == 37.6012018118991
    assert rows[2]['longitude'] == 127.057058429998
    assert rows[0]['naverScope'] == rows[1]['naverScope'] == 'shared_sections'
    assert rows[2]['naverScope'] == 'single_section'
    assert '1·2단지' in rows[0]['naverMappingNote']
    assert '3단지' in rows[2]['naverMappingNote']
    with mock.patch.object(naver, '_search', side_effect=AssertionError('offline mapping required')):
        naver.attach_links(rows)
    assert [r['naverComplexNo'] for r in rows] == ['174562', '174562', '184737']
    assert [r['displayName'] for r in rows] == [
        '이문아이파크자이(3-1BL)',
        '이문아이파크자이(3-1BL)',
        '이문아이파크자이(3-2BL)',
    ]
    assert all(r['naverComplexNo'] != '26159' for r in rows)
    for row in rows:
        entity = budget._price_lookup_entity(row)
        assert entity['apartmentId'] == row['apartmentId']
        assert budget._map_address(row, entity) == row['address']
        assert budget._naver_property_link(row, entity)['naverComplexNo'] == row['naverComplexNo']
        assert len(trades.source_rows_for_entity(entity)) == 1
        assert len(search.suggest_apartments(row['name'])) == 1


def test_third_section_keeps_its_own_naver_listing_range_without_calling_it_a_trade():
    third = imun()[2]
    entity = budget._price_lookup_entity(third)
    reference = server._naver_listing_reference_for_entity(entity)
    assert reference == {
        'provider': '네이버 부동산', 'asOf': '2026-10-19',
        'saleListingCount': 8, 'saleMinPriceEok': 12.7, 'saleMaxPriceEok': 18.0,
        'leaseListingCount': 12, 'leaseMinPriceEok': 7.0, 'leaseMaxPriceEok': 11.0,
        'sourceUrl': 'https://fin.land.naver.com/complexes/184737',
    }


def test_no_official_trade_response_keeps_the_verified_naver_listing_range():
    third = imun()[2]
    with mock.patch.object(server.budget_candidates, 'apartment_candidate_result', return_value=None), \
         mock.patch.object(server.rone_estimates, 'estimate', return_value=({'error': '없음'}, 404)), \
         mock.patch.object(server, '_molit_affordability_estimate', return_value=None), \
         mock.patch.object(server.molit_transactions, 'last_error', return_value=None):
        payload, status = server._apartment_affordability({
            'name': third['name'], 'region': third['region'], 'legal_dong': third['legalDong'],
            'jibun': third['jibun'], 'apartment_id': third['apartmentId'],
            'kapt_code': third['kaptCode'], 'months': 24,
        })
    assert status == 200
    assert payload['state'] == 'unavailable'
    assert payload['priceStatus'] == 'no_recent_official_trades'
    assert payload['naverListingReference']['saleMinPriceEok'] == 12.7
    assert payload['naverListingReference']['saleMaxPriceEok'] == 18.0


def test_shared_parcel_cannot_erase_section_name_or_id():
    first, second, _ = imun()
    assert budget._find_entity(first['name'], first['region'], first['legalDong'], first['jibun'])['apartmentId'] == first['apartmentId']
    assert budget._price_lookup_entity({**first, 'apartmentId':second['apartmentId']}) is None
    assert not identity.satisfies(first, second)
    assert budget._find_entity('이문아이파크자이', '동대문구', '이문동', '149-8') is None


def test_reviewed_shared_scope_labels_unnumbered_1_and_2_transactions():
    first, second, third = imun()
    sources = [trades.source_rows_for_entity(budget._price_lookup_entity(r))[0] for r in (first, second)]
    item = {'apartment':'이문아이파크자이','legalDong':'이문동','jibun':'149-8'}
    assert all(row['transactionScope']['label'] == '이문아이파크자이 1·2단지 통합 거래' for row in sources)
    assert all(trades._matches_transaction(row, item, row['대표단지명']) for row in sources)
    assert trades._matches_transaction(sources[0], {**item, 'buildingDong':'101동'}, first['name'])
    assert not trades._matches_transaction(sources[1], {**item, 'buildingDong':'101동'}, second['name'])
    assert trades._matches_transaction(sources[1], {**item, 'apartment':second['name']}, second['name'])
    assert not trades._matches_transaction(sources[0], {**item, 'apartment':second['name']}, first['name'])
    third_source = trades.source_rows_for_entity(budget._price_lookup_entity(third))[0]
    assert third_source.get('transactionScope') is None
    assert not trades._matches_transaction(third_source, item, third['name'])


def test_source_phase_is_preserved_before_merging_same_parcel():
    assert search._apartment_display_name({'대표단지명':'선경아파트', '단지명_공시가격':'선경1차(1동-7동)'}) == '선경1차(1동-7동)'
    assert search._apartment_display_name({'대표단지명':'선경아파트', '단지명_공시가격':'선경2차(8동-12동)'}) == '선경2차(8동-12동)'
    assert identity.phase_conflicts('햇살1단지', '햇살2단지')
    assert identity.phase_conflicts('햇살5-1단지', '햇살5-2단지')
    assert not identity.phase_conflicts('우성1차', '우성1,2차')
    assert not identity.phase_numbers('현대101동(149-8)')


def test_candidate_public_scope_keeps_both_official_feeds_for_market_signals():
    """A price-bearing card must read the same trades as the full master."""
    recent = momentum_signals._months_ago(2)
    prior = momentum_signals._months_ago(8)
    transactions = [
        {'apartment': '이문아이파크자이', 'legalDong': '이문동', 'jibun': '149-8',
         'dealDate': f'{month}-{day:02}', 'dealAmountEok': price,
         'dealAmountManwon': price * 10000,
         'exclusiveArea': 84.95, 'dealType': '중개거래'}
        for month, price in ((recent, 20), (prior, 18)) for day in (1, 2, 3)
    ]
    def cached_month(_lawd, month, transaction_kind=trades.TRANSACTION_KIND_APARTMENT):
        if transaction_kind != trades.TRANSACTION_KIND_PRESALE:
            return []
        return [t for t in transactions if t['dealDate'].replace('-', '').startswith(month)]

    for card in imun()[:2]:
        entity = budget._price_lookup_entity(card)
        scope = trades.transaction_scope_for_entity(entity)
        row = {**card, **budget._candidate_identity_fields(card, entity),
               'transactionScope': trades._public_transaction_scope(scope)}
        assert 'sectionIdentity' not in row
        assert trades._transaction_kinds_for_apartment(row['name'], row['region'], row) == ('apartment', 'presale')
        with mock.patch.object(trades, '_read_cached_month_memory', side_effect=cached_month):
            signal = momentum_signals.raw_signals(row['name'], region=row['region'],
                area_label='84.95', entity=row, cache_only=True)
        assert signal['status'] == 'ok'
        assert signal['dealCount'] == 6
        assert signal['recentDealCount'] == signal['priorDealCount'] == 3
        with mock.patch.object(trades, '_transactions_for_apartment_kind', return_value=[]) as load:
            trades.transactions_for_apartment(row['name'], region=row['region'], entity=row)
        assert [call.args[-1] for call in load.call_args_list] == ['apartment', 'presale']


def test_card_scope_recovery_rejects_another_parcel_or_section():
    first, _, third = imun()
    assert sections.transaction_scope(first)
    assert sections.transaction_scope({**first, 'jibun': '419-1'}) is None
    assert sections.transaction_scope({**first, 'legalDong': '전농동'}) is None
    assert sections.transaction_scope({**first, 'apartmentId': third['apartmentId']}) is None
    assert sections.transaction_scope(third) is None


def test_naver_never_matches_on_dong_alone_or_overrides_explicit_phase():
    entries = [{'hscpNo':'3','hscpNm':'햇살마을3단지','cortarAddress':'서울특별시 동대문구 이문동'}]
    assert naver._pick(entries, '전혀다른아파트', '이문동') is None
    assert naver._pick(entries, '햇살마을1단지', '이문동', alternate_names=['햇살마을']) is None
    assert naver._pick(entries, '햇살마을', '이문동') is None
    assert naver._pick(entries, '햇살마을3단지', '이문동')['complexNo'] == '3'
    assert naver._pick(entries, '햇살마을3단지', '이문동', region='부산 중구') is None
    assert naver._pick([{**entries[0], 'hscpTypeCd':'A02'}], '햇살마을3단지', '이문동') is None


def test_jev_never_selects_a_number_for_a_family_or_accepts_another_section():
    rows = imun()[:2]
    with mock.patch.object(jev.requests, 'post') as post:
        assert jev.choose_apartment_identity({'name':'이문아이파크자이','region':'동대문구','legalDong':'이문동','jibun':'149-8'},
            [{**r,'district':r['region']} for r in rows])['reason'] == 'section_number_missing'
        assert jev.choose_apartment_identity(rows[0], [{**rows[1],'district':'동대문구'}])['status'] == 'unavailable'
        post.assert_not_called()


def test_display_name_preserves_a_section_when_naver_combines_it():
    row={'name':'개포우성1차','displayName':'개포우성1차'}
    with mock.patch.object(naver, 'resolve', return_value={'complexNo':'65','complexName':'개포우성1,2차'}):
        naver.attach_links([row])
    assert row['displayName'] == '개포우성1차'
    assert row['naverComplexName'] == '개포우성1,2차'


def test_all_numbered_source_names_and_reviewed_mappings_are_consistent():
    for entity in search.APARTMENT_MASTER:
        if entity.get('aggregate') or not entity.get('district'):
            continue
        if any(identity.phase_numbers(alias) for alias in entity.get('aliases', [])):
            assert identity.phase_numbers(entity['name']), entity
    entries = json.loads(naver.STATIC_OVERRIDES_PATH.read_text())['entries']
    for entry in entries:
        assert (not identity.phase_conflicts(entry['name'], entry['complexName'])
                or naver.verified_phase_alias(entry['name'], entry)), entry
        assert not naver.rejected_mapping(entry['complexNo'], entry['legalDong'], entry['jibun'], entry.get('region')), entry
    for review in naver.mapping_reviews():
        if review['status'] != 'corrected':
            continue
        for alias in review['aliases']:
            actual=naver.resolve_static(alias, review['legalDong'], review['jibun'], region=review['region'])
            assert actual and actual['complexNo'] == review['complexNo'], (review, alias, actual)


def test_naver_static_and_builder_preserve_parcel_and_region_boundaries():
    import build_naver_complex_overrides as builder
    entries = [
        {'name':'햇살1단지','legalDong':'중앙동','jibun':parcel,'region':region,'complexNo':str(index), 'complexName':'햇살1단지'}
        for index,(parcel,region) in enumerate([('1-11','서울 중구'), ('11-1','서울 중구'), ('1-11','부산 중구')],1)
    ]
    assert len({builder._entry_identity(e) for e in entries}) == 3
    overrides = {}
    for entry in entries:
        overrides.setdefault(naver._override_key(entry['name'],entry['legalDong'],entry['jibun']),[]).append(entry)
    with mock.patch.object(naver,'_STATIC_COMPLEX_OVERRIDES',overrides):
        assert naver.resolve_static('햇살1단지','중앙동','1-11',region='서울 중구')['complexNo']=='1'
        assert naver.resolve_static('햇살1단지','중앙동','11-1',region='서울 중구')['complexNo']=='2'
        assert naver.resolve_static('햇살1단지','중앙동','1-11',region='부산 중구')['complexNo']=='3'
        assert naver.resolve_static('햇살1단지','중앙동','1-11') is None


def test_reviewed_wrong_mapping_cannot_return_from_live_or_cache():
    review=next(r for r in naver.mapping_reviews() if r['status']=='unresolved')
    bad={'complexNo':review['rejectedComplexNos'][0], 'complexName':'강동리엔파크14단지'}
    with mock.patch.object(naver,'resolve_static',return_value=None), mock.patch.object(naver,'_read_cache',return_value=bad), mock.patch.object(naver,'_search_by_cortar',return_value=[]), mock.patch.object(naver,'_search',return_value=None):
        assert naver.resolve(review['aliases'][0],review['legalDong'],review['jibun'],region=review['region']) is None
    assert naver._pick([{'hscpNo':bad['complexNo'],'hscpNm':'강동리엔파크'}], '강동리엔파크',review['legalDong'],jibun=review['jibun'],region=review['region']) is None


def test_known_section_rejects_stale_parcel_and_another_section_page():
    with mock.patch.object(naver,'_search') as search_live, mock.patch.object(naver,'_search_by_cortar') as search_dong:
        assert naver.resolve('이문아이파크자이 3단지','이문동','149-8',region='동대문구') is None
        search_live.assert_not_called()
        search_dong.assert_not_called()
    assert naver._pick([{'hscpNo':'184737','hscpNm':'이문아이파크자이(3-2BL)'}],
                       '이문아이파크자이 1단지','이문동',jibun='149-8',region='동대문구') is None


def test_browser_map_cache_keeps_distinct_parcels_and_sections():
    import re
    import shutil
    import subprocess
    import pytest
    if not shutil.which('node'):
        pytest.skip('node required')
    html=(ROOT/'앱화면/real-estate-search.html').read_text()
    functions='\n'.join(re.search(r'    function '+name+r'\(.*?\n    \}',html,re.S).group()
                       for name in ['parcelIdentityKey','candidateMapAddress','candidateMapLocationKey','candidateMapCacheKey'])
    js=functions+'''
const assert=require('node:assert/strict');
const compactText=v=>String(v||'').replace(/[^0-9A-Za-z가-힣]/g,'').toLowerCase();
const candidateDisplayName=v=>v.name;
const a={name:'현대',region:'서울 중구',legalDong:'중앙동',jibun:'1-11'};
assert.notEqual(candidateMapCacheKey(a),candidateMapCacheKey({...a,jibun:'11-1'}));
assert.notEqual(candidateMapCacheKey({...a,apartmentId:'section:1'}),candidateMapCacheKey({...a,apartmentId:'section:2'}));
'''
    result=subprocess.run(['node'],input=js,text=True,capture_output=True)
    assert result.returncode==0,result.stderr


def test_builder_does_not_replay_legacy_or_wrong_phase_cache(tmp_path):
    import build_naver_complex_overrides as builder
    candidate={'name':'햇살1단지','aliases':['햇살1단지'],'region':'중구','legalDong':'중앙동','jibun':'1-11'}
    (tmp_path/'v6_햇살1단지_중앙동_111.json').write_text(json.dumps({'complexNo':'3','complexName':'햇살3단지'}))
    with mock.patch.object(naver,'CACHE_DIR',tmp_path):
        assert builder._cached_resolved_complex(candidate) is None
        path=naver._cache_path(naver._cache_key(candidate['name'],candidate['legalDong'],candidate['jibun'],candidate['region']))
        path.write_text(json.dumps({'complexNo':'3','complexName':'햇살3단지'}))
        assert builder._cached_resolved_complex(candidate) is None
        path.write_text(json.dumps({'complexNo':'1','complexName':'햇살1단지'}))
        assert builder._cached_resolved_complex(candidate)['complexNo']=='1'
    assert builder._entry_by_complex_no([], '99') is None
