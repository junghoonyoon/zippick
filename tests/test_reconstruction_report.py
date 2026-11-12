"""Render the real report helpers and exercise async identity/area transitions."""
import json

from test_report_loading import run_js
from test_common_purchase_verdict import run

NAMES = ["zippickOwnDevelopmentModel", "zippickReconstructionModel", "zippickReconstructionFeasibility", "zippickReconstructionHtml", "refreshZippickReconstruction"]
HARNESS = """
const esc=value=>String(value).replaceAll('<','&lt;'), spinnerHtml=()=>'<span>loading</span>';
const item={apartmentId:'complex-3',name:'예시3단지',legalDong:'월계동',jibun:'320-11',areaLabel:'59'};
const model=(patch={})=>({version:'reconstruction-conditions-v1',apartmentId:item.apartmentId,
 identity:{legalDong:item.legalDong,jibun:item.jibun},status:'basis_missing',grade:'unknown',
 heading:'현재 용적률은 확인됐지만 늘릴 수 있는 규모는 아직 판단할 수 없어요',reason:'적용 기준 미확인',
 limitation:'용적률만으로 수익을 확정할 수 없어요.',summary:'',
 profile:{scope:'whole_registered_site',floorAreaRatio:160,buildingCoverageRatio:18,landAreaSqm:40000,
 sourceUrl:'https://www.data.go.kr/data/15134735/openapi.do',fetchedAt:'2026-11-11'},...patch});
const rows=[item,{...item,areaLabel:'84'},{...item,apartmentId:'complex-2',jibun:'320-9'}];
const candidateRowsForLookup=()=>rows;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
"""


def test_rendered_current_values_unknown_limit_and_retry_states():
    run_js(NAMES, HARNESS + """
item.reconstructionConditions=model();
let html=zippickReconstructionHtml(item);
assert.match(html,/160%/);assert.match(html,/18%/);assert.match(html,/40,000㎡/);
assert.doesNotMatch(html,/300%|재건축 확정|가능성.*[0-9]+%/);
for(const status of ['not_collected','connection_error','stale']){
 item.reconstructionConditions=model({status});
 assert.match(zippickReconstructionHtml(item),/data-reconstruction-retry/);
}
item.reconstructionConditions=model({status:'loading'});
assert.match(zippickReconstructionHtml(item),/role="status"/);
item.reconstructionConditions=model({apartmentId:'other'});assert.equal(zippickReconstructionHtml(item),'');
item.reconstructionConditions=model({identity:{legalDong:'월계동',jibun:'320-9'}});assert.equal(zippickReconstructionHtml(item),'');
""")


def test_rendered_parcel_ordinance_and_district_plan_are_not_shown_as_an_approved_project():
    run_js(NAMES, HARNESS + """
item.reconstructionConditions=model({status:'reference',grade:'reference',differencePp:90,
 heading:'현재 용적률은 대표 지번의 조례 기준보다 낮아요',
 planningReference:{floorAreaRatio:250,buildingCoverageRatio:50,districtPlanName:'월계3택지',
 sourceUrl:'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp',
 districtPlanUrl:'https://www.nowon.kr/plan',checkedAt:'2026-11-11'}});
const html=zippickReconstructionHtml(item);
for(const expected of ['대표 지번 조례 용적률','250%','조례 기준과 단순 차이','90%p',
 '대표 지번 조례 건폐율','50%','월계3택지','토지이음 조례 기준','지구단위계획 자료']) assert.ok(html.includes(expected));
assert.doesNotMatch(html,/공식 정비계획|재건축 확정|세대수 증가/);
""")


