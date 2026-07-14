import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

import reb_price_estimator


class RebPriceEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "data.db"
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE reb_index(region TEXT, period TEXT, value REAL, PRIMARY KEY(region, period))")
            con.executemany("INSERT INTO reb_index VALUES(?,?,?)", [
                ("서울>강남지역>동남권>강남구", "202601", 100),
                ("서울>강남지역>동남권>강남구", "202602", 110),
                ("부산>도심권>중구", "202601", 100),
                ("서울>도심권>중구", "202601", 100),
            ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_adjust_price_uses_same_index_ratio_as_backtest(self):
        self.assertEqual(reb_price_estimator.adjust_price(10, 100, 110), 11)

    def test_resolve_region_prefers_city_and_district_leaf(self):
        self.assertEqual(
            reb_price_estimator.resolve_region("서울시 강남구", self.db),
            "서울>강남지역>동남권>강남구",
        )

    def test_ambiguous_district_requires_parent_region(self):
        with self.assertRaises(reb_price_estimator.AmbiguousRegionError):
            reb_price_estimator.resolve_region("중구", self.db)

    def test_estimate_adjusts_old_trade_and_keeps_post_index_trade(self):
        result = reb_price_estimator.estimate_transactions([
            {"dealDate": "2026-01-15", "dealAmountEok": 10},
            {"dealDate": "2026-02-20", "dealAmountEok": 12},
            {"dealDate": "2026-03-02", "dealAmountEok": 13},
        ], "서울 강남구", self.db, today=dt.date(2026, 3, 10))
        self.assertEqual(
            [row["adjustedPriceEok"] for row in result["adjustedTransactions"]],
            [13.0, 12.0, 11.0],
        )
        self.assertEqual(result["estimate"]["midPriceEok"], 12.0)
        self.assertEqual(result["estimate"]["minPriceEok"], 11.5)
        self.assertEqual(result["estimate"]["maxPriceEok"], 12.5)
        self.assertEqual(result["index"]["latestPeriod"], "202602")


if __name__ == "__main__":
    unittest.main()
