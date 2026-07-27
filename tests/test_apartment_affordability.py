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
    def test_manual_asking_price_reuses_current_financing_profile(self):
        payload, status = search_server._asking_price_financing({
            "region": "동대문구",
            "asking_price_eok": "8",
            "profile": {
                "home_ownership": "no_home",
                "first_time": "false",
                "cash_eok": "5",
                "annual_income": "8000",
                "monthly_debt_payment": "0",
                "co_borrower": "false",
                "mortgage_rate": "4.2",
                "loan_term_years": "30",
                "purchase_cost_rate": "0",
            },
        })

        self.assertEqual(status, 200)
        self.assertEqual(payload["askingPriceEok"], 8)
        self.assertGreater(payload["requiredCashEok"], 0)
        self.assertEqual(
            payload["cashGapEok"],
            round(5 - payload["requiredCashEok"], 2),
        )
        self.assertGreater(payload["estimatedLoanLimitEok"], 0)

    def test_manual_asking_price_requires_a_complete_profile(self):
        payload, status = search_server._asking_price_financing({
            "region": "동대문구",
            "asking_price_eok": "8",
            "profile": {"home_ownership": "no_home"},
        })

        self.assertEqual(status, 400)
        self.assertIn("구매력 조건", payload["error"])

    def test_exact_entity_keeps_card_and_chart_on_the_same_transactions(self):
        entity = {
            "name": "현대",
            "district": "동대문구",
            "legalDong": "이문동",
            "jibun": "54",
        }
        band = {
            "latestDealDate": "2026-07-04",
            "latestDealPriceEok": 9.27,
            "latestDealExclusiveArea": 59.92,
            "previousDealDate": "2026-04-05",
            "previousDealPriceEok": 8.5,
            "transactionCount": 2,
            "minPriceEok": 8.5,
            "midPriceEok": 8.89,
            "maxPriceEok": 9.27,
            "currentEstimateMinPriceEok": 8.5,
            "currentEstimateMidPriceEok": 8.89,
            "currentEstimateMaxPriceEok": 9.27,
        }
        trades = [
            {"apartment": "현대", "legalDong": "이문동", "jibun": "54", "dealDate": "2026-07-04", "dealAmountEok": 9.27, "exclusiveArea": 59.92},
            {"apartment": "현대", "legalDong": "이문동", "jibun": "54", "dealDate": "2026-04-05", "dealAmountEok": 8.5, "exclusiveArea": 59.92},
        ]
        with mock.patch.object(
            search_server.molit_transactions,
            "price_band_for_apartment",
            return_value=band,
        ) as price_band, mock.patch.object(
            search_server.molit_transactions,
            "transactions_for_apartment",
            return_value=trades,
        ) as transactions, mock.patch.object(
            search_server,
            "_regional_index_for_apartment",
            return_value=None,
        ):
            payload = search_server._molit_affordability_estimate(
                "현대", "동대문구", "59.92", 24, entity=entity,
            )

        self.assertEqual(payload["latestTrade"]["dealAmountEok"], 9.27)
        self.assertEqual(payload["previousTrade"]["dealAmountEok"], 8.5)
        self.assertEqual(
            [row["originalPriceEok"] for row in payload["adjustedTransactions"]],
            [9.27, 8.5],
        )
        self.assertTrue(all(row["legalDong"] == "이문동" and row["jibun"] == "54" for row in payload["adjustedTransactions"]))
        self.assertIs(price_band.call_args.kwargs["entity"], entity)
        self.assertIs(transactions.call_args.kwargs["entity"], entity)

    def test_listing_review_reuses_ready_affordability_payload(self):
        affordability = {
            "state": "ready",
            "selectedArea": "59.4",
            "areaBasis": "전용 59.4㎡ 최근 거래 기준",
            "estimate": {
                "minPriceEok": 8.5,
                "midPriceEok": 8.8,
                "maxPriceEok": 9.1,
                "sampleCount": 8,
                "confidence": "높음",
                "latestTradeDate": "2026-06-20",
                "latestTradeAgeDays": 30,
                "method": "최근 동일 평형 실거래",
                "source": "molit",
            },
            "market": {"adjustedTransactions": []},
        }
        with mock.patch.object(
            search_server,
            "_apartment_affordability",
            return_value=(affordability, 200),
        ):
            payload, status = search_server._listing_review({
                "name": "꿈의숲해링턴플레이스",
                "region": "강북구",
                "asking_price_eok": 8.9,
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["review"]["pricing"]["askingPriceEok"], 8.9)

    def test_listing_review_returns_market_error_when_price_is_unavailable(self):
        with mock.patch.object(
            search_server,
            "_apartment_affordability",
            return_value=(
                {"state": "unavailable", "error": "실거래 없음"},
                200,
            ),
        ):
            payload, status = search_server._listing_review({
                "name": "테스트아파트",
                "region": "강북구",
                "asking_price_eok": 8.9,
            })

        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "실거래 없음")

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

        def attach_location_score_side_effect(rows, _lookup):
            for index, score_row in enumerate(rows):
                score_row["locationScore"] = {
                    "status": "ok",
                    "score": 80 - index,
                }
            return rows

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
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={"score": 80},
        ), mock.patch.object(
            search_server.momentum_signals,
            "attach_signals",
        ) as attach_signals, mock.patch.object(
            search_server.location_scores,
            "attach_scores",
            side_effect=attach_location_score_side_effect,
        ) as attach_location_scores, mock.patch.object(
            search_server.momentum_signals,
            "district_peer_reports",
            return_value=[
                {
                    "name": "비교1아파트",
                    "region": "성남분당구",
                    "legalDong": "정자동",
                    "households": 1200,
                    "priceEok": 12.0,
                    "latestDealPriceEok": 12.0,
                    "score": 61,
                    "momentumPct": 1.2,
                    "recent3Pct": 0.8,
                },
                {
                    "name": "비교2아파트",
                    "region": "성남분당구",
                    "legalDong": "정자동",
                    "households": 1000,
                    "priceEok": 10.0,
                    "latestDealPriceEok": 10.0,
                    "score": 58,
                    "momentumPct": 0.6,
                    "recent3Pct": 0.3,
                },
            ],
        ) as district_peer_reports, mock.patch.object(
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
        self.assertEqual(district_peer_reports.call_args.kwargs["target_households"], 1651)
        self.assertEqual(report["educationEnvironment"], {"score": 80})
        attach_location_scores.assert_called_once()
        score_rows = attach_location_scores.call_args.args[0]
        self.assertEqual([row["name"] for row in score_rows], [entity["name"], "비교1아파트", "비교2아파트"])
        self.assertEqual(score_rows[1]["latestDealPriceEok"], 12.0)
        self.assertEqual(report["peers"][0]["locationScore"]["score"], 79)
        self.assertEqual(report["peers"][1]["locationScore"]["score"], 78)

    def test_apartment_report_resolves_xi_brand_typo_to_canonical_entity(self):
        entity = {
            "name": "서울숲리버뷰자이",
            "aliases": ["행당동 서울숲리버뷰자이"],
            "province": "서울특별시",
            "city": "서울시",
            "district": "성동구",
            "legalDong": "행당동",
            "jibun": "380",
            "address": "서울특별시 성동구 행당동 380",
            "households": 858,
            "approvedAt": "2018-06-22",
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
            return_value=[{"필지고유번호": "1120010700103800000"}],
        ), mock.patch.object(
            search_server.molit_transactions,
            "prefetch_months",
        ), mock.patch.object(
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={"score": 80},
        ), mock.patch.object(
            search_server.momentum_signals,
            "attach_signals",
        ), mock.patch.object(
            search_server.molit_transactions,
            "latest_transaction_for_apartment",
            return_value=None,
        ), mock.patch.object(
            search_server.momentum_signals,
            "district_peer_reports",
            return_value=[],
        ), mock.patch.object(
            search_server.location_scores,
            "attach_scores",
        ) as attach_location_scores:
            payload = search_server._apartment_report("서울숲 리버뷰 ZI", "")

        report = payload["report"]
        self.assertEqual(report["name"], "서울숲리버뷰자이")
        self.assertEqual(report["displayName"], "서울숲리버뷰자이")
        self.assertEqual(report["households"], 858)
        self.assertEqual(report["buildYear"], 2018)
        self.assertEqual(report["buildingAge"], 8)
        self.assertEqual(attach_location_scores.call_args.args[0][0]["name"], "서울숲리버뷰자이")

    def test_leader_context_returns_only_chart_metadata_and_reuses_cache(self):
        entity = {
            "name": "장미(시영6)",
            "district": "노원구",
            "legalDong": "하계동",
            "jibun": "270-1",
            "households": 1880,
        }

        def attach(rows, **kwargs):
            self.assertTrue(kwargs["include_leader_context"])
            rows[0]["signals"] = {
                "score": 97,
                "leaderName": "우성",
                "leaderRegion": "하계동",
                "leaderLegalDong": "하계동",
                "leaderJibun": "270",
                "districtLeaderName": "청구3",
                "districtLeaderRegion": "노원구",
                "districtLeaderLegalDong": "중계동",
                "districtLeaderJibun": "360-2",
                "isRegionalLeader": False,
                "isDistrictLeader": False,
            }

        with mock.patch.object(
            search_server,
            "APARTMENT_LEADER_CONTEXT_CACHE",
            {},
        ), mock.patch.object(
            search_server.budget_candidates,
            "_price_lookup_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.momentum_signals,
            "attach_signals",
            side_effect=attach,
        ) as attach_signals:
            payload, status = search_server._apartment_leader_context(
                "장미(시영6)",
                "노원구",
                legal_dong="하계동",
                jibun="270-1",
            )
            cached, cached_status = search_server._apartment_leader_context(
                "장미(시영6)",
                "노원구",
                legal_dong="하계동",
                jibun="270-1",
            )

        self.assertEqual(status, 200)
        self.assertEqual(cached_status, 200)
        self.assertEqual(payload["signals"]["leaderName"], "우성")
        self.assertEqual(payload["signals"]["districtLeaderName"], "청구3")
        self.assertNotIn("score", payload["signals"])
        self.assertEqual(cached, payload)
        attach_signals.assert_called_once()

    def test_leader_context_keeps_district_comparison_when_locality_leader_is_missing(self):
        entity = {
            "name": "서강GS",
            "district": "마포구",
            "legalDong": "신정동",
            "jibun": "30",
            "households": 538,
        }

        def attach(rows, **kwargs):
            self.assertTrue(kwargs["include_leader_context"])
            rows[0]["signals"] = {
                "districtLeaderName": "래미안 마포 리버웰",
                "districtLeaderRegion": "마포구",
                "districtLeaderLegalDong": "용강동",
                "districtLeaderJibun": "502",
                "isDistrictLeader": False,
            }

        with mock.patch.object(
            search_server,
            "APARTMENT_LEADER_CONTEXT_CACHE",
            {},
        ), mock.patch.object(
            search_server.budget_candidates,
            "_price_lookup_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.momentum_signals,
            "attach_signals",
            side_effect=attach,
        ):
            payload, status = search_server._apartment_leader_context(
                "서강GS",
                "마포구",
                legal_dong="신정동",
                jibun="30",
            )

        self.assertEqual(status, 200)
        self.assertFalse(payload["leaderReady"])
        self.assertTrue(payload["districtLeaderReady"])
        self.assertNotIn("leaderName", payload["signals"])
        self.assertEqual(
            payload["signals"]["districtLeaderName"],
            "래미안 마포 리버웰",
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
        ), mock.patch.object(
            search_server.molit_transactions,
            "area_options_for_apartment",
            return_value=[{"value": "59", "label": "전용 59㎡"}],
        ):
            payload, status = search_server._apartment_affordability({
                "name": "테스트아파트",
                "region": "성남분당구",
                "search_region": "성남분당구",
                "budget": "10",
                "min_area": "59",
                "min_households": "9999",
                "max_building_age": "1",
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
        self.assertTrue(all(
            call.kwargs["min_households"] == 0
            and call.kwargs["max_building_age"] == 0
            for call in common_result.call_args_list
        ))

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
        ), mock.patch.object(
            search_server,
            "_regional_transaction_index",
            return_value={
                "source": "국토부 실거래 기반 지역 대표 단지 평균지수",
                "region": "의왕시",
                "latestPeriod": "202607",
                "latestValue": 102.0,
                "history": [
                    {"period": "202605", "value": 99.0},
                    {"period": "202606", "value": 100.0},
                    {"period": "202607", "value": 102.0},
                ],
                "method": "district_transaction_median",
                "comparisonComplexCount": 1,
            },
        ):
            index = search_server._regional_index_for_apartment(
                "분양권단지",
                "의왕시",
                24,
            )

        self.assertEqual(index["method"], "district_transaction_median")
        self.assertEqual(
            [row["period"] for row in index["history"]],
            ["202605", "202606", "202607"],
        )

    def test_regional_transaction_index_uses_each_complex_change_rate(self):
        candidates = [
            {"name": "저가단지", "region": "테스트구"},
            {"name": "고가단지", "region": "테스트구"},
        ]
        transactions = {
            "저가단지": [
                {"dealDate": "2026-01-10", "dealAmountEok": 10, "exclusiveArea": 1},
                {"dealDate": "2026-02-10", "dealAmountEok": 10, "exclusiveArea": 1},
            ],
            "고가단지": [
                {"dealDate": "2026-01-10", "dealAmountEok": 100, "exclusiveArea": 1},
                {"dealDate": "2026-02-10", "dealAmountEok": 130, "exclusiveArea": 1},
            ],
        }

        with mock.patch.object(
            search_server.molit_transactions,
            "transactions_for_apartment",
            side_effect=lambda name, **_kwargs: transactions.get(name, []),
        ):
            index = search_server._regional_transaction_index("테스트구", candidates, 24)

        self.assertEqual(index["source"], "국토부 실거래 기반 지역 대표 단지 변화율")
        self.assertEqual(
            index["history"],
            [
                {"period": "202601", "value": 100.0},
                {"period": "202602", "value": 115.0},
            ],
        )

    def test_sparse_official_rone_index_is_used_when_enough_months_exist(self):
        payload = {
            "index": {
                "source": "한국부동산원 R-ONE 월간 아파트 매매가격지수",
                "region": "서울>영등포구",
                "latestPeriod": "202606",
                "latestValue": 105.5,
            },
            "adjustedTransactions": [
                {"basePeriod": "202410", "baseIndex": 88.4},
                {"basePeriod": "202503", "baseIndex": 89.5},
                {"basePeriod": "202504", "baseIndex": 89.9},
                {"basePeriod": "202506", "baseIndex": 91.7},
            ],
        }

        index = search_server._regional_index_from_rone_payload(payload, "브라이튼 여의도")

        self.assertEqual(index["method"], "official_rone")
        self.assertEqual(index["sourceApartment"], "브라이튼 여의도")
        self.assertEqual(
            [row["period"] for row in index["history"]],
            ["202410", "202503", "202504", "202506", "202606"],
        )

    def test_apartment_location_score_refreshes_transport_and_education(self):
        entity = {
            "name": "점수보강아파트",
            "province": "서울특별시",
            "city": "서울시",
            "district": "성동구",
            "legalDong": "행당동",
            "jibun": "1",
            "households": 1200,
            "approvedAt": "2018-01-01",
        }
        station = {
            "nearestStationName": "행당역",
            "nearestStationDistance": 420,
            "latitude": 37.5,
            "longitude": 127.0,
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.kakao_station_distances,
            "configured",
            return_value=True,
        ), mock.patch.object(
            search_server.kakao_station_distances,
            "cached_station",
            return_value=station,
        ), mock.patch.object(
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={
                "score": 76,
                "elementarySchoolNames": ["행당초"],
                "elementaryDistanceMeters": 320,
            },
        ), mock.patch.object(
            search_server.molit_transactions,
            "configured",
            return_value=False,
        ):
            payload, status = search_server._apartment_location_score({
                "name": "점수보강아파트",
                "region": "성동구",
                "midPriceEok": 12,
                "transactionCount": 6,
                "signals": {"status": "insufficient"},
            })

        self.assertEqual(status, 200)
        parts = {
            row["key"]: row
            for row in payload["candidate"]["locationScore"]["parts"]
        }
        demand_details = {
            row["key"]: row
            for row in parts["demand"]["details"]
        }
        self.assertEqual(demand_details["station"]["reason"], "행당역 · 직선 420m")
        self.assertEqual(demand_details["education"]["reason"], "행당초 · 320m 거리")

    def test_apartment_location_score_refreshes_missing_jeonse_ratio(self):
        entity = {
            "name": "전세보강아파트",
            "province": "서울특별시",
            "city": "서울시",
            "district": "성북구",
            "legalDong": "삼선동2가",
            "jibun": "1",
            "households": 864,
            "approvedAt": "2008-01-01",
        }
        jeonse = {
            "latestJeonseDepositEok": 6.1,
            "latestJeonseDate": "2026-07-03",
            "latestJeonseExclusiveArea": 59.9,
            "medianJeonseDepositEok": 6.0,
            "jeonseTransactionCount": 4,
            "jeonseRatioPct": 64.9,
            "jeonseSalePriceBasisEok": 9.4,
            "jeonseSourceNote": "국토부 전월세 실거래가 최근 6개월 · 월세 제외",
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.kakao_station_distances,
            "configured",
            return_value=False,
        ), mock.patch.object(
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={"score": None},
        ), mock.patch.object(
            search_server.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            search_server.molit_transactions,
            "jeonse_ratio_for_apartment",
            return_value=jeonse,
        ) as refresh:
            payload, status = search_server._apartment_location_score({
                "name": "전세보강아파트",
                "region": "성북구",
                "areaLabel": "전용 59㎡",
                "currentEstimateMidPriceEok": 9.4,
                "transactionCount": 6,
                "signals": {"status": "insufficient"},
            })

        self.assertEqual(status, 200)
        candidate = payload["candidate"]
        self.assertEqual(candidate["jeonseRatioPct"], 64.9)
        self.assertEqual(candidate["latestJeonseDepositEok"], 6.1)
        parts = {row["key"]: row for row in candidate["locationScore"]["parts"]}
        self.assertIn("전세가율 64.9%", parts["jeonse"]["reason"])
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.kwargs["area_label"], "전용 59㎡")

    def test_apartment_location_score_uses_cached_jeonse_when_live_rent_api_fails(self):
        entity = {
            "name": "전세캐시아파트",
            "province": "서울특별시",
            "city": "서울시",
            "district": "성북구",
            "legalDong": "삼선동2가",
            "jibun": "1",
            "households": 864,
            "approvedAt": "2008-01-01",
        }
        cached = {
            "latestJeonseDepositEok": 5.8,
            "latestJeonseDate": "2026-06-21",
            "medianJeonseDepositEok": 5.7,
            "jeonseTransactionCount": 2,
            "jeonseRatioPct": 61.7,
            "jeonseSalePriceBasisEok": 9.4,
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.kakao_station_distances,
            "configured",
            return_value=False,
        ), mock.patch.object(
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={"score": None},
        ), mock.patch.object(
            search_server.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            search_server.molit_transactions,
            "jeonse_ratio_for_apartment",
            side_effect=RuntimeError("권한 없음"),
        ), mock.patch.object(
            search_server.molit_transactions,
            "cached_jeonse_ratio_for_apartment",
            return_value=cached,
        ) as cached_refresh:
            payload, status = search_server._apartment_location_score({
                "name": "전세캐시아파트",
                "region": "성북구",
                "areaLabel": "전용 59㎡",
                "currentEstimateMidPriceEok": 9.4,
                "transactionCount": 6,
                "signals": {"status": "insufficient"},
            })

        self.assertEqual(status, 200)
        candidate = payload["candidate"]
        self.assertEqual(candidate["jeonseDataStatus"], "cached")
        self.assertEqual(candidate["jeonseRatioPct"], 61.7)
        self.assertIn("저장된 전세 실거래", candidate["jeonseSourceNote"])
        parts = {row["key"]: row for row in candidate["locationScore"]["parts"]}
        self.assertIn("전세가율 61.7%", parts["jeonse"]["reason"])
        cached_refresh.assert_called_once()

    def test_apartment_location_score_hides_live_rent_api_permission_error(self):
        entity = {
            "name": "전세권한아파트",
            "province": "서울특별시",
            "city": "서울시",
            "district": "성북구",
            "legalDong": "삼선동2가",
            "jibun": "1",
            "households": 864,
            "approvedAt": "2008-01-01",
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value=entity,
        ), mock.patch.object(
            search_server.kakao_station_distances,
            "configured",
            return_value=False,
        ), mock.patch.object(
            search_server.education_environment,
            "education_environment_for_entity",
            return_value={"score": None},
        ), mock.patch.object(
            search_server.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            search_server.molit_transactions,
            "jeonse_ratio_for_apartment",
            return_value=None,
        ), mock.patch.object(
            search_server.molit_transactions,
            "last_error",
            return_value="국토부 실거래가 API 권한이 없거나 인증키가 승인되지 않았어요.",
        ), mock.patch.object(
            search_server.molit_transactions,
            "cached_jeonse_ratio_for_apartment",
            return_value=None,
        ):
            payload, status = search_server._apartment_location_score({
                "name": "전세권한아파트",
                "region": "성북구",
                "areaLabel": "전용 59㎡",
                "currentEstimateMidPriceEok": 9.4,
                "transactionCount": 6,
                "signals": {"status": "insufficient"},
            })

        self.assertEqual(status, 200)
        candidate = payload["candidate"]
        self.assertEqual(candidate["jeonseDataStatus"], "api_error")
        self.assertEqual(
            candidate["jeonseSourceNote"],
            "전세 실거래를 지금 불러오지 못했어요. 잠시 후 다시 확인해 주세요.",
        )
        self.assertNotIn("API 권한", candidate["jeonseSourceNote"])


if __name__ == "__main__":
    unittest.main()