def test_auto_parcel_reference_never_displays_an_unverified_gap():
    run_js(NAMES, HARNESS + """
item.reconstructionConditions=model({status:'reference_partial',grade:'reference',
 heading:'대표 지번의 용도지역과 조례 기준을 확인했어요',
 planningReference:{kind:'parcel_zoning',floorAreaRatio:250,buildingCoverageRatio:50,
 districtPlanName:'월계3택지',sourceUrl:'https://www.eum.go.kr/',
 ordinanceSourceUrl:'https://www.law.go.kr/ordinInfoP.do',checkedAt:'2026-11-11'}});
const html=zippickReconstructionHtml(item);
assert.match(html,/250%/);assert.match(html,/50%/);assert.match(html,/도시계획 조례/);
assert.doesNotMatch(html,/단순 차이|NaN|[0-9]+%p/);
item.reconstructionConditions=model({status:'not_collected',profile:{},
 planningReference:{kind:'parcel_zoning',zoneName:'제3종일반주거지역',floorAreaRatio:250,
 buildingCoverageRatio:50,sourceUrl:'https://www.eum.go.kr/'}});
const missing=zippickReconstructionHtml(item);assert.match(missing,/대표 지번 용도지역/);
assert.match(missing,/250%/);assert.doesNotMatch(missing,/단순 차이|NaN/);
""")


def test_official_project_plan_displays_its_own_scope_without_implying_an_approved_ceiling():
    run_js(NAMES, HARNESS + """
item.reconstructionConditions=model({projectPlan:{status:'ready',apartmentId:item.apartmentId,identityMatch:'district_dong_parcel_and_name',projectName:'예시3단지',stageLabel:'구역지정',
 stageAsOf:'2026-10-01',plannedFloorAreaRatio:280,plannedBuildingCoverageRatio:25,plannedHouseholds:1000,
 projectAreaSqm:50000,sourceUrl:'https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do'}});
let html=zippickReconstructionHtml(item);
for(const expected of ['계획 용적률','280%','계획 건폐율','25%','계획 세대수','1,000세대',
 '정비사업 범위','50,000㎡','차이를 계산하지 않았어요','서울시 정비사업 자료']) assert.ok(html.includes(expected));
assert.doesNotMatch(html,/일반분양.*확정|사업성.*확정/);
item.reconstructionConditions=model({projectPlan:{status:'ambiguous'}});
html=zippickReconstructionHtml(item);assert.match(html,/사업이 여러 개/);assert.doesNotMatch(html,/계획 용적률/);
""")


