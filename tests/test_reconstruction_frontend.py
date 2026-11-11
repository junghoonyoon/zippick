import os
from pathlib import Path
import re, shutil, subprocess
import pytest
HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='Node required')

def run_js(names, script):
    source = HTML.read_text()
    functions = [re.search(r'^    (?:async )?function '+name+r'\([^\n]*\) \{.*?^    \}', source, re.M | re.S).group() for name in names]
    result = subprocess.run(['node'], input="const assert=require('node:assert/strict');\n"+'\n'.join(functions)+'\n'+script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

"""Render the real report helpers and exercise async identity/area transitions."""
import json


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
item.reconstructionConditions=model({projectPlan:{status:'ready',apartmentId:item.apartmentId,
 identityMatch:'district_dong_parcel_and_name',projectName:'예시3단지',stageLabel:'구역지정',
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



def test_missing_register_displays_the_actual_query_result_instead_of_hiding_it_behind_feasibility():
    run_js(NAMES, HARNESS + r'''
item.reconstructionConditions=model({status:'no_records',profile:{},
 heading:'재건축 여건은 자료가 부족해 판단할 수 없어요',
 reason:'이 주소의 단지 전체 건축물대장 조회 결과가 없어요.',
 feasibility:{version:'reconstruction-feasibility-v1',status:'unknown',
 headline:'사업성은 자료가 부족해 판단할 수 없어요',reason:'현재 용적률을 확인하지 못했어요.',
 financialLimitation:'실제 수익성은 별도로 확인해야 해요.'}});
const html=zippickReconstructionHtml(item);
assert.match(html,/단지 전체 건축물대장 조회 결과가 없어요/);
assert.doesNotMatch(html,/현재 용적률을 확인하지 못했어요/);
assert.doesNotMatch(html,/0%|NaN|role="status"/);
''')
