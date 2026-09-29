import datetime
import unittest

import price_valuation


class PriceValuationTest(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 9, 29)
        self.row = {
            "priceIdentityVerified": True,
            "areaLabel": "84㎡",
            "latestDealDate": "2026-09-10",
            "transactionCount": 12,
            "currentEstimateSampleCount": 12,
            "currentEstimateMinPriceEok": 9.7,
            "currentEstimateMidPriceEok": 10.0,
            "currentEstimateMaxPriceEok": 10.3,
            "valuationEstimateSampleCount": 11,
            "valuationEstimateMinPriceEok": 9.7,
            "valuationEstimateMidPriceEok": 10.0,
            "valuationEstimateMaxPriceEok": 10.3,
            "signals": {
                "status": "ok",
                "momentumPct": 6.0,
                "districtMomentumPct": 4.0,
                "leaderMomentumPct": 5.0,
            },
            "peers": [
                {"momentumPct": 3.0},
                {"momentumPct": 5.0},
                {"momentumPct": 4.0},
            ],
        }

    def test_builds_dynamic_fair_range_and_three_verdicts(self):
        result = price_valuation.valuation_for_candidate(self.row, today=self.today)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["modelVersion"], price_valuation.MODEL_VERSION)
        self.assertEqual(result["dataQuality"]["level"], "high")
        fair = result["fairPrice"]
        self.assertLess(fair["lowEok"], fair["centerEok"])
        self.assertGreater(fair["highEok"], fair["centerEok"])
        self.assertEqual(price_valuation.verdict_for_price(result, fair["lowEok"] - 0.01), "cheap")
        self.assertEqual(price_valuation.verdict_for_price(result, fair["centerEok"]), "fair")
        self.assertEqual(price_valuation.verdict_for_price(result, fair["highEok"] + 0.01), "expensive")

    def test_adjusts_only_for_gap_after_latest_trade(self):
        recent = price_valuation.valuation_for_candidate(self.row, today=self.today)
        older_row = {**self.row, "latestDealDate": "2026-07-01"}
        older = price_valuation.valuation_for_candidate(older_row, today=self.today)

        self.assertEqual(recent["marketAdjustmentPct"], 0.0)
        self.assertGreater(older["marketAdjustmentPct"], 0.0)
        self.assertLessEqual(older["marketAdjustmentPct"], price_valuation.MAX_MARKET_ADJUSTMENT_PCT)

    def test_widens_range_when_market_context_is_missing(self):
        no_market = {**self.row, "signals": {}, "peers": []}
        result = price_valuation.valuation_for_candidate(no_market, today=self.today)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["market"]["status"], "unavailable")
        self.assertGreaterEqual(result["fairPrice"]["widthPct"], 10.0)
        self.assertEqual(result["macro"]["status"], "unavailable")

    def test_holds_when_sample_is_sparse_or_stale(self):
        sparse = {**self.row, "valuationEstimateSampleCount": 2, "transactionCount": 3}
        stale = {**self.row, "latestDealDate": "2026-01-01"}

        self.assertEqual(price_valuation.valuation_for_candidate(sparse, today=self.today)["status"], "unavailable")
        self.assertEqual(price_valuation.valuation_for_candidate(stale, today=self.today)["status"], "unavailable")

    def test_holds_when_latest_trade_cannot_be_excluded(self):
        row = {
            key: value for key, value in self.row.items()
            if not key.startswith("valuationEstimate")
        }

        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["status"], "unavailable")
        self.assertIn("평가할 거래를 뺀 비교 자료", result["reason"])

    def test_does_not_use_asking_price_as_a_feature(self):
        cheap_ask = price_valuation.valuation_for_candidate({**self.row, "askingPriceEok": 8}, today=self.today)
        high_ask = price_valuation.valuation_for_candidate({**self.row, "askingPriceEok": 15}, today=self.today)

        self.assertEqual(cheap_ask["fairPrice"], high_ask["fairPrice"])

    def test_uses_leave_one_out_estimate_for_latest_trade_judgment(self):
        row = {
            **self.row,
            "valuationEstimateMinPriceEok": 8.7,
            "valuationEstimateMidPriceEok": 9.0,
            "valuationEstimateMaxPriceEok": 9.3,
            "valuationEstimateSampleCount": 4,
        }

        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["latestTradeExcluded"])
        self.assertEqual(result["fairPrice"]["centerEok"], 9.0)
        self.assertEqual(result["dataQuality"]["sampleCount"], 4)
        self.assertIn("평가할 최근 거래는 기준가격 계산에서 뺐어요.", result["reasons"])

    def test_exposes_official_rate_as_separate_market_risk(self):
        row = {
            **self.row,
            "marketIndicators": {
                "status": "available",
                "asOf": "2026-09-29",
                "baseRatePct": 2.75,
                "baseRateChangePp12m": -0.5,
                "source": "한국은행 ECOS",
            },
        }
        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["macro"]["status"], "available")
        self.assertIn("기준금리 2.75%", result["macro"]["message"])
        self.assertIn("0.5%p 낮아요", result["macro"]["message"])

    def test_explains_when_korean_bank_rate_connection_is_not_configured(self):
        result = price_valuation.valuation_for_candidate({
            **self.row,
            "marketIndicators": {"status": "unavailable", "reason": "ECOS API 키가 설정되지 않았어요."},
        }, today=self.today)

        self.assertEqual(result["macro"]["status"], "unavailable")
        self.assertIn("연결 설정", result["macro"]["message"])
        self.assertIn("실거래와 주변 시세", result["macro"]["message"])


if __name__ == "__main__":
    unittest.main()
