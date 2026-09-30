import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import policy_evaluator  # noqa: E402
import purchase_capacity as pc  # noqa: E402


def region_code(district, province=None):
    return next(
        region["code"]
        for region in pc.load_purchase_regions()
        if region["district"] == district and (province is None or region["province"] == province)
    )


def capacity(district="강남구", province="서울특별시", **overrides):
    region = pc.resolve_region_policy(region_code(district, province))
    values = {
        "region_policy": region,
        "home_ownership": "no_home",
        "first_time_buyer": True,
        "own_capital_eok": 2,
        "annual_income_manwon": 10000,
        "monthly_debt_manwon": 0,
        "mortgage_rate_percent": 4.48,
        "loan_term_years": 30,
        # 작업지침서 14번 예시는 스트레스 금리 +3.0%p 전체를 쓰는 변동형 기준이다.
        "rate_type": "variable",
    }
    values.update(overrides)
    return pc.calculate_purchase_capacity(**values)


class MortgagePrincipalTest(unittest.TestCase):
    def test_principal_from_payment_matches_annuity_formula(self):
        # 월 100만원, 연 6%, 30년이면 약 1억 6,679만원.
        principal = pc.calculate_mortgage_principal_from_payment(100, 6, 30)
        self.assertAlmostEqual(principal, 16679.16, places=1)
        # 역산한 원금으로 다시 월 상환액을 계산하면 처음 값이 나온다.
        self.assertAlmostEqual(pc.calculate_monthly_payment(principal, 6, 30), 100, places=6)

    def test_zero_rate_and_zero_payment(self):
        self.assertEqual(pc.calculate_mortgage_principal_from_payment(100, 0, 10), 12000)
        self.assertEqual(pc.calculate_mortgage_principal_from_payment(0, 5, 30), 0)


class RegionPolicyTest(unittest.TestCase):
    def test_region_list_covers_only_seoul_gyeonggi_incheon(self):
        provinces = {region["province"] for region in pc.load_purchase_regions()}
        self.assertEqual(provinces, {"서울특별시", "경기도", "인천광역시"})

    def test_regulated_area_is_resolved_by_district(self):
        cases = {
            ("강남구", "서울특별시"): (True, True),
            ("성남시 수정구", None): (True, True),
            ("용인시 기흥구", None): (True, True),
            ("화성시 동탄구", None): (True, True),
            ("구리시", None): (True, True),
            ("용인시 처인구", None): (True, False),
            ("부평구", "인천광역시"): (True, False),
        }
        for (district, province), expected in cases.items():
            policy = pc.resolve_region_policy(region_code(district, province))
            self.assertEqual((policy["isCapitalArea"], policy["isRegulatedArea"]), expected, district)

    def test_simple_region_groups_follow_regulated_config(self):
        groups = {group["regionCode"]: group for group in pc.purchase_region_groups()}
        self.assertEqual(list(groups), ["seoul", "gyeonggi_regulated", "gyeonggi_general", "incheon"])
        self.assertTrue(groups["seoul"]["isRegulatedArea"])
        self.assertTrue(groups["gyeonggi_regulated"]["isRegulatedArea"])
        self.assertFalse(groups["gyeonggi_general"]["isRegulatedArea"])
        self.assertFalse(groups["incheon"]["isRegulatedArea"])
        snapshot = policy_evaluator.load_policy_snapshot()
        for name in snapshot["regulatedRegions"]["gyeonggi"]:
            self.assertIn(name, groups["gyeonggi_regulated"]["description"])

    def test_simple_region_group_changes_ltv(self):
        regulated = capacity(first_time_buyer=False)
        general = pc.calculate_purchase_capacity(
            region_policy=pc.resolve_region_policy("gyeonggi_general"),
            home_ownership="no_home",
            first_time_buyer=False,
            own_capital_eok=2,
            annual_income_manwon=10000,
            monthly_debt_manwon=0,
            mortgage_rate_percent=4.48,
        )
        self.assertEqual(pc.resolve_region_policy("gyeonggi_regulated")["isRegulatedArea"], True)
        self.assertEqual(regulated["housingPolicy"]["ltv"], 0.4)
        self.assertEqual(general["housingPolicy"]["ltv"], 0.7)

    def test_unknown_region_returns_none(self):
        self.assertIsNone(pc.resolve_region_policy(""))
        self.assertIsNone(pc.resolve_region_policy("99999"))


