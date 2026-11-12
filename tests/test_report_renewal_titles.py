"""Own renewal evidence changes report wording, never scores or section order."""
import re

import pytest

from test_common_purchase_verdict import HTML, run


DEVELOPMENT_FUNCTIONS = [
    'zippickDevelopmentArticleSignalAllowed', 'zippickOwnDevelopmentNewsAllowed',
    'zippickValidatedNewsBundle', 'zippickDevelopmentEvidenceText',
    'zippickDevelopmentExclusionText', 'zippickDevelopmentRows',
    'zippickConfirmedOwnDevelopmentRow', 'zippickOwnDevelopmentProgressRow',
    'zippickOwnDevelopmentRows', 'zippickOwnDevelopmentModel', 'zippickOwnDevelopmentZones',
    'zippickConfirmedOwnDevelopmentRows', 'zippickDevelopmentStageTier',
    'zippickDevelopmentProjectWord', 'zippickDevelopmentPolicyKind', 'zippickDevelopmentRatingView',
    'zippickDevelopmentCompletedOfficialZone', 'zippickActiveOfficialDevelopmentZones',
    'zippickDevelopmentIdentityKeys', 'zippickDevelopmentOfficialZoneSelfMatch',
    'zippickDevelopmentRatingBasisHtml', 'zippickDevelopmentHtml', 'zippickLocationHeading',
    'zippickReconstructionModel', 'zippickReconstructionFeasibility',
    'zippickReconstructionHtml', 'zippickReconstructionVerdictCopy',
    'zippickReconstructionConclusion', 'zippickReconstructionReportHtml',
]


def renewal_run(script):
    source = HTML.read_text()
    constants = re.findall(r'^    const ZIPPICK_(?:DEVELOPMENT_PATTERN|DEVELOPMENT_EXCLUDED_PATTERN|MINIMUM_ARTICLE_RECONSTRUCTION_AGE|OWN_DEVELOPMENT_BOUNDARY_TOLERANCE_METERS) = .*?;', source, re.M)
    constants.append(re.search(r'    const ZIPPICK_DEVELOPMENT_STAGE_RATINGS = \[.*?\n    \];', source, re.S).group())
    constants.append(re.search(r'    const ZIPPICK_RECONSTRUCTION_STAGE_RATINGS = \[.*?\n    \];', source, re.S).group())
    constants.append(re.search(r'    const ZIPPICK_REMODELING_STAGE_RATINGS = \[.*?\n    \];', source, re.S).group())
    fixture = r'''
const esc=String, compactText=value=>String(value||'').replace(/\s+/g,''), candidateDisplayName=item=>item.name;
const zpJosa=(word,a,b)=>word+a, zippickDevelopmentDistanceText=()=>'', zippickDevelopmentOfficialType=String;
const candidateNewsSourceLabel=()=>'', zippickDevelopmentBadge=()=>'';
function oldApartment(){
 const item=base();
 Object.assign(item,{apartmentId:'11350100002615',name:'검증아파트',province:'서울특별시',
  district:'노원구',region:'노원구',legalDong:'월계동',jibun:'12',buildingAge:39,households:910});
 item.locationScore.parts[1].details[1].score=15;
 item.locationScore.parts[0].details[0].reason='광운대역 경춘선 · 직선 347m';
 item.locationScore.parts[0].details[1].reason='서울녹천초등학교 · 261m 거리';
 return item;
}
function attach(item, word='재건축', stage='추진위원회승인'){
 const projectType=word==='리모델링'?'remodeling':'reconstruction';
 const rating=(projectType==='remodeling'?ZIPPICK_REMODELING_STAGE_RATINGS:ZIPPICK_RECONSTRUCTION_STAGE_RATINGS).find(row=>row.stages.includes(stage));
 const own={version:'apartment-development-v1',apartmentId:item.apartmentId,status:'confirmed',
  identity:{province:item.province,district:item.district,legalDong:item.legalDong,jibun:item.jibun},
  projects:[{name:`검증아파트 ${word}`,projectTypeLabel:word,stageLabel:stage,sourceUrl:'https://cleanup.seoul.go.kr/test'}],
  rating:rating?{state:'ready',sourceStage:stage,stageLabel:rating.label,points:rating.points,
   scoreText:`${rating.points.toFixed(1)}/5`,checkedAt:'2026-10-20',projectType,version:'own-development-stage-v3'}
   :{state:'missing',points:null,projectType,version:'own-development-stage-v3'}};
 item.futureTransformation={apartmentId:item.apartmentId,ownDevelopment:own};
 return item;
}
function calculation(v){
 const {reviewHeadline,title,summary,summaryFactors,ownDevelopmentCopy,propertyHeading,...rest}=v;
 return rest;
}
'''
    run('\n'.join(constants)+fixture+script, extra=DEVELOPMENT_FUNCTIONS)


