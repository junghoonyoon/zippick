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
    names = ['zpNum', 'zippickCommonProperty', 'zippickCommonPurchaseVerdict',
             'zippickLatestTradeDetails', 'zippickBuyBandTradeMatchesArea',
             'zippickTradeAreaScope', 'zippickAreaContains',
             'zippickBuyBandTier', 'zippickBandPriceEvidence', *extra]
    functions = []
    for name in names:
        match = re.search(r'^    function ' + name + r'\(.*?^    \}', source, re.M | re.S)
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
  assert.doesNotMatch(result.title,/저점|상승.*기대|예산|현금/);
}
const before=verdict(item);item.signals={score:100,momentumPct:20,recent3Pct:10,isAtPeak:true};
assert.equal(verdict(item).title,before.title);
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
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).title,/단지 조건은 좋지만.*평소 가격 차이.*비싸요/);
item.locationScore.parts[1].details[1].score=20;
assert.equal(verdict(item).tone,'hold');assert.match(verdict(item).title,/연식/);
item.priceComparison.shiftPp=0;
assert.equal(verdict(item).tone,'conditional');
for(const part of item.locationScore.parts.slice(0,2)) for(const metric of part.details) metric.score=30;
assert.equal(verdict(item).tone,'hold');assert.doesNotMatch(verdict(item).title,/흐름.*약|신호.*약/);
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
assert.match(result.title,/가격이 적절한지는 판단할 수 없어요/);assert.doesNotMatch(result.title,/조건.*약|매수가.*불리/);
""")


def test_trade_drop_is_observed_and_does_not_mean_price_is_at_the_bottom():
    run("""
const item=base();item.signals={score:99,recentDealCount:9,priorDealCount:20};
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).title,/최근 6개월 거래가 절반 넘게 줄/);
item.signals.recentDealCount=10;assert.equal(verdict(item).tone,'yes');
item.signals={score:0,recentDealCount:1,priorDealCount:4};assert.equal(verdict(item).tone,'yes');
item.signals={score:0,recentDealCount:null,priorDealCount:20};assert.equal(verdict(item).tradeDrop,false);
""")


def test_price_boundary_matches_comparison_policy():
    run("""
const item=base();
for(const [shift,price] of [[-3.1,'low'],[-3,'similar'],[0,'similar'],[3,'similar'],[3.1,'high']]) {
 item.priceComparison.shiftPp=shift;assert.equal(verdict(item).price,price);
}
""")


def test_rendered_header_uses_same_stars_title_and_excludes_private_finance():
    run(r"""
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const zippickMarketVerdict=()=>({summary:'가격은 내렸고 거래는 비슷해요'});
const zippickBuyBandHtml=()=>'';
const zippickDecisionScoresHtml=()=>'';
const item=base();let result=verdict(item);
const html=zippickDecisionHtml(item,result);
assert.match(html,/매수 판단 4\/5/);assert.match(html,/최근 6개월 실거래 비교 기준/);
assert.match(html,/<strong>매수 검토<\/strong>/);assert.match(html,/입지와 단지 조건이 좋고/);
assert.doesNotMatch(html,/예산 안|현금.*부족|조건부로 매수 검토할 만해요/);
item.policyImpact={cashGapEok:-100};assert.equal(zippickDecisionHtml(item,verdict(item)),html);
item.priceComparison.method='simple';result=verdict(item);
assert.match(zippickDecisionHtml(item,result),/판단 보류/);
assert.doesNotMatch(zippickDecisionHtml(item,result),/매수 판단 3\/5/);
assert.match(zippickDecisionHtml(item,result),/가격이 적절한지는 판단할 수 없어요/);
""", ['zippickPriceBasesHtml','zippickCommonDecisionHtml','zippickOverallRatingHtml','zippickDecisionHtml'])


def test_live_shared_report_calls_common_policy_not_signal_matrix():
    source=HTML.read_text()
    report=source.split('    function candidateZippickReportHtml(item) {',1)[1].split('    function candidateDisplayName',1)[0]
    assert 'zippickCommonPurchaseVerdict(item)' in report
    assert 'zippickMatrixVerdict(' not in report
    assert 'zippickGuardVerdict(' not in report
    assert 'zippickLocationBarsHtml(item)' in report
    assert 'zippickDecisionHtml(item, verdict)' in report
    for entry in ['openAptReport']:
        body=re.search(r'^    async function '+entry+r'\(.*?^    \}', source, re.M|re.S).group()
        assert 'candidateZippickReportHtml(report)' in body or 'candidateZippickReportHtml(item)' in body


def test_pending_price_enrichment_does_not_claim_completed_evaluation():
    run("""
