"""Shared purchase conclusions must not turn momentum or personal cash into value."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import pytest

HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='Node required')


def run(script, extra=()):
    source = HTML.read_text()
    names = ['zippickDevelopmentVerdictCopy', 'zippickOwnDevelopmentCopy', 'zippickSynthesisSummary', 'zippickMonthlyDeals', 'zippickLiquidityStat', 'zippickLifestylePlanRating', 'zippickLifestyleChangeRatingData', 'zippickFutureSourceIsOfficial', 'zpNum', 'zippickCommonProperty', 'zippickCommonPurchaseVerdict',
             'zippickLatestTradeDetails', 'zippickBuyBandTradeMatchesArea',
             'zippickTradeAreaScope', 'zippickAreaContains',
             'zippickBuyBandTier', 'zippickValuationMatchesTrade', 'candidateSignalNumber',
             'candidateSignalDataUnavailable', 'candidateLocationScoreNumber', 'zippickBandPriceEvidence', 'zippickPriceComparisonStars', *extra]
    functions = re.findall(r'^    const ZP_LIQ_\w+ = .*?;', source, re.M)
    for name in names:
        match = re.search(r'^    (?:async )?function ' + name + r'\(.*?^    \}', source, re.M | re.S)
        assert match, name
        functions.append(match.group())
    fixture = """
const assert=require('node:assert/strict');
const now=new Date(2026,9,31);
const metric=(key,score)=>({key,score,status:'ok',reason:`${key} 확인`});
function base(){return {
  locationScore:{score:50,parts:[
    {key:'demand',details:[metric('station',80),metric('education',80),metric('commute',0)]},
    {key:'product',details:[metric('households',80),metric('age',80)]},
    {key:'jeonse',details:[metric('jeonse_ratio',0)]}]},
  priceComparison:{status:'ready',method:'usual_gap',shiftPp:-4,averagePriceEok:10,
    transactionCount:12,periodMonths:6,throughMonth:'2026-10',scope:'nearby',lowData:false,
    peers:[{tier:0,lowData:false},{tier:0,lowData:false}]},
  signals:{score:0,momentumPct:-5,recent3Pct:-2,recentDealCount:12,priorDealCount:12}
};}
const verdict=item=>zippickCommonPurchaseVerdict(item,now);
"""
    result = subprocess.run(['node'], input='\n'.join(functions)+fixture+script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_quiet_or_falling_market_can_be_a_purchase_candidate():
    run("""
const item=base();
for(const score of [0,10,44,45,69,70,100,null,undefined]) {
  item.signals.score=score;
  const result=verdict(item);
  assert.equal(result.tone,'yes');
  assert.equal(result.stars,4);
  assert.doesNotMatch(result.reason,/저점|상승.*기대|예산|현금/);
}
const before=verdict(item);item.signals={score:100,momentumPct:20,recent3Pct:10,isAtPeak:true};
assert.equal(verdict(item).reason,before.reason);
""")


def test_private_finance_and_personal_commute_never_change_common_decision():
    run("""
const item=base(), original=verdict(item);
item.policyImpact={cashGapEok:-100,missingInputs:['income']};item.budgetGapEok=-100;
item.jeonseRatioPct=10;item.commuteAccessScore=0;
item.locationScore.score=99;item.locationScore.parts[0].details[2].score=100;
item.locationScore.parts[2].details[0].score=100;
assert.deepEqual(verdict(item),original);
item.policyImpact={cashGapEok:100};assert.deepEqual(verdict(item),original);
""")


def test_price_and_property_are_the_actual_reasons():
    run("""
const item=base();item.signals.score=100;
item.priceComparison.shiftPp=4;
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).reason,/단지 조건은 좋지만.*평소 가격 차이.*비싸요/);
item.locationScore.parts[1].details[1].score=20;
assert.equal(verdict(item).tone,'hold');assert.match(verdict(item).reason,/연식/);
item.priceComparison.shiftPp=0;
assert.equal(verdict(item).tone,'conditional');
for(const part of item.locationScore.parts.slice(0,2)) for(const metric of part.details) metric.score=30;
assert.equal(verdict(item).tone,'hold');assert.doesNotMatch(verdict(item).reason,/흐름.*약|신호.*약/);
""")


@pytest.mark.parametrize('patch', [
    "item.priceComparison.method='simple'", "item.priceComparison.status='error'",
    "item.priceComparison.shiftPp=null", "item.priceComparison.peers=[]",
    "item.priceComparison.throughMonth='2025-12'",
    "item.priceComparison.throughMonth='2027-01'", "item.priceComparison.throughMonth='2026-99'",
])
def test_missing_price_is_distinct_from_a_bad_price(patch):
    run("const item=base();" + patch + """;
const result=verdict(item);
assert.equal(result.tone,'missing');assert.equal(result.stars,null);
assert.match(result.reason,/가격이 적절한지는 판단할 수 없어요/);assert.doesNotMatch(result.reason,/조건.*약|매수가.*불리/);
""")


def test_current_peer_price_uses_one_comparable_without_grading_usual_gap():
    run(r"""
const item=base();
Object.assign(item.priceComparison,{scope:'district',region:'관악구',method:'usual_gap',
 peers:[{name:'비교아파트',tier:1}],peerAveragePriceEok:12.5,differencePct:-20,shiftPp:10});
const result=verdict(item);
assert.match(result.title,/^이 단지의 최근 6개월 평균 거래 가격은 관악구 내 비슷한 단지인 비교아파트보다 20% 싸요\. 평소보다 싼지 비싼지는 자료가 부족해/);
assert.equal(result.stars,null);
Object.assign(item.priceComparison,{method:'simple',shiftPp:null,peerAveragePriceEok:8,differencePct:25});
assert.match(verdict(item).title,/비교아파트보다 25% 비싸요/);
Object.assign(item.priceComparison,{peerAveragePriceEok:10,differencePct:0});
assert.match(verdict(item).title,/비교아파트의 평균 거래 가격과 같아요/);
item.priceComparison.throughMonth='2026-05';
assert.match(verdict(item).title,/평균 거래 가격을 비교할 자료가 부족해요/);
item.priceComparison.throughMonth='2026-10';item.priceIdentityVerified=false;
assert.match(verdict(item).title,/단지 일치가 확인되지 않아/);
assert.doesNotMatch(verdict(item).title,/비교아파트의 평균 거래 가격과 같아요/);
""")

def test_trade_drop_is_observed_and_does_not_mean_price_is_at_the_bottom():
    run("""
const item=base();item.signals={score:99,recentDealCount:9,priorDealCount:20};
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).reason,/최근 6개월 거래가 절반 넘게 줄/);
item.signals.recentDealCount=10;assert.equal(verdict(item).tone,'yes');
item.signals={score:0,recentDealCount:1,priorDealCount:4};assert.equal(verdict(item).tone,'yes');
item.signals={score:0,recentDealCount:null,priorDealCount:20};assert.equal(verdict(item).tradeDrop,false);
""")


def test_price_boundary_matches_comparison_policy():
    run("""
