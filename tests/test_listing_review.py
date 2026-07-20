import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import listing_review


def affordability(sample_count=8):
    return {
        "selectedArea": "59.4",
        "areaBasis": "전용 59.4㎡ 최근 거래 기준",
        "estimate": {
            "minPriceEok": 8.5,
            "midPriceEok": 8.8,
            "maxPriceEok": 9.1,
            "sampleCount": sample_count,
            "confidence": "높음",
            "latestTradeDate": "2026-06-20",
            "latestTradeAgeDays": 30,
            "method": "최근 동일 평형 실거래",
            "source": "molit",
        },
        "market": {
            "adjustedTransactions": [
                {
                    "dealDate": "2026-06-20",
                    "originalPriceEok": 9.0,
                    "adjustedPriceEok": 9.0,
                    "exclusiveArea": 59.4,
                    "floor": "12",
                },
                {
                    "dealDate": "2026-05-12",
                    "originalPriceEok": 8.7,
                    "adjustedPriceEok": 8.75,
                    "exclusiveArea": 59.4,
                    "floor": "7",
                },
            ],
        },
    }


def profile(cash_eok=5):
    return {
        "home_ownership": "no_home",
        "first_time": "true",
        "cash_eok": cash_eok,
        "annual_income": 8000,
        "monthly_debt_payment": 0,
        "co_borrower": "false",
        "mortgage_rate": 4.1,
        "loan_term_years": 30,
        "purchase_cost_rate": 0,
    }


class ListingReviewTests(unittest.TestCase):
    def test_builds_price_and_financing_review(self):
        result = listing_review.build_review(
            {
                "name": "꿈의숲해링턴플레이스",
                "region": "강북구",
                "asking_price_eok": 9.2,
                "area": "59.4",
                "floor": "12",
                "orientation": "south",
                "condition": "original",
                "repair_cost_manwon": 3000,
                "tenancy": "vacant",
                "profile": profile(cash_eok=6),
            },
            affordability(),
        )

        self.assertEqual(result["verdict"]["code"], "negotiate")
        self.assertEqual(result["pricing"]["askingPriceEok"], 9.2)
        self.assertLess(result["pricing"]["reviewCeilingPriceEok"], 9.2)
        self.assertGreater(result["financing"]["monthlyPaymentManwon"], 0)
        self.assertGreater(
            result["financing"]["stressMonthlyPaymentManwon"],
            result["financing"]["monthlyPaymentManwon"],
        )
        self.assertEqual(
            result["financing"]["purchaseCostRatePercent"],
            listing_review.DEFAULT_PURCHASE_COST_RATE_PERCENT,
        )
        self.assertTrue(result["checklist"])
        self.assertTrue(result["comparables"])

    def test_marks_funding_shortage_before_price_opinion(self):
        result = listing_review.build_review(
            {
                "name": "꿈의숲해링턴플레이스",
                "region": "강북구",
                "asking_price_eok": 9.0,
                "profile": profile(cash_eok=0.5),
            },
            affordability(),
        )

        self.assertEqual(result["verdict"]["code"], "funding_short")
        self.assertLess(result["financing"]["cashGapEok"], 0)
        self.assertTrue(any(row["level"] == "high" for row in result["risks"]))

    def test_allows_price_only_review_without_financial_profile(self):
        result = listing_review.build_review(
            {
                "name": "꿈의숲해링턴플레이스",
                "region": "강북구",
                "asking_price_eok": 8.7,
            },
            affordability(),
        )

        self.assertFalse(result["financing"]["profileComplete"])
        self.assertIsNone(result["financing"]["monthlyPaymentManwon"])
        self.assertEqual(result["verdict"]["code"], "reviewable")

    def test_requires_asking_price(self):
        with self.assertRaisesRegex(ValueError, "매물가격"):
            listing_review.build_review(
                {"name": "꿈의숲해링턴플레이스", "region": "강북구"},
                affordability(),
            )


if __name__ == "__main__":
    unittest.main()
