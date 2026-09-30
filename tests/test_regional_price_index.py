import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import regional_price_index


def _api_row(name, period, value, item="지수"):
    return {
        "STATBL_ID": regional_price_index.STATBL_ID,
        "DTACYCLE_CD": "WK",
        "CLS_NM": name.split(">")[-1],
        "CLS_FULLNM": name,
        "ITM_NM": item,
        "DTA_VAL": value,
        "WRTTIME_DESC": period,
    }


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RegionalPriceIndexTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"regions": regional_price_index._parse_rows([
            _api_row("서울>강북지역>도심권>종로구", "2026-09-07", 101.0),
            _api_row("서울>강북지역>도심권>종로구", "2026-08-31", 100.0),
            _api_row("서울>강북지역>도심권>종로구", "2026-09-14", 102.0),
            _api_row("서울>강북지역>도심권>중구", "2026-09-07", 90.0),
            _api_row("서울>강북지역>도심권>중구", "2026-09-14", 91.0),
            _api_row("부산>중부산권>중구", "2026-09-07", 80.0),
            _api_row("부산>중부산권>중구", "2026-09-14", 79.0),
            _api_row("충남>천안시>동남구", "2026-09-07", 95.0),
            _api_row("충남>천안시>동남구", "2026-09-14", 95.5),
            _api_row("경기>경부1권>성남시>분당구", "2026-09-07", 110.0),
            _api_row("경기>경부1권>성남시>분당구", "2026-09-14", 111.0),
            _api_row("서울>강북지역>도심권>종로구", "2026-09-14", 0.3, item="변동률"),
        ])}

    def test_parses_weekly_rows_in_date_order(self):
        points = self.snapshot["regions"]["서울>강북지역>도심권>종로구"]

        self.assertEqual(points, [["2026-08-31", 100.0], ["2026-09-07", 101.0], ["2026-09-14", 102.0]])

    def test_matches_region_by_province_and_district(self):
        jongno = regional_price_index.series_for_region("서울특별시 종로구", self.snapshot)
        seoul_jung = regional_price_index.series_for_region("서울특별시 중구", self.snapshot)
        busan_jung = regional_price_index.series_for_region("부산광역시 중구", self.snapshot)
        bundang = regional_price_index.series_for_region("경기도 성남시 분당구", self.snapshot)

        self.assertEqual(jongno["name"], "서울>강북지역>도심권>종로구")
        self.assertEqual(seoul_jung["points"][-1][1], 91.0)
        self.assertEqual(busan_jung["points"][-1][1], 79.0)
        self.assertEqual(bundang["label"], "경기 성남시 분당구")

    def test_does_not_borrow_same_district_name_from_another_city(self):
        self.assertIsNone(regional_price_index.series_for_region("충청남도 아산시 동남구", self.snapshot))
        self.assertIsNone(regional_price_index.series_for_region("서울특별시 없는구", self.snapshot))
        self.assertIsNone(regional_price_index.series_for_region("", self.snapshot))

    def test_uses_the_week_in_effect_on_the_deal_date(self):
        series = regional_price_index.series_for_region("서울특별시 종로구", self.snapshot)

        self.assertEqual(regional_price_index.value_on(series, "2026-09-07"), 101.0)
        self.assertEqual(regional_price_index.value_on(series, "2026-09-13"), 101.0)
        self.assertEqual(regional_price_index.value_on(series, "2026-09-30"), 102.0)
        self.assertEqual(regional_price_index.value_on(series, "2026-08-25"), 100.0)
        self.assertIsNone(regional_price_index.value_on(series, "2026-07-01"))

    def test_rejects_an_index_that_is_too_old(self):
        series = regional_price_index.series_for_region("서울특별시 종로구", self.snapshot)

        fresh = regional_price_index.latest_point(series, today=datetime.date(2026, 9, 29))
        stale = regional_price_index.latest_point(series, today=datetime.date(2026, 11, 1))

        self.assertEqual(fresh, {"period": "2026-09-14", "value": 102.0})
        self.assertIsNone(stale)

    def test_without_key_never_calls_the_api(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(regional_price_index, "CACHE_PATH", Path(directory) / "index.json"), \
                mock.patch.object(regional_price_index.config, "RONE_API_KEY", ""), \
                mock.patch.object(regional_price_index, "urlopen") as urlopen:
            self.assertIsNone(regional_price_index.latest_snapshot(allow_fetch=True))
            urlopen.assert_not_called()

    def test_fetches_all_pages_and_reuses_the_saved_snapshot(self):
        pages = [
            {"SttsApiTblData": [
                {"head": [{"list_total_count": 3}, {"RESULT": {"CODE": "INFO-000"}}]},
                {"row": [
                    _api_row("서울>강북지역>도심권>종로구", "2026-09-07", 101.0),
                    _api_row("서울>강북지역>도심권>종로구", "2026-09-14", 102.0),
                ]},
            ]},
            {"SttsApiTblData": [
                {"head": [{"list_total_count": 3}, {"RESULT": {"CODE": "INFO-000"}}]},
                {"row": [_api_row("서울>강북지역>도심권>중구", "2026-09-14", 91.0)]},
            ]},
        ]
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(regional_price_index, "CACHE_PATH", Path(directory) / "index.json"), \
                mock.patch.object(regional_price_index.config, "RONE_API_KEY", "test-key"), \
                mock.patch.object(regional_price_index, "PAGE_SIZE", 2), \
                mock.patch.object(
                    regional_price_index, "urlopen",
                    side_effect=[_Response(page) for page in pages],
                ) as urlopen:
            first = regional_price_index.latest_snapshot(allow_fetch=True)
            second = regional_price_index.latest_snapshot(allow_fetch=True)

            self.assertEqual(urlopen.call_count, 2)
            self.assertIn("pIndex=2", urlopen.call_args_list[1].args[0].full_url)
            self.assertEqual(first["asOf"], "2026-09-14")
            self.assertEqual(len(first["regions"]), 2)
            self.assertEqual(second["regions"], first["regions"])

    def test_error_response_leaves_the_index_unavailable(self):
        error = {"RESULT": {"CODE": "ERROR-290", "MESSAGE": "인증키가 유효하지 않습니다."}}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(regional_price_index, "CACHE_PATH", Path(directory) / "index.json"), \
                mock.patch.object(regional_price_index.config, "RONE_API_KEY", "bad-key"), \
                mock.patch.object(regional_price_index, "urlopen", return_value=_Response(error)):
            self.assertIsNone(regional_price_index.latest_snapshot(allow_fetch=True))


if __name__ == "__main__":
    unittest.main()
