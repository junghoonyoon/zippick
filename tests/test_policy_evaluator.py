import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import policy_evaluator  # noqa: E402


class PolicyEvaluatorTest(unittest.TestCase):
    def test_small_eok_amount_is_displayed_in_manwon(self):
        self.assertEqual(policy_evaluator._money(0.01), "100만원")
        self.assertEqual(policy_evaluator._money(0.34), "3,400만원")
        self.assertEqual(policy_evaluator._money(1.34), "1억 3,400만원")

    def test_guri_is_regulated_from_july_2026(self):
        profile = policy_evaluator.user_profile(home_ownership="no_home", cash_eok="8")
        impact = policy_evaluator.evaluate_candidate(
            {"region": "구리시", "midPriceEok": 12},
            profile=profile,
        )

        self.assertTrue(impact["isRegulated"])
        self.assertEqual(impact["ltvRate"], 40)
        self.assertEqual(impact["estimatedLoanLimitEok"], 4.8)
        self.assertEqual(impact["requiredCashEok"], 7.2)
        self.assertEqual(impact["status"], "possible")

    def test_regulated_price_cap_is_applied_above_fifteen_eok(self):
        profile = policy_evaluator.user_profile(home_ownership="no_home", cash_eok="20")
        impact = policy_evaluator.evaluate_candidate(
            {"region": "강남구", "midPriceEok": 20},
            profile=profile,
        )

        self.assertEqual(impact["ltvLimitEok"], 8)
        self.assertEqual(impact["priceCapEok"], 4)
        self.assertEqual(impact["estimatedLoanLimitEok"], 4)

    def test_additional_home_in_capital_region_has_zero_ltv(self):
        profile = policy_evaluator.user_profile(home_ownership="one_home_keep", cash_eok="5")
        impact = policy_evaluator.evaluate_candidate(
            {"region": "평택시", "midPriceEok": 8},
            profile=profile,
        )

        self.assertFalse(impact["isRegulated"])
        self.assertEqual(impact["ltvRate"], 0)
        self.assertEqual(impact["status"], "restricted")

    def test_income_exposes_simple_dsr_payment_room_without_converting_to_loan(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            annual_income="6000",
            monthly_debt_payment="50",
        )
        impact = policy_evaluator.evaluate_candidate(
            {"region": "노원구", "midPriceEok": 9},
            profile=profile,
        )

        self.assertEqual(impact["dsrAnnualRoomManwon"], 1800)
        self.assertIn("금융회사 심사", " ".join(impact["warnings"]))

    def test_dsr_loan_principal_uses_borrower_and_joint_borrower_debt(self):
        single = policy_evaluator.user_profile(
            annual_income="8000",
            monthly_debt_payment="100",
            mortgage_rate="4.2",
            loan_term_years="30",
        )
        joint = policy_evaluator.user_profile(
            annual_income="8000",
            monthly_debt_payment="100",
            co_borrower="true",
            spouse_annual_income="5000",
            spouse_monthly_debt_payment="50",
            mortgage_rate="4.2",
            loan_term_years="30",
        )

        self.assertGreater(single["dsrLoanLimitEok"], 0)
        self.assertGreater(joint["dsrLoanLimitEok"], single["dsrLoanLimitEok"])
        self.assertEqual(joint["combinedIncomeManwon"], 13000)

    def test_purchase_ceiling_is_derived_from_cash_dsr_and_costs(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            cash_eok="3",
            annual_income="8000",
            mortgage_rate="4.2",
            loan_term_years="30",
            purchase_cost_rate="4",
        )
        ceiling = policy_evaluator.estimated_purchase_ceiling(profile, ["서울시"])

        self.assertGreater(ceiling, 0)
        self.assertLess(ceiling, 15)

    def test_candidate_exposes_required_cash_for_full_transaction_range(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
            cash_eok="6",
            annual_income="9000",
            mortgage_rate="4.2",
            loan_term_years="30",
            purchase_cost_rate="4",
        )
        impact = policy_evaluator.evaluate_candidate(
            {
                "region": "강동구",
                "minPriceEok": 7.7,
                "midPriceEok": 8.3,
                "maxPriceEok": 8.42,
            },
            profile=profile,
        )

        self.assertEqual(impact["dsrLoanLimitEok"], 4.42)
        self.assertEqual(impact["minRequiredCashEok"], 3.59)
        self.assertEqual(impact["maxRequiredCashEok"], 4.34)


if __name__ == "__main__":
    unittest.main()
