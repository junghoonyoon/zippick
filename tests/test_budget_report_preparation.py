"""Only prepared candidate reports can open; list interactions stay available."""
from test_report_loading import CORE, HARNESS, run_js

BUTTONS = ['budgetCandidateReportReady', 'budgetCandidateReportButtonState',
           'candidateReportActionHtml', 'budgetReportMessageHtml']
QUEUE = ['budgetReportRowIsCurrent', 'prepareBudgetCandidateReports',
         'drainBudgetReportQueue', 'canOpenBudgetCandidateReport']


def test_candidate_buttons_wait_for_final_scores_and_the_selected_area_report():
    run_js([*BUTTONS, 'zippickReportAreaKey'], r"""
const esc=String,spinnerHtml=()=>'<i>spinner</i>',candidateIdentityKey=i=>i.name;
const zippickTradeAreaScope=i=>({minSqm:i.area,maxSqm:i.area,upperInclusive:true});
let currentBudgetData={candidateScoreDataReady:false,enrichmentPending:true};
const item={name:'남서울힐스테이트',area:59,budgetReportRequired:true};
for(const action of ['data-candidate-detail-open','data-candidate-map-detail-open']) {
 assert.match(candidateReportActionHtml(item,action),/ disabled/);
 assert.match(candidateReportActionHtml(item,action),/분석 준비 중/);
}
currentBudgetData.candidateScoreDataReady=true;
assert.equal(budgetCandidateReportButtonState(item).disabled,true);
item.reportPeerState='ready';item.reportPeerResolvedKey=zippickReportAreaKey(item);
assert.equal(budgetCandidateReportButtonState(item).disabled,false);
assert.equal(budgetCandidateReportButtonState(item).label,'집픽 분석 보기');
item.area=84;
assert.equal(budgetCandidateReportButtonState(item).disabled,true);
item.reportPeerState='error';
assert.deepEqual(budgetCandidateReportButtonState(item),{disabled:true,busy:false,label:'분석 보기 불가',message:'분석 자료를 불러오지 못했어요. 나중에 다시 검색해 주세요.'});
assert.match(candidateReportActionHtml(item,'data-candidate-detail-open'),/ disabled/);
assert.match(budgetReportMessageHtml(item),/분석 자료를 불러오지 못했어요/);
currentBudgetData={candidateScoreDataReady:false,enrichmentPending:false};
assert.equal(budgetCandidateReportButtonState(item).busy,false);
assert.equal(budgetCandidateReportButtonState(item).disabled,true);
// The ordinary apartment-search/map path keeps its existing action.
assert.equal(budgetCandidateReportButtonState({name:'검색 단지'}).label,'집픽 분석 보기');
""")


def test_failed_report_updates_list_and_map_and_clears_message_when_ready():
    run_js([*BUTTONS, 'refreshBudgetReportButton', 'zippickReportAreaKey'], r"""
const esc=String, spinnerHtml=()=>'<i>spinner</i>', candidateIdentityKey=i=>i.name;
const zippickTradeAreaScope=i=>({minSqm:i.area,maxSqm:i.area,upperInclusive:true});
const item={name:'강동리엔파크14단지',area:59,budgetReportRequired:true,reportPeerState:'error'};
const currentBudgetData={candidateScoreDataReady:true};
const buttons=Array.from({length:2},()=>({dataset:{budgetReportKey:item.name},setAttribute(k,v){this[k]=v;}}));
const messages=Array.from({length:2},()=>({dataset:{budgetReportMessage:item.name}}));
const document={querySelectorAll:s=>s==='[data-budget-report-key]'?buttons:messages};
refreshBudgetReportButton(item);
for(const b of buttons){assert.equal(b.disabled,true);assert.equal(b['aria-busy'],'false');assert.equal(b.innerHTML,'분석 보기 불가');}
for(const m of messages){assert.equal(m.hidden,false);assert.match(m.textContent,/나중에 다시 검색/);}
item.reportPeerState='ready';item.reportPeerResolvedKey=zippickReportAreaKey(item);
refreshBudgetReportButton(item);
for(const b of buttons){assert.equal(b.disabled,false);assert.equal(b.innerHTML,'집픽 분석 보기');}
for(const m of messages){assert.equal(m.hidden,true);assert.equal(m.textContent,'');}
""")


