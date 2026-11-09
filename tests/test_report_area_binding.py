"""Selected-area reports must keep one transaction and reject obsolete responses."""
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import subprocess
from contextlib import ExitStack
from unittest.mock import patch

import pytest
import molit_transactions as molit
import price_valuation

HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'
CORE = ['zpNum', 'zippickTradeAreaScope', 'zippickAreaContains', 'zippickLatestTradeDetails',
        'zippickBuyBandTradeMatchesArea', 'zippickValuationMatchesTrade', 'zippickReportAreaKey']


def run_js(script, extra=()):
    if not shutil.which('node'):
        pytest.skip('Node required')
    source = HTML.read_text()
    functions = [re.search(r'^    (?:async )?function '+name+r'\([^\n]*\) \{.*?^    \}', source, re.M | re.S).group()
                 for name in [*CORE, *extra]]
    result = subprocess.run(['node'], input="const assert=require('node:assert/strict');\n"+'\n'.join(functions)+'\n'+script,
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_client_uses_the_server_area_filter_and_keeps_decimal_areas():
    labels = ['전용 59㎡', '84.97', '전용 60~60㎡', '전용 50~59㎡']
    cases = [{'scope':molit.area_scope(label), 'area':area,
              'matches':molit._matches_area({'exclusiveArea':area}, label)}
             for label in labels for area in [49, 50, 58.99, 59.43, 59.98, 60, 64.5, 74.9, 84.97, 85.98]]
    run_js('const cases='+json.dumps(cases)+';'+r'''
for (const c of cases) {
  const item={tradeAreaScope:c.scope, latestDealPriceEok:10,latestDealExclusiveArea:c.area,latestDealDate:'2026-10-01'};
  assert.equal(zippickBuyBandTradeMatchesArea(item),c.matches,JSON.stringify(c));
}
assert(zippickBuyBandTradeMatchesArea({areaLabel:'50~59㎡',displayAreaLabel:'50㎡',
 latestDealPriceEok:10,latestDealExclusiveArea:59.98}));
''')


def test_latest_price_date_area_and_floor_are_never_combined_across_records():
    run_js(r'''
const item={displayAreaLabel:'59㎡',latestDealPriceEok:99,latestDealDate:'2026-10-20',
 latestTrade:{dealAmountEok:10,exclusiveArea:59.98,dealDate:'2026-10-01',floor:'7'}};
assert.deepEqual(zippickLatestTradeDetails(item),{price:10,area:59.98,date:'2026-10-01',floor:'7'});
item.latestDealExclusiveArea=59.98;
assert.deepEqual(zippickLatestTradeDetails(item),{price:99,area:59.98,date:'2026-10-20',floor:''});
item.latestDealExclusiveArea=84.97;
assert.equal(zippickLatestTradeDetails(item).price,10,'use the matching complete record');
''')


def test_switching_area_discards_the_old_band_and_request_label():
    run_js(r'''
const previous={name:'선택단지',areaLabel:'50~59㎡',displayAreaLabel:'59㎡',areaMin:50,areaMax:59,
 valuation:{status:'ready',areaLabel:'59㎡',fairPrice:{lowEok:8,centerEok:9,highEok:10}},
 latestDealPriceEok:10,latestDealDate:'2026-09-01',latestDealExclusiveArea:59.98,latestDealFloor:'1'};
const payload={resolvedArea:'84.97',tradeAreaScope:{label:'84.97',minSqm:83.97,maxSqm:85.97,upperInclusive:true},
 latestTrade:{dealAmountEok:20,exclusiveArea:84.97,dealDate:'2026-10-01',floor:'12'},estimate:{}};
const changed=aptMarketCandidate(previous,payload);
assert.equal(changed.valuation.status,'loading');
assert.equal(changed.areaLabel,'84.97');
assert.equal(aptReportContextParams(changed).get('area_label'),'84.97');
assert.deepEqual(zippickLatestTradeDetails(changed),{price:20,area:84.97,date:'2026-10-01',floor:'12'});
const empty=aptMarketCandidate(changed,{resolvedArea:'59.98',latestTrade:{},estimate:{}});
assert.equal(zippickLatestTradeDetails(empty).price,0,'an empty selected unit must not inherit the prior unit price');
''', ['aptMarketCandidate', 'aptReportContextParams'])


def test_a_band_from_another_area_or_another_evaluated_trade_is_rejected():
    run_js(r'''
const item={areaLabel:'84㎡',latestDealPriceEok:20,latestDealDate:'2026-10-01',latestDealExclusiveArea:84.97,latestDealFloor:'12',
 valuation:{areaLabel:'59㎡'}};
assert.equal(zippickValuationMatchesTrade(item),false);
item.valuation={areaLabel:'84㎡',evaluatedTrade:{dealAmountEok:20,dealDate:'2026-10-01',exclusiveArea:84.97,floor:'12'}};
assert(zippickValuationMatchesTrade(item));
item.valuation.evaluatedTrade.floor='7';
assert.equal(zippickValuationMatchesTrade(item),false);
''')


def test_reverse_responses_during_59_84_59_switch_cannot_overwrite_current_trade():
    run_js(r'''
const waiting=[];
const fetchAptReport=()=>new Promise(resolve=>waiting.push(resolve));
const zippickRefreshReportLocation=()=>{};
const scope=area=>({label:String(area),minSqm:area-1,maxSqm:area+1,upperInclusive:true});
const report=(area,price,floor)=>({report:{tradeAreaScope:scope(area),peers:[],
 latestDealPriceEok:price,latestDealExclusiveArea:area,latestDealDate:'2026-10-01',latestDealFloor:floor,
 valuation:{status:'ready',areaLabel:String(area)}}});
(async()=>{
 const item={name:'선택단지',apartmentId:'unit-test',tradeAreaScope:scope(59)};
 const first=ensureZippickReportPeers(item);
 item.tradeAreaScope=scope(84); const second=ensureZippickReportPeers(item);
 item.tradeAreaScope=scope(59); const third=ensureZippickReportPeers(item);
 assert.equal(waiting.length,3);
 waiting[2](report(59,11,'7'));await third;
 waiting[0](report(59,9,'1'));await first;
 waiting[1](report(84,20,'12'));await second;
 assert.equal(item.latestDealPriceEok,11);
 assert.equal(item.latestDealExclusiveArea,59);
 assert.equal(item.latestDealFloor,'7');
 assert.equal(item.valuation.areaLabel,'59');
 assert.equal(item.reportPeerState,'ready');
})().catch(e=>{console.error(e);process.exitCode=1;});
''', ['ensureZippickReportPeers'])


def test_newer_report_trade_replaces_area_and_floor_as_well_as_price_and_date():
    import search_server as server
    entity={'name':'단지검수', 'district':'검수구', 'legalDong':'가동','jibun':'1','apartmentId':'test-only'}
    older={'latestDealPriceEok':9, 'latestDealDate':'2026-09-01','latestDealExclusiveArea':84.2,'latestDealFloor':'1'}
    newer={'latestDealPriceEok':10,'latestDealDate':'2026-10-01','latestDealExclusiveArea':84.97,'latestDealFloor':'12'}
    with ExitStack() as stack:
        for module, name, value in [
            (server.molit_transactions,'configured',True), (server.molit_transactions,'source_rows_for_entity',[]),
            (server.molit_transactions,'prefetch_months',None), (server.molit_transactions,'price_band_for_apartment',older),
            (server.molit_transactions,'latest_transaction_for_apartment',newer),
            (server.momentum_signals,'attach_signals',None), (server.momentum_signals,'district_peer_reports',[]),
            (server.location_scores,'attach_scores',None), (server.market_indicators,'attach',None),
            (server.price_valuation,'attach_valuations',None),
            (server.future_transformation,'analyze',{}), (server.future_transformation,'public_facts',{}),
        ]:
            stack.enter_context(patch.object(module,name,return_value=value))
        result=server._apartment_report(entity['name'],'검수구',area_label='전용 84㎡',entity_override=entity)['report']
    assert {k:result[k] for k in newer} == newer
    assert result['latestTrade']=={'dealAmountEok':10,'dealDate':'2026-10-01','exclusiveArea':84.97,'floor':'12'}
    assert result['tradeAreaScope']==molit.area_scope('전용 84㎡')


def test_valuation_cannot_use_a_transaction_from_a_different_selected_area():
    result=price_valuation.valuation_for_candidate({'priceIdentityVerified':True,'areaLabel':'59㎡',
        'latestDealExclusiveArea':84.97,'latestDealDate':'2026-10-01'},today=dt.date(2026,11,4))
    assert result['status']=='unavailable'
    assert '면적이 맞지 않아' in result['reason']
