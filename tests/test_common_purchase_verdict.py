"""Shared purchase conclusions must not turn momentum or personal cash into value."""
from pathlib import Path
import re
import shutil
import subprocess
import pytest

HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='Node required')


def run(script, extra=()):
    source = HTML.read_text()
    names = ['zpNum', 'zippickCommonProperty', 'zippickCommonPurchaseVerdict', *extra]
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
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).title,/단지 조건은 좋지만 비교 가격 부담/);
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
    "item.priceComparison.transactionCount=4", "item.priceComparison.lowData=true",
    "item.priceComparison.scope='district'", "item.priceComparison.areaAdjusted=true",
    "item.priceComparison.periodMonths=12", "item.priceComparison.throughMonth='2025-12'",
    "item.priceComparison.throughMonth='2027-01'", "item.priceComparison.throughMonth='2026-99'",
    "item.priceIdentityVerified=false", "item.locationScore.parts[0].details[0].score=null",
    "item.locationScore.parts[0].details[0].status='missing'", "item.locationScore.parts=[]",
])
def test_missing_or_loose_evidence_never_becomes_a_bad_rating(patch):
    run("const item=base();" + patch + """;
const result=verdict(item);
assert.equal(result.tone,'missing');assert.equal(result.stars,null);
assert.match(result.title,/자료.*부족/);assert.doesNotMatch(result.title,/조건.*약|매수가.*불리/);
""")


def test_trade_drop_is_observed_and_does_not_mean_price_is_at_the_bottom():
    run("""
const item=base();item.signals={score:99,recentDealCount:9,priorDealCount:20};
assert.equal(verdict(item).tone,'conditional');assert.match(verdict(item).title,/거래 건수가 절반 넘게 줄/);
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
const item=base();let result=verdict(item);
const html=zippickDecisionHtml(item,result);
assert.match(html,/매수 판단 4\/5/);assert.match(html,/최근 6개월 실거래 비교 기준/);
assert.match(html,/매수 검토할 만해요/);assert.doesNotMatch(html,/예산 안|현금.*부족/);
item.policyImpact={cashGapEok:-100};assert.equal(zippickDecisionHtml(item,verdict(item)),html);
item.priceComparison.method='simple';result=verdict(item);
assert.doesNotMatch(zippickDecisionHtml(item,result),/zpr-section-stars/);
""", ['zippickCommonDecisionHtml','zippickOverallRatingHtml','zippickDecisionHtml'])


def test_live_shared_report_calls_common_policy_not_signal_matrix():
    source=HTML.read_text()
    report=source.split('    function candidateZippickReportHtml(item) {',1)[1].split('    function candidateDisplayName',1)[0]
    assert 'zippickCommonPurchaseVerdict(item)' in report
    assert 'zippickMatrixVerdict(' not in report
    assert 'zippickGuardVerdict(' not in report
    assert 'zippickCommonPropertyHtml(verdict.property)' in report
    assert 'zippickDecisionHtml(item, verdict)' in report
    assert source.count('candidateZippickReportHtml(') >= 8


def test_pending_price_enrichment_does_not_claim_completed_evaluation():
    run("""
const item=base();delete item.priceComparison;item.reportPeerState='loading';
const result=verdict(item);
assert.equal(result.label,'판단 준비 중');assert.equal(result.stars,null);
assert.match(result.title,/불러오고 있어요/);
item.reportPeerState='error';assert.equal(verdict(item).label,'판단 보류');
""")
