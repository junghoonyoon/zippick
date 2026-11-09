"""Report price, finance and comparison contracts, independent of copy styling."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import policy_evaluator
import momentum_signals


class PaidReportTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_report_distinguishes_a_measured_zero_from_a_missing_signal(self):
        html = (ROOT / '앱화면/real-estate-search.html').read_text()
        matrix = re.search(r'    const ZIPPICK_MATRIX = \[.*?\n    \];', html, re.S).group()
        names = ['zpNum', 'zippickMatrixVerdict', 'zippickPartialVerdict',
                 'zippickCommonProperty', 'zippickCommonPurchaseVerdict',
                 'zippickBandPriceEvidence', 'zippickLatestTradeDetails', 'zippickTradeAreaScope',
                 'zippickAreaContains', 'zippickBuyBandTradeMatchesArea', 'zippickBuyBandTier',
                 'candidateFlowScoreBadgeHtml', 'candidateReadonlyFlowScoreBadgeHtml',
                 'signalBadgesHtml', 'candidateZippickReportHtml']
        functions = '\n'.join(re.search(
            r'    function ' + name + r'\([^\n]*\) \{.*?\n    \}', html, re.S,
        ).group() for name in names)
        stubs = ['zippickCommonPropertyHtml', 'zippickLocationBarsHtml', 'zippickSignalBarsHtml', 'zippickReportMapHtml',
                 'zippickPriceEvidenceHtml', 'zippickCommuteHtml', 'zippickLiquidityHtml',
                 'zippickLifestyleChangeHtml', 'zippickFundingHtml', 'zippickDevelopmentHtml',
                 'zippickAlternativesHtml', 'zippickBreakevenHtml', 'zippickSignalLabel',
                 'zippickEvidenceHtml', 'zippickMatrixTableHtml', 'zippickViewingChecklistHtml']
        script = matrix + functions + '\n' + '\n'.join(
            f'function {name}() {{ return ""; }}' for name in stubs
        ) + r'''
const assert = require('node:assert/strict');
const esc = String;
const candidateDisplayName = item => item.name;
const candidateShouldWaitForScores = () => false;
const zippickGuardVerdict = (_item, verdict) => verdict;
const zippickNumberSteps = html => html;
const zippickDecisionHtml = (_item, verdict) => `verdict:${verdict.tone}`;
const signalTierLabel = () => '신호 적음';
const base = {name:'테스트',locationScore:{score:78}};
const zero = {...base,signals:{status:'ok',score:0}};
// A measured zero is still displayed; no price/property evidence means unknown, not hold.
assert.match(candidateZippickReportHtml(zero),/verdict:missing/);
assert.match(signalBadgesHtml(zero),/최근 시장 신호 0점/);
assert.match(signalBadgesHtml({...base,signals:{status:'insufficient',score:''}}),/표본 부족/);
for (const badge of [candidateFlowScoreBadgeHtml, candidateReadonlyFlowScoreBadgeHtml]) {
  assert.match(badge(zero),/최근 시장 신호 0점/);
  for (const score of [null,undefined,'']) {
    assert.match(badge({...base,signals:{status:'insufficient',score}}),/측정 불가/);
  }
}
assert.match(candidateZippickReportHtml({...base,signals:{status:'insufficient',score:null}}),/verdict:missing/);
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_report_keeps_a_cautious_verdict_when_only_market_score_is_missing(self):
        html = (ROOT / '앱화면/real-estate-search.html').read_text()
        matrix = re.search(r'    function zippickMatrixVerdict\([^\n]*\) \{.*?\n    \}', html, re.S)
        partial = re.search(r'    function zippickPartialVerdict\([^\n]*\) \{.*?\n    \}', html, re.S)
        self.assertIsNotNone(matrix)
        self.assertIsNotNone(partial)
        script = matrix.group() + partial.group() + r'''
const assert = require('node:assert/strict');
const latest = new Date().toISOString().slice(0, 10);
const incompleteMarket = zippickPartialVerdict({
  locationScore:{score:78}, signals:{score:null}, priceIdentityVerified:true,
  latestDealPriceEok:20.6, latestDealDate:latest, transactionCount:2,
}, zippickMatrixVerdict(78, null));
assert.equal(incompleteMarket.tone, 'conditional');
assert.equal(incompleteMarket.partial, true);
const noVerifiedTrade = zippickPartialVerdict({
  locationScore:{score:78}, signals:{score:null}, priceIdentityVerified:false,
  latestDealPriceEok:20.6, latestDealDate:latest,
}, zippickMatrixVerdict(78, null));
assert.equal(noVerifiedTrade.tone, 'missing');
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_report_peer_lookup_finishes_loading(self):
        html = (ROOT / '앱화면/real-estate-search.html').read_text()
        lookup = re.search(
            r'    async function ensureZippickReportPeers\([^\n]*\) \{.*?\n    \}',
            html, re.S,
        )
        self.assertIsNotNone(lookup)
        self.assertIn('await ensureZippickReportPeers(report)', html)
        self.assertNotIn('현재 검색 결과 밖의 단지도 확인하고 있어요.', html)
        helper = re.search(r'    function zippickRefreshReportLocation\([^\n]*\) \{.*?\n    \}', html, re.S)
        area_helpers = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group()
                                 for name in ['zpNum', 'zippickTradeAreaScope', 'zippickAreaContains', 'zippickLatestTradeDetails',
                                              'zippickValuationMatchesTrade', 'zippickReportAreaKey'])
        script = area_helpers + helper.group() + lookup.group() + r'''
const assert = require('node:assert/strict');
let fetchAptReport = async () => ({report:{peers:[{apartmentId:'peer-1'}]}});
(async () => {
  const item = {name:'테스트 단지', region:'성남수정구', peers:[], reportPeerState:'pending'};
  const states = [];
  await ensureZippickReportPeers(item, () => states.push(item.reportPeerState));
  assert.deepEqual(states, ['loading', 'ready']);
  assert.equal(item.peers[0].apartmentId, 'peer-1');
  fetchAptReport = async () => { throw new Error('network error'); };
  const failed = {name:'다른 단지', region:'성남수정구', peers:[], reportPeerState:'pending'};
  await ensureZippickReportPeers(failed);
  assert.equal(failed.reportPeerState, 'error');
})().catch(error => { console.error(error); process.exit(1); });
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repayment_separates_interest_from_principal(self):
        result = policy_evaluator.report_loan_repayment(1, 12, 1)
        self.assertAlmostEqual(result['monthlyPaymentManwon'], 888.49, places=2)
        self.assertAlmostEqual(result['first3YearsInterestEok'], 0.0662, places=4)
        zero = policy_evaluator.report_loan_repayment(1, 0, 1)
        self.assertEqual(zero['first3YearsInterestEok'], 0)
        self.assertEqual(zero['monthlyPaymentManwon'], 833.33)
        self.assertIsNone(policy_evaluator.report_loan_repayment(1, None, 30))

    def test_each_price_scenario_keeps_its_own_cash_and_repayment(self):
        profile = policy_evaluator.user_profile(home_ownership='no_home', cash_eok=21,
            annual_income=13000, mortgage_rate=4.3, loan_term_years=30, purchase_cost_rate=4)
        result = policy_evaluator.evaluate_candidate({'region':'서울특별시 성동구',
            'latestDealPriceEok':24, 'recent3AdjustedAveragePriceEok':24.21,
            'recent3AdjustedTradeCount':4}, profile=profile)
        latest, average = result['cashScenarios']
        self.assertEqual(latest['priceEok'], 24)
        self.assertEqual(average['priceEok'], 24.21)
        self.assertGreater(latest['cashGapEok'], average['cashGapEok'])
        self.assertLess(average['cashGapEok'], 0)
        self.assertEqual(average['repayment']['ratePercent'], 4.3)
        self.assertEqual(result['reportProfile']['cashEok'], 21)

    def test_signal_basis_excludes_current_month_even_when_data_is_missing(self):
        result = momentum_signals.raw_signals('표본없음', transactions=[])
        basis = result['comparisonBasis']
        self.assertEqual(basis['recent3End'], momentum_signals._months_ago(1))
        self.assertEqual(basis['recent3Start'], momentum_signals._months_ago(3))
        self.assertEqual(basis['prior3End'], momentum_signals._months_ago(4))
        self.assertEqual(basis['prior6Start'], momentum_signals._months_ago(12))

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_report_uses_matching_price_scenario_and_handles_missing_data(self):
        html = (ROOT / '앱화면/real-estate-search.html').read_text()
        names = ['zpNum', 'zippickPriceCheckBasis', 'zippickReportFinance',
                 'zippickCommonProperty', 'zippickCommonPurchaseVerdict', 'zippickBandPriceEvidence',
                 'zippickTradeAreaScope', 'zippickAreaContains', 'zippickLatestTradeDetails',
                 'zippickBuyBandTradeMatchesArea', 'zippickBuyBandTier', 'zippickValuationMatchesTrade',
                 'zippickDecisionHtml', 'zippickCommonDecisionHtml', 'zippickReportPeers']
        functions = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in names)
        script = functions + r'''
const assert = require('node:assert/strict');
const esc=String, zippickPriceBasesHtml=()=>'', zippickDecisionScoresHtml=()=>'', zippickBuyBandHtml=()=>'';
const zippickOverallRatingHtml=verdict=>verdict.label;
const metric=(key)=>({key,score:80,status:'ok',reason:'확인됨'});
const item={apartmentId:'a',name:'A',region:'성동구',areaLabel:'84㎡',
 locationScore:{parts:[{key:'demand',details:[metric('station'),metric('education')]},
  {key:'product',details:[metric('households'),metric('age')]}]},
 signals:{recentDealCount:10,priorDealCount:12},
 priceComparison:{status:'ready',method:'usual_gap',shiftPp:5,averagePriceEok:24.21,
  periodMonths:6,throughMonth:'2026-10',transactionCount:10,peers:[{tier:0},{tier:0}]},
 statsThrough:new Date().toISOString().slice(0,10),recent3AdjustedTradeCount:4,
 recent3AdjustedAveragePriceEok:24.21,latestDealPriceEok:24,
 policyImpact:{cashGapEok:0.04,requiredCashEok:20.96,reportProfile:{cashEok:21},
  cashScenarios:[{priceEok:24,requiredCashEok:20.96,cashGapEok:0.04},
   {priceEok:24.21,requiredCashEok:21.18,cashGapEok:-0.18}]}};
const finance=zippickReportFinance(item);
assert.equal(finance.scenario.priceEok,24.21);
assert.equal(finance.required,21.18);assert.equal(finance.gap,-0.18);
const stale={...item,statsThrough:'2000-01-01'};
assert.equal(zippickPriceCheckBasis(stale).price,24);
assert.equal(zippickReportFinance(stale).required,20.96);
assert.equal(zippickReportFinance(stale).gap,0.04);
const missing=zippickReportFinance({...item,policyImpact:{}});
assert.equal(missing.scenarios.length,0);assert.equal(missing.scenario,undefined);
assert(Number.isNaN(missing.required));assert(Number.isNaN(missing.gap));
const render=value=>zippickDecisionHtml(value,zippickCommonPurchaseVerdict(value,new Date(2026,10,9)));
const decision=render(item);
assert.match(decision,/조건부 검토/);assert.match(decision,/단지 조건은 좋지만.*비싸요/);
assert.doesNotMatch(decision,/추가 자금|부족한 현금|마련해야|자금 조건/);
assert.equal(decision,render({...item,policyImpact:{}}));
assert.equal(decision,render({...item,policyImpact:{cashGapEok:100,missingInputs:['income']}}));
assert.match(render({...item,locationScore:{}}),/판단 보류.*확인된 항목이 적어요/s);
const candidateHeadlinePrice=()=>({priceEok:24});
const make=(id,region,price,area=84)=>({...item,apartmentId:id,name:id,region,areaLabel:`${area}㎡`,
 latestDealDate:'2026-10-01',latestDealExclusiveArea:area,latestDealPriceEok:price});
const rows=[item,make('same','성동구',24.4),make('far','강동구',24.22),make('expensive','성동구',40),make('big','성동구',24,110)];
rows.push(rows[1]);
function candidateRowsForLookup(){return rows;}
assert.deepEqual(zippickReportPeers(item).map(row=>row.apartmentId),['same']);
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