class HousingPolicyTest(unittest.TestCase):
    def setUp(self):
        self.seoul = pc.resolve_region_policy(region_code("강남구", "서울특별시"))
        self.incheon = pc.resolve_region_policy(region_code("부평구", "인천광역시"))

    def test_ltv_by_buyer_type(self):
        self.assertEqual(pc.get_housing_policy(self.seoul, "no_home", True)["ltv"], 0.7)
        self.assertEqual(pc.get_housing_policy(self.seoul, "no_home", False)["ltv"], 0.4)
        self.assertEqual(pc.get_housing_policy(self.seoul, "conditional_one_home", False)["ltv"], 0.4)
        self.assertEqual(pc.get_housing_policy(self.seoul, "one_home_keep", False)["ltv"], 0.0)
        self.assertEqual(pc.get_housing_policy(self.seoul, "multi_home", False)["ltv"], 0.0)
        self.assertEqual(pc.get_housing_policy(self.incheon, "no_home", False)["ltv"], 0.7)

    def test_policy_values_come_from_config(self):
        snapshot = policy_evaluator.load_policy_snapshot()
        policy = pc.get_housing_policy(self.seoul, "no_home", True, rate_type="variable")
        self.assertEqual(policy["dsr"], snapshot["bankDsrRate"])
        self.assertEqual(policy["stressRatePercent"], snapshot["stressRatePercent"])
        self.assertEqual(policy["maxTermYears"], snapshot["capitalRegionMaxLoanTermYears"])
        self.assertEqual(policy["policyDate"], "2026-09-30")
        self.assertEqual([band["loanCapEok"] for band in policy["mortgageAbsoluteLimits"]], [6, 4, 2])

    def test_stress_rate_depends_on_rate_type_and_region(self):
        snapshot = policy_evaluator.load_policy_snapshot()
        capital = snapshot["stressRatePercent"]
        ratios = snapshot["stressRateRatios"]["capitalOrRegulated"]
        # 수도권·규제지역 3.0%p × 주기형 40% / 혼합형 80% / 변동형 100%.
        self.assertEqual(pc.resolve_stress_rate(True, "periodic")["percent"], round(capital * ratios["periodic"], 4))
        self.assertEqual(pc.resolve_stress_rate(True, "periodic")["percent"], 1.2)
        self.assertEqual(pc.resolve_stress_rate(True, "mixed")["percent"], 2.4)
        self.assertEqual(pc.resolve_stress_rate(True, "variable")["percent"], 3.0)
        # 지방은 0.75%p × 30% / 60% / 100%.
        self.assertEqual(pc.resolve_stress_rate(False, "periodic")["percent"], 0.225)
        self.assertEqual(pc.resolve_stress_rate(False, "mixed")["percent"], 0.45)
        self.assertEqual(pc.resolve_stress_rate(False, "variable")["percent"], 0.75)
        # 금리 유형을 고르지 않으면 설정의 기본값(주기형)을 쓴다.
        self.assertEqual(pc.resolve_stress_rate(True, None)["rateType"], "periodic")

    def test_absolute_limit_by_price(self):
        policy = pc.get_housing_policy(self.seoul, "no_home", False)
        self.assertEqual(pc.resolve_mortgage_absolute_limit(15, policy), 6)
        self.assertEqual(pc.resolve_mortgage_absolute_limit(15.01, policy), 4)
        self.assertEqual(pc.resolve_mortgage_absolute_limit(25, policy), 4)
        self.assertEqual(pc.resolve_mortgage_absolute_limit(30, policy), 2)


