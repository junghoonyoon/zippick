"""Exercise real browser helpers through pending, completion and retry."""
import re
import subprocess
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'


def run(script):
    text = HTML.read_text(encoding='utf-8')
    match = re.search(r'^    async function fetchAptReport\(.*?^    \}', text, re.M | re.S)
    assert match
    harness = r'''
const assert=require('node:assert/strict');
const aptReportCache=new Map();
const zippickTradeAreaScope=c=>({label:c.areaLabel,minSqm:Number(c.areaLabel),maxSqm:Number(c.areaLabel)+1,upperInclusive:false});
const aptReportContextParams=c=>new URLSearchParams({area_label:c.areaLabel});
const nativeTimer=global.setTimeout;
global.setTimeout=(fn,ms)=>nativeTimer(fn,ms===3000?0:ms);
'''
    output = subprocess.run(['node'], input=harness + match.group() + '\n' + script,
                            capture_output=True, text=True, timeout=15)
    assert output.returncode == 0, output.stderr


def test_pending_rechecks_source_and_reloads_the_same_area_then_invalidates_cache_on_revision_change():
    run(r'''
let phase=0, statusCalls=0, reportCalls=0, revision='v1';
const getJson=async url=>{
 if(url.startsWith('/api/apartment-price-source')){
  statusCalls++;
  if(phase===0) return {priceDataCollection:{status:++phase?'collecting':'queued'}};
  return {priceDataCollection:{status:'ready',sourceRevision:revision}};
 }
 reportCalls++;
 if(reportCalls===1) return {report:{priceDataCollection:{status:'queued'}}};
 return {report:{priceDataCollection:{status:'ready',sourceRevision:revision},
  tradeAreaScope:{minSqm:59,maxSqm:60,upperInclusive:false},priceComparison:{status:'ready',shiftPp:reportCalls}}};
};
(async()=>{
 const item={apartmentId:'ID',name:'단지',region:'예시구',legalDong:'가동',jibun:'1',areaLabel:'59'};
 const result=await fetchAptReport(item.name,item.region,item);
 assert.equal(result.report.priceComparison.shiftPp,2);assert.equal(reportCalls,2);
 const cached=await fetchAptReport(item.name,item.region,item);
 assert.equal(cached.report.priceComparison.shiftPp,2);assert.equal(reportCalls,2);
 revision='v2';const updated=await fetchAptReport(item.name,item.region,item);
 assert.equal(updated.report.priceComparison.shiftPp,3);assert.equal(reportCalls,3);
 assert.ok(statusCalls>=3);assert.equal(item.areaLabel,'59');
})().catch(err=>{console.error(err);process.exitCode=1;});
''')


def test_failed_collection_is_not_cached_and_can_be_retried():
    run(r'''
let reportCalls=0, failed=true;
const getJson=async url=>{
 if(url.startsWith('/api/apartment-price-source')) return {priceDataCollection: failed
  ? {status:'error',message:'실거래 연결 실패'} : {status:'ready',sourceRevision:'v2'}};
 reportCalls++;
 return failed ? {report:{priceDataCollection:{status:'collecting'}}}
  : {report:{priceDataCollection:{status:'ready',sourceRevision:'v2'},tradeAreaScope:{minSqm:84,maxSqm:85,upperInclusive:false}}};
};
(async()=>{
 const item={name:'단지',region:'예시구',areaLabel:'84'};
 await assert.rejects(fetchAptReport(item.name,item.region,item),/실거래 연결 실패/);
 assert.equal(aptReportCache.size,0);
 failed=false;const result=await fetchAptReport(item.name,item.region,item);
 assert.equal(result.report.priceDataCollection.status,'ready');assert.equal(reportCalls,2);
})().catch(err=>{console.error(err);process.exitCode=1;});
''')


def test_collection_result_updates_every_same_area_row_and_open_map_without_touching_other_areas():
    source = HTML.read_text(encoding='utf-8')
    def extract(start, end):
        return source[source.index(start):source.index(end, source.index(start))]
    rows = extract('    function candidateRowsForLookup(', '    function repaintCandidateScoreBadges')
    identity = extract('    function candidateScoreAreaIdentity(', '    function syncAptSearchCandidateData')
    sync = extract('    function syncCandidateReportScores(', '    async function refreshLocationScoreSheet')
    script = r'''
const assert=require('node:assert/strict');
const base={apartmentId:'same',name:'단지',region:'예시구',legalDong:'가동',jibun:'1',areaLabel:'84.9㎡'};
const report={...base,priceComparison:{status:'ready',shiftPp:2},locationScore:{score:73},priceDataCollection:{sourceRevision:'v2'}};
const other={...base,areaLabel:'59㎡',priceComparison:{shiftPp:99}};
const search={...base,priceComparison:{status:'loading'}}, budget={...base,priceComparison:{status:'loading'}}, map={...base,priceComparison:{status:'loading'}};
const currentBudgetData={allCandidates:[budget],candidates:[budget]};
const personal={...base,commuteAccessRequested:true,commuteAccessScore:20,locationScore:{score:40}};
const currentAptSearchItems=[search,other,personal],currentAptSearchRivalItems=[],aptCandidateResults=new Map();
const candidateMapEntries=[{item:map}],candidateMapLocatedEntries=[{item:map}];
const candidateViewMode='map',candidateMapSelectedKey='same|84.9㎡';let shown;
const candidateIdentityKey=x=>`${x.apartmentId}|${x.areaLabel}`;
const sameCandidateIdentity=(a,b)=>a.apartmentId===b.apartmentId&&a.region===b.region&&a.legalDong===b.legalDong&&a.jibun===b.jibun;
const repaintCandidateScoreBadges=()=>{};
const selectCandidateMapItem=(item,options)=>shown={item,options};
''' + rows + identity + sync + r'''
syncCandidateReportScores(report);
for(const row of [search,budget,map]) {assert.equal(row.priceComparison.shiftPp,2);assert.equal(row.locationScore.score,73);}
assert.equal(other.priceComparison.shiftPp,99);
assert.equal(personal.priceComparison.shiftPp,2);assert.equal(personal.locationScore.score,40,'do not overwrite personal commute score');
assert.strictEqual(shown.item,map);assert.deepEqual(shown.options,{pan:false,stationRoute:false,preserveSheetState:true});
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_score_refresh_passes_comparison_and_preserves_personal_commute_and_selection():
    source = HTML.read_text(encoding='utf-8')
    def extract(start, end):
        return source[source.index(start):source.index(end, source.index(start))]
    payload = extract('    function locationScoreRefreshPayload(', '    function syncCandidateReportScores')
    refresh = extract('    async function refreshLocationScoreSheet(', '    function openLocationScoreSheet')
    script = r'''
