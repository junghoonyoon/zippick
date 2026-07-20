import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import apartment_leaders  # noqa: E402


def _trade(date, price, area=84.8, **extra):
    return {
        "dealDate": date,
        "dealAmountManwon": price,
        "exclusiveArea": area,
        **extra,
    }


def _monthly_trades(prices, area=84.8):
    return [
        _trade(f"{month}-15", price, area=area)
        for month, price in prices
    ]


class ApartmentLeadersTest(unittest.TestCase):
    def test_frontend_exposes_region_area_categories_and_confidence(self):
        html = (ROOT / "앱화면" / "real-estate-search.html").read_text(encoding="utf-8")
        self.assertIn('id="leaderEntry"', html)
        self.assertIn('id="leaderSido"', html)
        self.assertIn('id="leaderSigungu"', html)
        self.assertIn('id="leaderAreaBucket"', html)
        for category in ("overall", "price", "leadership", "residence", "new_build", "value"):
            self.assertIn(f'data-leader-category="{category}"', html)
        self.assertIn("데이터 신뢰도", html)
        self.assertIn("/api/apartment-leaders", html)

    def test_area_bucket_boundaries(self):
        cases = {
            38.99: "lt39",
            39: "39-49",
            49.99: "39-49",
            50: "50-69",
            69.99: "50-69",
            70: "70-89",
            89.99: "70-89",
            90: "90plus",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(apartment_leaders.area_bucket(value), expected)

    def test_percentile_rank_uses_average_rank_for_ties(self):
        self.assertEqual(
            apartment_leaders.percentile_ranks([10, 20, 20, 30, None]),
            [0.0, 50.0, 50.0, 100.0, None],
        )

    def test_sparse_price_is_adjusted_toward_district_median(self):
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 10), 120000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 5), 116000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 2), 110000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 1), 104000)
        self.assertIsNone(apartment_leaders.adjusted_price(120000, 100000, 0))

    def test_age_station_and_confidence_scores_follow_specification(self):
        self.assertEqual(apartment_leaders.age_score("2024-01-01", "2026-06"), 100)
        self.assertEqual(apartment_leaders.age_score("2013-01-01", "2026-06"), 70)
        self.assertEqual(apartment_leaders.station_score(300), 100)
        self.assertEqual(apartment_leaders.station_score(501), 75)
        self.assertEqual(apartment_leaders.station_score(None), None)
        self.assertEqual(apartment_leaders.confidence_for_count(10)[1], "HIGH")
        self.assertEqual(apartment_leaders.confidence_for_count(5)[1], "MEDIUM")
        self.assertEqual(apartment_leaders.confidence_for_count(2)[1], "LOW")
        self.assertEqual(apartment_leaders.confidence_for_count(1)[1], "CANDIDATE")

    def test_cancelled_direct_and_other_area_trades_are_excluded(self):
        transactions = [
            _trade("2026-06-15", 100000),
            _trade("2026-05-15", 100000, cancellationDate="2026-06-01"),
            _trade("2026-04-15", 100000, dealType="직거래"),
            _trade("2026-03-15", 100000, area=59.8),
        ]
        rows = apartment_leaders._transactions_in_window(
            transactions,
            "2026-06",
            12,
            "70-89",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dealDate"], "2026-06-15")

    def test_full_ranking_is_region_and_area_scoped_and_excludes_one_trade(self):
        entities = [
            {
                "name": "선도단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 1000,
                "approvedAt": "2021-01-01",
                "dedupeKey": "선도",
            },
            {
                "name": "신축단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 600,
                "approvedAt": "2025-01-01",
                "dedupeKey": "신축",
            },
            {
                "name": "한건고가",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "다동",
                "households": 2000,
                "approvedAt": "2018-01-01",
                "dedupeKey": "한건",
            },
        ]
        leader_prices = [
            ("2025-06", 80000),
            ("2025-07", 82000),
            ("2025-08", 84000),
            ("2025-09", 86000),
            ("2025-10", 88000),
            ("2025-11", 90000),
            ("2025-12", 92000),
            ("2026-01", 96000),
            ("2026-02", 100000),
            ("2026-03", 104000),
            ("2026-04", 108000),
            ("2026-05", 112000),
            ("2026-06", 116000),
        ]
        new_prices = [
            ("2025-06", 90000),
            ("2025-07", 90000),
            ("2025-08", 90000),
            ("2025-09", 90000),
            ("2025-10", 90000),
            ("2025-11", 90000),
            ("2025-12", 90000),
            ("2026-01", 90000),
            ("2026-02", 90000),
            ("2026-03", 90000),
            ("2026-04", 90000),
            ("2026-05", 90000),
            ("2026-06", 90000),
        ]
        data = [
            (entities[0], _monthly_trades(leader_prices)),
            (entities[1], _monthly_trades(new_prices)),
            (entities[2], [_trade("2026-06-15", 250000)]),
        ]
        with mock.patch.object(apartment_leaders, "matching_entities", return_value=entities), \
             mock.patch.object(apartment_leaders, "_load_transactions", return_value=data):
            result = apartment_leaders.calculate_rankings(
                "서울특별시",
                "테스트구",
                area_bucket_value="70-89",
                reference_month="2026-06",
            )

        overall = result["rankings"]["overall"]
        self.assertEqual(overall[0]["apartmentName"], "선도단지")
        self.assertNotIn("한건고가", {row["apartmentName"] for row in overall})
        self.assertEqual(result["rankings"]["new_build"][0]["apartmentName"], "신축단지")
        self.assertEqual(result["areaBucket"], "70-89")
        self.assertEqual(overall[0]["calculationVersion"], apartment_leaders.CALCULATION_VERSION)
        self.assertTrue(overall[0]["reasons"])
        self.assertIn(
            "지하철 거리 데이터가 없어 역 접근성은 점수에서 제외했습니다.",
            overall[0]["warnings"],
        )

    def test_tie_breaker_prefers_confidence_then_transactions_then_price(self):
        rows = [
            {
                "apartmentName": "나단지",
                "overallScore": 80,
                "dataConfidenceScore": 75,
                "transactionCount12m": 8,
                "priceScore": 90,
            },
            {
                "apartmentName": "가단지",
                "overallScore": 80,
                "dataConfidenceScore": 100,
                "transactionCount12m": 10,
                "priceScore": 70,
            },
        ]
        for row in rows:
            row.update({
                "confidenceLevel": "HIGH",
                "sigungu": "테스트구",
                "areaBucket": "70-89",
                "activeTransactionMonths12m": 3,
                "transactionTurnoverPercentile": 50,
                "activeTransactionMonthsPercentile": 50,
                "scores": {},
                "stationScore": None,
                "ageScore": 50,
                "householdCount": 100,
                "leadershipScore": 50,
                "liquidityScore": 50,
                "completionYear": 2010,
                "isNewBuild": False,
                "relativeReturn6m": 0,
            })
        ranked = apartment_leaders._rank_category(rows, "overall", 5)
        self.assertEqual(ranked[0]["apartmentName"], "가단지")


if __name__ == "__main__":
    unittest.main()
