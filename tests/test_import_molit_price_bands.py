import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import import_molit_price_bands  # noqa: E402
import budget_candidates  # noqa: E402


class ImportMolitPriceBandsTest(unittest.TestCase):
    def test_direct_and_cancelled_deals_are_excluded(self):
        fields = [
            "NO", "단지명", "전용면적(㎡)", "거래금액(만원)", "거래유형",
            "해제사유발생일", "시군구", "법정동", "지번", "계약년월", "계약일",
        ]
        base = {
            "단지명": "테스트아파트",
            "전용면적(㎡)": "59.9",
            "거래금액(만원)": "80000",
            "시군구": "서울특별시 성북구",
            "법정동": "테스트동",
            "지번": "1",
            "계약년월": "202606",
        }
        rows = [
            {**base, "NO": "1", "계약일": "1", "거래유형": "중개거래", "해제사유발생일": ""},
            {**base, "NO": "2", "계약일": "2", "거래유형": "직거래", "해제사유발생일": ""},
            {**base, "NO": "3", "계약일": "3", "거래유형": "중개거래", "해제사유발생일": "20260610"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "molit.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(rows)
            bands, raw_count = import_molit_price_bands.build_price_bands(
                source, min_transactions=1,
            )

        self.assertEqual(raw_count, 3)
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0]["transaction_count"], 1)
        self.assertEqual(bands[0]["market_transaction_only"], "true")

    def test_legacy_molit_csv_without_market_only_marker_is_ignored(self):
        fields = [
            "name", "region", "min_price_억", "mid_price_억", "max_price_억",
            "price_source", "market_transaction_only", "transaction_count",
        ]
        rows = [
            {
                "name": "검증전아파트", "region": "성북구", "min_price_억": "7",
                "mid_price_억": "8", "max_price_억": "9", "price_source": "molit_csv",
                "market_transaction_only": "", "transaction_count": "6",
            },
            {
                "name": "검증완료아파트", "region": "성북구", "min_price_억": "7",
                "mid_price_억": "8", "max_price_억": "9", "price_source": "molit_csv",
                "market_transaction_only": "true", "transaction_count": "5",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bands.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with mock.patch.object(budget_candidates, "PRICE_BAND_CSV_PATHS", [source]):
                loaded = budget_candidates._load_price_bands()

        self.assertEqual([row["name"] for row in loaded], ["검증완료아파트"])


if __name__ == "__main__":
    unittest.main()
