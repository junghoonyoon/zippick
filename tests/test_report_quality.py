"""Paid report evidence, verdict and transaction list regressions."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / '앱화면/real-estate-search.html'
FUNCTIONS = [
    'zpNum', 'zpPartRatio', 'marketPeriod', 'shiftMarketPeriod',
    'locationScorePartHasNoData', 'zpIsFundingPart', 'zpAllScoredParts', 'zpScoredParts',
    'zippickReportPriceData', 'zippickReportMissing', 'zippickReportAssessment',
    'zippickPriceCheckBasis', 'zippickPriceCheckText', 'zippickReportFinance',
    'zippickDecisionHtml', 'zippickReportTable', 'zippickTransactionListHtml', 'zippickPriceEvidenceHtml',
    'candidateDisplayName', 'zippickReportPeers', 'zippickAlternativesHtml',
    'zippickEvidenceHtml', 'zippickSignalHeading', 'zippickCommuteHeading', 'zippickBarReason',
    'candidateHeadlinePrice', 'candidateHalfYearDirectionMeta',
]


def run_js(body):
    html = HTML.read_text()
    source = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in FUNCTIONS)
    prelude = r'''
const assert = require('node:assert/strict');
const NativeDate = Date;
global.Date = class extends NativeDate { constructor(...args) { super(...(args.length ? args : ['2026-09-29T00:00:00Z'])); } static now() { return new NativeDate('2026-09-29T00:00:00Z').getTime(); } };
const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const policyMoney = value => `${Math.round(value*100)/100}억`;
const marketRateText = value=>`${value.toFixed(1)}%`;
const transactionMoney = value => `${Math.round(value*10000)/10000}억`;
const ZP_FUNDING_PART_KEYS = new Set(['jeonse']);
const ZP_COMMUTE_GOOD_MINUTES=30, ZP_COMMUTE_OK_MINUTES=40, ZP_COMMUTE_LONG_MINUTES=60;
let pool=[];
function candidateRowsForLookup(){ return pool; }
const trade = (price, date='2026-09-10', area=84.99, floor=7) => ({originalPriceEok:price,dealDate:date,exclusiveArea:area,floor});
function sample(prices=[10,11,12,13,14], extra={}) { return {
 name:'테스트',apartmentId:'a',region:'서울특별시 관악구',legalDong:'봉천동',jibun:'1',areaLabel:'84㎡',
 locationScore:{score:77,coverage:1,parts:[]},signals:{status:'ok',score:76,turnoverRatio:1},
 roneEstimate:{latestTrade:{exclusiveArea:84.99,dealDate:'2026-09-10'},adjustedTransactions:prices.map(price=>trade(price))},...extra
}; }
'''
    result = subprocess.run(['node'], input=prelude+source+'\n'+body, text=True,capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReportQualityTest(unittest.TestCase):
    def test_one_evidence_set_drives_count_price_and_all_rows(self):
        run_js(r'''
const item=sample([12,12.2,12.4,12.6,13],{recent3AdjustedTradeCount:13,recent3AdjustedAveragePriceEok:99});
const d=zippickReportPriceData(item);
assert.equal(d.count,5); assert.equal(d.median,12.4); assert.equal(d.months,3);
assert.equal(zippickPriceCheckBasis(item).price,12.4);
const html=zippickPriceEvidenceHtml(item);
assert.match(html,/계산에 쓴 거래 5건/); assert.doesNotMatch(html,/99억|13건/);
assert.equal((html.match(/2026-09-10<\/td>/g)||[]).length,5);
assert.match(html,/전용 84㎡대/);
''')

    def test_mixed_areas_cancellations_and_future_deals_are_excluded(self):
        run_js(r'''
const item=sample();
item.roneEstimate.adjustedTransactions.push(trade(100,'2026-09-11',114.99),
 {...trade(90),cancelDate:'2026-09-20'}, {...trade(80),isCanceled:true}, trade(70,'2027-01-01'),trade(0));
const d=zippickReportPriceData(item);assert.equal(d.count,5);assert.equal(d.median,12);
assert.ok(d.rows.every(r=>r.exclusiveArea===84.99));
assert.equal(zippickReportPriceData({...item,areaLabel:'59㎡'}).status,'missing');
''')

    def test_latest_area_is_visible_when_user_did_not_pick_area(self):
        run_js(r'''
const item=sample([12,12.1,12.2,12.3,12.4],{areaLabel:''});
assert.equal(zippickReportPriceData(item).area,84.99);
assert.match(zippickDecisionHtml(item,{tone:'yes'}),/전용 84㎡대/);
''')

    def test_sparse_quarter_extends_to_six_months_with_exact_sample(self):
        run_js(r'''
const item=sample([10,11]);
item.roneEstimate.adjustedTransactions.push(trade(12,'2026-06-20'),trade(13,'2026-05-12'),trade(14,'2026-04-01'),trade(100,'2026-03-31'));
const d=zippickReportPriceData(item);assert.equal(d.count,5);assert.equal(d.quarterCount,2);
assert.equal(d.months,6);assert.equal(d.period,'2026.04~2026.09');assert.equal(d.median,12);
assert.match(zippickPriceEvidenceHtml(item),/최근 3개월은 2건/);
''')

    def test_missing_sparse_and_stale_data_do_not_recommend_price(self):
        run_js(r'''
for (const item of [sample([]),sample([10,11]),sample([10,11,12,13,14])]) {
 if(item.roneEstimate.adjustedTransactions.length===5) item.roneEstimate.adjustedTransactions.forEach(r=>r.dealDate='2025-01-01');
 assert.equal(zippickPriceCheckBasis(item),null);
 assert.equal(zippickReportAssessment(item,{tone:'yes'}).verdict.tone,'missing');
 assert.match(zippickDecisionHtml(item,{tone:'yes'}),/판단을 보류/);
 assert.doesNotMatch(zippickPriceEvidenceHtml(item),/이하 매물부터/);
}
''')

    def test_even_median_and_outlier_not_silently_removed(self):
        run_js(r'''
const d=zippickReportPriceData(sample([10,11,12,14,15,100]));
assert.equal(d.median,13);assert.equal(d.count,6);assert.equal(d.high,100);
''')

    def test_weaknesses_change_positive_verdict_and_are_visible(self):
        run_js(r'''
const item=sample();assert.equal(zippickReportAssessment(item,{tone:'yes'}).verdict.tone,'yes');
for(const change of [
 {signals:{score:76,turnoverRatio:.8}},
 {locationScore:{score:77,coverage:.81,parts:[{key:'demand',label:'입지',points:16,maxPoints:30,details:[{label:'교육 접근성',status:'missing'}]}]}},
]) {
 const actual={...item,...change};assert.equal(zippickReportAssessment(actual,{tone:'yes'}).verdict.tone,'conditional');
 assert.match(zippickDecisionHtml(actual,{tone:'yes'}),/약점부터 확인/);
}
assert.match(zippickDecisionHtml({...item,signals:{score:76,turnoverRatio:.8}},{tone:'yes'}),/0.8배로 줄었어요/);
assert.equal(zippickReportAssessment({...item,locationScore:{coverage:.4}},{tone:'risk'}).verdict.tone,'missing');
''')

    def test_no_cash_condition_in_purchase_verdict_and_no_unmatched_finance(self):
        run_js(r'''
const item=sample([24,24.1,24.21,24.3,24.4],{policyImpact:{cashGapEok:50,requiredCashEok:1,reportProfile:{cashEok:21},cashScenarios:[{priceEok:24.21,requiredCashEok:21.18,cashGapEok:-.18}]}});
assert.equal(zippickReportFinance(item).required,21.18);
assert.equal(zippickReportFinance(item).gap,-.18);
assert.equal(zippickDecisionHtml(item,{tone:'yes'}),zippickDecisionHtml({...item,policyImpact:{}},{tone:'yes'}));
assert.ok(Number.isNaN(zippickReportFinance({...item,policyImpact:{requiredCashEok:1,cashGapEok:99}}).required));
''')

    def test_variations_include_missing_zero_and_recent_only_decline(self):
        run_js(r'''
const item=sample();
for(const tone of ['yes','conditional','hold','risk','missing']) assert.ok(zippickDecisionHtml(item,{tone}).length);
assert.match(zippickDecisionHtml(item,{tone:'yes',peakGuard:{}}),/최근 오른 가격/);
assert.match(zippickSignalHeading({signals:{}}),/판단을 보류/);
assert.match(zippickSignalHeading({signals:{recent3Pct:-2}}),/내리고/);
assert.match(zippickSignalHeading({signals:{momentumPct:21,recent3Pct:4,turnoverRatio:.8}}),/거래가 줄어/);
assert.match(zippickSignalHeading({signals:{momentumPct:0,recent3Pct:0}}),/멈춰/);
''')

    def test_peers_match_area_price_region_and_identity(self):
        run_js(r'''
const item=sample();
const make=(id,extra={})=>sample([11,11.5,12,12.5,13],{apartmentId:id,name:id,...extra});
const valid=make('other');pool=[item,valid,valid,make('elsewhere',{region:'서울특별시 성동구'}),make('sparse',{roneEstimate:{adjustedTransactions:[trade(12)]}}),make('big',{areaLabel:'114㎡'})];
assert.deepEqual(zippickReportPeers(item).map(r=>r.apartmentId),['other']);
const extra=make('near');item.reportPeers=[extra];assert.equal(zippickReportPeers(item).length,2);
assert.match(zippickAlternativesHtml(item),/함께|판단|고르세요/);
''')

    def test_empty_and_error_comparison_do_not_claim_no_alternative(self):
        run_js(r'''
pool=[];assert.match(zippickAlternativesHtml(sample()),/대안이 없다는 뜻은 아니에요/);
assert.match(zippickAlternativesHtml(sample([])),/가격 근거가 부족/);
assert.match(zippickAlternativesHtml(sample(undefined,{reportPeerState:'loading'})),/role="status"/);
assert.match(zippickAlternativesHtml(sample(undefined,{reportPeerState:'error'})),/재시도/);
''')

    def test_evidence_labels_distinct_price_and_market_windows(self):
        run_js(r'''
const item=sample(undefined,{signals:{recentDealCount:55,comparisonBasis:{areaLabel:'단지 전체 면적',recent6Start:'2026-03',recent6End:'2026-08'}}});
const html=zippickEvidenceHtml(item);assert.match(html,/가격 비교: 전용 84㎡대/);assert.match(html,/시장 흐름: 단지 전체 면적/);
assert.match(html,/2026-03~2026-08 · 55건/);assert.match(html,/2026.07~2026.09 · 5건/);
''')

    def test_html_escapes_untrusted_metadata(self):
        run_js(r'''
const item=sample(undefined,{region:'<img src=x onerror=alert(1)>'});
assert.doesNotMatch(zippickDecisionHtml(item,{tone:'yes'}),/<img/);
''')

    def test_card_and_report_six_month_counts_use_the_same_area(self):
        run_js(r"""
const item=sample([13,12.9,13.38,13.5]);
item.roneEstimate.adjustedTransactions.push(trade(13.3,'2026-06-22'),trade(12.8,'2026-06-19'),trade(13,'2026-05-22'),trade(13.3,'2026-05-16'),trade(12.8,'2026-05-15'),trade(13.5,'2026-05-07'),trade(12.8,'2026-05-01'),trade(13.4,'2026-04-11'),trade(13,'2026-04-01'));
item.recentAveragePriceEok=12.63;item.transactionCount=46;
const report=zippickReportPriceData(item),card=candidateHeadlinePrice(item);
assert.equal(report.count,13);assert.equal(report.median,13);
assert.equal(card.countValue,'13');assert.match(card.label,/6개월/);assert.match(card.note,/전용 84㎡대/);
assert.doesNotMatch(zippickPriceEvidenceHtml(item),/46건/);
""")

    def test_missing_school_data_is_not_described_as_good_school_access(self):
        run_js(r"""
const reason=zippickBarReason({}, {reason:'역·학교 접근성이 좋은 편이에요', details:[{label:'교육 접근성',status:'missing'}]});
assert.match(reason,/교육 접근성 자료가 없어/);assert.doesNotMatch(reason,/좋은 편/);
""")
