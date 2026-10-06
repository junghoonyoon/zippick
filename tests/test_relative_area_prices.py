import datetime
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import relative_area_prices  # noqa: E402


class RelativeAreaPricesTest(unittest.TestCase):
    def test_marks_84_or_59_only_when_ratio_moves_enough(self):
        today = datetime.date(2026, 10, 6)
        rows = []
        for deal_date, small_price, large_price in (
            ("2025-08-01", 8, 12),
            ("2025-09-01", 8, 12),
            ("2025-10-01", 8, 12),
            ("2026-07-01", 10, 13),
            ("2026-08-01", 10, 13),
            ("2026-09-01", 10, 13),
        ):
            rows.extend([
                {"exclusiveArea": 59.8, "dealAmountEok": small_price, "dealDate": deal_date},
                {"exclusiveArea": 84.9, "dealAmountEok": large_price, "dealDate": deal_date},
            ])
        signal = relative_area_prices.relative_area_price_signal(rows, today=today)
        self.assertEqual(signal["state"], "ready")
        self.assertEqual(signal["cheaperArea"], 84)
        self.assertEqual(signal["recentMedianPriceEok"], {"59": 10, "84": 13})
        self.assertEqual(signal["counts"]["recent"], {"59": 3, "84": 3})
        self.assertEqual(signal["latestDealDate"], "2026-09-01")

        reversed_prices = [
            {**row, "dealAmountEok": 17 if row["exclusiveArea"] > 80 else 10}
            if row["dealDate"] >= "2026-07-01" else row
            for row in rows
        ]
        self.assertEqual(
            relative_area_prices.relative_area_price_signal(reversed_prices, today=today)["cheaperArea"],
            59,
        )
        small_change = [
            {**row, "dealAmountEok": 15 if row["exclusiveArea"] > 80 else 10}
            if row["dealDate"] >= "2026-07-01" else row
            for row in rows
        ]
        self.assertIsNone(
            relative_area_prices.relative_area_price_signal(small_change, today=today)["cheaperArea"]
        )

    def test_refuses_sparse_or_stale_trades(self):
        today = datetime.date(2026, 10, 6)
        sparse = [
            {"exclusiveArea": area, "dealAmountEok": price, "dealDate": date}
            for area, price, date in (
                (59.8, 8, "2025-08-01"), (84.9, 12, "2025-08-01"),
                (59.8, 10, "2026-08-01"), (84.9, 13, "2026-08-01"),
            )
        ]
        self.assertEqual(
            relative_area_prices.relative_area_price_signal(sparse, today=today)["state"],
            "insufficient",
        )
        stale = [{**row, "dealDate": "2024-08-01"} for row in sparse]
        self.assertEqual(
            relative_area_prices.relative_area_price_signal(stale, today=today)["state"],
            "insufficient",
        )