@pytest.mark.parametrize('word', ['재건축', '리모델링'])
def test_all_stages_reach_headline_summary_and_detail_without_changing_any_calculation(word):
    renewal_run(r'''
const word=WORD;
const stages=word==='리모델링'?['추진위원회승인','조합설립인가','안전진단(1차)',
 '도시계획심의','건축심의','사업계획승인(리모델링허가)','이주','착공']
 :['추진위원회승인','조합설립인가','사업시행인가','관리처분인가','이주','착공'];
for (const shift of [-4,0,4,12]) for (const stage of stages) {
 const item=oldApartment();item.priceComparison.shiftPp=shift;
 const original=verdict(item), originalScores=JSON.stringify(item.locationScore);
 attach(item,word,stage);
 const updated=verdict(item), copy=updated.ownDevelopmentCopy;
 assert.deepEqual(calculation(updated),calculation(original));
 assert.equal(JSON.stringify(item.locationScore),originalScores);
 assert.equal(updated.priceTitle,original.priceTitle);
 assert.ok(updated.reviewHeadline.includes(copy.headline),updated.reviewHeadline);
 assert.ok(updated.summary.includes(copy.detail),updated.summary);
 assert.match(updated.summary,/39년차로 건물은 오래됐/);
 assert.match(updated.summary,/910세대.*광운대역.*347m.*서울녹천초등학교.*261m/);
 assert.ok(zippickLocationHeading(item,updated).includes(copy.detail));
 const section=zippickDevelopmentHtml(item);
 assert.ok(section.includes(`<h5>${copy.sectionHeading}</h5>`));
 if(word==='리모델링') {
  const lead=section.match(/<p class="zpr-insight">(.*?)<\/p>/s)[1];
  assert.doesNotMatch(lead,/구역 지정에서 입주까지|관리처분 이후 단계/);
  assert.match(lead,/공사·입주 일정과 추가분담금은 이 자료만으로 알 수 없어요/);
 }
 assert.equal(updated.reviewHeadline.split(/\.\s*/).filter(Boolean).length,2);
 assert.equal(zippickDevelopmentRatingView(item).points,item.futureTransformation.ownDevelopment.rating.points);
}
const remodel=verdict(attach(oldApartment(),'리모델링','사업계획승인(리모델링허가)'));
assert.match(remodel.reviewHeadline,/리모델링 사업계획이 승인됐어요/);
'''.replace('WORD', repr(word)))


def test_missing_price_and_trade_drop_keep_their_original_reason_and_rating():
    renewal_run(r'''
for (const kind of ['missing','trade_drop','missing_property','pending']) {
 const item=oldApartment();
 if(kind==='missing')item.priceComparison.status='insufficient_data';
 if(kind==='trade_drop')item.signals={status:'ok',recentDealCount:3,priorDealCount:20};
 if(kind==='missing_property')item.locationScore.parts=[];
 if(kind==='pending')item.priceComparison.status='pending';
 const before=verdict(item),after=verdict(attach(item));
 assert.deepEqual(calculation(after),calculation(before));
 if(kind==='missing')assert.ok(after.reviewHeadline.startsWith(before.reviewHeadline));
 if(kind==='trade_drop')assert.equal(after.tradeEvidence,before.tradeEvidence);
 if(kind==='missing_property')assert.match(after.summary,/확인할 자료가 부족/);
 if(kind==='pending')assert.equal(after.reviewHeadline,before.reviewHeadline);
}
''')