const assert=require('node:assert/strict');let send,resolve;
const getJson=(_url,options)=>{send=JSON.parse(options.body);return new Promise(r=>resolve=r);};
const candidateIdentityKey=x=>x.apartmentId;
const zippickReportAreaKey=x=>x.areaLabel;
const candidateRowsForLookup=()=>[];
const locationScoreNeedsRefresh=()=>false;
const repaintCandidateScoreBadges=()=>{};const syncCandidateReportScores=()=>{};
const locationScoreSheet={hidden:true};const locationScoreContent={};
''' + payload + refresh + r'''
(async()=>{
 const item={apartmentId:'id',name:'단지',region:'예시구',areaLabel:'84㎡',
  priceComparison:{status:'ready',shiftPp:-4},priceDataCollection:{sourceRevision:'v1'},
  commuteAccessRequested:true,commuteAccessScore:77,commuteAccessReason:'직장 조건'};
 const request=refreshLocationScoreSheet(item,null,{force:true});
 assert.equal(send.priceComparison.shiftPp,-4);assert.equal(send.areaLabel,'84㎡');
 assert.equal(send.commuteAccessScore,77);assert.equal(send.commuteAccessReason,'직장 조건');
 item.areaLabel='59㎡';resolve({candidate:{locationScore:{score:99}}});await request;
 assert.equal(item.locationScore,undefined,'old response cannot overwrite changed area');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_price_score_refresh_is_shared_and_retried_per_area_and_source_revision():
    source = HTML.read_text(encoding='utf-8')
    start = source.index('    async function refreshCollectedPriceScore(')
    end = source.index('    function openLocationScoreSheet(', start)
    helper = source[start:end]
    script = r"""
const assert=require('node:assert/strict');let calls=0,fail=false;
const zippickReportAreaKey=item=>item.areaLabel;
const refreshLocationScoreSheet=async(item,callback,options)=>{
 calls++;await Promise.resolve();if(!fail) (typeof callback==='function'?callback:options.onRefresh)();
};
""" + helper + r"""
(async()=>{
 const item={areaLabel:'84',reportPeerState:'ready',priceDataCollection:{sourceRevision:'v1'}};
 let updates=0;await Promise.all([refreshCollectedPriceScore(item,()=>updates++),refreshCollectedPriceScore(item,()=>updates++)]);
 assert.equal(calls,1);assert.equal(updates,2);
 await refreshCollectedPriceScore(item);assert.equal(calls,1);
 item.priceDataCollection.sourceRevision='v2';fail=true;await refreshCollectedPriceScore(item);assert.equal(calls,2);
 fail=false;await refreshCollectedPriceScore(item);assert.equal(calls,3);
 item.areaLabel='59';await refreshCollectedPriceScore(item);assert.equal(calls,4);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_list_and_map_detail_recalculate_score_after_a_collection():
    source = HTML.read_text(encoding='utf-8')
    start = source.index('    async function loadCandidateReportSheet(')
    end = source.index('    function candidateZippickReportHtml(', start)
    helper = source[start:end]
    script = r"""
const assert=require('node:assert/strict');let synced=0,refreshed=0;
const zippickReportAreaKey=item=>item.areaLabel;
const budgetCandidateReportReady=()=>false,zippickReportLoadStateHtml=()=>"loading";
const candidateZippickReportHtml=item=>`price:${item.priceComparison.shiftPp};score:${item.locationScore.score}`;
const ensureZippickReportPeers=async item=>{item.reportPeerState='ready';item.priceDataCollection={sourceRevision:'v1'};item.priceComparison={shiftPp:2};};
const syncCandidateReportScores=()=>synced++;
const refreshCollectedPriceScore=async(item,callback)=>{refreshed++;item.locationScore={score:77};callback();};
const scheduleZippickReportMaps=()=>{},refreshZippickReconstructionSection=()=>{},refreshZippickReconstruction=async()=>{};
""" + helper + r"""
(async()=>{
 for(const entry of ['list','map']){
  const slot={innerHTML:''},sheet={dataset:{},hidden:false,querySelector:()=>slot,querySelectorAll:()=>[],addEventListener(){}};
  const item={areaLabel:'84',locationScore:{score:50}};
  await loadCandidateReportSheet(sheet,item);await Promise.resolve();
  assert.equal(slot.innerHTML,'price:2;score:77',entry);
 }
 assert.equal(synced,2);assert.equal(refreshed,2);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
