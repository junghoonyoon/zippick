"""Real report rendering states: a stage, construction conclusion and limits."""
import json
from pathlib import Path

from test_reconstruction_frontend import HARNESS, NAMES, run_js

STAGES = json.loads((Path(__file__).resolve().parents[1] / 'data/apartment_development_policy.json').read_text())['stages']
FUNCTIONS = NAMES + ['zippickReconstructionConclusion','zippickReconstructionReportHtml',
                     'zippickDevelopmentHtml','zippickDevelopmentRatingView','zippickSectionRatingHtml','zippickVerdictTitle']
SETUP = HARNESS + 'const ZIPPICK_DEVELOPMENT_STAGE_RATINGS=' + json.dumps(STAGES, ensure_ascii=False) + ';' + r'''
const zippickSectionRatingData=(item,label)=>zippickDevelopmentRatingView(item);
const condition=(direction='favorable',kind='project_plan')=>({version:'reconstruction-feasibility-v1',
 status:'conditional',direction,basisKind:kind,headline:'건축 조건 판단',reason:'주택을 더 지을 여지가 있어요.',
 scopeNote:'단지 전체에 적용할 수 있는지는 아직 확인되지 않았어요.',
 financialLimitation:'공사비와 분양 수입이 없어 실제 수익성과 분담금은 판단할 수 없어요.',
 comparison:{currentFloorAreaRatio:160,referenceFloorAreaRatio:250}});
const own=(patch={})=>({version:'apartment-development-v1',apartmentId:item.apartmentId,
 identity:{legalDong:item.legalDong,jibun:item.jibun},status:'confirmed',
 projects:[{projectTypeLabel:'재건축'}],rating:{state:'ready',sourceStage:'추진위원회승인',
 sourceUrl:'https://www.gg.go.kr/official',sourceDate:'2026-09-30'},...patch});
const plan={status:'ready',apartmentId:item.apartmentId,identityMatch:'district_dong_parcel_and_name',
 stageLabel:'추진위원회승인',sourceDate:'2026-09-30',plannedFloorAreaRatio:250,sourceLabel:'경기도 정비사업 추진현황',
 sourceUrl:'https://www.gg.go.kr/official'};
'''


def test_unconfirmed_young_complex_explains_why_without_gray_stars_or_a_hold():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own({status:'not_applicable',projects:[],rating:null})};
item.reconstructionConditions=model({grade:'not_assessed',profile:{approvedAt:'20160615'},projectPlan:{status:'not_found'}});
const html=zippickDevelopmentHtml(item)+zippickSectionRatingHtml(item,'단지 변화');
assert.match(html,/재건축 추진이 확인되지 않았어요/);assert.doesNotMatch(html,/사업성에 유리/);
assert.match(html,/추진 미확인/);assert.doesNotMatch(html,/★★★★★|평가 보류|사업성에 유리/);
assert.equal(zippickVerdictTitle(item,{common:true,title:'기존 매수 판단'}),'기존 매수 판단');
''')


def test_confirmed_project_displays_stage_direction_evidence_and_uncertainty_first():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own()};
for(const [direction,text] of [['favorable','유리한 건축 조건'],['limited','늘릴 여지가 작아요'],['unfavorable','불리한 건축 조건']]) {
 item.reconstructionConditions=model({feasibility:condition(direction),projectPlan:plan});
 const html=zippickDevelopmentHtml(item);
 assert.ok(html.includes(text));assert.match(html,/재건축은 초기/);assert.match(html,/추진위원회/);
 assert.match(html,/160%/);assert.match(html,/계획 용적률/);assert.match(html,/250%/);assert.match(html,/같은 눈금/);
 assert.match(html,/실제 수익성/);assert.match(html,/분담금은 판단할 수 없어요/);
 assert.ok(html.indexOf(text)<html.indexOf('건축 수치와 공식 자료 보기'));
 assert.ok(zippickVerdictTitle(item,{common:true,title:'매수 판단'}).includes(text));
}
''')


def test_unconfirmed_old_building_can_explain_conditional_headroom_without_inventing_a_stage():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own({status:'not_found',projects:[],rating:null})};
item.reconstructionConditions=model({feasibility:condition('favorable','parcel_ordinance'),projectPlan:{status:'not_found'}});
const html=zippickDevelopmentHtml(item)+zippickSectionRatingHtml(item,'단지 변화');
assert.match(html,/재건축 추진은 미확인/);assert.match(html,/조례 기준이 적용되면/);
assert.match(html,/사업성에 유리한 건축 조건/);assert.match(html,/단지 전체에 적용/);
assert.doesNotMatch(html,/재건축은 초기|★★★★★|평가 보류/);
''')


def test_matching_plan_provides_the_stage_after_collection_without_waiting_for_an_old_card_cache():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own({status:'not_found',projects:[],rating:null})};
item.reconstructionConditions=model({feasibility:condition(),projectPlan:plan});
const c=zippickReconstructionConclusion(item);
assert.equal(c.confirmed,true);assert.equal(c.stage.points,2.5);
assert.equal(zippickDevelopmentRatingView(item).scoreText,'2.5/5');
''')


