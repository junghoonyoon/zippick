import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import market_indicators


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class MarketIndicatorsTest(unittest.TestCase):
    def test_reads_latest_base_rate_and_year_change(self):
        payload = {
            "StatisticSearch": {
                "row": [
                    {"TIME": "20250929", "DATA_VALUE": "3.25"},
                    {"TIME": "20260929", "DATA_VALUE": "2.75"},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            market_indicators.config, "ECOS_API_KEY", "test-key"
        ), mock.patch.object(
            market_indicators, "CACHE_PATH", Path(directory) / "market.json"
        ), mock.patch.object(
            market_indicators, "urlopen", return_value=_Response(payload)
        ):
            result = market_indicators.latest_snapshot(refresh=True)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["baseRatePct"], 2.75)
        self.assertEqual(result["baseRateChangePp12m"], -0.5)
        self.assertEqual(result["asOf"], "2026-09-29")

    def test_returns_clear_status_without_key(self):
        with mock.patch.object(market_indicators.config, "ECOS_API_KEY", ""):
            result = market_indicators.latest_snapshot(refresh=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("API 키", result["reason"])


if __name__ == "__main__":
    unittest.main()
