import datetime
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import report_price_comparison  # noqa: E402


TODAY = datetime.date(2026, 10, 27)


def _month_date(months_back):
    ordinal = TODAY.year * 12 + TODAY.month - 1 - months_back
    return f"{ordinal // 12}-{ordinal % 12 + 1:02d}-15"


def _series(prices_by_window, counts=None):
    """6개월 구간마다 같은 가격의 거래를 만든다. 0이 최근 6개월이다."""
    trades = []
    for window, price in enumerate(prices_by_window):
        if price is None:
            continue
        count = (counts or {}).get(window, 5)
        trades += [{"dealDate": _month_date(window * 6 + 1), "dealAmountEok": price} for _ in range(count)]
    return trades


def _complex(name, **overrides):
    return {"name": name, "district": "송파구", "legalDong": "잠실동", "jibun": name,
            "households": 9000, "approvedAt": "2018-01-01", **overrides}


class ReportPriceComparisonTest(unittest.TestCase):
    def setUp(self):
        self.target = _complex("대상", legalDong="가락동", households=9000, approvedAt="2018-01-01")
        self.trades = {}
        self.distances = {}

    def _compare(self, master, area="전용 84㎡"):
        distance = lambda target, peer: self.distances.get(peer["name"], 500)
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", [self.target, *master]), \
             mock.patch.object(report_price_comparison, "_entity_coordinates", return_value=(37.5, 127.1)), \
             mock.patch.object(report_price_comparison, "_peer_distance_meters", side_effect=distance), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, _area: self.trades.get(entity["name"], [])):
            return report_price_comparison.compare({}, self.target, [], area, today=TODAY)

    def test_location_premium_is_judged_against_the_usual_price_gap(self):
        # 대상은 늘 비교 단지의 86% 가격이었다. 지금도 86%면 싸 보여도 평소 수준이다.
        peers = [_complex("잠실A"), _complex("잠실B")]
        for peer in peers:
            self.trades[peer["name"]] = _series([30] * 8)
        for current, expected in [(25.8, "similar"), (27.3, "high"), (24.3, "low")]:
            self.trades["대상"] = _series([current] + [25.8] * 7)
            result = self._compare(peers)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["position"], expected, current)
            self.assertEqual(result["usualGapPct"], -14.0)
        self.assertEqual(result["peers"][0]["diffPct"], round((30 / 24.3 - 1) * 100, 1))

    def test_each_peer_counts_equally_in_the_shift(self):
        peers = [_complex("거래많음"), _complex("거래적음")]
        self.trades["대상"] = _series([10] * 8)
        self.trades["거래많음"] = _series([10] + [10] * 7, counts={0: 40})
        self.trades["거래적음"] = _series([9] + [10] * 7)
        result = self._compare(peers)
        self.assertEqual([peer["shiftPp"] for peer in result["peers"]], [0.0, 11.1])
        self.assertAlmostEqual(result["shiftPp"], 5.55, delta=0.06)
        self.assertEqual(result["position"], "high")

    def test_nearby_peers_are_used_first(self):
        near = [_complex("가까운1"), _complex("가까운2")]
        far = _complex("먼단지")
        self.distances = {"가까운1": 400, "가까운2": 900, "먼단지": 3000}
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [*near, far]}}
        result = self._compare([far, *near])
        self.assertEqual(result["scope"], "nearby")
        self.assertEqual([peer["name"] for peer in result["peers"]], ["가까운1", "가까운2"])

    def test_widens_to_the_same_district_when_nearby_peers_are_short(self):
        near = _complex("가까운")
        far = _complex("먼단지")
        other_district = _complex("다른구", district="강동구")
        self.distances = {"가까운": 500, "먼단지": 3000, "다른구": 3000}
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [near, far, other_district]}}
        result = self._compare([near, far, other_district])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["scope"], "district")
        self.assertEqual([peer["name"] for peer in result["peers"]], ["가까운", "먼단지"])
        self.assertFalse(result["conditionsRelaxed"])

    def test_same_dong_counts_as_nearby_when_coordinates_are_missing(self):
        same_dong = [_complex("같은동1", legalDong="가락동"), _complex("같은동2", legalDong="가락동")]
        other_dong = _complex("다른동")
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [*same_dong, other_dong]}}
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", [self.target, other_dong, *same_dong]), \
             mock.patch.object(report_price_comparison, "_entity_coordinates", return_value=None), \
             mock.patch.object(report_price_comparison, "_peer_distance_meters", return_value=None), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, _area: self.trades.get(entity["name"], [])):
            result = report_price_comparison.compare({}, self.target, [], "전용 84㎡", today=TODAY)
        self.assertEqual(result["scope"], "nearby")
        self.assertEqual([peer["name"] for peer in result["peers"]], ["같은동1", "같은동2"])

    def test_missing_distances_are_resolved_for_selected_complexes(self):
        peers = [_complex("비교1", legalDong="가락동"), _complex("비교2", legalDong="가락동")]
        self.trades = {"대상": _series([20] * 8), **{p["name"]: _series([22] * 8) for p in peers}}
        coordinates = {"대상": (37.50, 127.10), "비교1": (37.51, 127.10), "비교2": (37.50, 127.12)}
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", [self.target, *peers]), \
             mock.patch.object(report_price_comparison, "_entity_coordinates", return_value=None), \
             mock.patch.object(report_price_comparison, "_resolve_report_coordinates", side_effect=lambda entity: coordinates[entity["name"]]), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, _area: self.trades.get(entity["name"], [])):
            result = report_price_comparison.compare({}, self.target, [], "전용 84㎡", today=TODAY)
        self.assertEqual([p["name"] for p in result["peers"]], ["비교1", "비교2"])
        self.assertTrue(all(p["distanceMeters"] > 1000 for p in result["peers"]))
        self.assertTrue(all("_entity" not in p for p in result["peers"]))

    def test_peers_are_chosen_without_looking_at_price(self):
        cheap = _complex("싼단지", households=8800)
        pricey = _complex("비싼단지", households=8900)
        self.trades = {"대상": _series([20] * 8), "싼단지": _series([5] * 8), "비싼단지": _series([90] * 8)}
        result = self._compare([cheap, pricey])
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"싼단지", "비싼단지"})

    def test_similar_complexes_are_preferred_before_conditions_widen(self):
        similar = [_complex("비슷1", households=8000), _complex("비슷2", households=10000, approvedAt="2012-01-01")]
        different = _complex("작고오래됨", households=500, approvedAt="1990-01-01")
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [*similar, different]}}
        result = self._compare([different, *similar])
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"비슷1", "비슷2"})
        self.assertFalse(result["conditionsRelaxed"])

    def test_widened_conditions_are_marked_low_data(self):
        different = [_complex("작은단지", households=500, approvedAt="1990-01-01"),
                     _complex("중간단지", households=3000, approvedAt="2005-01-01")]
        too_small = _complex("초소형", households=50)
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [*different, too_small]}}
        result = self._compare([*different, too_small])
        self.assertEqual(result["status"], "ready")
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"작은단지", "중간단지"})
        self.assertTrue(result["conditionsRelaxed"])
        self.assertTrue(result["lowData"])

    def test_thin_recent_trades_are_marked_or_excluded(self):
        few = _complex("최근4건")
        none = _complex("최근1건")
        enough = _complex("충분")
        self.trades = {
            "대상": _series([20] * 8),
            "최근4건": _series([22] * 8, counts={0: 4}),
            "최근1건": _series([22] * 8, counts={0: 1}),
            "충분": _series([22] * 8),
        }
        result = self._compare([few, none, enough])
        self.assertEqual([peer["name"] for peer in result["peers"]], ["최근4건", "충분"])
        self.assertTrue(result["peers"][0]["lowData"])
        self.assertTrue(result["lowData"])
        self.assertEqual(result["excludedPeers"], ["최근1건"])

    def test_peer_without_usual_history_is_left_out_when_others_have_it(self):
        short_history = _complex("신축")
        peers = [_complex("오래된1"), _complex("오래된2")]
        self.trades = {"대상": _series([20] * 8), "신축": _series([22, 22, 22]),
                       **{c["name"]: _series([22] * 8) for c in peers}}
        result = self._compare([short_history, *peers])
        self.assertEqual(result["method"], "usual_gap")
        self.assertNotIn("신축", [peer["name"] for peer in result["peers"]])

    def test_falls_back_to_a_labelled_simple_comparison_without_usual_history(self):
        peers = [_complex("신축1"), _complex("신축2")]
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([25, 25]) for c in peers}}
        result = self._compare(peers)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["method"], "simple")
        self.assertIsNone(result["shiftPp"])
        self.assertIsNone(result["usualGapPct"])
        self.assertEqual(result["differencePct"], -20.0)
        self.assertEqual(result["position"], "low")
        self.assertTrue(result["lowData"])

    def test_single_peer_still_gives_a_low_data_result(self):
        peer = _complex("하나")
        self.trades = {"대상": _series([20] * 8), "하나": _series([22] * 8)}
        result = self._compare([peer])
        self.assertEqual((result["status"], result["method"]), ("ready", "usual_gap"))
        self.assertEqual(len(result["peers"]), 1)
        self.assertTrue(result["lowData"])

    def test_other_area_trades_are_converted_when_no_peer_has_this_area(self):
        def trades(entity, area):
            if entity["name"] == "대상":
                return [{**trade, "exclusiveArea": 84.0} for trade in _series([20] * 8)]
            # 같은 면적 거래는 없고, 80㎡ 거래만 있다. 84㎡로 환산하면 21억이다.
            return [{**trade, "exclusiveArea": 80.0} for trade in _series([20] * 8)] if "~" in area else []
        peers = [_complex("다른면적1"), _complex("다른면적2")]
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", [self.target, *peers]), \
             mock.patch.object(report_price_comparison, "_entity_coordinates", return_value=(37.5, 127.1)), \
             mock.patch.object(report_price_comparison, "_peer_distance_meters", return_value=500), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=trades):
            result = report_price_comparison.compare({}, self.target, [], "전용 84㎡", today=TODAY)
        self.assertTrue(result["areaAdjusted"])
        self.assertTrue(result["lowData"])
        self.assertEqual(result["peers"][0]["averagePriceEok"], 21.0)

    def test_thin_target_uses_the_last_twelve_months_and_is_low_data(self):
        # 이 단지의 최근 6개월 거래가 1건이면 최근 12개월(0~1구간)을 '지금'으로 본다.
        peers = [_complex("비교1"), _complex("비교2")]
        self.trades = {"대상": _series([27, 27] + [25.8] * 6, counts={0: 1, 1: 8}),
                       **{peer["name"]: _series([30] * 8) for peer in peers}}
        result = self._compare(peers)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["periodMonths"], 12)
        self.assertTrue(result["periodWidened"])
        self.assertTrue(result["lowData"])
        self.assertEqual(result["transactionCount"], 9)
        self.assertEqual(result["position"], "high")
        self.assertEqual(sorted(result["peers"][0]["yearlyRatios"]), ["2023", "2024", "2025"])

    def test_very_thin_target_uses_the_last_two_years(self):
        peers = [_complex("비교1"), _complex("비교2")]
        self.trades = {"대상": _series([20, 20, 20, 20, 20, 20, 20, 20], counts={0: 1, 1: 1, 2: 1, 3: 0}),
                       **{peer["name"]: _series([22] * 8) for peer in peers}}
        result = self._compare(peers)
        self.assertEqual(result["periodMonths"], 24)
        self.assertTrue(result["lowData"])

    def test_unavailable_only_when_real_trades_are_missing(self):
        self.trades = {"대상": _series([20] * 8, counts={0: 1, 1: 0, 2: 0, 3: 0}), "비교": _series([22] * 8)}
        self.assertEqual(self._compare([_complex("비교")])["reasonCode"], "insufficient_recent_trades")
        self.trades["대상"] = _series([20] * 8)
        self.assertEqual(self._compare([])["reasonCode"], "insufficient_peers")
        self.target = {**self.target, "households": 0}
        self.assertEqual(self._compare([])["reasonCode"], "missing_building_criteria")

    def test_yearly_gaps_leave_out_the_current_period(self):
        peers = [_complex("비교1"), _complex("비교2")]
        own = [{"dealDate": f"{year}-06-15", "dealAmountEok": 20} for year in (2022, 2023, 2024, 2025) for _ in range(5)]
        own += [{"dealDate": "2026-08-15", "dealAmountEok": 22}] * 5
        peer = [{"dealDate": f"{year}-06-15", "dealAmountEok": 25} for year in (2022, 2023, 2024, 2025) for _ in range(5)]
        peer += [{"dealDate": "2026-08-15", "dealAmountEok": 25}] * 5
        self.trades = {"대상": own, "비교1": peer, "비교2": peer}
        result = self._compare(peers)
        self.assertEqual([entry["year"] for entry in result["yearlyGaps"]], [2022, 2023, 2024, 2025])
        self.assertEqual({entry["gapPct"] for entry in result["yearlyGaps"]}, {-20.0})
        self.assertEqual((result["usualGapPct"], result["currentGapPct"], result["shiftPp"]), (-20.0, -12.0, 8.0))
        self.assertEqual(result["position"], "high")


if __name__ == "__main__":
    unittest.main()
