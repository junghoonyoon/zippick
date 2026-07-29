import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import applyhome_supply  # noqa: E402


class NormalizeRegionTest(unittest.TestCase):
    """주소를 앱이 쓰는 시군구 이름으로 맞추지 못하면 집계가 통째로 어긋난다."""

    def assert_region(self, address, expected, area=""):
        _sido, region = applyhome_supply.normalize_region(address, area)
        self.assertEqual(region, expected, f"{address} → {region}")

    def test_seoul_uses_bare_district(self):
        self.assert_region("서울특별시 노원구 상계동 670", "노원구")
        self.assert_region("서울특별시 강남구 대치동 964", "강남구")

    def test_gyeonggi_special_city_merges_city_and_district(self):
        self.assert_region("경기도 수원시 영통구 매탄동 176", "수원영통구")
        self.assert_region("경기도 성남시 분당구 정자동", "성남분당구")
        self.assert_region("경기도 고양시 덕양구 화정동", "고양덕양구")

    def test_gyeonggi_plain_city_keeps_city_name(self):
        self.assert_region("경기도 평택시 고덕면 방축리", "평택시")
        self.assert_region("경기도 남양주시 호평동 730", "남양주시")

    def test_county_is_supported(self):
        self.assert_region("경기도 가평군 가평읍", "가평군")

    def test_metro_city_district_gets_prefix(self):
        self.assert_region("부산광역시 해운대구 우동", "부산해운대구")
        self.assert_region("인천광역시 서구 청라동", "인천서구")

    def test_sejong_has_no_district(self):
        self.assert_region("세종특별자치시 나성동", "세종시")

    def test_namyangju_and_yangju_stay_distinct(self):
        """이 둘이 같은 키로 뭉치면 공급 경고가 뒤바뀐다."""
        _s1, namyangju = applyhome_supply.normalize_region("경기도 남양주시 호평동")
        _s2, yangju = applyhome_supply.normalize_region("경기도 양주시 옥정동")
        self.assertEqual(namyangju, "남양주시")
        self.assertEqual(yangju, "양주시")
        self.assertNotEqual(namyangju, yangju)

    def test_blank_address_is_not_guessed(self):
        self.assertEqual(applyhome_supply.normalize_region(""), ("", ""))

    def test_project_district_name_is_not_mistaken_for_a_gu(self):
        """`공공주택지구`처럼 구로 끝나는 사업지구명이 자치구로 잡히면 안 된다.

        실재하는 시·군·구는 가장 긴 것도 4자다(영등포구·미추홀구·부산진구).
        """
        self.assert_region("서울특별시 강동구 고덕강일 공공주택지구 1블록", "강동구")
        self.assert_region("경기도 화성시 동탄2택지개발지구", "화성시")

    def test_longest_real_district_names_still_pass(self):
        self.assert_region("서울특별시 영등포구 여의도동", "영등포구")
        self.assert_region("인천광역시 미추홀구 주안동", "인천미추홀구")
        self.assert_region("부산광역시 부산진구 부전동", "부산부산진구")


class ToRecordsTest(unittest.TestCase):
    def test_accepts_english_and_korean_field_names(self):
        """odcloud 자동변환은 영문, 파일데이터 노출은 한글로 온다. 둘 다 받아야 한다."""
        english = {
            "HOUSE_NM": "래미안 테스트",
            "HSSPLY_ADRES": "경기도 평택시 고덕면 방축리 100",
            "TOT_SUPLY_HSHLDCO": "1,234",
            "MVN_PREARNGE_YM": "202703",
        }
        korean = {
            "주택명": "힐스테이트 테스트",
            "공급위치": "서울특별시 노원구 상계동 670",
            "공급규모": "567",
            "입주예정월": "2027-09",
        }
        records, skipped = applyhome_supply.to_records([english, korean])

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["시군구"], "평택시")
        self.assertEqual(records[0]["세대수"], "1234")
        self.assertEqual(records[0]["입주예정월"], "2027-03")
        self.assertEqual(records[1]["자치구"], "노원구")
        self.assertEqual(records[1]["시군구"], "")
        self.assertEqual(records[1]["입주예정월"], "2027-09")
        self.assertEqual(sum(skipped.values()), 0)

    def test_rows_missing_required_fields_are_counted_not_guessed(self):
        rows = [
            {"HOUSE_NM": "월없음", "HSSPLY_ADRES": "경기도 평택시", "TOT_SUPLY_HSHLDCO": "100"},
            {"HOUSE_NM": "세대없음", "HSSPLY_ADRES": "경기도 평택시", "MVN_PREARNGE_YM": "202703"},
            {"HOUSE_NM": "주소없음", "TOT_SUPLY_HSHLDCO": "100", "MVN_PREARNGE_YM": "202703"},
        ]
        records, skipped = applyhome_supply.to_records(rows)

        self.assertEqual(records, [])
        self.assertEqual(skipped["no_month"], 1)
        self.assertEqual(skipped["no_households"], 1)
        self.assertEqual(skipped["no_region"], 1)

    def test_zero_households_is_dropped(self):
        rows = [{
            "HOUSE_NM": "0세대",
            "HSSPLY_ADRES": "경기도 평택시 고덕면",
            "TOT_SUPLY_HSHLDCO": "0",
            "MVN_PREARNGE_YM": "202703",
        }]
        records, skipped = applyhome_supply.to_records(rows)
        self.assertEqual(records, [])
        self.assertEqual(skipped["no_households"], 1)

    def test_output_columns_match_supply_forecast_reader(self):
        """수집 결과를 supply_forecast 가 그대로 읽어야 한다."""
        import supply_forecast

        rows = [{
            "HOUSE_NM": "테스트",
            "HSSPLY_ADRES": "경기도 평택시 고덕면 방축리",
            "TOT_SUPLY_HSHLDCO": "1000",
            "MVN_PREARNGE_YM": "202703",
        }]
        records, _ = applyhome_supply.to_records(rows)

        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        handle.close()
        applyhome_supply.write_csv(records, handle.name)

        supply_forecast._CACHE.clear()
        loaded = supply_forecast.load_rows(handle.name)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["region"], "평택시")
        self.assertEqual(loaded[0]["households"], 1000)
        supply_forecast._CACHE.clear()


