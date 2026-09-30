import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import policy_evaluator  # noqa: E402


class PolicyEvaluatorTest(unittest.TestCase):
    def test_budget_sheet_policy_and_reference_example(self):
        profile = policy_evaluator.user_profile(
            mortgage_rate_type="variable",
            home_ownership="no_home",
            first_time=True,
            cash_eok=2,
            annual_income=10000,
            mortgage_rate=4.48,
            loan_term_years=30,
            purchase_cost_rate=4,
        )

        review = policy_evaluator.purchase_power_review(profile, region_code="11680")

        self.assertEqual(policy_evaluator.POLICY["effectiveDate"], "2026-09-30")
        self.assertEqual(policy_evaluator.POLICY["regulatedLtvRate"], 0.4)
        self.assertEqual(policy_evaluator.POLICY["bankDsrRate"], 0.4)
        self.assertEqual(policy_evaluator.POLICY["stressRatePercent"], 3.0)
        self.assertEqual(policy_evaluator.POLICY["purchaseCostRate"], 0.04)
        # 작업지침서 예시: 서울·생애최초·자기자금 2억·연소득 1억·금리 4.48%.
        self.assertEqual(review["budgetEok"], 6.66)
        self.assertEqual(review["readyBudgetEok"], 5.88)
        self.assertEqual(review["constraint"]["type"], "LTV")
        self.assertEqual(review["ltvRate"], 0.7)
        self.assertEqual(review["appliedRatePercent"], 7.48)

    def test_purchase_power_review_keeps_reserve_cash_out_of_the_home_price(self):
        profile = policy_evaluator.user_profile(
            home_ownership="no_home", first_time=True, cash_eok=2, annual_income=10000, mortgage_rate=4.48,
        )
        review = policy_evaluator.purchase_power_review(profile, region_code="seoul", reserve_cash_eok=0.3)
        # 2억 중 3,000만원을 남기면 1.7억 ÷ 30% = 5.666억원 → 5.66억원.
        self.assertEqual(review["totalCashEok"], 2)
        self.assertEqual(review["reserveCashEok"], 0.3)
        self.assertEqual(review["cashEok"], 1.7)
        self.assertEqual(review["budgetEok"], 5.66)
        self.assertEqual(review["maxPurchase"]["ownCapitalUsedEok"], 1.7)

    def test_purchase_power_review_requires_purchase_region(self):
        profile = policy_evaluator.user_profile(home_ownership="no_home", cash_eok=2, annual_income=10000)
        with self.assertRaises(ValueError):
            policy_evaluator.purchase_power_review(profile)

    def test_purchase_power_review_uses_region_policy(self):
        base = {"home_ownership": "no_home", "cash_eok": 2, "annual_income": 10000, "mortgage_rate": 4.48}
        seoul = policy_evaluator.purchase_power_review(
            policy_evaluator.user_profile(first_time=False, **base), region_code="11680"
        )
        incheon_code = next(
            region["code"] for region in __import__("purchase_capacity").load_purchase_regions()
            if region["province"] == "인천광역시" and region["district"] == "부평구"
        )
        incheon = policy_evaluator.purchase_power_review(
            policy_evaluator.user_profile(first_time=False, **base), region_code=incheon_code
        )
        # 서울(규제지역) 일반 무주택 LTV 40%: 2억 ÷ 0.6 = 3.33억원.
        self.assertEqual(seoul["ltvRate"], 0.4)
        self.assertEqual(seoul["budgetEok"], 3.33)
        # 인천 부평구(수도권 비규제) LTV 70%.
        self.assertEqual(incheon["ltvRate"], 0.7)
        self.assertGreater(incheon["budgetEok"], seoul["budgetEok"])

    def test_capital_term_limit_cannot_be_bypassed_by_long_input(self):
        for years in (30, 40, 50):
            with self.subTest(years=years):
                profile = policy_evaluator.user_profile(
                    home_ownership="no_home", first_time=True, cash_eok=5,
                    annual_income=8000, mortgage_rate=4, loan_term_years=years,
                    purchase_cost_rate=3, mortgage_rate_type="variable",
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
            mortgage_rate_type="variable",
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
            mortgage_rate_type="variable",
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
            mortgage_rate_type="variable",
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
            mortgage_rate_type="variable",
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