@pytest.mark.parametrize('word', ['재건축', '리모델링'])
def test_price_comparison_headline_and_renewal_stage_remain_separate(word):
    renewal_run(r'''
const item=oldApartment();item.latestDealPriceEok=12;
item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
const before=verdict(item);
const after=verdict(attach(item,WORD));
assert.equal(before.tone,'conditional');assert.equal(before.stars,3);
assert.deepEqual(calculation(after),calculation(before));
assert.ok(after.reviewHeadline.startsWith(before.reviewHeadline+' '));
assert.ok(after.reviewHeadline.includes(after.ownDevelopmentCopy.headline));
assert.doesNotMatch(after.reviewHeadline,/낮아요, 매수는/);
'''.replace('WORD', repr(word)))


def test_news_only_does_not_become_an_official_approval():
    renewal_run(r'''
for(const word of ['재건축','리모델링']) {
 const item=oldApartment(),before=verdict(item);
 item.relatedNews=[{scope:'complex',status:'confirmed',title:`검증아파트 ${word} 조합설립인가 추진`,
  url:'https://news.example.com/article'}];
 let after=verdict(item);
 assert.equal(after.ownDevelopmentCopy.state,'signal');
 assert.match(after.reviewHeadline,/추진 소식만 있고 공식 단계는 확인되지 않았어요/);
 assert.doesNotMatch(after.summary,/승인받|승인을 받/);
 assert.match(zippickDevelopmentHtml(item),/공식 추진 단계는 아직 확인되지 않았습니다/);
 if(word==='리모델링') assert.doesNotMatch(zippickDevelopmentHtml(item),/재건축 일정/);
 assert.deepEqual(calculation(after),calculation(before));
 attach(item,word);item.futureTransformation.ownDevelopment.status='not_found';
 after=verdict(item);assert.equal(after.ownDevelopmentCopy.state,'signal');
 assert.match(zippickDevelopmentHtml(item),/공식 추진 단계는 아직 확인되지 않았습니다/);
 delete item.futureTransformation;
 item.relatedNews[0].apartmentId='another';assert.equal(zippickOwnDevelopmentCopy(item),null);
 delete item.relatedNews[0].apartmentId;
 item.relatedNews[0].scope='area';assert.equal(zippickOwnDevelopmentCopy(item),null);
 item.relatedNews[0].scope='complex';item.relatedNews[0].title+= ' 취소';
 assert.equal(zippickOwnDevelopmentCopy(item),null);
}
''')


def test_wrong_identity_unavailable_completed_and_unknown_stages_never_become_positive():
    renewal_run(r'''
for(const patch of [own=>own.apartmentId='another',own=>own.identity.jibun='13',
 own=>own.identity.legalDong='다른동',own=>own.identity.district='다른구',
 ...['error','stale','pending','not_found','completed_or_cancelled','not_applicable'].map(status=>own=>own.status=status)]) {
 const item=oldApartment(),before=verdict(item);attach(item);patch(item.futureTransformation.ownDevelopment);
 assert.deepEqual(verdict(item),before);
}
for(const stage of ['조합설립인가 신청','사업계획승인 예정','알수없음']) {
 const item=attach(oldApartment(),'리모델링',stage),result=verdict(item);
 assert.equal(result.ownDevelopmentCopy.state,'unknown');
 assert.match(result.reviewHeadline,/공식 추진 단계는 확인되지 않았어요/);
 assert.doesNotMatch(result.summary,/승인받|승인을 받|계획이 승인됐/);
}
const young=attach(oldApartment());young.buildYear=new Date().getFullYear()-5;
assert.equal(zippickOwnDevelopmentCopy(young),null);
const mismatched=attach(oldApartment());mismatched.futureTransformation.apartmentId='another';
assert.equal(zippickOwnDevelopmentCopy(mismatched),null);
''')