const item=base();
for(const [shift,price,stars] of [[-6,'low',5],[-3.1,'low',4],[-3,'similar',3],[0,'similar',3],[3,'similar',3],[3.1,'high',2],[6,'high',2],[6.1,'high',1]]) {
 item.priceComparison.shiftPp=shift;
 const result=verdict(item);
 assert.equal(result.price,price);assert.equal(result.scores.price,stars);
}
""")


def test_rendered_header_labels_verdict_score_and_keeps_component_stars():
    run(r"""
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const zippickMarketVerdict=()=>({summary:'가격은 내렸고 거래는 비슷해요'});
const zippickBuyBandHtml=()=>'';
const zippickDecisionScoresHtml=()=>'';
const item=base();let result=verdict(item);
const html=zippickDecisionHtml(item,result);
assert.deepEqual(result.scores,{price:4,property:4});
assert.match(html,/zpr-verdict-tag is-yes/);
assert.doesNotMatch(html,/zpr-overall-score|매수 판단 <b>/);
assert.ok(html.indexOf('zpr-verdict-tag')<html.indexOf('zpr-overall-opinion'));
const panels=[...html.matchAll(/<section class="zpr-title zpr-head-panel" aria-label="(.*?) 요약">(.*?)<\/section>/gs)];
assert.deepEqual(panels.map(match=>match[1]),['가격','단지 조건']);
assert.match(panels[0][2],/가격 비교 점수 4\.0\/5/);
assert.match(panels[1][2],/단지 조건 점수 4\.0\/5/);
assert.ok(panels[1][2].includes(result.property.summary));
assert.doesNotMatch(html,/<dl|<details/);
const body=zippickNumberSteps('<span class="zpr-kicker" data-zpr-step="가격 비교"></span><span class="zpr-kicker" data-zpr-step="단지 조건"></span>',item,result.scores);
assert.match(body,/가격 비교 점수 4\.0\/5/);assert.match(body,/단지 조건 점수 4\.0\/5/);
assert.doesNotMatch(html,/예산 안|현금.*부족|조건부로 매수 검토할 만해요/);
item.policyImpact={cashGapEok:-100};assert.equal(zippickDecisionHtml(item,verdict(item)),html);
item.signals={status:'ok',recentDealCount:4,priorDealCount:12};
const sharpDrop=verdict(item);
assert.deepEqual(sharpDrop.scores,result.scores);
assert.match(sharpDrop.reviewHeadline,/거래가 크게 줄어 매수는 신중히 검토하세요/);
assert.match(zippickDecisionHtml(item,sharpDrop),/zpr-verdict-tag is-conditional/);
assert.match(zippickDecisionHtml(item,sharpDrop),/zpr-review-caution.*직전 6개월 12건에서 4건으로 줄었어요/);
assert.doesNotMatch(sharpDrop.summary,/12건에서 4건/);
item.signals.status='error';assert.equal(verdict(item).tradeEvidence,'');
item.priceComparison.method='simple';result=verdict(item);
const incomplete=zippickDecisionHtml(item,result);
assert.deepEqual(result.scores,{price:null,property:4});
assert.match(incomplete,/<h3 class="zpr-overall-opinion">거래 자료가 부족해 매수 여부를 판단하기 어려워요\.<\/h3>/);
assert.doesNotMatch(incomplete.split('<section class="zpr-title zpr-head-panel"')[0],/zpr-overall-score|zpr-section-stars|점수 보류/);
assert.match(incomplete,/별점 보류/);assert.match(incomplete,/단지 조건 점수 4\.0\/5/);
assert.match(incomplete,/비슷한 주변 단지와 평균 거래 가격을 비교할 자료가 부족해요/);
item.priceComparison.method='usual_gap';item.locationScore.parts[0].details=[];
assert.deepEqual(verdict(item).scores,{price:4,property:null});
""", ['zippickCommonDecisionHtml','zippickOverallRatingHtml','zippickDecisionHtml',
       'zippickSectionRatingData','zippickSectionRatingHtml','zippickNumberSteps'])


def test_report_uses_the_same_property_assessment_beside_the_composite_score():
    run(r"""
const esc=String;
const ZP_FUNDING_PART_KEYS=new Set(['jeonse']);
const zippickSignalHeading=()=> '최근 시장 흐름은 보통이에요';
const zippickMarketEvidenceText=()=> '';
const zippickHasVerifiedMixedCorridor=()=>false;
const item=base();
Object.assign(item,{buildingAge:26,households:964});
item.priceComparison.shiftPp=0;
item.locationScore.score=74;
const [demand, product]=item.locationScore.parts;
Object.assign(demand,{points:27.3,maxPoints:30});
Object.assign(product,{points:4.2,maxPoints:10,label:'상품성·희소성'});
const [station, school]=demand.details;
const [size, age]=product.details;
Object.assign(station,{score:100,points:5,maxPoints:5,reason:'독립문역 3호선 · 직선 306m'});
Object.assign(school,{score:88,points:3.52,maxPoints:4,reason:'서울독립문초등학교 · 162m 거리'});
size.score=62;
Object.assign(age,{score:22,points:1.32,maxPoints:6,reason:'2000년 사용승인'});
const mixed=verdict(item);
assert.equal(mixed.scores.property,3.4);
const summary=zippickDecisionScoresHtml(item,mixed);
assert.match(summary,/종합 74점.*입지는 좋지만 26년차로 연식은 약점이에요/s);
assert.match(summary,/가격·전세·입지·단지·거래 흐름을 함께 반영한 100점 만점/);
assert.doesNotMatch(summary,/단지 조건은 좋아요|단지·입지 74점/);
assert.match(mixed.reviewHeadline,/가격과 입지는 괜찮지만, 단지 조건은 아쉬워요/);
const detailHeading=zippickLocationHeading(item,mixed);
assert.match(detailHeading,/입지는 좋지만 26년차로 연식은 약점이에요/);
for (const score of [35,90]) {
  item.locationScore.score=score;
  const result=verdict(item);
  assert.equal(result.reviewHeadline,mixed.reviewHeadline);
  assert.equal(zippickLocationHeading(item,result),detailHeading);
}
item.priceComparison.shiftPp=4;
const hold=verdict(item);
assert.equal(hold.tone,'hold');
assert.match(hold.reviewHeadline,/입지는 좋지만, 단지 조건에 아쉬움이 있고 가격도 부담돼요/);
assert.equal(zippickLocationHeading(item,hold),detailHeading);
item.priceComparison.shiftPp=0;
item.locationScore.score=35;
size.score=80;age.score=80;
assert.match(zippickLocationHeading(item,verdict(item)),/입지와 단지 조건이 전반적으로 좋아요/);
item.locationScore.score=90;
station.score=30;school.score=30;size.score=30;age.score=30;
assert.match(zippickLocationHeading(item,verdict(item)),/입지와 규모·연식 조건이 모두 아쉬워요/);
school.status='missing';age.status='missing';
assert.match(zippickLocationHeading(item,verdict(item)),/단지 조건을 판단하기 어려워요.*교육 접근성·연식 자료가 부족해요/);
""", ['zippickDecisionScoresHtml','zippickLocationHeading','zippickLocationHeadingFact','zippickLocationEvidenceText',
       'candidateLocationScoreBadgeHtml','candidateFlowScoreBadgeHtml','zpPartRatio','zpIsFundingPart',
       'zpAllScoredParts','zpScoredParts','locationScorePartHasNoData','zippickReportPartLabel'])


def test_size_limitation_uses_household_count_instead_of_internal_score():
    run("""
const item=base();
item.priceComparison.shiftPp=0;
const [size,age]=item.locationScore.parts[1].details;
age.score=70;
for(const [homes,score,description] of [
 [180,25,'180세대로 단지 규모가 작아요'],
 [499,42,'499세대로 단지 규모가 작아요'],
 [500,58,'500세대로 중간 규모 단지예요'],
 [919,58,'919세대로 중간 규모 단지예요']]) {
 item.households=homes;size.score=score;size.reason=`${homes}세대 · 규모 구간`;
 const before=JSON.stringify(item), result=verdict(item);
 assert.equal(result.property.summary,`입지는 좋지만 ${description}`);
 assert.match(result.reviewHeadline,/가격과 입지는 괜찮지만, 단지 조건은 (아쉬워요|보통이에요)/);
 assert.doesNotMatch(result.reviewHeadline,/세대|규모|연식|점수/);
 assert.doesNotMatch(result.reviewHeadline+result.property.summary,/단지 규모 점수|팔기|거래가 어렵|관리비/);
 assert.equal(result.stars,3);assert.equal(result.tone,'conditional');
 assert.equal(result.scores.property,Number(((80+(score+70)/2)/2/20).toFixed(1)));
 assert.equal(JSON.stringify(item),before);
 delete item.households;
 assert.equal(verdict(item).property.summary,result.property.summary);
}
item.households=2000;size.score=90;
assert.equal(verdict(item).property.grade,'good');
assert.doesNotMatch(verdict(item).property.summary,/규모가 작|규모는 아쉬/);
delete item.households;size.status='missing';size.reason='세대수 데이터 없음';
const missing=verdict(item).property;
assert.equal(missing.metrics.find(row=>row.key==='households').score,null);
assert.doesNotMatch(missing.summary,/규모가 작|규모는 아쉬|0세대/);
""")


def test_report_headline_summarizes_price_and_both_property_axes():
    run(r"""