const item=base();delete item.priceComparison;item.reportPeerState='loading';
const result=verdict(item);
assert.equal(result.label,'판단 준비 중');assert.equal(result.stars,null);
assert.match(result.title,/불러오고 있어요/);
item.locationScore.parts=[];
assert.equal(verdict(item).label,'판단 준비 중');assert.equal(verdict(item).stars,null);
assert.match(verdict(item).title,/불러오고 있어요/);
item.reportPeerState='error';assert.equal(verdict(item).label,'판단 보류');
""")


@pytest.mark.parametrize(('patch', 'title', 'basis'), [
    ("item.priceComparison.transactionCount=3", '가격 비교에 쓴 최근 거래가 적어요', '거래 3건'),
    ("item.priceComparison.scope='district'", '가까운 곳에 가격을 비교할 단지가 부족해요', '같은 구의 다른 단지'),
    ("item.priceComparison.peers[0].tier=1", '가까운 곳에 가격을 비교할 단지가 부족해요', '같은 구의 다른 단지'),
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
assert.equal(result.title,'단지 조건은 좋지만, {title}');
assert.ok(result.basis.includes('{basis}'));
assert.match(result.basis,/다른 단지와의 평소 가격 차이를 감안하면 적정해요/);
assert.doesNotMatch(result.title,/비교 근거|제한돼요|조건부로|확인하세요|적정 가격/);
""")


def test_known_price_and_property_weaknesses_survive_multiple_limitations():
    run("""
const item=base();item.priceComparison.shiftPp=4;
Object.assign(item.priceComparison,{transactionCount:3,periodMonths:12,scope:'district',areaAdjusted:true});
let result=verdict(item);
assert.match(result.title,/평소 가격 차이를 감안하면 비싸요/);
for(const text of ['거래 3건','12개월까지','같은 구의 다른 단지','같은 면적 기준으로 환산'])
  assert.ok(result.basis.includes(text),text);
item.buildingAge=28;item.locationScore.parts[1].details[1].score=20;
result=verdict(item);
assert.match(result.title,/28년차로 연식은 약점이에요/);
assert.match(result.title,/평소 가격 차이를 감안하면 비싸요/);
assert.equal(result.tone,'hold');assert.equal(result.stars,2);
item.signals={recentDealCount:3,priorDealCount:12};
assert.match(verdict(item).basis,/최근 6개월 3건.*그 전 6개월 12건/);
""")


def test_same_complex_price_position_and_missing_peer_comparison_are_both_explained():
    run("""
const item=base();item.priceComparison={status:'unavailable'};
item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,highEok:11},dataQuality:{sampleCount:3,periodMonths:6}};
for(const [price,meaning] of [[8,'저렴해요'],[10,'적정해요'],[12,'비싸요']]) {
 item.latestDealPriceEok=price;
 const result=verdict(item);
 assert.equal(result.tone,'conditional');assert.equal(result.stars,3);
 assert.ok(result.title.includes(meaning),result.title);
 assert.match(result.basis,/같은 단지 최근 6개월 다른 실거래 3건/);
 assert.match(result.basis,/다른 단지와의 평소 가격 차이를 판단하지 못해/);
 assert.doesNotMatch(result.title,/비교 근거|제한돼요/);
}
item.latestDealPriceEok=10;
assert.match(verdict(item).title,/다른 단지와의 평소 가격 차이는 판단할 수 없어요/);
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
assert.doesNotMatch(result.title,/아쉬워요|약점|나빠요/);
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
 fairPrice:{lowEok:9,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
item.locationScore.parts[1].details[1].score=20;
for(const [price,expected,stars] of [[8,'conditional',3],[10,'conditional',3],[12,'hold',2]]){
 item.latestDealPriceEok=price;
 const result=verdict(item);
 assert.equal(result.priceSource,'same_complex');
 assert.equal(result.tone,expected);assert.equal(result.stars,stars);
 assert.match(result.basis,/다른 단지와의 평소 가격 차이를 판단하지 못해/);
 if(expected==='hold') assert.match(result.title,/같은 단지 거래 기준으로 비싸요/);
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
 if(status==='error') assert.match(result.title,/불러오지 못해/);
}}
""" + """
item.reportPeerState='ready';item.priceComparison=original;
assert.equal(verdict(item).tone,'yes');assert.equal(verdict(item).stars,4);
""")