def test_collection_updates_all_areas_of_only_the_same_complex():
    run_js(NAMES, HARNESS + """
let calls=0;const getJson=async()=>{calls++;return {reconstructionConditions:model()};};
(async()=>{
 let paints=0;
 for(const area of ['59','84','59']) {item.areaLabel=area;await refreshZippickReconstruction(item,()=>paints++);}
 assert.equal(calls,3);assert.equal(paints,1);
 assert.equal(rows[1].reconstructionConditions.profile.floorAreaRatio,160);
 assert.equal(rows[2].reconstructionConditions,undefined);
 assert.equal(item.areaLabel,'59');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_loading_rechecks_sources_and_finishes_without_a_stuck_spinner():
    run_js(NAMES, HARNESS + """
const normalSetTimeout=global.setTimeout;
global.setTimeout=(fn,ms)=>normalSetTimeout(fn,ms===1500?0:ms);
let calls=0;const getJson=async()=>({reconstructionConditions:++calls===1
 ? model({status:'loading',projectPlan:{status:'not_collected'}})
 : model({status:'reference_partial',projectPlan:{status:'not_found'},planningReference:{kind:'parcel_zoning',
 zoneName:'제3종일반주거지역',floorAreaRatio:250,buildingCoverageRatio:50,sourceUrl:'https://www.eum.go.kr/'}})});
(async()=>{
 let updates=[];await refreshZippickReconstruction(item,()=>updates.push(zippickReconstructionHtml(item)));
 assert.equal(calls,2);assert.match(updates[0],/불러오고 있어요/);
 assert.doesNotMatch(updates[0],/data-reconstruction-retry/);
 assert.equal(item.reconstructionConditions.status,'reference_partial');
 assert.match(updates.at(-1),/250%/);assert.doesNotMatch(updates.at(-1),/role="status"/);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_late_previous_response_cannot_overwrite_new_view_or_newer_source():
    run_js(NAMES, HARNESS + """
const waiting=[];const getJson=()=>new Promise(resolve=>waiting.push(resolve));
(async()=>{
 const old=refreshZippickReconstruction(item);
 item.areaLabel='84';const latest=refreshZippickReconstruction(item);
 waiting[1]({reconstructionConditions:model({sourceRevision:'new'})});await latest;
 waiting[0]({reconstructionConditions:model({sourceRevision:'old'})});await old;
 assert.equal(item.reconstructionConditions.sourceRevision,'new');
 assert.equal(item.areaLabel,'84');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_network_error_ends_loading_preserves_facts_and_can_retry():
    run_js(NAMES, HARNESS + """
item.reconstructionConditions=model();let failed=true;
const getJson=async()=>{if(failed)throw new Error('offline');return {reconstructionConditions:model()};};
(async()=>{
 await refreshZippickReconstruction(item);
 assert.equal(item.reconstructionConditions.status,'stale');
 assert.equal(item.reconstructionConditions.profile.floorAreaRatio,160);
 assert.match(zippickReconstructionHtml(item),/다시 불러오기/);
 failed=false;await refreshZippickReconstruction(item);
 assert.equal(item.reconstructionConditions.status,'basis_missing');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_reconstruction_changes_explanation_but_never_scores_or_price():
    run("""
const item=base();item.apartmentId='example';item.legalDong='월계동';item.jibun='320-11';item.buildingAge=31;
const before=verdict(item);
item.reconstructionConditions={version:'reconstruction-conditions-v1',apartmentId:'example',
 identity:{legalDong:'월계동',jibun:'320-11'},status:'ready',grade:'potential',
 summary:'연식은 약점이지만, 낮은 용적률은 재건축 검토의 강점이에요.'};
const after=verdict(item);
for(const key of ['tone','stars','scores','priceTitle','price','reason']) assert.deepEqual(after[key],before[key]);
assert.match(after.summary,/재건축 검토의 강점/);
item.reconstructionConditions.status='basis_missing';assert.deepEqual(verdict(item),before);
item.reconstructionConditions.status='ready';item.reconstructionConditions.apartmentId='other';assert.deepEqual(verdict(item),before);
item.reconstructionConditions.apartmentId='example';item.reconstructionConditions.status='reference';
item.reconstructionConditions.grade='reference';item.reconstructionConditions.summary='대표 지번의 조례 기준보다 현재 용적률이 낮아요.';
assert.deepEqual(verdict(item),before);
""", extra=["zippickOwnDevelopmentModel", "zippickReconstructionModel", "zippickReconstructionFeasibility", "zippickReconstructionVerdictCopy"])


def test_building_facts_become_readable_insights_without_inventing_capacity():
    run_js(NAMES, HARNESS + r'''
item.reconstructionConditions=model({status:'reference_partial',grade:'not_assessed',
 heading:'현재 건축 규모와 대표 지번 기준을 확인했어요',
 profile:{scope:'whole_registered_site',floorAreaRatio:253.69,buildingCoverageRatio:25.76,
   landAreaSqm:11112,households:299,sourceUrl:'https://www.data.go.kr/data/15134735/openapi.do'},
 planningReference:{kind:'parcel_zoning',zoneName:'제3종일반주거지역(2020-12-31)',
   districtPlanName:'지구단위계획구역',sourceUrl:'https://www.eum.go.kr/'},
 projectPlan:{status:'not_found'},
 feasibility:{version:'reconstruction-feasibility-v1',status:'not_assessed',
   financialLimitation:'공사비와 분양 수입은 확인되지 않았어요.'}});
const before=JSON.stringify(item.reconstructionConditions);
const html=zippickReconstructionHtml(item);
assert.match(html,/<h6>재건축으로 더 지을 수 있는지는 아직 판단할 수 없어요<\/h6>/);
assert.match(html,/적용할 용적률 한도를 확인하지 못해/);
assert.match(html,/땅 넓이의 약 <b>2.54배<\/b>/);
assert.match(html,/땅 100㎡ 중 약 <b>25.8㎡<\/b>를 건물이 차지/);
assert.match(html,/지하층 등은 제외/);
assert.match(html,/세부 건축 기준/);
assert.match(html,/다른 자료에는 있을 수 있어요/);
// Raw facts, their original order, and the official sources remain available.
const facts=['253.69%','25.76%','11,112㎡','299세대','제3종일반주거지역(2020-12-31)','지구단위계획구역'];
let previous=-1;
for(const value of facts){const pos=html.indexOf(value);assert.ok(pos>previous,value);previous=pos;}
assert.match(html,/건축물대장 출처/);assert.match(html,/토지이음 용도지역/);
assert.doesNotMatch(html,/300%|늘릴 수 있어요|사업성에 유리|공원.*74|일반분양.*확정/);
assert.equal(JSON.stringify(item.reconstructionConditions),before,'copy must not change shared facts or scores');
// A parcel-only limit must not silently become a confirmed whole-site comparison.
item.reconstructionConditions.planningReference.floorAreaRatio=300;
const parcel=zippickReconstructionHtml(item);
assert.match(parcel,/단지 전체에 적용할 재건축 기준은 확인되지/);
assert.doesNotMatch(parcel,/46.31|단순 차이|사업성에 유리/);
''')


def test_insight_copy_keeps_connection_loading_and_missing_states_distinct():
    run_js(NAMES, HARNESS + r'''
for(const status of ['stale','connection_error','invalid_source','access_denied','loading']) {
 item.reconstructionConditions=model({status,heading:'원본 자료 연결 상태',reason:'원본 연결에 실패했어요'});
 const html=zippickReconstructionHtml(item);
 assert.match(html,/<h6>원본 자료 연결 상태<\/h6>/);
 assert.match(html,/원본 연결에 실패했어요/);
 assert.doesNotMatch(html,/적용할 용적률 한도를 확인하지 못해/);
 if(status==='loading') {assert.match(html,/role="status"/);assert.doesNotMatch(html,/data-reconstruction-retry/);}
 else {assert.match(html,/data-reconstruction-retry/);assert.doesNotMatch(html,/role="status"/);}
}
for(const value of [null,undefined,0,-1,'NaN','Infinity']) {
 item.reconstructionConditions=model({profile:{scope:'whole_registered_site',floorAreaRatio:value,buildingCoverageRatio:value}});
 const html=zippickReconstructionHtml(item);
 assert.doesNotMatch(html,/땅 넓이의 약|땅 100㎡ 중|NaN|Infinity/);
}
item.reconstructionConditions=model({profile:{scope:'single_building',floorAreaRatio:253.69,buildingCoverageRatio:25.76}});
assert.doesNotMatch(zippickReconstructionHtml(item),/땅 넓이의 약|땅 100㎡ 중/);
''')


def test_remodeling_keeps_current_building_facts_without_reconstruction_claims():
    run_js(NAMES, HARNESS + r'''
item.futureTransformation={ownDevelopment:{version:'apartment-development-v1',apartmentId:item.apartmentId,
 identity:{legalDong:item.legalDong,jibun:item.jibun},status:'confirmed',projects:[{projectTypeLabel:'리모델링'}],
 rating:{projectType:'remodeling',state:'ready',sourceStage:'도시계획심의'}}};
item.reconstructionConditions=model({status:'reference_partial',projectPlan:{status:'not_found'}});
const before=JSON.stringify(item),html=zippickReconstructionHtml(item);
assert.match(html,/현재 건물의 규모를 확인했어요/);
assert.match(html,/160%/);assert.match(html,/18%/);assert.match(html,/40,000㎡/);
assert.match(html,/리모델링 후 늘어날 면적이나 추가분담금을 뜻하지 않아요/);
assert.doesNotMatch(html,/재건축|사업성에 유리/);
assert.equal(JSON.stringify(item),before);
''')