const esc=String;
for(const [access,building,expected] of [
 [80,40,'가격과 입지는 괜찮지만, 단지 조건은 아쉬워요.'],
 [80,60,'가격과 입지는 괜찮지만, 단지 조건은 보통이에요.'],
 [40,80,'가격과 단지 조건은 괜찮지만, 입지는 아쉬워요.'],
 [60,80,'가격과 단지 조건은 괜찮지만, 입지는 보통이에요.'],
 [60,60,'가격은 괜찮지만, 입지와 단지 조건에는 아쉬움이 있어요.']]) {
 const item=base();item.priceComparison.shiftPp=0;
 for(const metric of item.locationScore.parts[0].details) metric.score=access;
 for(const metric of item.locationScore.parts[1].details) metric.score=building;
 const result=verdict(item),rendered=zippickOverallRatingHtml(result,result.label);
 assert.ok(result.reviewHeadline.startsWith(expected),result.reviewHeadline);
 assert.match(rendered,/zpr-verdict-tag is-conditional">조건부 검토<\/span>/);
 assert.ok(rendered.includes(`<h3 class="zpr-overall-opinion">${expected}</h3>`));
 assert.doesNotMatch(rendered,/연식|세대|규모|점수|입지은|조건는/);
 assert.equal(result.stars,3);assert.equal(result.scores.property,Number(((access+building)/40).toFixed(1)));
 item.priceComparison.shiftPp=4;
 assert.match(verdict(item).reviewHeadline,/아쉬움이 있고 가격도 부담돼요/);
 assert.equal(verdict(item).stars,2);
 item.priceComparison.shiftPp=0;item.signals={status:'ok',recentDealCount:2,priorDealCount:10};
 assert.match(verdict(item).reviewHeadline,/최근 거래도 크게 줄었어요/);
 item.priceComparison.status='loading';
 assert.doesNotMatch(verdict(item).reviewHeadline,/가격.*괜찮/);
 assert.match(verdict(item).reviewHeadline,/불러오고 있어요/);
}
""", ['zippickOverallRatingHtml'])


def test_live_shared_report_calls_common_policy_not_signal_matrix():
    source=HTML.read_text()
    report=source.split('    function candidateZippickReportHtml(item) {',1)[1].split('    function candidateDisplayName',1)[0]
    assert 'zippickCommonPurchaseVerdict(item)' in report
    assert 'zippickMatrixVerdict(' not in report
    assert 'zippickGuardVerdict(' not in report
    assert 'zippickCommonPropertyHtml(verdict.property)' in report
    assert 'zippickPriceEvidenceHtml(item, verdict.peerPriceAssessment)' in report
    assert 'zippickDecisionHtml(item, verdict)' in report
    for entry in ['openAptReport', 'loadCandidateReportSheet']:
        body=re.search(r'^    async function '+entry+r'\(.*?^    \}', source, re.M|re.S).group()
        assert 'candidateZippickReportHtml(report)' in body or 'candidateZippickReportHtml(item)' in body


def test_pending_price_enrichment_does_not_claim_completed_evaluation():
    run("""
const item=base();delete item.priceComparison;item.reportPeerState='loading';
const result=verdict(item);
assert.equal(result.label,'판단 준비 중');assert.equal(result.stars,null);
assert.match(result.reason,/불러오고 있어요/);
assert.equal(result.reviewHeadline,'가격 비교 자료를 불러오고 있어요.');
item.locationScore.parts=[];
assert.equal(verdict(item).label,'판단 준비 중');assert.equal(verdict(item).stars,null);
assert.match(verdict(item).reason,/불러오고 있어요/);
item.reportPeerState='error';assert.equal(verdict(item).label,'판단 보류');
""")


@pytest.mark.parametrize(('patch', 'title', 'basis'), [
    ("item.priceComparison.transactionCount=3", '가격 비교에 쓴 최근 거래가 적어요', '거래 3건'),
    ("item.priceComparison.scope='district'", '비교 단지와의 과거 가격 차이 자료가 적어요', '같은 지역 내 다른 단지'),
    ("item.priceComparison.peers[0].tier=1", '비교 단지와의 과거 가격 차이 자료가 적어요', '같은 지역 내 다른 단지'),
    ("item.priceComparison.periodMonths=12", '최근 거래가 적어 오래된 거래까지 비교했어요', '12개월까지'),
    ("item.priceComparison.conditionsRelaxed=true", '규모·연식이 비슷한 비교 단지가 부족해요', '규모·연식 조건을 넓혀'),
    ("item.priceComparison.areaAdjusted=true", '같은 면적의 거래가 부족해 다른 크기의 집과 비교했어요', '같은 면적 기준으로 환산'),
    ("item.priceComparison.peers[0].lowData=true", '비교 단지의 거래가 적어요', '다른 단지의 거래가 적어요'),
    ("item.priceComparison.lowData=true", '가격 비교에 쓸 자료가 적어요', '가격 차이를 비교할 자료가 적어요'),
])
def test_limited_price_names_the_actual_reason(patch, title, basis):
    run("const item=base();item.priceComparison.shiftPp=0;" + patch + f""";
const result=verdict(item);
assert.equal(result.tone,'conditional');assert.equal(result.stars,3);
assert.equal(result.reason,'단지 조건은 좋고 비교 가격은 평소 수준이지만, {title}');
assert.equal(result.reviewHeadline, result.reason+'. 매수는 신중히 검토하세요.');
assert.ok(result.basis.includes('{basis}'));
assert.match(result.basis,/다른 단지와의 평소 가격 차이를 감안하면 적정해요/);
assert.doesNotMatch(result.reason,/비교 근거|제한돼요|조건부로|확인하세요|적정 가격/);
""")


def test_known_price_and_property_weaknesses_survive_multiple_limitations():
    run("""
const item=base();item.priceComparison.shiftPp=4;
Object.assign(item.priceComparison,{transactionCount:3,periodMonths:12,scope:'district',areaAdjusted:true});
let result=verdict(item);
assert.match(result.reason,/평소 가격 차이를 감안하면 비싸요/);
for(const text of ['거래 3건','12개월까지','같은 지역 내 다른 단지','같은 면적 기준으로 환산'])
  assert.ok(result.basis.includes(text),text);
item.buildingAge=28;item.locationScore.parts[1].details[1].score=20;
result=verdict(item);
assert.match(result.reason,/28년차로 연식은 약점이에요/);
assert.match(result.reason,/평소 가격 차이를 감안하면 비싸요/);
assert.equal(result.tone,'hold');assert.equal(result.stars,2);
item.signals={recentDealCount:3,priorDealCount:12};
assert.match(verdict(item).basis,/최근 6개월 3건.*그 전 6개월 12건/);
""")


def test_same_complex_price_position_and_missing_peer_comparison_are_both_explained():
    run("""
const item=base();item.priceComparison={status:'unavailable'};
item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:3,periodMonths:6}};
for(const [price,meaning] of [[8,'저렴해요'],[10,'적정해요'],[12,'비싸요']]) {
 item.latestDealPriceEok=price;
 const result=verdict(item);
 assert.equal(result.tone,'conditional');assert.equal(result.stars,3);
 assert.ok(result.reason.includes(meaning),result.reason);
 assert.match(result.basis,/같은 단지 최근 6개월 다른 실거래 3건/);
 assert.match(result.basis,/다른 단지와의 평소 가격 차이를 판단하지 못해/);
 assert.doesNotMatch(result.reason,/비교 근거|제한돼요/);
}
item.latestDealPriceEok=10;
assert.match(verdict(item).reason,/다른 단지와의 평소 가격 차이는 판단할 수 없어요/);
""")


@pytest.mark.parametrize('patch', [
    "item.priceIdentityVerified=false",
    "item.locationScore.parts=[]",
    "item.locationScore.parts[0].details[0].status='missing';item.locationScore.parts[1].details[0].status='missing'",
])
def test_unverified_identity_or_missing_property_never_becomes_a_bad_rating(patch):
    run("const item=base();" + patch + """;