def test_reentry_and_area_switch_recompute_copy_without_mutating_the_item():
    renewal_run(r'''
const item=attach(oldApartment()),saved=JSON.stringify(item);
for(const area of ['59.49㎡','84.98㎡','59.49㎡']) {
 const selected={...item,areaLabel:area};
 assert.match(verdict(selected).summary,/재건축 추진위원회 승인을 받았지만.*초기.*절차/);
}
assert.equal(JSON.stringify(item),saved);
item.futureTransformation.ownDevelopment.status='completed_or_cancelled';
assert.doesNotMatch(verdict(item).reviewHeadline,/재건축/);
''')


def test_forming_a_committee_or_reviewing_a_plan_does_not_claim_approval():
    renewal_run(r'''
for(const stage of ['추진위구성','추진위원회구성','조합설립','건축심의','도시계획심의']) {
 const item=attach(oldApartment(),'리모델링',stage),result=verdict(item);
 assert.doesNotMatch(result.summary,/승인|인가/);
 assert.equal(result.ownDevelopmentCopy.state,'confirmed');
}
''')


def test_stage_specific_copy_explains_remaining_uncertainty_without_changing_scores():
    renewal_run(r'''
const cases=[
 {word:'리모델링',stage:'도시계획심의',headline:/심의 단계.*일정.*불확실/,
  detail:/도시계획 심의 단계.*공사·입주 일정.*불확실/,noEarly:true},
 {word:'리모델링',stage:'도시계획위원회심의',headline:/심의 단계.*일정.*불확실/,
  detail:/도시계획 심의 단계.*공사·입주 일정.*불확실/,noEarly:true},
 {word:'리모델링',stage:'건축심의',headline:/심의 단계.*일정.*불확실/,
  detail:/건축심의 단계.*공사·입주 일정.*불확실/,noEarly:true},
 {word:'리모델링',stage:'안전진단(1차)',headline:/안전진단 단계.*일정.*불확실/,
  detail:/1차 안전진단 단계.*공사·입주 일정.*불확실/,noEarly:true},
 {word:'리모델링',stage:'안전진단(1차)통과',headline:/1차 안전진단을 통과했지만.*일정.*불확실/,
  detail:/1차 안전진단을 통과했지만.*공사·입주 일정.*불확실/,noEarly:true},
 {word:'재건축',stage:'안전진단통과',headline:/초기.*일정.*불확실/,
  detail:/안전진단을 통과했지만.*일정.*불확실/},
 {word:'재건축',stage:'추진위원회승인',headline:/초기.*일정.*불확실/,
  detail:/추진위원회 승인을 받았지만.*초기.*절차/},
 {word:'리모델링',stage:'조합설립인가',headline:/조합 설립 인가/,
  detail:/조합 설립을 승인받았지만.*공사까지.*절차/},
 {word:'리모델링',stage:'사업계획승인(리모델링허가)',headline:/사업계획이 승인됐어요/,
  detail:/사업계획이 승인됐지만.*일정.*알 수 없어요/},
 {word:'리모델링',stage:'이주',headline:/이주.*단계/,
  detail:/이주.*단계지만.*입주 시기.*알 수 없어요/},
 {word:'리모델링',stage:'착공',headline:/공사가 진행 중/,
  detail:/공사가 진행 중이지만.*입주 시기.*알 수 없어요/},
];
for(const c of cases){
 const item=oldApartment(),before=verdict(item);attach(item,c.word,c.stage);
 const after=verdict(item),section=zippickDevelopmentHtml(item);
 assert.deepEqual(calculation(after),calculation(before));
 assert.equal(zippickDevelopmentRatingView(item).points,item.futureTransformation.ownDevelopment.rating.points);
 assert.match(after.reviewHeadline,c.headline);
 assert.match(after.summary,c.detail);
 assert.match(zippickLocationHeading(item,after),c.detail);
 assert.ok(section.includes(`<h5>${after.ownDevelopmentCopy.sectionHeading}</h5>`));
 if(c.noEarly){
  assert.doesNotMatch(after.reviewHeadline,/초기/);
  assert.doesNotMatch(after.summary,/초기/);
  assert.doesNotMatch(after.ownDevelopmentCopy.sectionHeading,/초기/);
 }
 if(c.stage==='도시계획심의'){
  assert.match(section,/집픽 점수표 분류: <b>도시계획 심의<\/b>/);
  assert.match(section,/자료 표기: 도시계획심의/);
  assert.match(section,/3\.0\/5/);
  assert.doesNotMatch(section,/후보지·대상지 선정/);
 }
}
''')


