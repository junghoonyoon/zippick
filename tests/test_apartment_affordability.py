import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import search_server  # noqa: E402


ESTIMATE_PAYLOAD = {
    "estimate": {
        "minPriceEok": 8.0,
        "midPriceEok": 9.0,
        "maxPriceEok": 10.0,
        "confidence": "높음",
        "sampleCount": 12,
        "latestTradeDate": "2026-07-01",
        "latestTradeAgeDays": 16,
        "method": "거래별 R-ONE 지수보정",
    },
    "latestTrade": {
        "dealDate": "2026-07-01",
        "dealAmountEok": 9.2,
        "exclusiveArea": 59.8,
        "floor": "10",
    },
    "adjustedTransactions": [
        {
            "dealDate": "2026-07-01",
            "originalPriceEok": 9.2,
            "adjustedPriceEok": 9.2,
            "basePeriod": "202607",
            "baseIndex": 100.0,
        },
    ],
    "index": {
        "region": "경기>성남시>분당구",
        "latestPeriod": "202607",
        "latestValue": 100.0,
    },
}


class ApartmentAffordabilityTest(unittest.TestCase):
    def test_price_is_returned_without_a_purchase_profile(self):
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=(ESTIMATE_PAYLOAD, 200),
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "성남분당구",
                "months": 24,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertFalse(payload["profileComplete"])
        self.assertEqual(payload["estimate"]["minPriceEok"], 8.0)
        self.assertEqual(len(payload["market"]["adjustedTransactions"]), 1)
        self.assertEqual(payload["market"]["index"]["latestPeriod"], "202607")
        self.assertNotIn("policyImpact", payload)

    def test_complete_profile_returns_required_cash_and_shortage(self):
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=(ESTIMATE_PAYLOAD, 200),
        ), mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=None,
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "성남분당구",
                "profile": {
                    "home_ownership": "no_home",
                    "first_time": "false",
                    "cash_eok": "2",
                    "annual_income": "7000",
                    "monthly_debt_payment": "0",
                    "co_borrower": "false",
                    "mortgage_rate": "4.3",
                    "loan_term_years": "30",
                    "purchase_cost_rate": "3",
                },
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["profileComplete"])
        self.assertEqual(payload["profile"]["cashEok"], 2.0)
        self.assertIn(payload["policyImpact"]["status"], {"short", "restricted"})
        self.assertGreater(payload["policyImpact"]["minRequiredCashEok"], 2.0)
        self.assertGreaterEqual(
            payload["policyImpact"]["maxRequiredCashEok"],
            payload["policyImpact"]["minRequiredCashEok"],
        )
        scenarios = {
            row["type"]: row
            for row in payload["policyImpact"]["cashScenarios"]
        }
        self.assertEqual(scenarios["latest_deal"]["priceEok"], 9.2)
        self.assertEqual(scenarios["recent3_average"]["priceEok"], 9.2)
        self.assertEqual(scenarios["recent3_average"]["tradeCount"], 1)

    def test_estimate_failure_becomes_an_inline_unavailable_state(self):
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=({"error": "거래 자료 없음"}, 404),
        ), mock.patch.object(
            search_server,
            "_molit_affordability_estimate",
            return_value=None,
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "성남분당구",
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "unavailable")
        self.assertEqual(payload["error"], "거래 자료 없음")

    def test_rone_failure_keeps_all_unit_types_until_area_is_selected(self):
        broad_band = {
            "latestDealExclusiveArea": 59.82,
            "latestDealPriceEok": 17.0,
            "latestDealDate": "2026-07-04",
            "transactionCount": 11,
            "currentEstimateMinPriceEok": 10.5,
            "currentEstimateMidPriceEok": 14.2,
            "currentEstimateMaxPriceEok": 18.4,
            "currentEstimateSampleCount": 11,
            "currentEstimateTrimmedCount": 2,
            "currentEstimateMethod": "최근 거래 가중 중앙값 · 가중 25~75백분위",
        }
        area_band = {
            **broad_band,
            "latestDealFloor": "10",
            "transactionCount": 9,
            "currentEstimateMinPriceEok": 12.35,
            "currentEstimateMidPriceEok": 15.0,
            "currentEstimateMaxPriceEok": 17.0,
            "currentEstimateSampleCount": 9,
            "currentEstimateTrimmedCount": 0,
            "currentEstimateMethod": "최근 거래 가중 중앙값 · 가중 25~75백분위",
        }

        def price_band(_name, region="", area_label="", lookback_months=24):
            if region:
                return None
            return area_band if area_label == "59.82" else broad_band

        trades = [
            {
                "dealDate": "2026-07-04",
                "dealAmountEok": 17.0,
                "exclusiveArea": 59.82,
                "floor": "10",
            },
            {
                "dealDate": "2026-06-15",
                "dealAmountEok": 16.2,
                "exclusiveArea": 59.82,
                "floor": "8",
            },
        ]
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=({"detail": "해당 단지·면적의 실거래를 찾지 못했어요."}, 404),
        ), mock.patch.object(
            search_server.molit_transactions,
            "price_band_for_apartment",
            side_effect=price_band,
        ), mock.patch.object(
            search_server.molit_transactions,
            "transactions_for_apartment",
            return_value=trades,
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "동대문구",
                "months": 24,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["estimate"]["source"], "molit")
        self.assertEqual(payload["estimate"]["minPriceEok"], 10.5)
        self.assertEqual(payload["estimate"]["maxPriceEok"], 18.4)
        self.assertEqual(payload["latestTrade"]["exclusiveArea"], 59.82)
        self.assertEqual(len(payload["market"]["adjustedTransactions"]), 2)
        self.assertEqual(payload["areaBasis"], "단지 전체 평형 거래 기준")
        self.assertEqual(payload["selectedArea"], "")

    def test_presale_complex_bypasses_rone_and_keeps_region_strict(self):
        band = {
            "latestDealExclusiveArea": 59.83,
            "latestDealFloor": "22",
            "latestDealPriceEok": 11.0076,
            "latestDealDate": "2026-07-07",
            "transactionCount": 2,
            "currentEstimateMinPriceEok": 11.0076,
            "currentEstimateMidPriceEok": 13.0038,
            "currentEstimateMaxPriceEok": 15.0,
            "currentEstimateSampleCount": 2,
            "currentEstimateTrimmedCount": 0,
            "currentEstimateMethod": "최근 거래 가중 중앙값 · 가중 25~75백분위",
        }
        trades = [
            {
                "apartment": "산성역 헤리스톤",
                "legalDong": "산성동",
                "jibun": "1336",
                "dealDate": "2026-07-07",
                "dealAmountEok": 11.0076,
                "exclusiveArea": 59.83,
                "floor": "22",
                "transactionKind": search_server.molit_transactions.TRANSACTION_KIND_PRESALE,
            },
        ]
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            side_effect=AssertionError("분양권은 R-ONE을 조회하면 안 됩니다"),
        ), mock.patch.object(
            search_server.molit_transactions,
            "price_band_for_apartment",
            return_value=band,
        ) as price_band, mock.patch.object(
            search_server.molit_transactions,
            "transactions_for_apartment",
            return_value=trades,
        ):
            payload, status = search_server._apartment_affordability({
                "name": "산성역헤리스톤",
                "region": "경기도 성남시 수정구 산성동",
                "area": "59.83",
                "months": 24,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["transactionKind"], "presale")
        self.assertEqual(payload["latestTrade"]["dealAmountEok"], 11.0076)
        self.assertEqual(payload["latestTrade"]["exclusiveArea"], 59.83)
        self.assertEqual(price_band.call_count, 1)
        self.assertEqual(
            price_band.call_args.kwargs["region"],
            "경기도 성남시 수정구 산성동",
        )


if __name__ == "__main__":
    unittest.main()
