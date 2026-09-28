import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import policy_evaluator  # noqa: E402


class PolicyEvaluatorTest(unittest.TestCase):
    def test_budget_sheet_policy_and_reference_example(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            cash_eok=20,
            annual_income=13000,
            mortgage_rate=4.3,
            loan_term_years=30,
            purchase_cost_rate=4,
        )

        review = policy_evaluator.purchase_power_review(profile)

        self.assertEqual(policy_evaluator.POLICY["effectiveDate"], "2026-09-27")
        self.assertEqual(policy_evaluator.POLICY["regulatedLtvRate"], 0.4)
        self.assertEqual(policy_evaluator.POLICY["bankDsrRate"], 0.4)
        self.assertEqual(policy_evaluator.POLICY["stressRatePercent"], 3.0)
        self.assertEqual(policy_evaluator.POLICY["purchaseCostRate"], 0.04)
        self.assertEqual(review["dsrLoanLimitEok"], 6.32)
        self.assertEqual(
            [(band["id"], band["reviewAmountEok"]) for band in review["bands"]],
            [("up_to_15", 15.0), ("15_to_25", 23.1)],
        )
        self.assertEqual(review["selectedBandId"], "15_to_25")
        self.assertEqual(review["budgetEok"], 23.1)

    def test_budget_sheet_price_band_boundaries(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", cash_eok=20, annual_income=13000,
            mortgage_rate=4.3, loan_term_years=30, purchase_cost_rate=4,
        )

        expected = ((15, "up_to_15"), (15.01, "15_to_25"), (25, "15_to_25"), (25.01, "over_25"))
        for price, band_id in expected:
            with self.subTest(price=price):
                result = policy_evaluator.purchase_power_price_check(profile, price)
                self.assertEqual(result["bandId"], band_id)

    def test_budget_sheet_price_check_includes_ltv_dsr_costs_and_cash(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", cash_eok=20, annual_income=13000,
            mortgage_rate=4.3, loan_term_years=30, purchase_cost_rate=4,
        )

        result = policy_evaluator.purchase_power_price_check(profile, 15)

        self.assertEqual(result["loanLimitEok"], 6)
        self.assertEqual(result["requiredLoanEok"], 0)
        self.assertTrue(result["isPossible"])

        limited_cash = policy_evaluator.user_profile(
            home_ownership="no_home", cash_eok=5, annual_income=30000,
            mortgage_rate=4.3, loan_term_years=30, purchase_cost_rate=4,
        )
        result = policy_evaluator.purchase_power_price_check(limited_cash, 10)
        self.assertEqual(result["loanLimitEok"], 4)
        self.assertEqual(result["requiredLoanEok"], 5.4)
        self.assertEqual(result["shortageEok"], 1.4)
        self.assertFalse(result["isPossible"])

    def test_capital_term_limit_cannot_be_bypassed_by_long_input(self):
        for years in (30, 40, 50):
            with self.subTest(years=years):
                profile = policy_evaluator.user_profile(
                    home_ownership="no_home", first_time=True, cash_eok=5,
                    annual_income=8000, mortgage_rate=4, loan_term_years=years,
                    purchase_cost_rate=3,
                )
                impact = policy_evaluator.evaluate_candidate(
                    {"region": "서울특별시", "midPriceEok": 9}, profile=profile,
                )
                self.assertEqual(impact["loanTermYears"], 30)
                self.assertEqual(impact["dsrLoanLimitEok"], 4.01)
                self.assertEqual(impact["requiredCashEok"], 5.24)
                self.assertEqual(policy_evaluator.estimated_purchase_ceiling(profile, ["서울특별시"]), 8.7)

    def test_incheon_price_caps_and_additional_home_restriction(self):
        for price, cap in ((15, 6), (15.01, 4), (25, 4), (25.01, 2)):
            profile = policy_evaluator.user_profile(
                home_ownership="no_home", annual_income=30000, mortgage_rate=4,
            )
            impact = policy_evaluator.evaluate_candidate(
                {"region": "인천광역시 연수구", "midPriceEok": price}, profile=profile,
            )
            self.assertTrue(impact["isCapitalRegion"])
            self.assertEqual(impact["estimatedLoanLimitEok"], cap)
        for ownership in ("one_home_keep", "multi_home"):
            impact = policy_evaluator.evaluate_candidate(
                {"midPriceEok": 16}, entity={"city": "인천광역시", "district": "연수구"},
                profile=policy_evaluator.user_profile(home_ownership=ownership),
            )
            self.assertEqual(impact["estimatedLoanLimitEok"], 0)

    def test_regional_dsr_uses_local_rate_without_mutating_profile(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", annual_income=8000, mortgage_rate=4,
            loan_term_years=40,
        )
        original = dict(profile)
        for region, rate, years in (("부산광역시 해운대구", .75, 40), ("서울특별시", 3, 30), ("인천광역시", 3, 30)):
            impact = policy_evaluator.evaluate_candidate(
                {"region": region, "midPriceEok": 12}, profile=profile,
            )
            self.assertEqual(impact["stressRatePercent"], rate)
            self.assertEqual(impact["loanTermYears"], years)
        self.assertEqual(profile, original)
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", annual_income=8000, mortgage_rate=4,
        )
        impact = policy_evaluator.evaluate_candidate(
            {"region": "부산광역시 해운대구", "midPriceEok": 10}, profile=profile,
        )
        self.assertEqual(impact["dsrLoanLimitEok"], 5.11)
        self.assertEqual(impact["estimatedLoanLimitEok"], 5.11)

    def test_local_first_time_ltv_is_eighty_percent(self):
        for first_time, expected in ((True, 80), (False, 70)):
            impact = policy_evaluator.evaluate_candidate(
                {"region": "부산광역시 해운대구", "midPriceEok": 5},
                profile=policy_evaluator.user_profile(home_ownership="no_home", first_time=first_time),
            )
            self.assertEqual(impact["ltvRate"], expected)
            self.assertEqual(impact["estimatedLoanLimitEok"], 5 * expected / 100)

    def test_local_first_time_cap_applies_to_all_price_scenarios(self):
        impact = policy_evaluator.evaluate_candidate(
            {"region": "부산광역시 해운대구", "minPriceEok": 8,
             "midPriceEok": 10, "maxPriceEok": 12},
            profile=policy_evaluator.user_profile(
                home_ownership="no_home", first_time=True,
                annual_income=30000, mortgage_rate=4,
            ),
        )
        self.assertEqual(impact["ltvRate"], 80)
        self.assertEqual(impact["estimatedLoanLimitEok"], 6)
        self.assertEqual(impact["minPriceLoanLimitEok"], 6)
        self.assertEqual(impact["maxPriceLoanLimitEok"], 6)

    def test_summary_uses_candidate_region_and_does_not_mix_dsr_values(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", annual_income=8000, mortgage_rate=4,
        )
        local = policy_evaluator.evaluate_candidate({"region": "부산광역시", "midPriceEok": 10}, profile=profile)
        capital = policy_evaluator.evaluate_candidate({"region": "인천광역시", "midPriceEok": 10}, profile=profile)
        summary = policy_evaluator.summarize([local], profile)
        self.assertEqual(summary["stressRatePercent"], .75)
        self.assertEqual(summary["dsrLoanLimitEok"], 5.11)
        summary = policy_evaluator.summarize([local, capital], profile)
        self.assertIsNone(summary["dsrLoanLimitEok"])
        self.assertIsNone(summary["stressRatePercent"])

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

    def test_first_time_buyer_changes_regulated_ltv_and_purchase_ceiling(self):
        base = {
            "home_ownership": "no_home",
            "cash_eok": "5",
            "annual_income": "10000",
            "mortgage_rate": "4.0",
            "loan_term_years": "30",
            "purchase_cost_rate": "3",
        }
        general = policy_evaluator.user_profile(first_time=False, **base)
        first_time = policy_evaluator.user_profile(first_time=True, **base)

        general_impact = policy_evaluator.evaluate_candidate(
            {"region": "서울시", "midPriceEok": 10},
            profile=general,
        )
        first_time_impact = policy_evaluator.evaluate_candidate(
            {"region": "서울시", "midPriceEok": 10},
            profile=first_time,
        )

        self.assertEqual(general_impact["ltvRate"], 40)
        self.assertEqual(first_time_impact["ltvRate"], 70)
        self.assertGreater(
            policy_evaluator.estimated_purchase_ceiling(first_time, ["서울시"]),
            policy_evaluator.estimated_purchase_ceiling(general, ["서울시"]),
        )

    def test_first_time_selection_does_not_override_existing_home_ownership(self):
        profile = policy_evaluator.user_profile(
            home_ownership="one_home_keep",
            first_time=True,
            cash_eok="5",
        )
        impact = policy_evaluator.evaluate_candidate(
            {"region": "평택시", "midPriceEok": 8},
            profile=profile,
        )

        self.assertTrue(profile["firstTimeRequested"])
        self.assertFalse(profile["firstTimeBuyer"])
        self.assertEqual(impact["ltvRate"], 0)
        self.assertIn("모순", " ".join(impact["warnings"]))

    def test_first_time_acquisition_tax_relief_reduces_purchase_cost(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
            cash_eok="6",
            purchase_cost_rate="3",
        )
        eligible = policy_evaluator.evaluate_candidate(
            {"region": "서울시", "midPriceEok": 10},
            profile=profile,
        )
        over_price_limit = policy_evaluator.evaluate_candidate(
            {"region": "서울시", "midPriceEok": 13},
            profile=profile,
        )

        self.assertEqual(eligible["grossPurchaseCostEok"], 0.3)
        self.assertEqual(eligible["firstTimeAcquisitionTaxReliefEok"], 0.02)
        self.assertEqual(eligible["purchaseCostEok"], 0.28)
        self.assertEqual(over_price_limit["firstTimeAcquisitionTaxReliefEok"], 0)

    def test_first_time_tax_relief_uses_population_decline_region_limit(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
            cash_eok="6",
            purchase_cost_rate="3",
        )
        population_decline = policy_evaluator.evaluate_candidate(
            {"region": "전북특별자치도 정읍시", "midPriceEok": 5},
            profile=profile,
        )
        ambiguous_non_target = policy_evaluator.evaluate_candidate(
            {"region": "대전광역시 동구", "midPriceEok": 5},
            profile=profile,
        )

        self.assertEqual(population_decline["firstTimeAcquisitionTaxReliefEok"], 0.03)
        self.assertEqual(population_decline["purchaseCostEok"], 0.12)
        self.assertEqual(ambiguous_non_target["firstTimeAcquisitionTaxReliefEok"], 0.02)

    def test_first_time_policy_summary_exposes_policy_difference(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
        )
        summary = policy_evaluator.summarize([], profile)

        self.assertTrue(summary["firstTimePolicy"]["selected"])
        self.assertEqual(summary["firstTimePolicy"]["regulatedGeneralLtvRate"], 40)
        self.assertEqual(summary["firstTimePolicy"]["regulatedFirstTimeLtvRate"], 70)
        self.assertEqual(summary["firstTimePolicy"]["acquisitionTaxMaxReliefManwon"], 200)

    def test_purchase_ceiling_is_not_limited_to_thirty_eok(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
            cash_eok="60",
            annual_income="8000",
            mortgage_rate="4.1",
            loan_term_years="30",
            purchase_cost_rate="3",
        )

        ceiling = policy_evaluator.estimated_purchase_ceiling(profile, ["서울시"])

        self.assertGreater(ceiling, 30)
        self.assertEqual(ceiling, 60.1)

    def test_cash_only_purchase_must_include_purchase_costs(self):
        profile = policy_evaluator.user_profile(
            home_ownership="one_home_keep",
            cash_eok="5",
            purchase_cost_rate="3",
        )
        impact = policy_evaluator.evaluate_candidate(
            {"region": "강남구", "midPriceEok": 5},
            profile=profile,
        )

        self.assertLess(impact["cashGapEok"], 0)
        self.assertEqual(impact["status"], "short")

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
        self.assertEqual(impact["minRequiredCashEok"], 3.57)
        self.assertEqual(impact["maxRequiredCashEok"], 4.32)

    def test_candidate_exposes_latest_and_outlier_adjusted_average_cash_scenarios(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home",
            first_time=True,
            cash_eok="4.7",
            annual_income="9000",
            mortgage_rate="4.2",
            loan_term_years="30",
        )
        impact = policy_evaluator.evaluate_candidate(
            {
                "region": "동대문구",
                "midPriceEok": 8.8,
                "latestDealPriceEok": 8.99,
                "recent3AveragePriceEok": 7.76,
                "recent3AdjustedAveragePriceEok": 8.89,
                "recent3TradeCount": 3,
                "recent3AdjustedTradeCount": 2,
                "recent3ExcludedTradeCount": 1,
            },
            profile=profile,
        )

        scenarios = {row["type"]: row for row in impact["cashScenarios"]}
        self.assertEqual(scenarios["latest_deal"]["priceEok"], 8.99)
        self.assertEqual(scenarios["recent3_average"]["priceEok"], 8.89)
        self.assertEqual(scenarios["recent3_average"]["tradeCount"], 2)
        self.assertEqual(scenarios["recent3_average"]["excludedTradeCount"], 1)
        self.assertEqual(
            scenarios["latest_deal"]["cashGapEok"],
            round(profile["cashEok"] - scenarios["latest_deal"]["requiredCashEok"], 2),
        )
        self.assertEqual(
            scenarios["recent3_average"]["cashGapEok"],
            round(profile["cashEok"] - scenarios["recent3_average"]["requiredCashEok"], 2),
        )
        self.assertEqual(impact["requiredCashEok"], max(
            scenarios["latest_deal"]["requiredCashEok"],
            scenarios["recent3_average"]["requiredCashEok"],
        ))

if __name__ == "__main__":
    unittest.main()
