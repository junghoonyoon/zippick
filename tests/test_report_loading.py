"""Reports must never paint a provisional verdict or reuse a previous selection."""
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HTML = Path(os.environ.get('REPORT_HTML', str(Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html')))
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='Node required')
CORE = ['zpNum', 'zippickTradeAreaScope', 'zippickAreaContains', 'zippickLatestTradeDetails',
        'zippickValuationMatchesTrade', 'zippickReportAreaKey', 'budgetCandidateReportReady', 'ensureZippickReportPeers']


def run_js(names, script):
    source = HTML.read_text()
    functions = [re.search(r'^    (?:async )?function '+name+r'\([^\n]*\) \{.*?^    \}', source, re.M | re.S).group()
                 for name in names]
    result = subprocess.run(['node'], input="const assert=require('node:assert/strict');\n"+'\n'.join(functions)+'\n'+script,
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


HARNESS = r'''
const esc=String, spinnerHtml=()=>'<span>loading</span>';
const trackDailyActiveUser=()=>{},trackEvent=()=>{},syncCandidateDetailScrollLock=()=>{};
const candidateDetailTitleHtml=(item,name)=>name, candidateBuildingAgeMeta=()=>'';
const scheduleZippickReportMaps=()=>{}, refreshAptSearchTrendCandidate=()=>{};
const syncCandidateReportScores=()=>{}, refreshLocationScoreSheet=()=>{}, refreshCollectedPriceScore=async()=>{};
const ensureZippickDevelopmentInsight=()=>{},enrichNewsCatalysts=async()=>{};
const refreshZippickReconstruction=async()=>{};
let aptReportReconstructionEvents=new AbortController();
const zippickRefreshReportLocation=()=>{};
let aptReportRequestId=0,currentAptReportItem=null,downloadReady=false;
const setAptReportDownloadReady=value=>downloadReady=value;
const aptReportSheet={hidden:true,setAttribute(){}};
const aptReportTitle={},aptReportMeta={};
const paints=[];
const retry={addEventListener(type,handler){this.handler=handler;}};
const aptReportContent={_html:'',scrollTop:0,set innerHTML(value){this._html=value;paints.push(value);},
  get innerHTML(){return this._html;},querySelector(){return retry;},addEventListener(){}};
const candidateZippickReportHtml=item=>`FINAL:${item.name}:${item.areaLabel}:${item.valuation?.fairPrice?.lowEok}`;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const scope=area=>({label:String(area),minSqm:area-1,maxSqm:area+1,upperInclusive:true});
const candidate=(name,area)=>({name,apartmentId:name,areaLabel:String(area),tradeAreaScope:scope(area),
 latestDealPriceEok:9,latestDealExclusiveArea:area,latestDealDate:'2026-10-24',latestDealFloor:'11',
 valuation:{status:'ready',fairPrice:{lowEok:9.03,highEok:10.49}},reportPeerState:'pending'});
const response=(name,area)=>({report:{...candidate(name,area),peers:[],priceComparison:{status:'ready'},
 valuation:{status:'ready',areaLabel:String(area),fairPrice:{lowEok:8.4,highEok:9.66}}}});
'''


@pytest.mark.parametrize('name,area', [('남서울힐스테이트',59.87),('잠실엘스',59.96),('래미안퍼스티지',84.93),('판교푸르지오그랑블',97.7)])
def test_first_painted_verdict_waits_for_selected_area_report(name, area):
    import json
    run_js([*CORE, 'openAptReport'], HARNESS + f'const name={json.dumps(name)}, area={area};' + r'''
let finish;
const fetchAptReport=()=>new Promise(resolve=>finish=resolve);
(async()=>{
 const item=candidate(name,area);
 const opening=openAptReport(name,'',item);
 await tick();
 assert(!paints.some(html=>html.includes('FINAL:')),'provisional price verdict was shown');
 assert.equal(downloadReady,false);
 assert.equal(currentAptReportItem,null);
 finish(response(name,area)); await opening;
 assert.equal(aptReportContent.innerHTML,`<div data-signal-report>FINAL:${name}:${area}:8.4</div>`);
 assert.equal(downloadReady,true);
 assert.equal(paints.filter(html=>html.includes('FINAL:')).length,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_an_already_running_report_request_is_shared_and_awaited():
    run_js(CORE, HARNESS + r'''
let finish,calls=0;
const fetchAptReport=()=>{calls++;return new Promise(resolve=>finish=resolve);};
(async()=>{
 const item=candidate('동일단지',59);
 const first=ensureZippickReportPeers(item);
 let secondDone=false;
 const second=ensureZippickReportPeers(item).then(()=>secondDone=true);
 await tick(); assert.equal(secondDone,false,'second caller must await in-flight data');
 assert.equal(calls,1);
 finish(response('동일단지',59));await Promise.all([first,second]);
 assert.equal(item.reportPeerState,'ready');
 assert.equal(item.valuation.fairPrice.lowEok,8.4);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_failed_report_is_retryable_without_showing_or_exporting_old_prices():
    run_js([*CORE,'openAptReport'], HARNESS + r'''
let fail=true;
const fetchAptReport=async()=>{if(fail)throw new Error('timeout');return response('남서울힐스테이트',59);};
(async()=>{
 const item=candidate('남서울힐스테이트',59);
 await openAptReport(item.name,'',item);
 assert(!paints.some(html=>html.includes('FINAL:')));
 assert.equal(downloadReady,false);
 assert.match(aptReportContent.innerHTML,/다시 불러오기/);
 assert.equal(typeof retry.handler,'function');
 fail=false; retry.handler(); await tick();
 assert.match(aptReportContent.innerHTML,/FINAL:남서울힐스테이트:59:8.4/);
 assert.equal(downloadReady,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_close_or_new_report_ignores_older_completion():
    run_js([*CORE,'openAptReport','closeAptReport'], HARNESS + r'''
const waiting=[];
const fetchAptReport=()=>new Promise(resolve=>waiting.push(resolve));
(async()=>{
 const first=openAptReport('첫단지','',candidate('첫단지',59));
 closeAptReport();
 waiting[0](response('첫단지',59)); await first;
 assert.equal(aptReportSheet.hidden,true);
 assert.equal(currentAptReportItem,null);
 assert.equal(downloadReady,false);
 const second=openAptReport('둘째단지','',candidate('둘째단지',84));
 const third=openAptReport('셋째단지','',candidate('셋째단지',59));
 waiting[2](response('셋째단지',59));await third;
 waiting[1](response('둘째단지',84));await second;
 assert.equal(currentAptReportItem.name,'셋째단지');
 assert(!paints.some(html=>/FINAL:(첫단지|둘째단지)/.test(html)));
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_59_84_59_late_chart_update_cannot_replace_new_59_data():
    run_js(['refreshAptSearchTrendCandidate'], r'''
const old={name:'남서울힐스테이트',areaLabel:'59',price:9.03};
const fresh={...old,price:8.4};
const aptCandidateResults=new Map([[0,fresh]]),currentAptSearchItems=[fresh];
const candidateIdentityKey=item=>`${item.name}:${item.areaLabel}`;
const aptSearchResults={querySelector:()=>null},candidateMapOrigin='none';
refreshAptSearchTrendCandidate(old);
assert.equal(fresh.price,8.4,'old request from the same area must not overwrite the new generation');
''')


def test_area_switch_locks_report_and_only_latest_response_unlocks_it():
    run_js(['selectAptArea','setAptAreaLoadState','renderAptCandidateResult','syncAptSearchCandidateData'], r'''
const esc=String,spinnerHtml=()=>'<span>loading</span>',trackDailyActiveUser=()=>{},trackEvent=()=>{};
const syncAptAreaChipSelection=()=>{},applyRoneLatestTradeFallback=()=>{},syncSparkAxisLabelSizes=()=>{};
const syncCompareSelection=()=>{},enrichAptSearchRivals=()=>{},enrichNewsCatalysts=async()=>{};
const candidateIdentityKey=item=>`${item.name}:${item.areaLabel}`,candidateMapOrigin='none';
const aptAffordabilityHtml=data=>data.error || 'selected data',aptPriceLookupFailure=error=>error;
const aptMarketCandidate=(item,data)=>({...item,areaLabel:data.resolvedArea,price:data.price});
const old={name:'남서울힐스테이트',areaLabel:'59',price:9.03};
const aptCandidateResults=new Map([[0,old]]),currentAptSearchItems=[old];
const button={disabled:false,setAttribute(){}},slot={innerHTML:'old data',classList:{add(){},remove(){}}};
const card={dataset:{aptCardIndex:'0',aptAreaRequest:'0',aptAreaState:'ready'},
 querySelector(selector){return selector==='[data-apt-affordability]' ? slot : selector==='[data-apt-area]' ? {} : null;},
 querySelectorAll(selector){return selector==='[data-apt-report-name]' ? [button] : [];}};
const requests=[];
const fetchAptAffordability=(item,area)=>new Promise((resolve,reject)=>requests.push({area,resolve,reject}));
(async()=>{
 const first=selectAptArea(card,'59');
 assert.equal(button.disabled,true);
 assert.equal(aptCandidateResults.has(0),false,'old selection must not remain report-openable');
 const second=selectAptArea(card,'84');
 const third=selectAptArea(card,'59');
 requests[1].resolve({resolvedArea:'84',price:20});await second;
 assert.equal(button.disabled,true,'obsolete response cannot unlock report');
 requests[2].resolve({resolvedArea:'59',price:8.4});await third;
 assert.equal(button.disabled,false);
 assert.equal(aptCandidateResults.get(0).price,8.4);
 requests[0].resolve({resolvedArea:'59',price:9.03});await first;
 assert.equal(aptCandidateResults.get(0).price,8.4);
 const failed=selectAptArea(card,'84');
 requests[3].reject({error:'연결 실패'});await failed;
 assert.equal(card.dataset.aptAreaState,'error');
 assert.equal(button.disabled,true);
 assert.equal(aptCandidateResults.has(0),false);
 assert.match(slot.innerHTML,/연결 실패/);
 const httpFailure=selectAptArea(card,'84');
 requests[4].resolve({state:'unavailable',priceStatus:'identity_unverified',error:'주소 확인 실패'});await httpFailure;
 assert.equal(button.disabled,true,'HTTP 200 failure is not ready');
 const retry=selectAptArea(card,'84');
 requests[5].resolve({resolvedArea:'84',price:20});await retry;
 assert.equal(button.disabled,false);
 assert.equal(aptCandidateResults.get(0).areaLabel,'84');
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_successful_no_trade_report_finishes_with_missing_data_not_old_band():
    run_js([*CORE,'openAptReport'], HARNESS + r'''
const fetchAptReport=async()=>({report:{tradeAreaScope:scope(59),peers:[],
 valuation:{status:'unavailable',reason:'선택한 평형의 거래 없음'},priceComparison:{status:'unavailable'}}});
(async()=>{
 const item={...candidate('거래없는단지',59),latestDealPriceEok:0,latestDealExclusiveArea:0,
  latestDealDate:'',valuation:{status:'loading'}};
 await openAptReport(item.name,'',item);
 assert.equal(item.reportPeerState,'ready');
 assert.equal(item.valuation.status,'unavailable');
 assert(!aptReportContent.innerHTML.includes('9.03'));
 assert.equal(downloadReady,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


@pytest.mark.parametrize('entry', ['list','map'])
def test_list_and_map_reports_wait_and_disable_export(entry):
    run_js([*CORE,'loadCandidateReportSheet','zippickReportLoadStateHtml'], HARNESS + r'''
let finish;
const fetchAptReport=()=>new Promise(resolve=>finish=resolve);
(async()=>{
 const slot={innerHTML:'old report'},button={disabled:false};
 const sheet={dataset:{},hidden:false,querySelector:()=>slot,querySelectorAll:()=>[button]};
 const item=candidate('단지',59);
 const opening=loadCandidateReportSheet(sheet,item);
 assert(!slot.innerHTML.includes('FINAL:'));
 assert.equal(button.disabled,true);
 finish(response('단지',59));await opening;
 assert.equal(slot.innerHTML,'FINAL:단지:59:8.4');
 assert.equal(button.disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
    source=HTML.read_text()
    name='setCandidateDetailOpen' if entry=='list' else 'setCandidateMapDetailOpen'
    body=re.search(r'^    function '+name+r'\(.*?^    \}',source,re.M|re.S).group()
    assert 'loadCandidateReportSheet(sheet, item)' in body


def test_prefetched_report_is_reused_even_when_comparison_data_is_missing():
    run_js([*CORE, 'loadCandidateReportSheet', 'zippickReportLoadStateHtml'], HARNESS + r"""
let calls=0,cached;
const fetchAptReport=async()=>{if(cached)return cached;calls++;return cached={report:{tradeAreaScope:scope(59),
 priceDataCollection:{sourceRevision:'v1'},valuation:{status:'unavailable'},priceComparison:{status:'unavailable'},peers:[]}};};
(async()=>{
 const item=candidate('자료 적은 단지',59);
 await ensureZippickReportPeers(item);
 assert.equal(budgetCandidateReportReady(item),true);
 const paints=[];
 const slot={set innerHTML(value){paints.push(value);}};
 const sheet={dataset:{},hidden:false,querySelector:()=>slot,querySelectorAll:()=>[]};
 await loadCandidateReportSheet(sheet,item);
 assert.equal(calls,1,'opening a prepared report must not request it again');
 assert(paints.every(html=>html.startsWith('FINAL:')),'prepared report must not flash loading');
 item.tradeAreaScope=scope(84);
 assert.equal(budgetCandidateReportReady(item),false,'ready is bound to the selected area');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_restored_loading_state_without_a_live_promise_retries():
    run_js(CORE, HARNESS + r"""
let calls=0;
const fetchAptReport=async()=>{calls++;return response('새로고침 단지',59);};
(async()=>{
 const item=candidate('새로고침 단지',59);
 Object.assign(item,{reportPeerState:'loading',reportPeerAreaKey:zippickReportAreaKey(item),reportPeerPromise:{}});
 await ensureZippickReportPeers(item);
 assert.equal(calls,1);
 assert.equal(budgetCandidateReportReady(item),true);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
