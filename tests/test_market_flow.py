import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

# 개별 API 호출은 각 테스트에서 mock 처리한다. 모듈 전체를 전역 대체하면
# 함께 실행되는 서버 테스트의 실제 모듈까지 바뀌므로 정상 모듈을 가져온다.
import market_flow  # noqa: E402


def trade_rows(values):
    rows = []
    for month, price in values.items():
        for day in range(1, 9):
            rows.append({
                "dealDate": f"{month}-{day:02d}",
                "dealAmountManwon": price * 84,
                "exclusiveArea": 84,
                "dealType": "중개거래",
            })
    return rows


class MarketFlowTest(unittest.TestCase):
    def test_regional_signal_compares_price_per_area_and_ignores_cancelled_trades(self):
        rows = trade_rows({
            "2026-02": 100,
            "2026-03": 100,
            "2026-04": 100,
            "2026-05": 100,
            "2026-06": 110,
            "2026-07": 110,
            "2026-08": 120,
        })
        rows.append({
            "dealDate": "2026-08-10",
            "dealAmountManwon": 999 * 84,
            "exclusiveArea": 84,
            "cancellationDate": "2026-08-11",
        })
        signal = market_flow._regional_signal(rows, datetime.date(2026, 8, 1), 1)

        self.assertEqual(signal["pastPriceChangePct"], 10.0)
        self.assertEqual(signal["pastTradeChangePct"], 0.0)
        self.assertEqual(signal["currentPriceChangePct"], 10.0)
        self.assertEqual(signal["currentTradeChangePct"], 0.0)

    def test_active_flow_keeps_candidate_when_source_is_still_rising(self):
        source = {"pastPriceChangePct": 8.0, "currentPriceChangePct": 10.0}
        current = {"pastPriceChangePct": 3.0, "currentPriceChangePct": 9.0}
        next_candidate = {"pastPriceChangePct": 0.5, "currentPriceChangePct": 6.0}
        already_ahead = {"pastPriceChangePct": 2.0, "currentPriceChangePct": 10.0}

        self.assertTrue(market_flow._is_active_flow_sequence(source, current, next_candidate))
        self.assertFalse(market_flow._is_active_flow_sequence(source, current, already_ahead))

    def test_flow_status_separates_candidate_already_rising_and_waiting(self):
        source = {"pastPriceChangePct": 8.0, "currentPriceChangePct": 10.0}
        current = {"pastPriceChangePct": 3.0, "currentPriceChangePct": 9.0}

        self.assertEqual(
            market_flow._flow_status(
                source, current, {"pastPriceChangePct": 0.5, "currentPriceChangePct": 6.0}
            ),
            market_flow.FLOW_STATUS_NEXT_CANDIDATE,
        )
        self.assertEqual(
            market_flow._flow_status(
                source, current, {"pastPriceChangePct": 2.0, "currentPriceChangePct": 10.0}
            ),
            market_flow.FLOW_STATUS_ALREADY_RISING,
        )
        self.assertEqual(
            market_flow._flow_status(
                source, current, {"pastPriceChangePct": 1.0, "currentPriceChangePct": 1.2}
            ),
            market_flow.FLOW_STATUS_WAITING,
        )

    def test_target_region_appears_once_even_when_routes_disagree(self):
        target = {"name": "중랑구", "signal": {"currentPriceChangePct": 7.6}}
        routes = [
            {"id": "through-dongdaemun", "status": market_flow.FLOW_STATUS_NEXT_CANDIDATE,
             "nodes": [{"name": "성동구"}, {"name": "동대문구"}, target]},
            {"id": "through-seongbuk", "status": market_flow.FLOW_STATUS_ALREADY_RISING,
             "nodes": [{"name": "동대문구"}, {"name": "성북구"}, target]},
        ]

        regions = market_flow._target_regions(routes)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["name"], "중랑구")
        self.assertEqual(regions[0]["status"], "watch")
        self.assertEqual(regions[0]["candidateRouteCount"], 1)
        self.assertEqual(regions[0]["alreadyRisingRouteCount"], 1)
        self.assertEqual(regions[0]["routeIds"], ["through-dongdaemun", "through-seongbuk"])

    def test_watch_ranking_uses_history_without_relabeling_already_risen_regions(self):
        def route(route_id, target_name, status, history_rate, current_price, target_price):
            return {
                "id": route_id,
                "status": status,
                "score": 50,
                "historicalPattern": {
                    "targetRiseRatePct": history_rate,
                    "precedingPatternCount": 10,
                },
                "nodes": [
                    {"name": "앞 지역"},
                    {"name": "오르는 지역", "signal": {"currentPriceChangePct": current_price}},
                    {"name": target_name, "signal": {"currentPriceChangePct": target_price}},
                ],
            }

        routes = [
            route("near-miss", "가구", market_flow.FLOW_STATUS_WAITING, 90, 5.0, 2.0),
            route("weaker-history", "나구", market_flow.FLOW_STATUS_WAITING, 70, 4.0, 1.0),
            route("already-risen", "다구", market_flow.FLOW_STATUS_ALREADY_RISING, 95, 4.0, 5.0),
            route("another-way-to-risen", "다구", market_flow.FLOW_STATUS_WAITING, 99, 6.0, 5.0),
            route("falling-target", "라구", market_flow.FLOW_STATUS_WAITING, 96, 4.0, -2.0),
        ]
        watch_ids = market_flow._watch_routes(routes)
        regions = market_flow._target_regions(routes, watch_ids)

        self.assertEqual(watch_ids, ["near-miss", "weaker-history"])
        self.assertEqual([region["name"] for region in regions[:2]], ["가구", "나구"])
        self.assertEqual([region["status"] for region in regions[:2]], ["watch", "watch"])
        self.assertNotEqual(next(region for region in regions if region["name"] == "다구")["status"], "watch")

    def test_snapshot_has_only_real_calculated_routes_and_marks_next_as_score(self):
        route = {
            "id": "test-route",
            "color": "#3182f6",
            "nodes": (
                ("과거구", ("11111",), 37.5, 127.0),
                ("현재구", ("22222",), 37.6, 127.1),
                ("후보구", ("33333",), 37.7, 127.2),
            ),
        }
        first_month = datetime.date(2016, 9, 1)
        values = {
            market_flow._shift_month(first_month, offset).strftime("%Y-%m"): 100 + offset
            for offset in range(120)
        }
        source_values = dict(values)
        current_values = dict(values)
        target_values = dict(values)
        for month in ("2025-12", "2026-01", "2026-02"):
            source_values[month] = current_values[month] = target_values[month] = 100
        for month in ("2026-03", "2026-04", "2026-05"):
            source_values[month] = 120
            current_values[month] = 105
            target_values[month] = 100
        for month in ("2026-06", "2026-07", "2026-08"):
            source_values[month] = 115
            current_values[month] = 115
            target_values[month] = 105
        transactions = {
            "11111": trade_rows(source_values),
            "22222": trade_rows(current_values),
            "33333": trade_rows(target_values),
        }
        with mock.patch.object(market_flow, "FLOW_ROUTES", (route,)), mock.patch.object(
            market_flow, "_fetch_region_transactions", return_value=(transactions, 0)
        ):
            payload = market_flow._build_snapshot(datetime.date(2026, 8, 1), 3)

        self.assertEqual(payload["source"], "국토교통부 실거래가 공개시스템 신고 거래")
        self.assertEqual(payload["historyMonths"], 120)
        self.assertEqual(payload["routeMode"], "data_generated")
        self.assertGreaterEqual(len(payload["routes"]), 1)
        self.assertLessEqual(len(payload["routes"]), market_flow.MAX_DISPLAY_ROUTES)
        self.assertEqual(payload["totalRouteCount"], len(payload["routes"]))
        self.assertEqual(payload["candidateRouteCount"], payload["statusCounts"]["next_candidate"])
        self.assertEqual(payload["targetRegionCount"], len(payload["targetRegions"]))
        self.assertEqual(payload["watchRegionCount"], 1)
        self.assertEqual(payload["displayRouteLimit"], market_flow.MAX_DISPLAY_ROUTES)
        self.assertIsInstance(payload["routes"][0]["score"], int)
        self.assertNotIn("prediction", payload["routes"][0])
        self.assertEqual(payload["candidateCriteria"]["minimumTargetLagPct"], 1.0)
        self.assertEqual(payload["routes"][0]["status"], market_flow.FLOW_STATUS_NEXT_CANDIDATE)
        self.assertEqual(payload["routes"][0]["nodes"][1]["signal"]["currentPriceChangePct"], 9.5)
        self.assertEqual(payload["routes"][0]["stageMetrics"]["targetLagPct"], 4.5)

    def test_historical_pattern_counts_completed_three_step_sequences(self):
        first_month = datetime.date(2016, 9, 1)
        values = {
            market_flow._shift_month(first_month, offset).strftime("%Y-%m"): 100 + offset
            for offset in range(120)
        }
        rows = trade_rows(values)

        pattern = market_flow._historical_route_pattern(
            rows, rows, rows, datetime.date(2026, 8, 1)
        )

        self.assertEqual(pattern["observedWindows"], 36)
        self.assertEqual(pattern["precedingPatternCount"], 36)
        self.assertEqual(pattern["targetRiseCount"], 36)
        self.assertEqual(pattern["targetRiseRatePct"], 100)
        self.assertEqual(pattern["minimumPatternCount"], 5)
        self.assertTrue(pattern["enoughHistory"])
        self.assertEqual(len(pattern["evidenceCases"]), 36)
        self.assertEqual(pattern["evidenceCases"][0]["targetEndMonth"], "2026-05")
        self.assertTrue(pattern["evidenceCases"][0]["targetRose"])

    def test_route_edges_are_directional(self):
        regions = {
            name: {"name": name}
            for name in ("동작구", "영등포구", "구로구")
        }

        self.assertTrue(market_flow._route_step_allowed(regions["동작구"], regions["영등포구"]))
        self.assertTrue(market_flow._route_step_allowed(regions["영등포구"], regions["구로구"]))
        self.assertFalse(market_flow._route_step_allowed(regions["구로구"], regions["영등포구"]))
        self.assertFalse(market_flow._route_step_allowed(regions["영등포구"], regions["동작구"]))

    def test_stale_snapshot_is_returned_while_refresh_runs_in_background(self):
        reference = datetime.date(2026, 8, 1)
        with tempfile.TemporaryDirectory() as cache_root, mock.patch.object(
            market_flow, "CACHE_DIR", Path(cache_root)
        ), mock.patch.object(market_flow, "_base_month", return_value=reference), mock.patch.object(
            market_flow, "_schedule_snapshot_refresh", return_value=True
        ) as schedule_refresh:
            path = market_flow._cache_path(reference, market_flow.FLOW_PERIOD_MONTHS)
            market_flow._write_cache(path, {"cachedAt": 1, "routes": []})

            payload = market_flow.get_snapshot()

        self.assertTrue(payload["cached"])
        self.assertTrue(payload["stale"])
        self.assertTrue(payload["refreshing"])
        schedule_refresh.assert_called_once_with(reference, market_flow.FLOW_PERIOD_MONTHS, path)

    def test_missing_snapshot_returns_preparing_state_without_blocking(self):
        reference = datetime.date(2026, 8, 1)
        with tempfile.TemporaryDirectory() as cache_root, mock.patch.object(
            market_flow, "CACHE_DIR", Path(cache_root)
        ), mock.patch.object(market_flow, "_base_month", return_value=reference), mock.patch.object(
            market_flow, "_schedule_snapshot_refresh", return_value=True
        ) as schedule_refresh:
            payload = market_flow.get_snapshot()

        self.assertTrue(payload["pending"])
        self.assertTrue(payload["refreshing"])
        self.assertEqual(payload["baseMonth"], "2026-08")
        schedule_refresh.assert_called_once()

    def test_saved_snapshot_survives_temporary_upstream_circuit_break(self):
        reference = datetime.date(2026, 8, 1)
        with tempfile.TemporaryDirectory() as cache_root, mock.patch.object(
            market_flow, "CACHE_DIR", Path(cache_root)
        ), mock.patch.object(market_flow, "_base_month", return_value=reference), mock.patch.object(
            market_flow.molit_transactions, "enabled", return_value=False
        ), mock.patch.object(market_flow, "_schedule_snapshot_refresh") as schedule_refresh:
            path = market_flow._cache_path(reference, market_flow.FLOW_PERIOD_MONTHS)
            market_flow._write_cache(path, {"cachedAt": 1, "routes": []})

            payload = market_flow.get_snapshot()

        self.assertTrue(payload["cached"])
        self.assertTrue(payload["stale"])
        self.assertFalse(payload["refreshing"])
        schedule_refresh.assert_not_called()
