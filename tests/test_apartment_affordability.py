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
    def test_apartment_report_keeps_exact_entity_location_for_dong_leader(self):
        entity = {
            "name": "한솔마을(4단지)(주공)",
            "aliases": ["한솔마을4단지주공"],
            "province": "경기도",
            "city": "성남시",
            "district": "분당구",
            "legalDong": "정자동",
            "jibun": "101",
            "address": "경기도 성남시 분당구 정자동 101",
            "households": 1651,
            "buildYear": 1994,
        }
        source_row = {
            "대표단지명": entity["name"],
            "법정동": "정자동",
            "지번": "101",
            "필지고유번호": "4113510100101010000",
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            search_server.molit_transactions,
            "source_rows_for_entity",
            return_value=[source_row],
        ) as exact_source, mock.patch.object(
            search_server.molit_transactions,
            "source_rows",
        ) as fuzzy_source, mock.patch.object(
            search_server.molit_transactions,
            "prefetch_months",
        ), mock.patch.object(
            search_server.momentum_signals,
            "attach_signals",
        ) as attach_signals, mock.patch.object(
            search_server.momentum_signals,
            "district_peer_reports",
            return_value=[],
        ), mock.patch.object(
            search_server.molit_transactions,
            "latest_transaction_for_apartment",
            return_value=None,
        ) as latest_transaction:
            payload = search_server._apartment_report(
                "한솔마을 4단지 주공",
                "성남분당구",
            )

        report = payload["report"]
        self.assertEqual(report["legalDong"], "정자동")
        self.assertEqual(report["jibun"], "101")
        self.assertEqual(report["displayName"], entity["name"])
        self.assertIn(entity["name"], report["aliases"])
        self.assertEqual(
            attach_signals.call_args.args[0][0]["legalDong"],
            "정자동",
        )
        self.assertGreaterEqual(exact_source.call_count, 2)
        fuzzy_source.assert_not_called()
        self.assertEqual(
            latest_transaction.call_args.kwargs["entity"]["legalDong"],
            "정자동",
        )

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

    def test_affordability_uses_the_common_candidate_as_its_canonical_result(self):
        candidate = {
            "resultSchemaVersion": 1,
            "name": "테스트아파트",
            "region": "성남분당구",
            "displayName": "테스트아파트",
            "displayRegion": "성남분당구 정자동",
            "displayAreaLabel": "전용 59㎡",
            "areaLabel": "전용 59~60㎡",
            "estimatedMinPriceEok": 7.5,
            "estimatedMidPriceEok": 8.5,
            "estimatedMaxPriceEok": 9.5,
            "estimatedPriceConfidence": "높음",
            "currentEstimateSampleCount": 7,
            "currentEstimateMethod": "최근 거래 가중 중앙값",
            "latestDealPriceEok": 8.7,
            "latestDealDate": "2026-07-03",
            "latestDealExclusiveArea": 59.8,
            "latestDealFloor": "12",
            "priceSource": "molit",
            "tradeLookbackMonths": 6,
            "policyImpact": {"status": "possible"},
            "signals": {"score": 71},
            "verdict": {"label": "검토"},
        }
        with mock.patch.object(
            search_server.budget_candidates,
            "apartment_candidate_result",
            return_value=candidate,
        ) as common_result, mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=(ESTIMATE_PAYLOAD, 200),
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "성남분당구",
                "search_region": "성남분당구",
                "budget": "10",
                "min_area": "59",
            })

        self.assertEqual(status, 200)
        self.assertIs(payload["candidate"], candidate)
        self.assertEqual(payload["estimate"]["minPriceEok"], 7.5)
        self.assertEqual(payload["estimate"]["midPriceEok"], 8.5)
        self.assertEqual(payload["estimate"]["maxPriceEok"], 9.5)
        self.assertEqual(payload["latestTrade"]["dealAmountEok"], 8.7)
        self.assertEqual(payload["areaBasis"], "전용 59㎡ 최근 거래 기준")
        self.assertEqual(common_result.call_args_list[0].kwargs["min_area"], "59")
        self.assertEqual(common_result.call_args_list[-1].kwargs["min_area"], 0)
        self.assertEqual(common_result.call_args_list[-1].kwargs["budget"], "10")

    def test_minimum_area_without_a_larger_unit_selects_the_closest_actual_unit(self):
        initial_candidate = {
            "resultSchemaVersion": 1,
            "name": "소형전용아파트",
            "displayAreaLabel": "전용 59㎡",
        }
        resolved_candidate = {
            "resultSchemaVersion": 1,
            "name": "소형전용아파트",
            "displayAreaLabel": "전용 41.9㎡",
            "selectedArea": 41.85,
        }
        estimate_payload = {
            **ESTIMATE_PAYLOAD,
            "latestTrade": {
                **ESTIMATE_PAYLOAD["latestTrade"],
                "exclusiveArea": 41.85,
            },
        }
        with mock.patch.object(
            search_server.budget_candidates,
            "apartment_candidate_result",
            side_effect=[initial_candidate, resolved_candidate],
        ) as common_result, mock.patch.object(
            search_server.molit_transactions,
            "area_options_for_apartment",
            return_value=[
                {"value": "35.28", "label": "전용 35~36㎡"},
                {"value": "41.85", "label": "전용 41~42㎡"},
            ],
        ), mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=(estimate_payload, 200),
        ) as estimate:
            payload, status = search_server._apartment_affordability({
                "name": "소형전용아파트",
                "region": "성남분당구",
                "min_area": "59",
                "months": 24,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertTrue(payload["areaFallback"])
        self.assertEqual(payload["requestedMinArea"], 59.0)
        self.assertEqual(payload["resolvedArea"], "41.85")
        self.assertEqual(payload["selectedArea"], "41.85")
        self.assertIs(payload["candidate"], resolved_candidate)
        self.assertEqual(estimate.call_args.kwargs["area"], "41.85")
        self.assertEqual(common_result.call_args_list[1].kwargs["area"], "41.85")
        self.assertEqual(common_result.call_args_list[1].kwargs["min_area"], 0)

    def test_minimum_area_resolves_the_closest_actual_unit_for_chart_and_title(self):
        candidate = {
            "resultSchemaVersion": 1,
            "name": "평형일치아파트",
            "displayAreaLabel": "전용 59㎡",
        }
        with mock.patch.object(
            search_server.budget_candidates,
            "apartment_candidate_result",
            return_value=candidate,
        ), mock.patch.object(
            search_server.molit_transactions,
            "area_options_for_apartment",
            return_value=[
                {"value": "59.82", "label": "전용 59~60㎡"},
                {"value": "84.91", "label": "전용 84~85㎡"},
            ],
        ), mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            return_value=(ESTIMATE_PAYLOAD, 200),
        ) as estimate:
            payload, status = search_server._apartment_affordability({
                "name": "평형일치아파트",
                "region": "성남분당구",
                "min_area": "59",
                "months": 24,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertTrue(payload["areaFallback"])
        self.assertEqual(payload["resolvedArea"], "59.82")
        self.assertEqual(payload["selectedArea"], "59.82")
        self.assertEqual(payload["latestTrade"]["dealAmountEok"], 9.2)
        self.assertEqual(estimate.call_args.kwargs["area"], "59.82")

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
        regional_index = {
            "source": "한국부동산원 R-ONE 월간 아파트 매매가격지수",
            "region": "경기>성남시>수정구",
            "latestPeriod": "202607",
            "latestValue": 101.0,
            "history": [
                {"period": "202606", "value": 100.0},
                {"period": "202607", "value": 101.0},
            ],
            "method": "official_rone",
        }
        with mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            side_effect=AssertionError("분양권은 R-ONE을 조회하면 안 됩니다"),
        ), mock.patch.object(
            search_server,
            "_regional_index_for_apartment",
            return_value=regional_index,
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
        self.assertEqual(payload["market"]["index"]["method"], "official_rone")
        self.assertEqual(
            payload["market"]["adjustedTransactions"][0]["baseIndex"],
            101.0,
        )
        self.assertEqual(price_band.call_count, 1)
        self.assertEqual(
            price_band.call_args.kwargs["region"],
            "경기도 성남시 수정구 산성동",
        )

    def test_regional_index_history_is_recovered_from_a_same_district_complex(self):
        source_payload = {
            "index": {
                "source": "한국부동산원 R-ONE 월간 아파트 매매가격지수",
                "region": "경기>경부1권>의왕시",
                "latestPeriod": "202607",
                "latestValue": 102.0,
            },
            "adjustedTransactions": [
                {"basePeriod": "202605", "baseIndex": 99.0},
                {"basePeriod": "202606", "baseIndex": 100.0},
            ],
        }
        search_server.REGIONAL_INDEX_CACHE.clear()

        def estimate(name, region, **_kwargs):
            if name == "지역대표단지":
                return source_payload, 200
            return {"detail": "단지 미매칭"}, 404

        with mock.patch.object(
            search_server.momentum_signals,
            "district_index_source_candidates",
            return_value=[{
                "name": "지역대표단지",
                "region": "의왕시",
                "households": 2000,
            }],
        ), mock.patch.object(
            search_server.rone_estimates,
            "estimate",
            side_effect=estimate,
        ):
            index = search_server._regional_index_for_apartment(
                "분양권단지",
                "의왕시",
                24,
            )

        self.assertEqual(index["method"], "official_rone")
        self.assertEqual(index["sourceApartment"], "지역대표단지")
        self.assertEqual(
            [row["period"] for row in index["history"]],
            ["202605", "202606", "202607"],
        )


if __name__ == "__main__":
    unittest.main()