class MergeTest(unittest.TestCase):
    """일일 트래픽 한도 때문에 나눠 받을 때 기존 수집분이 사라지면 안 된다."""

    def _tmp_csv(self, rows):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        handle.close()
        applyhome_supply.write_csv(rows, handle.name)
        return handle.name

    def _row(self, notice, name, region, month, households):
        return {
            "공고번호": notice,
            "시도": "경기도",
            "자치구": "",
            "시군구": region,
            "법정동": "",
            "대표단지명": name,
            "세대수": households,
            "상태": "입주예정",
            "입주예정월": month,
            "출처": "청약홈 분양정보 오픈API",
        }

    def test_same_name_and_month_but_different_notice_are_kept_apart(self):
        """블록·차수가 나뉜 별개 공고가 한 건으로 뭉개지면 세대수가 사라진다."""
        rows = [
            self._row("2026000001", "동탄 아이파크", "화성시", "2028-03", "500"),
            self._row("2026000002", "동탄 아이파크", "화성시", "2028-03", "700"),
        ]
        path = self._tmp_csv(rows)
        merged, added, before = applyhome_supply.merge_with_existing([], path)

        self.assertEqual(len(merged), 2)
        self.assertEqual(before, 2)
        self.assertEqual(sum(int(r["세대수"]) for r in merged), 1200)

    def test_rerun_does_not_shrink_the_file(self):
        rows = [
            self._row("2026000001", "가", "평택시", "2028-03", "500"),
            self._row("2026000002", "나", "평택시", "2028-09", "700"),
        ]
        path = self._tmp_csv(rows)
        merged, added, before = applyhome_supply.merge_with_existing(rows, path)

        self.assertEqual(len(merged), 2)
        self.assertEqual(added, 0)

    def test_partial_fetch_adds_to_existing(self):
        existing = [self._row("2026000001", "가", "평택시", "2028-03", "500")]
        path = self._tmp_csv(existing)
        incoming = [self._row("2026000002", "나", "평택시", "2028-09", "700")]

        merged, added, before = applyhome_supply.merge_with_existing(incoming, path)

        self.assertEqual(before, 1)
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)

    def test_same_notice_is_updated_not_duplicated(self):
        existing = [self._row("2026000001", "가", "평택시", "2028-03", "500")]
        path = self._tmp_csv(existing)
        updated = [self._row("2026000001", "가", "평택시", "2028-06", "520")]

        merged, added, _before = applyhome_supply.merge_with_existing(updated, path)

        self.assertEqual(len(merged), 1)
        self.assertEqual(added, 0)
        self.assertEqual(merged[0]["입주예정월"], "2028-06")
        self.assertEqual(merged[0]["세대수"], "520")


class QuotaTest(unittest.TestCase):
    def test_empty_response_raises_instead_of_reporting_no_supply(self):
        """한도 초과는 오류가 아니라 빈 응답으로 온다.

        이걸 '물량 없음'으로 넘기면 공급 경고가 통째로 사라진다.
        """
        calls = []

        def fake_fetch(key, page, size):
            calls.append(page)
            return {"currentCount": 0, "data": [], "totalCount": 0}

        original = applyhome_supply.fetch_page
        applyhome_supply.fetch_page = fake_fetch
        try:
            with self.assertRaises(applyhome_supply.QuotaExhausted):
                applyhome_supply.fetch_all("key", verbose=False)
        finally:
            applyhome_supply.fetch_page = original
        self.assertEqual(calls, [1])

    def test_budget_stops_before_exceeding_daily_limit(self):
        def fake_fetch(key, page, size):
            return {"data": [{"n": i} for i in range(size)], "totalCount": 5000}

        original = applyhome_supply.fetch_page
        applyhome_supply.fetch_page = fake_fetch
        try:
            rows = applyhome_supply.fetch_all(
                "key", page_size=1000, verbose=False, budget=900
            )
        finally:
            applyhome_supply.fetch_page = original
        self.assertEqual(len(rows), 900)


if __name__ == "__main__":
    unittest.main()
