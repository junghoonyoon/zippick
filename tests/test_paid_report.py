"""Report price, finance and comparison contracts, independent of copy styling."""
from pathlib import Path
import shutil
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

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_report_price_and_finance_contracts(self):
        from test_report_quality import run_js
        run_js("""
const item = sample([24,24.1,24.21,24.3,24.4], {policyImpact:{cashScenarios:[
 {priceEok:24,requiredCashEok:20.96,cashGapEok:.04},
 {priceEok:24.21,requiredCashEok:21.18,cashGapEok:-.18}]}});
assert.equal(zippickReportFinance(item).required,21.18);
assert.equal(zippickReportFinance(item).gap,-.18);
assert.equal(zippickPriceCheckBasis(sample([24])),null);
""")
