import datetime
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import molit_transactions  # noqa: E402
import report_price_comparison  # noqa: E402


def _trades(end_month, month_offset, prices):
    month = molit_transactions._shift_month(end_month, -month_offset)
    date = f"{month[:4]}-{month[4:]}-15"
    return [{"dealDate": date, "dealAmountEok": price} for price in prices]


class ReportPriceComparisonTest(unittest.TestCase):
    def setUp(self):
        self.end_month = molit_transactions._shift_month(datetime.date.today().strftime("%Y%m"), -1)
        self.target = {"name": "대상", "district": "도봉구"}
        self.peers = [
            {"name": "비교1", "region": "도봉구", "legalDong": "창동"},
            {"name": "비교2", "region": "도봉구", "legalDong": "창동"},
            {"name": "비교3", "region": "도봉구", "legalDong": "창동"},
        ]

    def _compare(self, trades):
        with mock.patch.object(report_price_comparison, "_peer_entity", side_effect=lambda peer: {"name": peer["name"], "district": "도봉구"}), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, area: trades[entity["name"]]):
            return report_price_comparison.compare({}, self.target, self.peers, "84.5")

    def test_uses_same_calendar_months_and_falls_back_to_six_months(self):
        month = self.end_month
        trades = {
            "대상": _trades(month, 0, [10, 10, 10]) + _trades(month, 3, [9, 9, 9]),
            "비교1": _trades(month, 0, [11, 11, 11]) + _trades(month, 3, [10, 10, 10]),
            "비교2": _trades(month, 0, [9]) + _trades(month, 3, [10, 10, 10]),
            "비교3": _trades(month, 0, [10]) + _trades(month, 3, [11, 11, 11]),
        }
        result = self._compare(trades)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["periodMonths"], 6)
        self.assertEqual(result["averagePriceEok"], 9.5)
        self.assertEqual(result["peerAveragePriceEok"], 10.3333)
        self.assertEqual(result["differencePct"], -8.1)
        self.assertEqual(result["position"], "low")
        self.assertEqual(len(result["peers"]), 3)

    def test_three_month_comparison_needs_two_peers_with_three_trades_each(self):
        month = self.end_month
        trades = {
            "대상": _trades(month, 0, [10, 10, 10]),
            "비교1": _trades(month, 0, [11, 11, 11]),
            "비교2": _trades(month, 0, [12, 12, 12]),
            "비교3": _trades(month, 0, [8]),
        }
        result = self._compare(trades)

        self.assertEqual(result["periodMonths"], 3)
        self.assertEqual([peer["name"] for peer in result["peers"]], ["비교1", "비교2"])
        self.assertEqual(result["peerAveragePriceEok"], 11.5)
        self.assertEqual(result["differencePct"], -13.0)

    def test_peer_lookup_keeps_name_dong_and_jibun_together(self):
        master = [
            {"name": "주공19단지", "district": "도봉구", "legalDong": "창동", "jibun": "27"},
            {"name": "다른 단지", "district": "도봉구", "legalDong": "창동", "jibun": "827"},
        ]
        peer = {"name": "주공19단지", "region": "도봉구", "legalDong": "창동", "jibun": "27"}
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", master):
            self.assertIs(report_price_comparison._peer_entity(peer), master[0])

    def test_finds_trading_peers_beyond_initial_selection_as_reference(self):
        month = self.end_month
        target = {"name": "대상", "district": "도봉구", "legalDong": "창동", "jibun": "1", "households": 1000, "approvedAt": "2000-01-01"}
        master = [target,
                  {"name": "거래없음", "district": "도봉구", "legalDong": "창동", "jibun": "2", "households": 950, "approvedAt": "2001-01-01"},
                  {"name": "추가1", "district": "도봉구", "legalDong": "창동", "jibun": "3", "households": 900, "approvedAt": "2002-01-01"},
                  {"name": "추가2", "district": "도봉구", "legalDong": "창동", "jibun": "4", "households": 1100, "approvedAt": "2003-01-01"}]
        trades = {"대상": _trades(month, 0, [10, 10, 10]), "거래없음": [],
                  "추가1": _trades(month, 0, [9, 9, 9]), "추가2": _trades(month, 0, [11, 11, 11])}
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, area: trades[entity["name"]]):
            result = report_price_comparison.compare({}, target, [
                {"name": "거래없음", "region": "도봉구", "legalDong": "창동", "jibun": "2"}], "84")

        self.assertEqual(result["status"], "reference")
        self.assertEqual(result["selectionMethod"], "expanded")
        self.assertEqual(result["periodMonths"], 3)
        self.assertEqual([peer["name"] for peer in result["peers"]], ["추가1", "추가2"])
        self.assertEqual(result["differencePct"], 0)

    def test_twelve_month_only_comparison_is_reference(self):
        month = self.end_month
        trades = {"대상": _trades(month, 0, [10, 10, 10]),
                  "비교1": _trades(month, 8, [11, 11, 11]),
                  "비교2": _trades(month, 8, [9, 9, 9]),
                  "비교3": []}
        result = self._compare(trades)

        self.assertEqual(result["status"], "reference")
        self.assertEqual(result["periodMonths"], 12)
        self.assertEqual(result["selectionMethod"], "selected")

    def test_relaxes_price_and_scale_when_district_has_matching_trades(self):
        month = self.end_month
        target = {"name": "삼호4", "district": "노원구", "legalDong": "월계동", "jibun": "12", "households": 910, "approvedAt": "1987-07-06"}
        master = [target,
                  {"name": "비교1", "district": "노원구", "legalDong": "상계동", "jibun": "1", "households": 2600, "approvedAt": "1988-01-01"},
                  {"name": "비교2", "district": "노원구", "legalDong": "하계동", "jibun": "2", "households": 1900, "approvedAt": "1989-01-01"}]
        trades = {"삼호4": _trades(month, 0, [8, 8, 8]),
                  "비교1": _trades(month, 0, [6, 6, 6]),
                  "비교2": _trades(month, 0, [7, 7, 7])}
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=lambda entity, area: trades[entity["name"]]):
            result = report_price_comparison.compare({}, target, [], "50")

        self.assertEqual(result["status"], "reference")
        self.assertEqual(result["selectionMethod"], "relaxed")
        self.assertEqual(result["periodMonths"], 3)
        self.assertEqual({peer["name"] for peer in result["peers"]}, {"비교1", "비교2"})
        self.assertEqual(result["differencePct"], 23.1)

    def test_uses_nearby_area_and_normalizes_peer_prices_as_last_resort(self):
        month = self.end_month
        target = {"name": "대상", "district": "노원구", "legalDong": "월계동", "jibun": "12", "households": 900}
        master = [target,
                  {"name": "비교1", "district": "노원구", "legalDong": "월계동", "jibun": "13", "households": 900},
                  {"name": "비교2", "district": "노원구", "legalDong": "월계동", "jibun": "14", "households": 900}]
        own = [{**trade, "exclusiveArea": 50} for trade in _trades(month, 0, [8, 8, 8])]
        near = [{**trade, "exclusiveArea": 54} for trade in _trades(month, 0, [8.64, 8.64, 8.64])]
        def transactions(entity, area):
            if entity["name"] == "대상":
                return own
            return [] if area == "50" else near
        with mock.patch.object(report_price_comparison.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(report_price_comparison, "_transactions", side_effect=transactions):
            result = report_price_comparison.compare({}, target, [], "50")

        self.assertEqual(result["status"], "reference")
        self.assertEqual(result["selectionMethod"], "area_adjusted")
        self.assertEqual(result["peerAveragePriceEok"], 8)
        self.assertEqual(len(result["peers"]), 2)


if __name__ == "__main__":
    unittest.main()