const result=verdict(item);
assert.equal(result.tone,'missing');assert.equal(result.stars,null);
assert.doesNotMatch(result.reason,/아쉬워요|약점|나빠요/);
""")


@pytest.mark.parametrize('limitation', [
    "item.priceComparison.transactionCount=3",
    "item.priceComparison.scope='district'",
    "item.priceComparison.peers[0].tier=1",
    "item.priceComparison.periodMonths=12",
    "item.priceComparison.conditionsRelaxed=true",
    "item.priceComparison.areaAdjusted=true",
    "item.priceComparison.peers[0].lowData=true",
    "item.priceComparison.lowData=true",
])
def test_evidence_limit_is_a_ceiling_and_never_upgrades_a_hold(limitation):
    run("""
for(const [access,building,shift,expected] of [
 [80,80,-4,'conditional'], [80,80,0,'conditional'], [80,80,4,'conditional'],
 [80,40,-4,'conditional'], [80,40,0,'conditional'], [80,40,4,'hold'],
 [30,30,-4,'hold'], [30,30,0,'hold'], [30,30,4,'hold']
]) {
 const item=base();
 for(const metric of item.locationScore.parts[0].details)metric.score=access;
 for(const metric of item.locationScore.parts[1].details)metric.score=building;
 item.priceComparison.shiftPp=shift;
 const before=verdict(item);
 """ + limitation + """;
 const after=verdict(item);
 assert.equal(after.limitedPrice,true);
 assert.equal(after.tone,expected,JSON.stringify({access,building,shift,after}));
 assert.ok(after.stars<=before.stars,'adding a limitation must not increase the rating');
 assert.equal(after.stars,expected==='hold'?2:3);
}
""")


def test_same_complex_evidence_does_not_upgrade_expensive_mixed_property():
    run("""
const item=base();item.priceComparison={status:'unavailable'};
item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
item.locationScore.parts[1].details[1].score=20;
for(const [price,expected,stars] of [[8,'conditional',3],[10,'conditional',3],[12,'hold',2]]){
 item.latestDealPriceEok=price;
 const result=verdict(item);
 assert.equal(result.priceSource,'same_complex');
 assert.equal(result.tone,expected);assert.equal(result.stars,stars);
 assert.match(result.basis,/다른 단지와의 평소 가격 차이를 판단하지 못해/);
 if(expected==='hold') assert.match(result.reason,/같은 단지 거래 기준으로 비싸요/);
}
""")


@pytest.mark.parametrize('source', ['reportPeerState', 'priceComparison.status'])
def test_price_loading_failure_absence_and_recovery_are_distinct(source):
    run("""
const item=base(), original=structuredClone(item.priceComparison);
item.priceComparison={status:'unavailable'};
""" + f"""
for(const status of ['pending','loading','error','unavailable']){{
 item.{source}=status;
 const result=verdict(item);
 assert.equal(result.stars,null);
 assert.equal(result.label,['pending','loading'].includes(status)?'판단 준비 중':'판단 보류');
 if(status==='error') assert.match(result.reason,/불러오지 못해/);
}}
""" + """
item.reportPeerState='ready';item.priceComparison=original;
assert.equal(verdict(item).tone,'yes');assert.equal(verdict(item).stars,4);
""")


def test_top_headline_excludes_same_complex_price_in_all_property_grades():
    run("""
