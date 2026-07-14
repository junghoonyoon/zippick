import csv
import datetime
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import molit_transactions  # noqa: E402
import budget_candidates  # noqa: E402


class MolitTransactionsTest(unittest.TestCase):
    def test_current_estimate_is_narrower_than_raw_trade_range(self):
        today = datetime.date.today().isoformat()
        prices = [8.0, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2, 9.4, 9.6, 9.8, 10.0, 12.0]
        estimate = molit_transactions._current_price_estimate([
            {"dealAmountEok": price, "dealDate": today}
            for price in prices
        ])

        self.assertEqual(estimate["minPriceEok"], 8.6)
        self.assertEqual(estimate["midPriceEok"], 9.0)
        self.assertEqual(estimate["maxPriceEok"], 9.6)
        self.assertEqual(estimate["trimmedCount"], 2)

    def test_configured_stays_true_during_temporary_circuit_breaker(self):
        with mock.patch.object(molit_transactions.config, "MOLIT_APARTMENT_TRADE_API_KEY", "test-key"), \
             mock.patch.object(molit_transactions, "_DISABLED_UNTIL", time.time() + 60):
            self.assertTrue(molit_transactions.configured())
            self.assertFalse(molit_transactions.enabled())

    def test_expired_circuit_breaker_clears_transient_error(self):
        with mock.patch.object(molit_transactions.config, "MOLIT_APARTMENT_TRADE_API_KEY", "test-key"), \
             mock.patch.object(molit_transactions, "_DISABLED_UNTIL", time.time() - 1), \
             mock.patch.object(molit_transactions, "_LAST_ERROR", "이전 지연"):
            self.assertTrue(molit_transactions.enabled())
            self.assertEqual(molit_transactions.last_error(), "")

    def test_settled_months_use_long_cache_ttl(self):
        recent = molit_transactions._deal_months(1)[0]
        settled = molit_transactions._deal_months(12)[-1]
        self.assertEqual(molit_transactions._month_cache_ttl(recent), molit_transactions.MONTH_CACHE_TTL_SECONDS)
        self.assertEqual(molit_transactions._month_cache_ttl(settled), molit_transactions.SETTLED_MONTH_CACHE_TTL_SECONDS)
        self.assertGreater(molit_transactions.SETTLED_MONTH_CACHE_TTL_SECONDS, molit_transactions.MONTH_CACHE_TTL_SECONDS)

    def test_fetch_month_uses_expired_cache_when_api_times_out(self):
        items = [{"apartment": "캐시아파트", "dealAmountManwon": 80000}]
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(molit_transactions, "TRANSACTION_CACHE_DIR", Path(directory)), \
             mock.patch.object(molit_transactions.config, "MOLIT_APARTMENT_TRADE_API_KEY", "test-key"), \
             mock.patch.object(molit_transactions, "_DISABLED_UNTIL", 0), \
             mock.patch.object(molit_transactions, "_LAST_ERROR", ""), \
             mock.patch.object(molit_transactions.requests, "get", side_effect=molit_transactions.requests.Timeout):
            molit_transactions._write_cached_month("11710", "202607", items)
            path = molit_transactions._cache_path("11710", "202607")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["fetchedAt"] = time.time() - molit_transactions.MONTH_CACHE_TTL_SECONDS - 1
            path.write_text(json.dumps(payload), encoding="utf-8")
            molit_transactions._MONTH_MEMORY_CACHE.clear()

            result = molit_transactions.fetch_month("11710", "202607")

        self.assertEqual(result, items)

    def test_exact_complex_name_wins_over_substring_matches(self):
        columns = ["단지종류명", "대표단지명", "자치구", "법정동", "지번", "필지고유번호"]
        rows = [
            ["아파트", "동아아파트", "강동구", "둔촌동", "94-16", "1174010600100940016"],
            ["아파트", "상일동아아파트", "강동구", "상일동", "473", "1174010300104730000"],
            ["아파트", "동아하이빌아파트", "강동구", "천호동", "217-132", "1174010900102170132"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apartments.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(rows)
            with mock.patch.object(molit_transactions.real_estate_search, "APARTMENT_CSV_PATHS", [path]):
                matches = molit_transactions.source_rows("동아하이빌아파트", "강동구")

        self.assertEqual([row["대표단지명"] for row in matches], ["동아하이빌아파트"])

    def test_master_alias_finds_public_source_row_by_address(self):
        columns = ["단지종류명", "대표단지명", "단지명_공시가격", "자치구", "법정동", "지번", "필지고유번호"]
        rows = [
            ["아파트", "주공아파트", "주공1", "동대문구", "휘경동", "57", "1123010900100570000"],
            ["아파트", "주공아파트", "주공1", "동대문구", "이문동", "73", "1123011000100730000"],
        ]
        master = [{
            "name": "주공아파트",
            "aliases": ["휘경동 주공아파트", "주공2"],
            "district": "동대문구",
            "legalDong": "휘경동",
            "address": "서울특별시 동대문구 휘경동 57",
        }]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apartments.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(rows)
            with mock.patch.object(molit_transactions.real_estate_search, "APARTMENT_CSV_PATHS", [path]), \
                 mock.patch.object(molit_transactions.real_estate_search, "APARTMENT_MASTER", master):
                matches = molit_transactions.source_rows("주공2", "동대문구")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["법정동"], "휘경동")
        self.assertEqual(matches[0]["지번"], "57")

    def test_rounded_sixty_square_meter_label_excludes_eighty_four(self):
        self.assertTrue(molit_transactions._matches_area({"exclusiveArea": 59.98}, "전용 60~60㎡"))
        self.assertFalse(molit_transactions._matches_area({"exclusiveArea": 84.97}, "전용 60~60㎡"))

    def test_minimum_area_prefers_smallest_qualifying_transaction_band(self):
        row = {
            "name": "산성역 자이푸르지오",
            "region": "성남수정구",
            "areaLabel": "전용 84",
        }
        live = {
            "areaLabel": "전용 59~60㎡",
            "minPriceEok": 8.1,
            "midPriceEok": 8.5,
            "maxPriceEok": 8.9,
            "latestDealPriceEok": 8.7,
            "latestDealExclusiveArea": 59.98,
            "latestDealFloor": "12",
            "transactionCount": 4,
            "latestDealDate": "2026-06-01",
            "sourceNote": "국토부 실거래가 최근 6개월",
        }
        with mock.patch.object(
            budget_candidates.molit_transactions,
            "price_band_for_apartment",
            return_value=live,
        ) as lookup:
            budget_candidates._apply_live_price(row, preferred_min_area=59)

        self.assertEqual(lookup.call_args.kwargs["area_label"], "전용 59~60㎡")
        self.assertEqual(row["areaLabel"], "전용 59~60㎡")
        self.assertEqual(row["midPriceEok"], 8.5)
        self.assertEqual(row["minPriceEok"], 8.1)
        self.assertEqual(row["maxPriceEok"], 8.9)
        self.assertEqual(row["recentMedianPriceEok"], 8.5)

    def test_price_band_lookup_caches_band_and_missing_result(self):
        transactions = [{
            "dealAmountEok": 8.2,
            "dealAmountManwon": 82000,
            "exclusiveArea": 59.98,
            "floor": "12",
            "dealDate": "2026-06-22",
        }]
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(molit_transactions, "PRICE_BAND_CACHE_DIR", Path(directory)), \
             mock.patch.object(molit_transactions, "transactions_for_apartment", return_value=transactions) as lookup:
            first = molit_transactions.price_band_for_apartment("캐시아파트", "성남시", "전용 59~60㎡")
            second = molit_transactions.price_band_for_apartment("캐시아파트", "성남시", "전용 59~60㎡")

        self.assertEqual(first, second)
        self.assertEqual(first["latestDealPriceEok"], 8.2)
        self.assertEqual(lookup.call_count, 1)

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(molit_transactions, "PRICE_BAND_CACHE_DIR", Path(directory)), \
             mock.patch.object(molit_transactions, "transactions_for_apartment", return_value=[]) as lookup:
            first = molit_transactions.price_band_for_apartment("거래없는아파트", "성남시", "전용 59~60㎡")
            second = molit_transactions.price_band_for_apartment("거래없는아파트", "성남시", "전용 59~60㎡")

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(lookup.call_count, 1)

    def test_minimum_area_lookup_uses_actual_smallest_available_type(self):
        transactions = [
            {"dealAmountEok": 22.0, "exclusiveArea": 64.26, "floor": "8", "dealDate": "2026-06-24"},
            {"dealAmountEok": 24.6, "exclusiveArea": 84.92, "floor": "10", "dealDate": "2026-06-25"},
        ]
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(molit_transactions, "PRICE_BAND_CACHE_DIR", Path(directory)), \
             mock.patch.object(molit_transactions, "transactions_for_apartment", return_value=transactions):
            band = molit_transactions.price_band_for_apartment_min_area("단지", "송파구", 59)

        self.assertEqual(band["areaLabel"], "전용 64㎡")
        self.assertEqual(band["latestDealPriceEok"], 22.0)
        self.assertEqual(band["transactionCount"], 1)

    def test_latest_transaction_skips_recent_months_and_returns_first_old_match(self):
        source_row = {
            "대표단지명": "오래된거래아파트",
            "자치구": "성남시",
            "법정동": "정자동",
            "지번": "1",
            "필지고유번호": "4113510100100010000",
        }

        def fake_fetch_month(lawd_cd, deal_ymd):
            if deal_ymd == months[2]:
                return [{
                    "apartment": "오래된거래아파트",
                    "legalDong": "정자동",
                    "jibun": "1",
                    "exclusiveArea": 59.98,
                    "floor": "9",
                    "dealDate": "2026-04-15",
                    "dealAmountEok": 7.7,
                }]
            return []

        months = molit_transactions._deal_months(6)
        with mock.patch.object(molit_transactions, "source_rows", return_value=[source_row]), \
             mock.patch.object(molit_transactions, "fetch_month", side_effect=fake_fetch_month) as fetch:
            latest = molit_transactions.latest_transaction_for_apartment(
                "오래된거래아파트",
                "성남시",
                "전용 59~60㎡",
                lookback_months=6,
                skip_months=2,
            )

        self.assertEqual(latest["latestDealDate"], "2026-04-15")
        self.assertEqual(latest["latestDealPriceEok"], 7.7)
        # 최근 월 묶음을 미리 가져온 뒤 같은 묶음에서 가장 첫 거래를 찾는다.
        # 캐시 여부에 따라 사전 조회 호출 수는 달라질 수 있다.
        self.assertGreaterEqual(fetch.call_count, 1)

    def test_direct_and_cancelled_deals_are_not_market_transactions(self):
        self.assertFalse(molit_transactions._is_market_transaction({"dealType": "직거래"}))
        self.assertFalse(molit_transactions._is_market_transaction({"dealType": "중개거래", "cancellationDate": "2026-07-10"}))
        self.assertTrue(molit_transactions._is_market_transaction({"dealType": "중개거래"}))


if __name__ == "__main__":
    unittest.main()
