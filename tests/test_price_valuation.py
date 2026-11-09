import datetime
import unittest
from unittest import mock

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
        row = {**self.row, "latestDealFloor": "10", "valuationTrades": [
            [f"2026-09-{day:02d}", 9.8 + index * 0.04, "10"]
            for index, day in enumerate(range(1, 12))
        ]}
        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["modelVersion"], price_valuation.MODEL_VERSION)
        self.assertEqual(result["dataQuality"]["level"], "high")
        fair = result["fairPrice"]
        self.assertLess(fair["lowEok"], fair["centerEok"])
        self.assertGreater(fair["highEok"], fair["centerEok"])
        self.assertEqual(price_valuation.verdict_for_price(result, fair["lowEok"] - 0.01), "cheap")
        self.assertEqual(price_valuation.verdict_for_price(result, fair["centerEok"]), "fair")
        self.assertEqual(price_valuation.verdict_for_price(result, fair["highEok"] + 0.01), "expensive")
        self.assertEqual(
            price_valuation.verdict_for_price(price_valuation.valuation_for_candidate(self.row, today=self.today), 9),
            "hold",
        )

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

    def test_sparse_samples_hold_but_old_trades_keep_a_reference_range(self):
        sparse = {**self.row, "valuationEstimateSampleCount": 2, "transactionCount": 3}
        stale = {**self.row, "latestDealDate": "2026-01-01"}

        self.assertEqual(price_valuation.valuation_for_candidate(sparse, today=self.today)["status"], "unavailable")
        result = price_valuation.valuation_for_candidate(stale, today=self.today)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["referenceOnly"])
        self.assertEqual(result["dataQuality"]["level"], "low")
        self.assertEqual(price_valuation.verdict_for_price(result, 9), "hold")

    def _sparse_row(self):
        return {**self.row, "name": "검수단지", "region": "검수구", "legalDong": "검수동", "jibun": "1",
                "latestDealPriceEok": 10.5, "latestDealExclusiveArea": 84.5, "latestDealFloor": "10",
                "valuationEstimateMinPriceEok": None, "valuationEstimateMidPriceEok": None,
                "valuationEstimateMaxPriceEok": None, "valuationEstimateSampleCount": 0}

    def _trade(self, date, price=10, floor="10", area=84.5):
        return {"dealDate": date, "dealAmountEok": price, "floor": floor, "exclusiveArea": area}

    def test_widens_to_twelve_months_without_using_evaluated_trade(self):
        history = [self._trade("2026-09-10", 10.5), self._trade("2026-09-01"),
                   self._trade("2026-08-01", 10.1, "9"), self._trade("2026-02-01", 9.8, "11")]
        row = self._sparse_row()
        before = dict(row)
        with mock.patch.object(price_valuation, "_cached_history", return_value=(history, "cached")):
            result = price_valuation.valuation_for_candidate(row, today=self.today)
        self.assertEqual(row, before)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["dataQuality"]["periodMonths"], 12)
        self.assertEqual(result["dataQuality"]["sampleCount"], 3)
        self.assertEqual(result["dataQuality"]["level"], "low")
        self.assertTrue(result["referenceOnly"])
        self.assertEqual(result["comparisonSearch"]["windows"][0]["sampleCount"], 2)
        self.assertEqual(result["floorComparison"]["status"], "matched")

    def test_widens_to_twenty_four_months_only_when_twelve_is_insufficient(self):
        history = [self._trade("2026-09-10", 10.5), self._trade("2026-09-01"),
                   self._trade("2026-08-01"), self._trade("2025-02-01", 9.8)]
        with mock.patch.object(price_valuation, "_cached_history", return_value=(history, "cached")):
            result = price_valuation.valuation_for_candidate(self._sparse_row(), today=self.today)
        self.assertEqual(result["dataQuality"]["periodMonths"], 24)
        self.assertEqual([window["sampleCount"] for window in result["comparisonSearch"]["windows"]], [2, 2, 3])
        self.assertTrue(result["referenceOnly"])

    def test_uses_other_floors_as_reference_without_inventing_a_floor_discount(self):
        history = [self._trade("2026-09-10", 10.5), self._trade("2026-09-01", floor="1"),
                   self._trade("2026-08-01", floor="20"), self._trade("2026-07-01", floor="25")]
        with mock.patch.object(price_valuation, "_cached_history", return_value=(history, "cached")):
            result = price_valuation.valuation_for_candidate(self._sparse_row(), today=self.today)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["dataQuality"]["periodMonths"], 6)
        self.assertEqual(result["floorComparison"]["sampleCount"], 0)
        self.assertTrue(result["referenceOnly"])
        self.assertEqual(price_valuation.verdict_for_price(result, 1), "hold")

    def test_excludes_future_other_area_and_evaluated_transactions(self):
        history = [self._trade("2026-09-10", 10.5), self._trade("2026-09-11", 100),
                   self._trade("2026-08-01", 10), self._trade("2026-07-01", 10.1),
                   self._trade("2026-06-01", 100, area=114.5)]
        with mock.patch.object(price_valuation, "_cached_history", return_value=(history, "cached")):
            result = price_valuation.valuation_for_candidate(self._sparse_row(), today=self.today)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("fairPrice", result)
        self.assertIn("2건", result["reason"])
        self.assertIn("24개월", result["reason"])

    def test_history_lookup_failure_is_not_reported_as_proven_absence(self):
        with mock.patch.object(price_valuation, "_cached_history", side_effect=RuntimeError):
            result = price_valuation.valuation_for_candidate(self._sparse_row(), today=self.today)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("불러오지 못해", result["reason"])
        self.assertEqual(result["comparisonSearch"]["source"], "lookup_failed")

    def test_a_fresh_sufficient_similar_floor_sample_needs_no_extra_lookup(self):
        row = {**self.row, "latestDealFloor": "10", "valuationTrades": [
            ["2026-09-01", 10, "10"], ["2026-08-01", 10, "9"], ["2026-07-01", 10, "11"]]}
        with mock.patch.object(price_valuation, "_cached_history") as lookup:
            result = price_valuation.valuation_for_candidate(row, today=self.today)
        lookup.assert_not_called()
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["referenceOnly"])

    def test_expanded_period_can_use_complete_weekly_index_but_stays_low_confidence(self):
        history = [self._trade("2026-09-10", 10.5), self._trade("2026-09-01"),
                   self._trade("2026-08-01"), self._trade("2026-02-01")]
        with mock.patch.object(price_valuation, "_cached_history", return_value=(history, "cached")), \
             mock.patch.object(price_valuation.regional_price_index, "series_for_region",
                               return_value=self._weekly_index(.1, weeks=50)):
            result = price_valuation.valuation_for_candidate(self._sparse_row(), today=self.today)
        self.assertEqual(result["indexAdjustment"]["status"], "applied")
        self.assertFalse(result["referenceOnly"])
        self.assertEqual(result["dataQuality"]["level"], "low")

    def test_history_lookup_requires_exact_complex_identity(self):
        import budget_candidates
        with mock.patch.object(budget_candidates, "_price_lookup_entity", return_value=None), \
             mock.patch.object(price_valuation.molit_transactions, "transactions_for_apartment_cached") as lookup:
            history, status = price_valuation._cached_history(self._sparse_row())
        lookup.assert_not_called()
        self.assertEqual(history, [])
        self.assertEqual(status, "identity_unavailable")

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

    def test_uses_similar_floor_trades_when_enough_exist(self):
        row = {
            **self.row,
            "latestDealFloor": "1",
            "valuationTrades": [
                ["2026-09-01", 9.0, "1"], ["2026-08-20", 9.2, "2"],
                ["2026-08-10", 9.4, "3"], ["2026-08-01", 14.0, "17"],
                ["2026-07-20", 14.2, "18"], ["2026-07-10", 14.4, "19"],
            ],
            "valuationEstimateSampleCount": 6,
        }

        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["floorComparison"]["status"], "matched")
        self.assertEqual(result["dataQuality"]["sampleCount"], 3)
        self.assertLess(result["fairPrice"]["centerEok"], 10.0)

    def test_flags_low_floor_trade_without_similar_floor_comparables(self):
        row = {
            **self.row,
            "latestDealFloor": "1",
            "valuationTrades": [
                ["2026-09-01", 14.0, "17"], ["2026-08-20", 14.2, "18"],
                ["2026-08-10", 14.4, "19"], ["2026-08-01", 14.5, "20"],
            ],
        }

        result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["floorComparison"]["status"], "insufficient")
        self.assertEqual(result["floorComparison"]["sampleCount"], 0)
        self.assertEqual(result["fairPrice"]["centerEok"], 14.2)
        self.assertTrue(result["referenceOnly"])
        self.assertIn("최근 거래의 층은 확인했지만", result["limitations"][0])

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

    def _weekly_index(self, weekly_change_pct, weeks=30, last_monday=datetime.date(2026, 9, 28)):
        points, value = [], 100.0
        for offset in range(weeks, -1, -1):
            points.append([(last_monday - datetime.timedelta(weeks=offset)).isoformat(), round(value, 6)])
            value *= 1 + weekly_change_pct / 100
        return {"name": "서울>강북지역>도심권>종로구", "label": "서울 종로구", "points": points}

    def _index_row(self):
        return {
            **self.row,
            "region": "서울특별시 종로구",
            "valuationTrades": [
                ["2026-08-31", 10.0], ["2026-08-10", 10.0], ["2026-07-06", 10.0],
                ["2026-06-01", 10.0], ["2026-05-04", 10.0],
            ],
            "valuationEstimateSampleCount": 5,
        }

    def test_moves_each_trade_by_regional_weekly_index(self):
        series = self._weekly_index(0.25)
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=series):
            result = price_valuation.valuation_for_candidate(self._index_row(), today=self.today)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["indexAdjustment"]["status"], "applied")
        self.assertEqual(result["indexAdjustment"]["region"], "서울 종로구")
        self.assertEqual(result["indexAdjustment"]["asOf"], "2026-09-28")
        # 4주 전 거래는 약 1%, 21주 전 거래는 약 5% 오른다. 중심가는 그 사이에 있다.
        self.assertGreater(result["fairPrice"]["centerEok"], 10.09)
        self.assertLess(result["fairPrice"]["centerEok"], 10.55)
        self.assertEqual(result["marketAdjustmentPct"], result["indexAdjustment"]["centerChangePct"])
        self.assertIn("주간 지수", result["fairPrice"]["method"])
        # 화면은 이유를 앞에서 세 개만 보여 준다. 지수 설명이 그 안에 들어야 한다.
        self.assertIn("한국부동산원 서울 종로구 주간 가격 변화", result["reasons"][2])
        self.assertFalse(any("주변 비교 단지" in reason for reason in result["reasons"]))

    def test_falling_index_lowers_the_range(self):
        series = self._weekly_index(-0.2)
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=series):
            result = price_valuation.valuation_for_candidate(self._index_row(), today=self.today)

        self.assertLess(result["fairPrice"]["centerEok"], 10.0)
        self.assertLess(result["indexAdjustment"]["centerChangePct"], 0)

    def test_index_adjustment_replaces_peer_momentum_adjustment(self):
        # 최근 거래가 오래돼 예전 방식이면 주변 단지 흐름으로 올렸을 상황이다.
        row = {**self._index_row(), "latestDealDate": "2026-07-01"}
        flat = self._weekly_index(0.0)
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=flat):
            result = price_valuation.valuation_for_candidate(row, today=self.today)

        self.assertEqual(result["indexAdjustment"]["status"], "applied")
        self.assertEqual(result["marketAdjustmentPct"], 0.0)
        self.assertEqual(result["fairPrice"]["centerEok"], 10.0)

    def test_limits_a_single_trade_adjustment(self):
        series = self._weekly_index(5.0)
        row = self._index_row()
        row["latestDealFloor"] = "10"
        row["valuationTrades"] = [[*trade, "10"] for trade in row["valuationTrades"]]
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=series):
            result = price_valuation.valuation_for_candidate(row, today=self.today)

        cap = price_valuation.MAX_INDEX_ADJUSTMENT_PCT
        adjustments = result["indexAdjustment"]["transactions"]
        capped = [trade for trade in adjustments if trade["rawChangePct"] > cap]
        self.assertTrue(capped)
        self.assertTrue(all(trade["changePct"] == cap for trade in capped))
        self.assertLessEqual(result["fairPrice"]["centerEok"], round(10.0 * (1 + cap / 100), 2))
        self.assertEqual(result["floorComparison"]["status"], "matched")
        self.assertTrue(result["indexAdjustment"]["limited"])
        self.assertTrue(result["referenceOnly"])
        self.assertNotIn("오늘 기준", result["fairPrice"]["method"])

    def test_keeps_previous_method_when_index_is_missing_or_incomplete(self):
        row = self._index_row()
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=None):
            no_index = price_valuation.valuation_for_candidate(row, today=self.today)
        short = self._weekly_index(0.25, weeks=4)
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=short):
            incomplete = price_valuation.valuation_for_candidate(row, today=self.today)
        stale = self._weekly_index(0.25, last_monday=datetime.date(2026, 8, 3))
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region", return_value=stale):
            old_index = price_valuation.valuation_for_candidate(row, today=self.today)
        with mock.patch.object(price_valuation.regional_price_index, "series_for_region") as lookup:
            no_trades = price_valuation.valuation_for_candidate(self.row, today=self.today)
            lookup.assert_not_called()

        self.assertIn("최근 21일", no_index["indexAdjustment"]["reason"])
        self.assertIn("비교 거래 시점", incomplete["indexAdjustment"]["reason"])
        self.assertIn("최근 21일", old_index["indexAdjustment"]["reason"])
        self.assertIn("비교 거래의 날짜와 가격", no_trades["indexAdjustment"]["reason"])

        for result in (no_index, incomplete, old_index, no_trades):
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["indexAdjustment"]["status"], "unavailable")
            self.assertEqual(result["fairPrice"]["centerEok"], 10.0)
            self.assertIn("참고 가격대", result["fairPrice"]["method"])
            self.assertTrue(result["referenceOnly"])


if __name__ == "__main__":
    unittest.main()