class MaxPurchasePriceTest(unittest.TestCase):
    def test_reference_case_from_work_order(self):
        result = capacity()

        # 심사 금리 4.48% + 3.0%p = 7.48%, DSR 한도 약 4.78억원.
        self.assertEqual(result["stressedRatePercent"], 7.48)
        self.assertAlmostEqual(result["dsrLimitEok"], 4.78, delta=0.01)
        # P × 30% <= 2억원 → 약 6.667억원. 100만원 단위로 내려 6억 6,600만원.
        maximum = result["maxPurchase"]
        self.assertEqual(maximum["priceEok"], 6.66)
        self.assertEqual(maximum["loanEok"], 4.66)
        self.assertLessEqual(maximum["loanEok"], result["dsrLimitEok"])
        self.assertEqual(result["constraint"]["type"], "LTV")
        self.assertIn("LTV가 먼저 제한", result["constraint"]["message"])
        self.assertEqual(pc.format_korean_money(maximum["priceEok"]), "6억 6,600만원")
        # 부대비용 4%를 넣으면 2억 ÷ 0.34 = 5.88억원.
        self.assertEqual(result["costAdjusted"]["priceEok"], 5.88)

    def test_periodic_rate_raises_dsr_limit(self):
        variable = capacity(annual_income_manwon=6000)
        periodic = capacity(annual_income_manwon=6000, rate_type="periodic")
        # 심사 금리 4.48% + 1.2%p = 5.68%라 DSR 한도가 변동형보다 커진다.
        self.assertEqual(periodic["stressedRatePercent"], 5.68)
        self.assertGreater(periodic["dsrLimitEok"], variable["dsrLimitEok"])
        self.assertGreater(periodic["maxPurchase"]["priceEok"], variable["maxPurchase"]["priceEok"])

    def test_dsr_binds_for_lower_income(self):
        result = capacity(annual_income_manwon=6000)
        self.assertEqual(result["constraint"]["type"], "DSR")
        # 집값을 100만원 단위로 내리므로 대출은 DSR 한도보다 100만원 안쪽으로 적다.
        self.assertLessEqual(result["maxPurchase"]["loanEok"], result["dsrLimitEok"])
        self.assertLess(result["dsrLimitEok"] - result["maxPurchase"]["loanEok"], 0.01)

    def test_existing_debt_reduces_dsr_and_is_named(self):
        without = capacity(annual_income_manwon=6000)
        with_debt = capacity(annual_income_manwon=6000, monthly_debt_manwon=50)
        self.assertLess(with_debt["dsrLimitEok"], without["dsrLimitEok"])
        self.assertEqual(with_debt["constraint"]["type"], "EXISTING_DEBT")

    def test_exhausted_dsr_explains_no_additional_loan(self):
        result = capacity(annual_income_manwon=6000, monthly_debt_manwon=200)
        self.assertEqual(result["dsrLimitEok"], 0)
        self.assertEqual(result["maxPurchase"]["priceEok"], 2)
        self.assertEqual(result["constraint"]["type"], "EXISTING_DEBT")
        self.assertIn("추가 주택담보대출 여력이 없는", result["constraint"]["message"])

    def test_mortgage_cap_binds_before_dsr(self):
        # 자기자금 10억, 연소득 3억: LTV 40%로 16.6억이 가능하지만 15억 초과 구간은 한도 4억.
        result = capacity(first_time_buyer=False, own_capital_eok=10, annual_income_manwon=30000)
        self.assertEqual(result["maxPurchase"]["priceEok"], 15)
        self.assertEqual(result["constraint"]["type"], "MORTGAGE_CAP")

    def test_higher_price_segment_is_chosen_when_it_is_larger(self):
        # 자기자금 20억, 연소득 1.3억: 15억 이하 구간은 15억, 15~25억 구간은 20억 + 4억 = 24억.
        result = capacity(first_time_buyer=False, own_capital_eok=20, annual_income_manwon=13000)
        self.assertEqual(result["maxPurchase"]["segmentId"], "band_2")
        self.assertEqual(result["maxPurchase"]["priceEok"], 24)

    def test_home_owner_restriction_uses_cash_only(self):
        result = capacity(home_ownership="one_home_keep", first_time_buyer=False, own_capital_eok=5)
        self.assertEqual(result["maxPurchase"]["priceEok"], 5)
        self.assertEqual(result["maxPurchase"]["loanEok"], 0)
        self.assertEqual(result["constraint"]["type"], "OWNER_RESTRICTION")

    def test_non_regulated_capital_region_uses_general_ltv(self):
        result = capacity(district="부평구", province="인천광역시", first_time_buyer=False, annual_income_manwon=20000)
        self.assertEqual(result["housingPolicy"]["ltv"], 0.7)
        self.assertEqual(result["constraint"]["type"], "LTV")

    def test_default_rate_and_term_come_from_config(self):
        result = capacity(mortgage_rate_percent=None, loan_term_years=None)
        snapshot = policy_evaluator.load_policy_snapshot()
        self.assertEqual(result["mortgageRate"]["valuePercent"], snapshot["mortgageRateDefault"]["value"])
        self.assertTrue(result["mortgageRate"]["isDefault"])
        self.assertEqual(result["loanTermYears"], 30)
        # 수도권에서 40년을 골라도 정책 상한 30년으로 계산한다.
        self.assertEqual(capacity(loan_term_years=40)["loanTermYears"], 30)