def test_visible_reports_are_bounded_deduplicated_and_stale_searches_do_not_update():
    run_js([*CORE, *QUEUE], HARNESS + r"""
const budgetReportQueue=[],budgetReportQueued=new WeakSet();let budgetReportsInFlight=0;
const pending=[],started=[],updated=[];
const fetchAptReport=(name)=>{started.push(name);return new Promise(resolve=>pending.push({name,resolve}));};
const refreshBudgetReportButton=()=>{},refreshMarketInsight=item=>updated.push(item.name);
const rows=['A','B','C','D'].map(name=>({...candidate(name,59),budgetReportRequired:true}));
let currentBudgetData={candidateScoreDataReady:false,candidates:rows};
(async()=>{
 prepareBudgetCandidateReports(rows);assert.equal(started.length,0,'scores must be complete');
 currentBudgetData.candidateScoreDataReady=true;
 prepareBudgetCandidateReports(rows);prepareBudgetCandidateReports(rows);
 assert.deepEqual(started,['A','B'],'at most two requests and no duplicates');
 assert.equal(canOpenBudgetCandidateReport(rows[0]),false);
 pending[0].resolve(response('A',59));await tick();
 assert.deepEqual(started,['A','B','C']);
 assert.equal(canOpenBudgetCandidateReport(rows[0]),true);
 const fresh={...candidate('새 검색',84),budgetReportRequired:true};
 currentBudgetData={candidateScoreDataReady:true,candidates:[fresh]};
 prepareBudgetCandidateReports([fresh]);
 pending[1].resolve(response('B',59));await tick();
 assert.deepEqual(started,['A','B','C','새 검색'],'old queued D must be skipped');
 pending[2].resolve(response('C',59));pending[3].resolve(response('새 검색',84));await tick();
 assert.deepEqual(updated,['A','새 검색'],'old completion cannot update the current cards');
 assert.equal(budgetReportsInFlight,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_failed_preparation_retries_without_opening_partial_report():
    run_js([*CORE,*QUEUE,'budgetCandidateReportButtonState'], HARNESS + r"""
const budgetReportQueue=[],budgetReportQueued=new WeakSet();let budgetReportsInFlight=0;
const refreshBudgetReportButton=()=>{},refreshMarketInsight=()=>{};
const item={...candidate('재시도 단지',59),budgetReportRequired:true};
let currentBudgetData={candidateScoreDataReady:true,candidates:[item]},calls=0,searches=0;
const loadBudgetCandidates=async()=>{searches++;};
const fetchAptReport=async()=>{if(++calls===1)throw new Error('offline');return response(item.name,59);};
(async()=>{
 prepareBudgetCandidateReports([item]);await tick();
 assert.equal(item.reportPeerState,'error');
 assert.equal(budgetCandidateReportButtonState(item).busy,false);
 prepareBudgetCandidateReports([item]);await tick();assert.equal(calls,1,'no endless auto-retry');
 assert.equal(canOpenBudgetCandidateReport(item),false);
 await tick();assert.equal(calls,2);assert.equal(canOpenBudgetCandidateReport(item),true);
 currentBudgetData={candidateScoreDataReady:false,enrichmentPending:false,candidates:[item]};
 assert.equal(canOpenBudgetCandidateReport(item),false);assert.equal(searches,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_completed_report_updates_visible_score_before_the_button_unlocks():
    run_js(['refreshMarketInsight'], r"""
const item={name:'단지',locationScore:{score:66}};
const badge={outerHTML:'old score 67'};
const card={dataset:{candidateKey:'단지'},querySelector:selector=>selector==='.candidate-score-badges'?badge:null};
const currentBudgetData={},candidateListMode='all',candidateViewMode='list';
const budgetResultEl={querySelectorAll:()=>[card]};
const candidateIdentityKey=i=>i.name;
const candidateTopScoreBadgesHtml=i=>`score ${i.locationScore.score}`;
refreshMarketInsight(item);
assert.equal(badge.outerHTML,'score 66');
""")


def test_score_refresh_name_spacing_keeps_the_report_button_bound_to_its_area():
    run_js(['parcelIdentityKey','candidateIdentityKey','candidateRowsForLookup',
            'refreshLocationScoreSheet','budgetCandidateReportReady',
            'canOpenBudgetCandidateReport','setCandidateDetailOpen'], r"""
const candidateDisplayName=i=>i.displayName||i.name;
const item={name:'휘경해모로프레스티지',displayName:'휘경해모로프레스티지',
 apartmentId:'11230120401250',region:'동대문구',legalDong:'휘경동',jibun:'375',
 areaLabel:'전용 59~60㎡',budgetReportRequired:true,reportPeerState:'ready',locationScore:{score:76}};
const zippickReportAreaKey=i=>`${i.apartmentId}:${i.areaLabel}`;
item.reportPeerResolvedKey=zippickReportAreaKey(item);
const currentBudgetData={candidates:[item],allCandidates:[item],candidateScoreDataReady:true};
const currentAptSearchItems=[],currentAptSearchRivalItems=[],aptCandidateResults=new Map();
const candidateMapEntries=[],candidateMapLocatedEntries=[{item}];
const originalKey=candidateIdentityKey(item),candidateMapSelectedKey=originalKey;
const selectedCandidateNames=new Set([originalKey]);
const trigger={setAttribute(){}};
const card={dataset:{candidateKey:originalKey},querySelector:()=>trigger};
const sheet={hidden:true,closest:()=>card,setAttribute(){},querySelector:()=>null};
const budgetResultEl={querySelectorAll:()=>[sheet]};
const sameCandidateScoreIdentity=(a,b)=>a.apartmentId===b.apartmentId&&a.areaLabel===b.areaLabel;
const locationScoreRefreshPayload=i=>i;
const locationScoreSheetRequest=0,locationScoreSheet={hidden:true};
const getJson=async()=>({candidate:{...item,name:'완전히 다른 공식 별칭',locationScore:{score:73}}});
const repaintCandidateScoreBadges=()=>{},syncCandidateReportScores=()=>{};
const ensureZippickDevelopmentInsight=()=>{},ensureCandidateCommuteProfile=()=>{};
const scheduleZippickReportMaps=()=>{},syncCandidateDetailScrollLock=()=>{};
let openedItem;
const loadCandidateReportSheet=(s,i)=>{openedItem=i;};
(async()=>{
 await refreshLocationScoreSheet(item,null,{force:true});
 assert.equal(item.name,'완전히 다른 공식 별칭');
 assert.equal(item.locationScore.score,73);
 // The button uses the same lookup as the actual delegated click handler.
 const clicked=candidateRowsForLookup().find(row=>candidateIdentityKey(row)===card.dataset.candidateKey);
 assert.equal(clicked,item,'score refresh detached the visible report button');
 assert.equal(canOpenBudgetCandidateReport(clicked),true);
 setCandidateDetailOpen(sheet,true);
 assert.equal(sheet.hidden,false);assert.equal(openedItem,item);
 assert.equal(candidateMapLocatedEntries.find(entry=>candidateIdentityKey(entry.item)===candidateMapSelectedKey).item,item);
 assert.ok(selectedCandidateNames.has(candidateIdentityKey(item)));
 for(const patch of [{apartmentId:'other'},{region:'중랑구'},{legalDong:'이문동'},{jibun:'376'},
  {kaptCode:'other'},{complexNo:'other'},{areaLabel:'전용 84~85㎡'}])
  assert.notEqual(candidateIdentityKey({...item,...patch}),originalKey);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_saved_comparison_keys_keep_all_identity_fields_when_name_spacing_changes():
    run_js(['parcelIdentityKey','candidateIdentityKey','restoredCandidateIdentityKey'], r"""
const candidateDisplayName=i=>i.name||'';
const item={apartmentId:'11230120401250',name:'휘경 해모로 프레스티지',region:'동대문구',
 legalDong:'휘경동',jibun:'375',areaLabel:'전용 59~60㎡'};
const previous=encodeURIComponent([item.apartmentId,'','',item.region,item.name,item.legalDong,item.jibun,item.areaLabel].join('\u001f'));
const restored=restoredCandidateIdentityKey(previous);
assert.equal(restored,candidateIdentityKey(item));
assert.equal(restoredCandidateIdentityKey(restored),restored);
const fields=decodeURIComponent(restored).split('\u001f');
assert.equal(fields[0],item.apartmentId);assert.equal(fields[3],item.region);
assert.equal(fields[5],item.legalDong);assert.equal(fields[6],item.jibun);assert.equal(fields[7],item.areaLabel);
for(const text of ['legacy apartment name','%invalid',''])assert.equal(restoredCandidateIdentityKey(text),text);
""")
