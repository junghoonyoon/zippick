import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import breakeven  # noqa: E402


EOK = 100000000


class AcquisitionTaxTest(unittest.TestCase):
    def test_under_six_eok_uses_one_percent(self):
        result = breakeven.acquisition_tax(5 * EOK, area_sqm=59.8)
        self.assertAlmostEqual(result["rate"], 0.011, places=4)

    def test_over_nine_eok_uses_three_percent(self):
        result = breakeven.acquisition_tax(10 * EOK, area_sqm=59.8)
        self.assertAlmostEqual(result["rate"], 0.033, places=4)

    def test_large_area_adds_rural_tax(self):
        small = breakeven.acquisition_tax(10 * EOK, area_sqm=59.8)
        large = breakeven.acquisition_tax(10 * EOK, area_sqm=114.0)
        self.assertAlmostEqual(large["rate"] - small["rate"], 0.002, places=4)

    def test_middle_band_is_between_one_and_three_percent(self):
        result = breakeven.acquisition_tax(7 * EOK, area_sqm=59.8)
        self.assertGreater(result["rate"], 0.011)
        self.assertLess(result["rate"], 0.033)

    def test_multi_house_owner_is_not_calculated(self):
        self.assertIsNone(breakeven.acquisition_tax(10 * EOK, owned_houses=2))


class BrokerageFeeTest(unittest.TestCase):
    def test_rate_rises_with_price(self):
        cheap = breakeven.brokerage_fee(8 * EOK)["rate"]
        mid = breakeven.brokerage_fee(10 * EOK)["rate"]
        expensive = breakeven.brokerage_fee(16 * EOK)["rate"]
        self.assertLess(cheap, mid)
        self.assertLess(mid, expensive)


class CalculateTest(unittest.TestCase):
    def test_breakeven_rate_is_positive_and_reasonable(self):
        result = breakeven.calculate(1040000000, years=3, area_sqm=59.84)
        self.assertGreater(result["ratePercent"], 3)
        self.assertLess(result["ratePercent"], 8)

    def test_total_matches_item_sum(self):
        result = breakeven.calculate(1040000000, years=3, area_sqm=59.84)
        self.assertEqual(
            result["totalAmount"],
            sum(item["amount"] for item in result["items"]),
        )

    def test_headline_names_the_years_and_rate(self):
        result = breakeven.calculate(1040000000, years=3, area_sqm=59.84)
        self.assertIn("3년", result["headline"])
        self.assertIn(str(result["ratePercent"]), result["headline"])

    def test_expensive_house_leaves_capital_gains_uncertain(self):
        result = breakeven.calculate(25 * EOK, years=3, area_sqm=84.9)
        self.assertIn("양도세", result["uncertainItems"])

    def test_loan_interest_is_never_included(self):
        result = breakeven.calculate(1040000000, years=3, area_sqm=59.84)
        self.assertIn("대출 이자", result["excludes"])
        keys = {item["key"] for item in result["items"]}
        self.assertNotIn("interest", keys)

    def test_missing_price_returns_none(self):
        self.assertIsNone(breakeven.calculate(None))
        self.assertIsNone(breakeven.calculate(0))


if __name__ == "__main__":
    unittest.main()
