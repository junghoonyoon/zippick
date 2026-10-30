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

    def test_does_not_widen_when_nearby_peers_are_short(self):
        near = _complex("가까운")
        far = _complex("먼단지")
        unknown = _complex("위치없음")
        self.distances = {"가까운": 500, "먼단지": 1001, "위치없음": None}
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in [near, far, unknown]}}
        result = self._compare([near, far, unknown])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reasonCode"], "insufficient_peers")

    def test_peers_are_chosen_without_looking_at_price(self):
        cheap = _complex("싼단지", households=8800)
        pricey = _complex("비싼단지", households=8900)
        self.trades = {"대상": _series([20] * 8), "싼단지": _series([5] * 8), "비싼단지": _series([90] * 8)}
        result = self._compare([cheap, pricey])
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"싼단지", "비싼단지"})

    def test_comparable_size_and_year_boundaries(self):
        small = _complex("작음", households=7199)
        big = _complex("큼", households=10801)
        old = _complex("오래됨", approvedAt="2012-01-01")
        missing = _complex("정보없음", approvedAt="")
        ok = [_complex("하한", households=7200, approvedAt="2013-01-01"),
              _complex("상한", households=10800, approvedAt="2023-01-01")]
        all_peers = [small, big, old, missing, *ok]
        self.trades = {"대상": _series([20] * 8), **{c["name"]: _series([22] * 8) for c in all_peers}}
        result = self._compare(all_peers)
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"하한", "상한"})
        self.assertEqual(result["selectionCriteria"]["householdsMin"], 7200)
        self.assertEqual(result["selectionCriteria"]["householdsMax"], 10800)

    def test_thin_recent_trades_are_marked_or_excluded(self):
        few = _complex("최근4건")
        none = _complex("최근2건")
        enough = _complex("충분")
        self.trades = {
            "대상": _series([20] * 8),
            "최근4건": _series([22] * 8, counts={0: 4}),
            "최근2건": _series([22] * 8, counts={0: 2}),
            "충분": _series([22] * 8),
        }
        result = self._compare([few, none, enough])
        self.assertEqual([peer["name"] for peer in result["peers"]], ["최근4건", "충분"])
        self.assertTrue(result["peers"][0]["lowData"])
        self.assertTrue(result["lowData"])
        self.assertEqual(result["excludedPeers"], ["최근2건"])

    def test_peer_needs_four_usual_windows(self):
        short_history = _complex("신축")
        peers = [_complex("오래된1"), _complex("오래된2")]
        self.trades = {"대상": _series([20] * 8), "신축": _series([22, 22, 22, 22]),
                       **{c["name"]: _series([22] * 8) for c in peers}}
        result = self._compare([short_history, *peers])
        self.assertNotIn("신축", [peer["name"] for peer in result["peers"]])
        self.assertEqual(result["excludedPeers"], [])

    def test_thin_target_uses_the_last_twelve_months_and_is_low_data(self):
        # 이 단지의 최근 6개월 거래가 1건이면 최근 12개월(0~1구간)을 '지금'으로 본다.
        peers = [_complex("비교1"), _complex("비교2")]
        self.trades = {"대상": _series([27, 27] + [25.8] * 6, counts={0: 1, 1: 8}),
                       **{peer["name"]: _series([30] * 8) for peer in peers}}
        result = self._compare(peers)
        self.assertEqual(result["status"], "ready")
        self.assertEqual((result["periodMonths"], result["historyMonths"]), (12, 36))
        self.assertTrue(result["periodWidened"])
        self.assertTrue(result["lowData"])
        self.assertEqual(result["transactionCount"], 9)
        self.assertEqual(result["position"], "high")
        self.assertEqual(result["peers"][0]["usualWindowCount"], 6)

    def test_unavailable_reasons(self):
        self.trades = {"대상": _series([20] * 8, counts={0: 1, 1: 1}), "비교": _series([22] * 8)}
        self.assertEqual(self._compare([_complex("비교")])["reasonCode"], "insufficient_recent_trades")
        self.trades["대상"] = _series([20] * 8)
        self.assertEqual(self._compare([_complex("비교")])["reasonCode"], "insufficient_peers")
        self.target = {**self.target, "households": 0}
        self.assertEqual(self._compare([])["reasonCode"], "missing_building_criteria")

    def test_missing_target_coordinates_withholds_comparison(self):
        self.trades = {"대상": _series([20] * 8)}
        with mock.patch.object(report_price_comparison, "_entity_coordinates", return_value=None), \
             mock.patch.object(report_price_comparison, "_transactions", return_value=self.trades["대상"]):
            result = report_price_comparison.compare({}, self.target, [], "전용 84㎡", today=TODAY)
        self.assertEqual(result["reasonCode"], "missing_coordinates")

    def test_window_medians_bucket_six_months_back_from_today(self):
        trades = [{"dealDate": _month_date(0), "dealAmountEok": 10}, {"dealDate": _month_date(5), "dealAmountEok": 12},
                  {"dealDate": _month_date(6), "dealAmountEok": 20}, {"dealDate": _month_date(48), "dealAmountEok": 99}]
        windows = report_price_comparison._window_medians(trades, TODAY)
        self.assertEqual(windows, {0: (11, 2), 1: (20, 1)})


if __name__ == "__main__":
    unittest.main()