class ValidationTest(unittest.TestCase):
    def base(self, **overrides):
        values = {
            "purchase_region": region_code("강남구", "서울특별시"),
            "home_ownership": "no_home",
            "first_time": "true",
            "cash_eok": "2",
            "annual_income": "10000",
        }
        values.update(overrides)
        return pc.validate_purchase_inputs(values)[0]

    def test_valid_input_has_no_errors(self):
        self.assertEqual(self.base(), [])

    def test_missing_region(self):
        self.assertIn("구매 희망지역을 선택해주세요", self.base(purchase_region=""))

    def test_invalid_numbers(self):
        self.assertIn("연소득은 0보다 커야 해요.", self.base(annual_income="0"))
        self.assertIn("자기자금은 0보다 커야 해요.", self.base(cash_eok="0"))
        self.assertIn("자기자금은 숫자로 입력해 주세요.", self.base(cash_eok="abc"))
        self.assertIn("월 대출 상환액은 0보다 작을 수 없어요.", self.base(monthly_debt_payment="-1"))
        self.assertIn("자기자금 값을 확인해 주세요.", self.base(cash_eok="inf"))
        self.assertIn("자기자금 값을 확인해 주세요.", self.base(cash_eok="nan"))
        self.assertIn("자기자금이 너무 커요. 단위를 확인해 주세요.", self.base(cash_eok="100000"))

    def test_rate_type_must_be_known(self):
        self.assertEqual(self.base(rate_type="mixed"), [])
        self.assertIn("금리 유형을 다시 선택해 주세요.", self.base(rate_type="fixed"))

    def test_reserve_cash_must_be_less_than_cash(self):
        self.assertEqual(self.base(reserve_cash_eok="0.3"), [])
        self.assertIn("남겨둘 돈은 자기자금보다 적어야 해요.", self.base(reserve_cash_eok="2"))
        self.assertIn("남겨둘 돈은 0보다 작을 수 없어요.", self.base(reserve_cash_eok="-1"))

    def test_first_time_conflict_with_owned_home(self):
        errors = self.base(home_ownership="multi_home")
        self.assertTrue(any("생애최초" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