def test_conflicting_price_bases_keep_their_existing_caution():
    run("""
const item=base();item.valuation={status:'ready',latestTradeExcluded:true,
 fairPrice:{lowEok:9,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
item.latestDealPriceEok=12;
assert.equal(verdict(item).tone,'conditional');
assert.equal(verdict(item).priceDisagreement,true);
assert.match(verdict(item).title,/최근 한 건은 이 단지 안에서 비싸요/);
item.latestDealPriceEok=8;item.priceComparison.shiftPp=4;
assert.equal(verdict(item).tone,'conditional');
assert.equal(verdict(item).priceDisagreement,true);
assert.match(verdict(item).title,/최근 한 건은 이 단지 안에서 저렴해요/);
""")


def test_sufficient_district_history_can_reach_four_stars_without_hiding_scope():
    run("""
const item=base();item.priceComparison.scope='district';
item.priceComparison.peers=[0,1].map(tier=>({tier,lowData:false,transactionCount:12,
 yearlyRatios:{'2023':85,'2024':88,'2025':87}}));
for(const shift of [-4,0,3]){
 item.priceComparison.shiftPp=shift;
 const result=verdict(item);
 assert.equal(result.tone,'yes');assert.equal(result.stars,4);
 assert.equal(result.limitedPrice,true,'the expanded comparison scope remains visible');
 assert.equal(result.priceRatingCapped,false);
 assert.match(result.basis,/자료 적음/);assert.match(result.basis,/같은 구의 다른 단지/);
 assert.doesNotMatch(result.title,/비교할 단지가 부족/);
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
 if(sample.report.priceComparison.scope==='district')assert.match(result.basis,/같은 구의 다른 단지/);
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


def test_observed_exceptional_fundamentals_can_earn_five_at_fair_price():
    sample = next(case for case in LIVE_CASES if case['request'][0] == '헬리오시티')
    run("const item=" + json.dumps(sample['report'], ensure_ascii=False) + ";" + """
const observedVerdict=item=>zippickCommonPurchaseVerdict(item,new Date(2026,10,9));
const actual=observedVerdict(item);
assert.equal(actual.stars,5);
assert.equal(actual.label,'우선 검토');
assert.match(actual.title,/가격이 평소 수준 이하이며 최근 거래도 충분해요/);
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
  fairPrice:{lowEok:9,highEok:11},dataQuality:{sampleCount:8,periodMonths:6}};
 item.latestDealPriceEok=10;
 return item;
}
function mixed(item){item.locationScore.parts[1].details[1].score=20;return item;}
"""


def test_five_star_candidate_needs_price_advantage_property_and_observed_trades():
    run(EXTREME_FIXTURE + """
const item=complete(), result=verdict(item);
assert.equal(result.stars,5);assert.equal(result.label,'우선 검토');
assert.match(result.title,/우수.*저렴.*거래도 유지/);
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
assert.match(verdict(item).title,/가격 부담이 크게/);
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
assert.match(verdict(item).title,/비싸고.*절반 넘게/);
item.signals.status='error';assert.equal(verdict(item).stars,2);
item.signals={status:'ok',recentDealCount:0,priorDealCount:4};assert.equal(verdict(item).stars,2);
item.signals={status:'ok',recentDealCount:null,priorDealCount:10};assert.equal(verdict(item).stars,2);
for(const part of item.locationScore.parts.slice(0,2)) for(const metric of part.details) metric.score=30;
assert.equal(verdict(item).stars,1);assert.match(verdict(item).title,/입지와 단지 조건이 모두 아쉽고/);
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


def test_all_five_ratings_render_their_actual_fill_label_and_published_rules():
    run(EXTREME_FIXTURE + """
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
 assert.ok(html.includes(`매수 판단 ${stars}/5`));
 assert.ok(html.includes(`--zpr-rating-fill:${stars*20}%`));
 assert.ok(html.includes(`<strong>${result.label}</strong>`));
 const rules=zippickCommonDecisionBasisHtml(result);
 for(const score of [1,2,3,4,5])assert.ok(rules.includes(`· ${score}점`));
 assert.ok(rules.includes('판단 보류 · 별점 없음'));
}
""", ['zippickOverallRatingHtml','zippickCommonDecisionBasisHtml'])