def test_same_official_stage_has_type_specific_score_and_old_scores_are_not_reused():
    renewal_run(r'''
for(const [word,expected] of [['재건축',1.5],['리모델링',3.0]]){
 const item=attach(oldApartment(),word,'도시계획심의');
 const rating=zippickDevelopmentRatingView(item);
 assert.equal(rating.points,expected);
 const fallback=oldApartment(),today=new Date().toISOString().slice(0,10);
 fallback.futureTransformation={apartmentId:fallback.apartmentId,subjectZoneReferences:[{
  id:'example',name:'검증아파트',projectTypeLabel:word,stageLabel:'도시계획심의',stage:'planning',
  containsSubject:true,zoneKind:'renewal',businessNameConfirmed:true,districtCode:'11350',
  distanceMeters:0,sourceUrl:'https://data.seoul.go.kr/official',sourceDate:today}]};
 assert.equal(zippickDevelopmentRatingView(fallback).points,expected);
 assert.equal(zippickDevelopmentRatingView(fallback).projectType,rating.projectType);
 const section=zippickDevelopmentHtml(item);
 assert.match(section,new RegExp(`${expected.toFixed(1)}/5`));
 if(word==='리모델링') {
  assert.match(section,/서울시 리모델링 절차 안내/);
  assert.match(section,/<td>도시계획 심의<\/td><td>3\.0 \/ 5<\/td>/);
  assert.doesNotMatch(section,/<td>후보지·대상지 선정<\/td>/);
 }
}
const stale=attach(oldApartment(),'리모델링','도시계획심의');
Object.assign(stale.futureTransformation.ownDevelopment.rating,
 {version:'own-development-stage-v2',points:1.5,stageLabel:'후보지·대상지 선정'});
assert.equal(zippickDevelopmentRatingView(stale).points,null);
assert.match(zippickDevelopmentHtml(stale),/리포트를 닫고 다시 열어 주세요/);
stale.futureTransformation.ownDevelopment.rating.version='own-development-stage-v3';
assert.equal(zippickDevelopmentRatingView(stale).points,null);
assert.equal(zippickDevelopmentRatingView(stale).code,'policy_mismatch');
const conflict=attach(oldApartment(),'리모델링','조합설립인가');
conflict.futureTransformation.ownDevelopment.projects.push({name:'검증아파트 재건축',
 projectTypeLabel:'재건축',stageLabel:'조합설립인가'});
conflict.futureTransformation.ownDevelopment.rating={state:'missing',points:null,
 code:'project_type_conflict',reason:'공식 자료에 서로 다른 사업 종류가 있어 단계별 점수를 매기지 않았어요.'};
const conflictHtml=zippickDevelopmentHtml(conflict);
assert.equal(zippickDevelopmentRatingView(conflict).points,null);
assert.match(conflictHtml,/사업 종류가 서로 달라 단지 변화 점수를 판단할 수 없어요/);
assert.match(conflictHtml,/사업 종류가 확인되면 해당 단계별 점수표를 보여드려요/);
assert.doesNotMatch(conflictHtml,/이 단지가 리모델링 대상입니다/);
''')