def test_published_phase_does_not_claim_a_completed_permit_or_award_stars():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own({rating:null})};
item.reconstructionConditions=model({feasibility:condition(),projectPlan:{...plan,stageLabel:'사업시행'}});
const html=zippickDevelopmentHtml(item)+zippickSectionRatingHtml(item,'단지 변화');
assert.match(html,/사업시행/);assert.doesNotMatch(html,/사업시행 인가|사업시행인가|★★★★★|평가 보류/);
''')


def test_missing_stale_and_failed_sources_never_keep_a_favorable_title():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own()};
for(const status of ['stale','connection_error','loading']) {
 item.reconstructionConditions=model({status,feasibility:condition()});
 const title=zippickVerdictTitle(item,{common:true,title:'매수 판단'});
 assert.doesNotMatch(title,/유리한/);
 assert.match(title,status==='loading'?/수집하고 있어요/:/판단할 수 없어요/);
}
item.reconstructionConditions=model({feasibility:{...condition(),status:'unknown',direction:'unknown'}});
assert.match(zippickDevelopmentHtml(item),/사업성은 자료가 부족/);
''')


def test_other_apartment_or_remodeling_evidence_cannot_override_this_reconstruction():
    run_js(FUNCTIONS, SETUP + r'''
item.futureTransformation={ownDevelopment:own({apartmentId:'another',projects:[{projectTypeLabel:'리모델링'}]})};
item.reconstructionConditions=model({feasibility:condition(),projectPlan:plan});
assert.equal(zippickReconstructionConclusion(item).confirmed,true);
item.futureTransformation={ownDevelopment:own({projects:[{projectTypeLabel:'리모델링'}]})};
assert.equal(zippickReconstructionConclusion(item),null);
''')



def test_visual_report_has_one_insight_and_keeps_failed_sources_retryable():
    run_js(FUNCTIONS, SETUP + r"""
item.futureTransformation={ownDevelopment:own({status:'not_found',projects:[],rating:null})};
item.reconstructionConditions=model({status:'reference_partial',grade:'not_assessed',projectPlan:{status:'not_found'}});
let html=zippickReconstructionReportHtml(item);
assert.match(html,/<h5>현재 건축 규모는 확인됐지만,[^<]*아직 알 수 없어요<\/h5>/);
assert.equal((html.match(/<h5>/g)||[]).length,1);
assert.match(html,/zpr-density-units/);assert.match(html,/zpr-coverage-track/);
assert.match(html,/건축 수치와 공식 자료 보기/);
for(const status of ['stale','connection_error']){
 item.reconstructionConditions.status=status;
 html=zippickReconstructionReportHtml(item);
 assert.match(html,/건축 자료를 확인하지 못해/);assert.match(html,/data-reconstruction-retry/);
 assert.doesNotMatch(html,/<h5>현재 건축 규모는 확인됐지만/);
}
""")



def test_stage_date_and_link_never_come_from_another_stage_source():
    run_js(FUNCTIONS, SETUP + r"""
item.futureTransformation={ownDevelopment:own({rating:{state:'ready',sourceStage:'추진위원회승인',checkedAt:'2026-10-20'}})};
item.reconstructionConditions=model({projectPlan:{...plan,stageLabel:'구역지정',stageAsOf:'2026-06-04'}});
const c=zippickReconstructionConclusion(item);
assert.equal(c.stage.sourceStage,'추진위원회승인');
assert.equal(c.stage.sourceDate,undefined);assert.equal(c.stage.sourceUrl,undefined);
assert.match(c.stageLine,/확인일 2026-10-20/);assert.doesNotMatch(c.stageLine,/2026-06-04|자료 기준/);
item.futureTransformation={ownDevelopment:own({status:'not_found',rating:null,projects:[]})};
const fallback=zippickReconstructionConclusion(item);
assert.equal(fallback.stage.sourceStage,'구역지정');assert.equal(fallback.stage.sourceDate,'2026-06-04');
assert.equal(fallback.stage.sourceUrl,plan.sourceUrl);
""")