for(const grade of ['good','mixed','weak']) for(const months of [6,12]) for(const price of [8,10,12]) {
 const item=base();item.priceComparison={status:'unavailable'};
 if(grade==='mixed')item.locationScore.parts[1].details[1].score=20;
 if(grade==='weak')for(const p of item.locationScore.parts.slice(0,2))for(const m of p.details)m.score=30;
 item.latestDealPriceEok=price;
 item.valuation={status:'ready',latestTradeExcluded:true,
  fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:months,periodWidened:months>6}};
 const result=verdict(item);
 assert.equal(result.priceSource,'same_complex');
 assert.doesNotMatch(result.reviewHeadline,/같은 단지|단지 내|과거 거래|거래로만|비쌌|저렴|가격.*비교/);
 assert.match(result.reviewHeadline,/입지/);
 assert.equal(result.stars,grade==='weak'||grade==='mixed'&&price===12?2:3);
 assert.equal(result.bandEvidence.position,price===8?'low':price===10?'similar':'high');
 assert.match(result.basis,/같은 단지 최근/);
 assert.match(result.priceTitle,/최근 한 건/);
}
const item=base();item.priceComparison={status:'unavailable'};item.latestDealPriceEok=10;
item.valuation={status:'ready',latestTradeExcluded:true,fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
item.signals={status:'ok',recentDealCount:2,priorDealCount:10};
assert.match(verdict(item).reviewHeadline,/최근 거래는 크게 줄었어요/);
""")


def test_conflicting_price_bases_keep_their_existing_caution():
    run("""
const item=base();item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
item.latestDealPriceEok=12;
assert.equal(verdict(item).tone,'conditional');
assert.equal(verdict(item).priceDisagreement,true);
assert.equal(verdict(item).reason,"최근 한 건은 단지 내에서 비싸게 거래됐지만, 이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 평소보다 낮아요");
item.latestDealPriceEok=8;item.priceComparison.shiftPp=4;
assert.equal(verdict(item).tone,'conditional');
assert.equal(verdict(item).priceDisagreement,true);
assert.equal(verdict(item).reason,"최근 한 건은 단지 내에서 저렴하게 거래됐지만, 이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 평소보다 높아요");
""")


def test_conflicting_price_headline_omits_same_complex_comparison_without_changing_scores():
    run(r"""
const esc=String, zippickMarketVerdict=()=>({summary:''});
const zippickBuyBandHtml=()=>'', zippickDecisionScoresHtml=()=>'';
const cases=[
 [12,-4,4,'입지와 단지 조건은 좋고, 비슷한 주변 단지와 비교한 평균 거래 가격은 평소보다 낮아요. 매수는 신중히 검토하세요.'],
 [12,0,3,'입지와 단지 조건은 좋고, 비슷한 주변 단지와 비교한 평균 거래 가격은 평소 수준이에요. 매수는 신중히 검토하세요.'],
 [8,4,2,'입지와 단지 조건은 좋지만, 비슷한 주변 단지와 비교한 평균 거래 가격은 평소보다 높아요. 매수는 신중히 검토하세요.'],
];
for(const [latest,shift,priceStars,headline] of cases){
 const item=base();item.latestDealPriceEok=latest;item.priceComparison.shiftPp=shift;
 item.valuation={status:'ready',latestTradeExcluded:true,
  fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
 const result=verdict(item),html=zippickDecisionHtml(item,result);
 assert.equal(result.priceDisagreement,true);
 assert.equal(result.tone,'conditional');assert.equal(result.stars,3);
 assert.deepEqual(result.scores,{price:priceStars,property:4});
 assert.equal(result.reviewHeadline,headline);
 const renderedHeadline=html.match(/<h3 class="zpr-overall-opinion">(.*?)<\/h3>/s)[1];
 assert.equal(renderedHeadline.replace(/<[^>]+>/g,''),headline.replace(' 매수는 신중히 검토하세요.',''));
 assert.match(html,/zpr-verdict-tag is-conditional">조건부 검토<\/span>/);
 assert.doesNotMatch(html,/zpr-overall-score|매수 판단 <b>|<dl|<details/);
 assert.match(html,/zpr-head-inline/);
 assert.ok(html.includes('이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 '+{4:'평소보다 낮아요',3:'평소 수준이에요',2:'평소보다 높아요'}[priceStars]));
 const pricePanel=html.match(/aria-label="가격 요약">(.*?)<\/section>/s)[1];
 assert.doesNotMatch(pricePanel,/최근 거래|최근 한 건|적정했어요/);
 assert.ok(pricePanel.includes(result.peerPriceAssessment.heading));
 assert.match(html,/비교하는 거래가 달라 결과가 다를 수 있어요/);
 assert.doesNotMatch(html,/두 가격 비교 결과가 엇갈려/);
 assert.ok(html.indexOf('zpr-overall-verdict')<html.indexOf('가격 비교 점수'));
 assert.ok(html.indexOf('가격 비교 점수')<html.indexOf('단지 조건 점수'));
}
const old=base();old.latestDealPriceEok=12;
old.valuation={status:'ready',latestTradeExcluded:true,fairPrice:{lowEok:9,centerEok:10,highEok:11},
 dataQuality:{sampleCount:8,periodMonths:12,periodWidened:true}};
Object.assign(old.priceComparison,{scope:'district',region:'남양주시'});
const historical=verdict(old);
assert.equal(historical.stars,3);
assert.doesNotMatch(historical.reviewHeadline,/같은 단지|과거 거래|최근 거래/);
assert.match(historical.reviewHeadline,/남양주시 내 비슷한 단지와 비교한 평균 거래 가격/);
assert.equal(historical.peerPriceAssessment.comparisonLabel,'남양주시 내 비슷한 단지');
assert.match(historical.reason,/단지 내에서 비싸게 거래됐지만/);
assert.equal(historical.bandEvidence.historicalOnly,true);
""", ['zippickCommonDecisionHtml','zippickOverallRatingHtml','zippickDecisionHtml',
       'zippickSectionRatingData','zippickSectionRatingHtml'])


def test_sufficient_district_history_can_reach_four_stars_without_hiding_scope():
    run("""
const item=base();Object.assign(item.priceComparison,{scope:'district',region:'남양주시'});
item.priceComparison.peers=[0,1].map(tier=>({tier,lowData:false,transactionCount:12,
 yearlyRatios:{'2023':85,'2024':88,'2025':87}}));
for(const shift of [-4,0,3]){
 item.priceComparison.shiftPp=shift;
 const result=verdict(item);
 assert.equal(result.tone,'yes');assert.equal(result.stars,4);
 assert.equal(result.limitedPrice,true,'the expanded comparison scope remains visible');
 assert.equal(result.priceRatingCapped,false);
 assert.match(result.basis,/자료 적음/);assert.match(result.basis,/남양주시 내 다른 단지/);
 assert.match(result.title,/남양주시 내 비슷한 단지와 비교하면/);
 assert.doesNotMatch(result.reason,/비교할 단지가 부족/);
}
item.priceComparison.shiftPp=3.1;
assert.equal(verdict(item).tone,'conditional');
item.priceComparison.shiftPp=0;item.signals={recentDealCount:4,priorDealCount:10};
assert.equal(verdict(item).tone,'conditional');
""")


@pytest.mark.parametrize('patch', [
    "item.priceComparison.transactionCount=4",
    "item.priceComparison.periodMonths=12",
    "item.priceComparison.conditionsRelaxed=true",
    "item.priceComparison.areaAdjusted=true",
    "item.priceComparison.lowData=true",
    "item.priceComparison.peers[0].tier=2",
    "item.priceComparison.peers[0].lowData=true",
    "item.priceComparison.peers[0].transactionCount=4",
    "delete item.priceComparison.peers[0].yearlyRatios",
    "item.priceComparison.peers[0].yearlyRatios={'2025':90}",
    "item.priceComparison.peers[0].yearlyRatios={'2024':null,'2025':90}",
    "item.priceComparison.peers[0].yearlyRatios={'2024':Infinity,'2025':90}",
    "item.priceComparison.peers[0].yearlyRatios={'2024':0,'2025':90}",
    "item.priceComparison.peers[0].yearlyRatios={'2026':90,'2027':90}",
    "item.priceComparison.peers[0].yearlyRatios={'2019':90,'2020':90}",
])
def test_wider_scope_still_requires_sufficient_unrelaxed_comparison(patch):
    run("""
const item=base();item.priceComparison.scope='district';
item.priceComparison.peers=[0,1].map(tier=>({tier,lowData:false,transactionCount:12,
 yearlyRatios:{'2023':85,'2024':88,'2025':87}}));
assert.equal(verdict(item).tone,'yes');
""" + patch + """;
assert.equal(verdict(item).tone,'conditional');assert.equal(verdict(item).stars,3);
assert.equal(verdict(item).priceRatingCapped,true);
""")


LIVE_CASES = json.loads((Path(__file__).parent / 'fixtures/purchase_verdict_live_20261109.json').read_text())['cases']


@pytest.mark.parametrize('case', LIVE_CASES, ids=[case['request'][0] for case in LIVE_CASES])
def test_observed_apartments_cover_all_five_stars_and_missing_data(case):
    run("const sample=" + json.dumps(case, ensure_ascii=False) + ";" + """
const result=zippickCommonPurchaseVerdict(sample.report,new Date(2026,10,9));
assert.equal(result.tone,sample.expected,JSON.stringify(result));
assert.equal(result.stars,sample.expectedStars);
if(sample.expected==='yes'){
 assert.equal(result.priceRatingCapped,false);
 if(sample.report.priceComparison.scope==='district')assert.ok(result.basis.includes(`${sample.report.priceComparison.region || '같은 지역'} 내 다른 단지`));
 if(result.moderateEvidence)assert.match(result.basis,/자료 적음/);
}
""")


def test_observed_moderate_comparison_uses_available_history_without_overclaiming():
    sample = next(case for case in LIVE_CASES if case['request'][0] == '마포래미안푸르지오2단지')
    run("const item=" + json.dumps(sample['report'], ensure_ascii=False) + ";" + """
const actual=zippickCommonPurchaseVerdict(item,new Date(2026,10,9));
assert.equal(actual.stars,4);
assert.equal(actual.moderateEvidence,true);
assert.equal(actual.priceRatingCapped,false);
assert.match(actual.basis,/자료 적음/);
for(const weaken of [
  item=>item.priceComparison.peers[0].transactionCount=2,
  item=>item.priceComparison.peers[0].yearlyRatios={'2025':95.5},
  item=>item.priceComparison.areaAdjusted=true,
  item=>item.priceComparison.periodMonths=12,
  item=>item.priceComparison.scope='district',
]) {
 const changed=structuredClone(item);weaken(changed);
 const verdict=zippickCommonPurchaseVerdict(changed,new Date(2026,10,9));
 assert.equal(verdict.stars,3,JSON.stringify(verdict));
 assert.equal(verdict.priceRatingCapped,true);
}
item.priceComparison.shiftPp=-11;
assert.equal(zippickCommonPurchaseVerdict(item,new Date(2026,10,9)).stars,4,
  'limited evidence must never earn five stars');
""")


def test_older_large_complex_can_earn_four_only_with_reliable_fair_price():
    run("""
const item=base();item.buildingAge=28;item.priceIdentityVerified=true;
item.locationScore.parts[1].details[0].score=90;
item.locationScore.parts[1].details[1].score=25;
item.priceComparison.shiftPp=0;
item.priceComparison.peers.forEach(peer=>Object.assign(peer,{transactionCount:12,
  yearlyRatios:{'2023':85,'2024':88,'2025':87}}));
const actual=verdict(item);
assert.equal(actual.stars,4);assert.equal(actual.olderLargeCandidate,true);
assert.match(actual.reason,/적정해요.*28년차 연식은 약점/);
assert.match(actual.basis,/단지 규모 90점과 연식 25점/);
item.priceComparison.shiftPp=-4;assert.equal(verdict(item).stars,4);
item.priceComparison.shiftPp=4;assert.equal(verdict(item).stars,2);
item.priceComparison.shiftPp=0;
item.priceComparison.peers[0].transactionCount=2;assert.equal(verdict(item).stars,3);
item.priceComparison.peers[0].transactionCount=12;
item.priceComparison.conditionsRelaxed=true;assert.equal(verdict(item).stars,3);
item.priceComparison.conditionsRelaxed=false;
item.locationScore.parts[1].details[0].score=80;assert.equal(verdict(item).stars,3);
item.locationScore.parts[1].details[0].score=90;
item.locationScore.parts[0].details[0].score=30;assert.equal(verdict(item).stars,3);
item.locationScore.parts[0].details[0].score=80;
item.signals.recentDealCount=5;item.signals.priorDealCount=12;
assert.equal(verdict(item).stars,3);
""")


def test_observed_exceptional_fundamentals_can_earn_five_at_fair_price():
    sample = next(case for case in LIVE_CASES if case['request'][0] == '헬리오시티')
    run("const item=" + json.dumps(sample['report'], ensure_ascii=False) + ";" + """
const observedVerdict=item=>zippickCommonPurchaseVerdict(item,new Date(2026,10,9));
const actual=observedVerdict(item);
assert.equal(actual.stars,5);
assert.equal(actual.label,'우선 검토');
assert.deepEqual(actual.scores,{price:3,property:4.5});
assert.match(actual.reason,/가격이 평소 수준 이하이며 최근 거래도 충분해요/);
assert.match(actual.basis,/최근 6개월 32건.*그 전 6개월 52건보다 줄었어요/);
const fewer=structuredClone(item);fewer.signals.recentDealCount=19;fewer.signals.priorDealCount=30;
assert.equal(observedVerdict(fewer).stars,4);
const sharpDrop=structuredClone(item);sharpDrop.signals.recentDealCount=25;
assert.equal(observedVerdict(sharpDrop).stars,3);
const weakerAccess=structuredClone(item);
weakerAccess.locationScore.parts[0].details[0].score=70;
assert.equal(observedVerdict(weakerAccess).stars,4);
const referenceBand=structuredClone(item);referenceBand.valuation.referenceOnly=true;
assert.equal(observedVerdict(referenceBand).stars,4);
const widerBand=structuredClone(item);widerBand.valuation.dataQuality.periodMonths=12;
assert.equal(observedVerdict(widerBand).stars,4);
""")


EXTREME_FIXTURE = """
function complete(){
 const item=base();item.priceIdentityVerified=true;
 item.priceComparison.peers=[0,1].map(()=>({tier:0,lowData:false,transactionCount:12,
  yearlyRatios:{'2023':85,'2024':88,'2025':87}}));
 item.signals={status:'ok',recentDealCount:12,priorDealCount:12};
 item.valuation={status:'ready',latestTradeExcluded:true,referenceOnly:false,
  fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
 item.latestDealPriceEok=10;
 return item;
}
function mixed(item){item.locationScore.parts[1].details[1].score=20;return item;}
"""


def test_five_star_candidate_needs_price_advantage_property_and_observed_trades():
    run(EXTREME_FIXTURE + """
const item=complete(), result=verdict(item);
assert.equal(result.stars,5);assert.equal(result.label,'우선 검토');
assert.match(result.reason,/우수.*저렴.*거래도 유지/);
assert.match(result.basis,/입지 80점·단지 80점/);
assert.match(result.basis,/최근 6개월 12건.*그 전 6개월 12건/);
item.signals.score=0;item.signals.momentumPct=-30;
assert.equal(verdict(item).stars,5,'market direction does not replace the observed criteria');
item.policyImpact={cashGapEok:-100};assert.equal(verdict(item).stars,5);
item.priceComparison.shiftPp=-3;assert.equal(verdict(item).stars,4);
item.priceComparison.shiftPp=-3.01;assert.equal(verdict(item).stars,5);
item.signals.recentDealCount=11;assert.equal(verdict(item).stars,4);
item.signals.recentDealCount=5;assert.equal(verdict(item).stars,3);
""")


@pytest.mark.parametrize('patch', [
    "item.priceIdentityVerified=undefined",
    "item.locationScore.parts[0].details[0].status='missing'",
    "item.locationScore.parts[0].details[0].score=69",
    "item.locationScore.parts[0].details[0].score=49;item.locationScore.parts[0].details[1].score=100",
    "item.signals.recentDealCount=null",
    "item.signals.priorDealCount=null",
    "item.signals.recentDealCount=4;item.signals.priorDealCount=4",
    "item.signals.status='error'",
    "item.signals.recentDealCount=Infinity",
    "item.signals.recentDealCount=12.5",
    "delete item.valuation",
    "item.valuation.referenceOnly=true",
    "item.valuation.dataQuality.sampleCount=2",
    "item.valuation.dataQuality.periodMonths=12",
    "item.valuation.dataQuality.periodWidened=true",
    "item.valuation.latestTradeExcluded=false",
    "delete item.priceComparison.peers[0].yearlyRatios",
    "item.priceComparison.peers[0].transactionCount=4",
])
def test_missing_or_weaker_extra_evidence_preserves_four_stars_without_claiming_five(patch):
    run(EXTREME_FIXTURE + "const item=complete();" + patch + ";assert.equal(verdict(item).stars,4);")


def test_five_star_property_and_trade_thresholds_are_inclusive():
    run(EXTREME_FIXTURE + """
const item=complete();
item.locationScore.parts[0].details[0].score=50;
item.locationScore.parts[0].details[1].score=100;
item.locationScore.parts[1].details[0].score=50;
item.locationScore.parts[1].details[1].score=100;
item.signals.recentDealCount=5;item.signals.priorDealCount=5;
assert.equal(verdict(item).stars,5);
item.locationScore.parts[0].details[0].score=49.99;
assert.equal(verdict(item).stars,4);
""")


def test_one_star_distinguishes_large_price_burden_from_ordinary_two_star_caution():
    run(EXTREME_FIXTURE + """
const item=mixed(complete());
item.priceComparison.shiftPp=3;assert.equal(verdict(item).stars,3);
item.priceComparison.shiftPp=3.01;assert.equal(verdict(item).stars,2);
item.priceComparison.shiftPp=10;assert.equal(verdict(item).stars,2);
item.priceComparison.shiftPp=10.01;
assert.equal(verdict(item).stars,1);assert.equal(verdict(item).label,'다른 후보 우선');
assert.match(verdict(item).reason,/가격 부담이 크게/);
assert.match(verdict(item).basis,/10.01포인트.*10포인트/);
item.locationScore.parts[1].details[1].score=80;
assert.equal(verdict(item).stars,3,'good property with expensive price remains a conditional candidate');
""")


def test_one_star_requires_combined_adverse_facts_and_respects_trade_drop_boundary():
    run(EXTREME_FIXTURE + """
const item=mixed(complete());item.priceComparison.shiftPp=4;
item.signals={status:'ok',recentDealCount:5,priorDealCount:10};
assert.equal(verdict(item).stars,2);
item.signals.recentDealCount=4;assert.equal(verdict(item).stars,1);
assert.match(verdict(item).reason,/비싸고.*절반 넘게/);
item.signals.status='error';assert.equal(verdict(item).stars,2);
item.signals={status:'ok',recentDealCount:0,priorDealCount:4};assert.equal(verdict(item).stars,2);
item.signals={status:'ok',recentDealCount:null,priorDealCount:10};assert.equal(verdict(item).stars,2);
for(const part of item.locationScore.parts.slice(0,2)) for(const metric of part.details) metric.score=30;
assert.equal(verdict(item).stars,1);assert.match(verdict(item).reason,/입지와 단지 조건이 모두 아쉽고/);
item.priceComparison.shiftPp=3;assert.equal(verdict(item).stars,2);
""")


@pytest.mark.parametrize('patch', [
    "item.priceIdentityVerified=undefined",
    "item.locationScore.parts[0].details[0].status='missing'",
    "item.priceComparison.lowData=true",
    "item.priceComparison.areaAdjusted=true",
    "item.priceComparison.conditionsRelaxed=true",
    "item.priceComparison.periodWidened=true",
    "item.priceComparison.periodMonths=12",
    "item.priceComparison.transactionCount=4",
    "item.priceComparison.peers[0].lowData=true",
    "item.priceComparison.peers[0].tier=2",
    "item.priceComparison.peers[0].transactionCount=4",
    "item.priceComparison.peers[0].yearlyRatios={'2025':90}",
])
def test_limited_evidence_cannot_escalate_a_caution_to_one_star(patch):
    run(EXTREME_FIXTURE + "const item=mixed(complete());item.priceComparison.shiftPp=11;" + patch + ";assert.equal(verdict(item).stars,2);")


def test_conflicting_price_evidence_and_missing_identity_never_get_extreme_ratings():
    run(EXTREME_FIXTURE + """
const good=complete();good.latestDealPriceEok=12;
assert.equal(verdict(good).stars,3);
const bad=mixed(complete());bad.priceComparison.shiftPp=11;bad.latestDealPriceEok=8;
assert.equal(verdict(bad).stars,3);
for(const item of [good,bad]){
 item.priceIdentityVerified=false;assert.equal(verdict(item).stars,null);
}
const unavailable=complete();delete unavailable.valuation;delete unavailable.priceComparison;
assert.equal(verdict(unavailable).stars,null);
""")


def test_review_grades_and_displayed_score_use_the_same_judgment():
    run(EXTREME_FIXTURE + r"""
const esc=s=>String(s);
const zippickReportTable=(head,rows)=>rows.map(row=>row.join(':')).join('\n');
const samples=[complete(),complete(),complete(),mixed(complete()),mixed(complete())];
samples[1].priceComparison.shiftPp=0;
samples[2].priceComparison.shiftPp=4;
samples[3].priceComparison.shiftPp=4;
samples[4].priceComparison.shiftPp=11;
const headlineByGrade=[/최근 거래도 받쳐줘 먼저 검토할 만해요/, /평소 수준 이하여서 매수를 검토할 만해요/,
 /가격이 부담돼 매수는 신중히 검토하세요/, /단지 조건에 아쉬움이 있고 가격도 부담돼요/,
 /단지 조건에 아쉬움이 있고 가격도 크게 부담돼요/];
for(const [index,item] of samples.entries()){
 const result=verdict(item), stars=5-index;
 assert.equal(result.stars,stars);
 const html=zippickOverallRatingHtml(result,result.label);
 assert.match(result.reviewHeadline,headlineByGrade[index]);
 assert.ok(html.includes(`<h3 class="zpr-overall-opinion">${result.reviewHeadline.split(/(?<=\.)\s+/)[0]}`));
 assert.ok(html.includes(`zpr-verdict-tag is-${result.tone}`));
 assert.doesNotMatch(html,/zpr-overall-score|매수 판단 <b>/);
 assert.doesNotMatch(html,/zpr-section-stars|★★★★★/);
 const rules=zippickCommonDecisionBasisHtml(result);
 for(const label of ['우선 검토','매수 검토','조건부 검토','매수 보류','다른 후보 우선','판단 보류'])
   assert.ok(rules.includes(label));
 assert.doesNotMatch(rules,/검토 · [1-5]점/);
}
""", ['zippickOverallRatingHtml','zippickCommonDecisionBasisHtml'])


def test_all_complex_titles_include_both_independent_price_judgments():
    run("""
const ownWords=['저렴하게 거래됐','적정한 가격에 거래됐','비싸게 거래됐'];
const peerWords=['평소보다 낮아요','평소 수준이에요','평소보다 높아요'];
for(const grade of ['good','mixed','weak']) for(const drop of [false,true]) {
 for(const [ownIndex,latest] of [8,10,12].entries()) for(const [peerIndex,shift] of [-4,0,4].entries()) {
  const item=base();
  if(grade==='mixed') item.locationScore.parts[1].details[1].score=20;
  if(grade==='weak') for(const p of item.locationScore.parts.slice(0,2)) for(const m of p.details) m.score=30;
  if(drop) item.signals={recentDealCount:4,priorDealCount:12};
  item.latestDealPriceEok=latest;item.priceComparison.shiftPp=shift;
  item.valuation={status:'ready',latestTradeExcluded:true,fairPrice:{lowEok:9,centerEok:10,highEok:11},
   dataQuality:{sampleCount:8,periodMonths:6}};
  const v=verdict(item);
  assert.ok(v.title.includes('최근 한 건은 단지 내에서 '+ownWords[ownIndex]),v.title);
  assert.ok(v.title.startsWith('이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 '+peerWords[peerIndex]),v.title);
  assert.ok(v.reason.length>0);
 }
}
""")


def test_price_titles_do_not_invent_missing_or_mismatched_evidence():
    run("""
const item=base();item.latestDealPriceEok=10;
item.displayAreaLabel='59㎡';item.latestDealExclusiveArea=59.97;
item.valuation={status:'ready',latestTradeExcluded:true,fairPrice:{lowEok:9,centerEok:10,highEok:11},
 dataQuality:{sampleCount:8,periodMonths:6}};
item.valuation.dataQuality={sampleCount:3,periodMonths:24,periodWidened:true};
assert.match(verdict(item).title,/평소보다 낮아요.*최근 한 건은 단지의 과거 거래 기준으로 적정한 가격에 거래됐어요/);
item.valuation.status='loading';
assert.match(verdict(item).title,/평소보다 낮아요.*단지 내 가격을 확인 중이에요/);
item.valuation.status='error';
assert.match(verdict(item).title,/평소보다 낮아요.*단지 내 가격 자료를 불러오지 못했어요/);
item.valuation.status='ready';item.latestDealExclusiveArea=84;
assert.match(verdict(item).title,/평소보다 낮아요.*일치하는 단지 내 비교 가격대를 확인하지 못했어요/);
item.latestDealExclusiveArea=59.97;
for(const [state,word] of [['loading','불러오고 있어요'],['error','불러오지 못했어요'],['unavailable','비교할 자료가 부족해요']]) {
 item.priceComparison={status:state};item.reportPeerState=state;
 const v=verdict(item);
 assert.match(v.title,/^비슷한 주변 단지와 평균 거래 가격을 비교할.*적정한 가격에 거래됐어요/);
 assert.ok(v.title.includes(word),v.title);
 assert.doesNotMatch(v.title,/평소보다 낮아요|평소보다 높아요|평소 수준이에요/);
}
item.priceIdentityVerified=false;
assert.match(verdict(item).title,/단지 일치가 확인되지 않아.*최근 한 건은 이 단지 거래인지 확인되지 않았어요/);
assert.doesNotMatch(verdict(item).title,/적정한 가격|비싸게 거래|저렴하게 거래/);
""")


def test_detailed_decision_preserves_rating_reason_below_price_title():
    run("""
const esc=String,zippickReportTable=()=>'';
const item=base();item.signals={recentDealCount:4,priorDealCount:12};
const v=verdict(item);
assert.match(v.title,/비슷한 주변 단지.*최근 한 건/);
assert.match(zippickCommonDecisionBasisHtml(v),/최근 6개월 거래가 절반 넘게 줄었어요/);
""", ['zippickCommonDecisionBasisHtml'])


def test_peer_price_detail_reuses_verified_price_evidence():
    run("""
const esc=String;
const item=base();
Object.assign(item.priceComparison,{position:'high',peerAveragePriceEok:9.8,differencePct:2.1,
 currentGapPct:2.1,usualGapPct:6.2,yearlyGaps:[{year:2025,gapPct:6.2}]});
item.priceComparison.peers.forEach(peer=>Object.assign(peer,{name:'비교 단지',averagePriceEok:9.8}));
const render=()=>{const result=verdict(item);return zippickPriceEvidenceHtml(item,result.peerPriceAssessment);};
assert.match(render(),/평소보다 낮아요/);
assert.match(render(),/평소 → 지금/);
assert.doesNotMatch(render(),/평소보다 높아요/);
item.priceComparison.peers.pop();
assert.equal(verdict(item).scores.price,null);
assert.match(render(),/2.1% 비싸요.*평소보다 싼지 비싼지는 자료가 부족해/);
assert.doesNotMatch(render(),/평소 → 지금|zpr-price-years|평소 가격 차이를 감안하면/);
item.priceComparison.throughMonth='2025-11';
assert.match(render(),/평균 거래 가격을 비교할 자료가 부족해요/);
assert.doesNotMatch(render(),/zpr-price-peer-table|비싸요/);
""", ['candidateDisplayName','zippickPriceGapSentence','zippickPriceSelectionTier',
       'zippickPriceEvidenceHtml','zippickPriceComparisonHtml'])


def test_own_price_detail_uses_the_same_bound_trade_and_sample():
    run(r"""
const esc=String, transactionMoney=String;
const zippickBandTradeHistoryHtml=()=>'', candidateTrendPanelHtml=()=>'',
 zippickBuyBandPriorTrades=()=>({}), zippickBuyBandResultHtml=()=>'';
const item=base();
item.areaLabel='59㎡';item.latestDealPriceEok=10;item.latestDealExclusiveArea=59.8;
item.latestDealDate='2026-10-12';item.latestDealFloor=7;
item.priceComparison={status:'unavailable'};
item.valuation={status:'ready',latestTradeExcluded:true,areaLabel:'59㎡',
 fairPrice:{lowEok:9,centerEok:10,highEok:11},dataQuality:{sampleCount:6,periodMonths:6},
 evaluatedTrade:{dealAmountEok:10,exclusiveArea:59.8,dealDate:'2026-10-12',floor:7}};
const render=()=>zippickBuyBandHtml(item,verdict(item));
assert.equal(verdict(item).priceSource,'same_complex');
assert.match(render(),/적정한 가격에 거래됐어요/);
item.valuation.evaluatedTrade.dealDate='2026-09-30';
assert.equal(verdict(item).price,'missing');
assert.match(render(),/일치하는 단지 내 비교 가격대를 확인하지 못했어요/);
assert.doesNotMatch(render(),/zpr-buy-band-result|확인 중<\/span>/);
item.valuation.evaluatedTrade.dealDate=item.latestDealDate;
item.valuation.dataQuality.sampleCount=2;
assert.equal(verdict(item).price,'missing');
assert.match(render(),/판단할 자료가 부족해요/);
assert.doesNotMatch(render(),/zpr-buy-band-result/);
""", ['zippickPriceCheckBasis','zippickBuyBandHtml','zippickBuyBandPeakText'])


def test_score_sheet_keeps_the_report_snapshot_and_ignores_an_older_response():
    run("""
let locationScoreSheetRequest=0, locationScoreReturnFocus=null;
const requests=[];
const getJson=()=>new Promise(resolve=>requests.push(resolve));
const locationScoreNeedsRefresh=()=>true;
const locationScoreRefreshPayload=item=>item;
const locationScoreSheet={hidden:true,setAttribute(){},querySelector(){return null}};
const locationScoreTitle={}, locationScoreContent={};
const syncCandidateDetailScrollLock=()=>{}, requestAnimationFrame=()=>{};
const document={activeElement:null};
const candidateIdentityKey=item=>item.name+'|'+item.areaLabel;
const zippickReportAreaKey=item=>candidateIdentityKey(item);
const sameCandidateScoreIdentity=(a,b)=>candidateIdentityKey(a)===candidateIdentityKey(b);
const repaintCandidateScoreBadges=()=>{},syncCandidateReportScores=()=>{};
const candidateRowsForLookup=()=>[];
const locationScoreSheetHtml=item=>String(item.locationScore.score);
const candidateLegacySignalReportHtml=item=>String(item.signals.score);
const first={name:'A',areaLabel:'59㎡',locationScore:{score:50}};
const second={name:'A',areaLabel:'84㎡',locationScore:{score:74},signals:{score:59}};
const button={};
const event=selector=>({target:{closest:value=>value===selector ? button : null},stopPropagation(){}});
(async()=>{
  openLocationScoreSheet(first);
  assert.equal(requests.length,1);
  assert.equal(handleZippickReportScoreClick(event('[data-location-score-open]'),second),true);
  assert.equal(locationScoreContent.innerHTML,'74');
  assert.equal(requests.length,1);
  requests[0]({candidate:{locationScore:{score:22}}});
  await Promise.resolve();
  assert.equal(locationScoreContent.innerHTML,'74');
  assert.equal(handleZippickReportScoreClick(event('[data-flow-score-open]'),second),true);
  assert.equal(locationScoreContent.innerHTML,'59');
})().catch(error=>{console.error(error);process.exitCode=1;});
""", ['candidateDisplayName','openLocationScoreSheet','openFlowScoreSheet',
       'refreshLocationScoreSheet','handleZippickReportScoreClick'])


def test_rendered_header_uses_same_stars_title_and_excludes_private_finance():
    run(r"""
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const zippickMarketVerdict=()=>({summary:'가격은 내렸고 거래는 비슷해요'});
const zippickBuyBandHtml=()=>'';
const zippickDecisionScoresHtml=()=>'';
const item=base();let result=verdict(item);
const html=zippickDecisionHtml(item,result);
assert.equal(result.stars,4);assert.match(html,/aria-label="가격 요약"/);
assert.match(html,/zpr-verdict-tag is-yes">매수 검토<\/span>/);assert.match(html,/단지 조건이 좋고 가격도 평소 수준 이하/);
assert.doesNotMatch(html,/예산 안|현금.*부족|조건부로 매수 검토할 만해요/);
item.policyImpact={cashGapEok:-100};assert.equal(zippickDecisionHtml(item,verdict(item)),html);
item.priceComparison.method='simple';result=verdict(item);
assert.match(zippickDecisionHtml(item,result),/판단 보류/);
assert.doesNotMatch(zippickDecisionHtml(item,result),/매수 판단 3\/5/);
assert.match(zippickDecisionHtml(item,result),/평균 거래 가격을 비교할 자료가 부족해요/);
""", ['zippickSectionRatingHtml','zippickSectionRatingData','zippickCommonDecisionHtml','zippickOverallRatingHtml','zippickDecisionHtml'])


def test_all_five_ratings_render_their_actual_fill_label_and_published_rules():
    run(EXTREME_FIXTURE + r"""
const esc=s=>String(s);
const zippickReportTable=(head,rows)=>rows.map(row=>row.join(':')).join('\\n');
const samples=[complete(),complete(),complete(),mixed(complete()),mixed(complete())];
samples[1].priceComparison.shiftPp=0;
samples[2].priceComparison.shiftPp=4;
samples[3].priceComparison.shiftPp=4;
samples[4].priceComparison.shiftPp=11;
for(const [index,item] of samples.entries()){
 const result=verdict(item), stars=5-index;
 assert.equal(result.stars,stars);
 const html=zippickOverallRatingHtml(result,result.label);
 assert.ok(html.includes(`zpr-verdict-tag is-${result.tone}">${result.label}</span>`));
 assert.doesNotMatch(html,/매수 판단 [1-5]\/5|zpr-section-stars/);
 const rules=zippickCommonDecisionBasisHtml(result);
 for(const label of ['우선 검토','매수 검토','조건부 검토','매수 보류','다른 후보 우선','판단 보류'])assert.ok(rules.includes(label));
 assert.ok(rules.includes('판단 보류로 표시'));
}
""", ['zippickOverallRatingHtml','zippickCommonDecisionBasisHtml'])
