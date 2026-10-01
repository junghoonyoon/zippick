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
        self.assertIn('조건부로 매수 검토할 만해요. ${conditionalStrength} ${conditionalAction}', html)
        self.assertIn('conditionalChecks.push("하락기 거래")', html)
        names = ['zpNum', 'zippickPriceCheckBasis', 'zippickReportFinance',
                 'zippickDecisionHtml', 'candidateIdentityKey', 'candidateDisplayName', 'zippickReportPeers']
        functions = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in names)
        script = functions + r'''
const assert = require('node:assert/strict');
const esc = value => String(value).replaceAll('<','&lt;');
const transactionMoney = value => `${value}억`;
const zippickWeakestPart = () => null;
const zpScoredParts = () => [];
const zpPartRatio = () => 0;
const zippickLocationEvidenceText = () => '';
const zippickMarketVerdict = () => ({heading:'최근 시장 흐름은 보통이에요'});
const candidateLocationScoreBadgeHtml = () => '';
const candidateFlowScoreBadgeHtml = () => '';
const zippickMarketEvidenceText = () => '';
const zippickBuyBandHtml = () => '';
const zippickVerdictTitle = (_item, verdict) => verdict.peakGuard
  ? '매수 후보로 검토할 만해요. 단지 조건과 최근 흐름은 좋지만 가격은 2년 고점권이에요'
  : verdict.tone === 'yes' ? '매수 후보로 우선 검토할 만해요. 가격·단지 조건·최근 흐름이 좋아요'
  : verdict.tone === 'conditional' ? '조건부로 매수 검토할 만해요. 가격과 단지 조건은 좋지만, 약한 항목을 확인하세요'
  : verdict.tone === 'hold' ? '지금은 매수를 서두르지 마세요. 최근 흐름이 약해요'
  : verdict.tone === 'risk' ? '다른 단지를 먼저 검토하세요. 단지 조건과 최근 흐름이 모두 약해요'
  : '자료가 더 필요해 매수 판단을 보류해요';
const item = {locationScore:{score:71}, signals:{score:52}, apartmentId:'a', name:'A', region:'성동구', areaLabel:'84㎡',
 statsThrough:new Date().toISOString().slice(0,10), recent3AdjustedTradeCount:4,
 recent3AdjustedAveragePriceEok:24.21, latestDealPriceEok:24,
 policyImpact:{cashGapEok:0.04, requiredCashEok:20.96, reportProfile:{cashEok:21},
 cashScenarios:[{priceEok:24,requiredCashEok:20.96,cashGapEok:0.04},
 {priceEok:24.21,requiredCashEok:21.18,cashGapEok:-0.18}]}};
assert.equal(zippickReportFinance(item).required,21.18);
assert.equal(zippickReportFinance(item).gap,-0.18);
const decision = zippickDecisionHtml(item,{tone:'conditional'});
assert.match(decision,/조건부로 매수 검토할 만해요/);
assert.doesNotMatch(decision,/추가 자금|부족한 현금|마련해야|자금 조건/);
assert.equal(decision,zippickDecisionHtml({...item, policyImpact:{}},{tone:'conditional'}));
assert.equal(decision,zippickDecisionHtml({...item, policyImpact:{cashGapEok:100,missingInputs:['income']}},{tone:'conditional'}));
assert.match(zippickDecisionHtml(item,{tone:'yes'}),/매수 후보로 우선 검토할 만해요/);
assert.match(zippickDecisionHtml(item,{tone:'hold'}),/지금은 매수를 서두르지/);
assert.match(zippickDecisionHtml(item,{tone:'risk'}),/다른 단지를 먼저/);
assert.match(zippickDecisionHtml(item,{tone:'conditional',peakGuard:{atPeak:true}}),/가격은 2년 고점권/);
assert.match(zippickDecisionHtml({...item, policyImpact:{}},{tone:'missing'}),/자료가 더 필요해 매수 판단을 보류/);
assert.equal(zippickPriceCheckBasis({...item,statsThrough:'2000-01-01'}).price,24);
const make = (id, region, price, area='84㎡') => ({...item,apartmentId:id,name:id,region,areaLabel:area,
  latestDealDate:new Date().toISOString().slice(0,10),latestDealExclusiveArea:Number(area.replace('㎡','')),
  latestDealPriceEok:price,recent3AdjustedAveragePriceEok:price});
const rows = [item,make('same','성동구',24.4),make('far','강동구',24.22),make('expensive','성동구',40),make('big','성동구',24,'110㎡')];
rows.push(rows[1]);
function candidateRowsForLookup() { return rows; }
assert.deepEqual(zippickReportPeers(item).map(row=>row.apartmentId),['same']);
console.log('ok');
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
