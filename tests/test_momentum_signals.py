import datetime
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import momentum_signals  # noqa: E402


def _deal(months_ago, ppsm, area=84.9):
    today = datetime.date.today()
    year, month = today.year, today.month - months_ago
    while month <= 0:
        year -= 1
        month += 12
    return {
        "dealDate": f"{year}-{month:02d}-15",
        "exclusiveArea": area,
        "dealAmountManwon": ppsm * area,
    }


def _rising_deals():
    # 직전 6개월(7~12개월 전) ㎡당 1000만원 x 4건, 최근 6개월 1100만원 x 6건
    return [_deal(m, 1000) for m in (7, 8, 9, 10)] + [_deal(m, 1100) for m in (1, 1, 2, 3, 4, 5)]


class MomentumSignalsTest(unittest.TestCase):
    def test_rising_complex_scores_positive_momentum(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=_rising_deals()):
            signals = momentum_signals.raw_signals("상승단지", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertAlmostEqual(signals["momentumPct"], 10.0, delta=0.2)
        self.assertEqual(signals["turnoverRatio"], 1.5)
        self.assertIsNotNone(signals["recoveryPct"])

    def test_insufficient_sample_gets_no_score(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=[_deal(1, 1000)] * 3):
            signals = momentum_signals.raw_signals("표본부족", region="강동구")
        self.assertEqual(signals["status"], "insufficient")

    def test_attach_signals_sets_leader_gap_and_badges(self):
        def fake_tx(name, **kwargs):
            if name == "대장":
                return [_deal(m, 1500) for m in (1, 2, 3, 7, 8, 9)]
            return _rising_deals()  # current ppsm ~1100 → 갭 약 27%

        candidates = [
            {"name": "대장", "region": "강동구", "households": 3000},
            {"name": "추격", "region": "강동구", "households": 1000},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", [
                 {"name": "대장", "district": "강동구", "households": 3000},
                 {"name": "추격", "district": "강동구", "households": 1000},
             ]), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None):
            momentum_signals.attach_signals(candidates)

        chaser = candidates[1]["signals"]
        self.assertEqual(chaser["status"], "ok")
        self.assertGreater(chaser["leaderGapPct"], 20)
        self.assertEqual(chaser["leaderName"], "대장")
        self.assertEqual(chaser["leaderRegion"], "강동구")
        self.assertFalse(chaser["isRegionalLeader"])
        self.assertIsInstance(chaser["score"], int)
        kinds = {badge["kind"] for badge in chaser["badges"]}
        self.assertIn("momentum", kinds)
        self.assertIn("leaderGap", kinds)
        leader_badge = next(badge for badge in chaser["badges"] if badge["kind"] == "leaderGap")
        self.assertEqual(leader_badge["label"], "강동구 대장 대비 -27%")
        # 대장 단지 자신에게는 leaderGap이 없다
        self.assertIsNone(candidates[0]["signals"]["leaderGapPct"])
        self.assertTrue(candidates[0]["signals"]["isRegionalLeader"])

    def test_leader_is_fixed_from_entire_district_when_not_in_search_results(self):
        def fake_tx(name, **kwargs):
            if name == "구전체대장":
                return [_deal(m, 1600) for m in (1, 2, 3, 7, 8, 9)]
            return [_deal(m, 1200) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [{"name": "검색후보", "region": "강동구", "households": 2000}]
        district_master = [
            {"name": "구전체대장", "district": "강동구", "households": 5000},
            {"name": "검색후보", "district": "강동구", "households": 2000},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "구전체대장")
        self.assertEqual(signals["leaderHouseholds"], 5000)
        self.assertEqual(signals["leaderBasis"], "district_households")
        self.assertFalse(signals["isRegionalLeader"])
        self.assertAlmostEqual(signals["leaderGapPct"], 25.0, delta=0.1)

    def test_score_uses_available_metrics_only(self):
        signals = {"momentumPct": 10.0, "turnoverRatio": None, "leaderGapPct": None, "recoveryPct": None}
        self.assertEqual(momentum_signals._composite_score(signals), 100)


if __name__ == "__main__":
    unittest.main()
