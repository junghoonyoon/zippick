import csv
import datetime
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import supply_forecast  # noqa: E402
import planned_rail  # noqa: E402


COLUMNS = ["시도", "자치구", "시군구", "법정동", "대표단지명", "세대수", "입주예정월"]


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


class SupplyForecastTest(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 7, 1)
        supply_forecast._CACHE.clear()

    def tearDown(self):
        supply_forecast._CACHE.clear()

    def _fixture(self, rows):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8"
        )
        handle.close()
        write_csv(handle.name, rows)
        return handle.name

    def test_aggregates_by_half_year(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "평택시", "세대수": "1200", "입주예정월": "2027-03"},
                {"시도": "경기도", "시군구": "평택시", "세대수": "800", "입주예정월": "2027-05"},
                {"시도": "경기도", "시군구": "평택시", "세대수": "500", "입주예정월": "2027-09"},
            ]
        )
        result = supply_forecast.outlook("평택시", today=self.today, path=path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["offeredHouseholds"], 2500)
        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["timeline"][0]["label"], "2027년 상반기")
        self.assertEqual(result["timeline"][0]["offeredHouseholds"], 2000)
        self.assertEqual(result["timeline"][1]["offeredHouseholds"], 500)
        self.assertEqual(result["peak"]["offeredHouseholds"], 2000)

    def test_yangju_supply_is_not_counted_for_namyangju(self):
        """이름이 겹치는 다른 지역 물량이 섞이면 경고가 통째로 틀린다."""
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "양주시", "세대수": "5000", "입주예정월": "2027-03"},
                {"시도": "경기도", "시군구": "남양주시", "세대수": "300", "입주예정월": "2027-03"},
            ]
        )
        namyangju = supply_forecast.outlook("남양주시", today=self.today, path=path)
        yangju = supply_forecast.outlook("양주시", today=self.today, path=path)

        self.assertEqual(namyangju["offeredHouseholds"], 300)
        self.assertEqual(yangju["offeredHouseholds"], 5000)

    def test_parent_region_still_matches_child_district(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "수원영통구", "세대수": "700", "입주예정월": "2027-03"},
            ]
        )
        result = supply_forecast.outlook("수원", today=self.today, path=path)
        self.assertEqual(result["offeredHouseholds"], 700)

    def test_past_and_far_future_rows_are_excluded(self):
        path = self._fixture(
            [
                {"시도": "서울특별시", "자치구": "노원구", "세대수": "900", "입주예정월": "2025-03"},
                {"시도": "서울특별시", "자치구": "노원구", "세대수": "400", "입주예정월": "2027-03"},
                {"시도": "서울특별시", "자치구": "노원구", "세대수": "600", "입주예정월": "2035-03"},
            ]
        )
        result = supply_forecast.outlook("노원구", today=self.today, path=path)
        self.assertEqual(result["offeredHouseholds"], 400)

    def test_missing_region_is_marked_unavailable_not_zero(self):
        """자료가 없는 것과 물량이 0인 것은 다르다. 섞으면 잘못된 안심을 준다."""
        path = self._fixture(
            [{"시도": "경기도", "시군구": "평택시", "세대수": "100", "입주예정월": "2027-03"}]
        )
        result = supply_forecast.outlook("강릉시", today=self.today, path=path)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("totalHouseholds", result)

    def test_heavy_level_triggers_on_peak_or_cumulative(self):
        peak_heavy = self._fixture(
            [{"시도": "경기도", "시군구": "평택시", "세대수": "3500", "입주예정월": "2027-03"}]
        )
        supply_forecast._CACHE.clear()
        self.assertEqual(
            supply_forecast.outlook("평택시", today=self.today, path=peak_heavy)["level"],
            "heavy",
        )

        spread_heavy = self._fixture(
            [
                {"시도": "경기도", "시군구": "평택시", "세대수": "2200", "입주예정월": "2027-03"},
                {"시도": "경기도", "시군구": "평택시", "세대수": "2200", "입주예정월": "2027-09"},
                {"시도": "경기도", "시군구": "평택시", "세대수": "2200", "입주예정월": "2028-03"},
            ]
        )
        supply_forecast._CACHE.clear()
        self.assertEqual(
            supply_forecast.outlook("평택시", today=self.today, path=spread_heavy)["level"],
            "heavy",
        )

    def test_sentence_always_discloses_the_undercount(self):
        """조합원 분양분 누락을 안 밝히면 과소 물량을 사실처럼 파는 셈이 된다."""
        path = self._fixture(
            [{"시도": "경기도", "시군구": "평택시", "세대수": "4000", "입주예정월": "2027-03"}]
        )
        text = supply_forecast.sentence(
            supply_forecast.outlook("평택시", today=self.today, path=path)
        )
        self.assertIn("조합원", text)
        self.assertIn("5,680세대", text)

    def test_rows_without_month_or_households_are_dropped(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "평택시", "세대수": "", "입주예정월": "2027-03"},
                {"시도": "경기도", "시군구": "평택시", "세대수": "500", "입주예정월": ""},
                {"시도": "경기도", "시군구": "평택시", "세대수": "700", "입주예정월": "2027-03"},
            ]
        )
        result = supply_forecast.outlook("평택시", today=self.today, path=path)
        self.assertEqual(result["offeredHouseholds"], 700)
        self.assertEqual(result["complexCount"], 1)

    def test_duplicate_complex_keeps_larger_household_count(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "산성동", "대표단지명": "산성역 헤리스톤", "세대수": "1224", "입주예정월": "2027-12"},
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "산성동", "대표단지명": "산성역 헤리스톤", "세대수": "3487", "입주예정월": "2027-12"},
            ]
        )
        rows = supply_forecast.load_rows(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["households"], 3487)

    def test_lifestyle_change_groups_split_city_districts(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "산성동", "대표단지명": "산성역 헤리스톤", "세대수": "3487", "입주예정월": "2027-12"},
                {"시도": "경기도", "시군구": "성남중원구", "법정동": "중앙동", "대표단지명": "해링턴 스퀘어 신흥역", "세대수": "1319", "입주예정월": "2027-12"},
            ]
        )
        result = supply_forecast.lifestyle_change(
            {"name": "산성역 헤리스톤", "district": "성남수정구", "province": "경기도", "legalDong": "산성동"},
            today=self.today,
            path=path,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["lifestyleKey"], "구성남 생활권")
        self.assertEqual(result["totalHouseholds"], 4806)
        self.assertEqual(result["largeComplexCount"], 2)
        self.assertEqual(result["complexes"][0]["name"], "산성역 헤리스톤")
        self.assertTrue(result["complexes"][0]["isTarget"])
        self.assertEqual(len(result["redevelopmentProjects"]), 6)
        self.assertEqual(result["redevelopmentProjects"][0]["name"], "산성구역")

    def test_dongdaemun_report_keeps_district_projects_without_move_in_rows(self):
        path = self._fixture([])
        result = supply_forecast.lifestyle_change(
            {"name": "이문 아이파크 자이", "district": "동대문구", "province": "서울특별시", "legalDong": "이문동"},
            today=self.today,
            path=path,
        )

        self.assertEqual(result["status"], "projects_only")
        self.assertEqual(result["lifestyleKey"], "동대문구")
        self.assertEqual(
            {(project["name"], project["legalDong"]) for project in result["redevelopmentProjects"]},
            {("청량리제8구역", "청량리동"), ("전농제9구역", "전농동"), ("제기제4구역", "제기동")},
        )
        self.assertTrue(all(project["sourceUrl"].startswith("https://www.ddm.go.kr/") for project in result["redevelopmentProjects"]))
        other_district = supply_forecast.lifestyle_change(
            {"district": "성북구", "province": "서울특별시", "legalDong": "석관동"},
            today=self.today,
            path=path,
        )
        self.assertEqual(other_district["redevelopmentProjects"], [])

    def test_cheongnyangni_gtx_keeps_station_and_stage_sources(self):
        lines = planned_rail.planned_rail_for_candidate({
            "province": "서울특별시", "district": "동대문구", "legalDong": "이문동",
        })
        gtx = {line["id"]: line for line in lines if line["id"].startswith("gtx-")}
        self.assertEqual(set(gtx), {"gtx-b", "gtx-c"})
        self.assertTrue(all(line["stations"] == ["청량리"] for line in gtx.values()))
        self.assertTrue(all(line["region"] == "동대문구" for line in gtx.values()))
        self.assertTrue(all(line["stationsSourceUrl"].startswith("https://www.molit.go.kr/") for line in gtx.values()))
        self.assertEqual(gtx["gtx-c"]["sourceDate"], "2026-09-14")
        self.assertEqual(gtx["gtx-c"]["verifiedAt"], "2026-10-16")
        seongbuk = planned_rail.planned_rail_for_candidate({
            "province": "서울특별시", "district": "성북구", "legalDong": "석관동",
        })
        self.assertNotIn("gtx-b", {line["id"] for line in seongbuk})

    def test_lifestyle_change_uses_verified_full_size_only_for_exact_project(self):
        path = self._fixture(
            [
                {"시도": "서울특별시", "자치구": "노원구", "법정동": "월계동", "대표단지명": "서울원 아이파크", "세대수": "1856", "입주예정월": "2028-07"},
                {"시도": "서울특별시", "자치구": "노원구", "법정동": "공릉동", "대표단지명": "서울원 아이파크", "세대수": "1856", "입주예정월": "2028-07"},
            ]
        )
        result = supply_forecast.lifestyle_change(
            {"name": "다른 단지", "district": "노원구", "province": "서울특별시"},
            today=self.today,
            path=path,
        )

        self.assertEqual(result["status"], "ok")
        by_dong = {row["legalDong"]: row for row in result["complexes"]}
        self.assertEqual(by_dong["월계동"]["plannedTotalHouseholds"], 2264)
        self.assertIn("seoulone_recruitment_full.pdf", by_dong["월계동"]["plannedTotalSourceUrl"])
        self.assertNotIn("plannedTotalHouseholds", by_dong["공릉동"])

    def test_major_development_is_scoped_to_same_district_and_dong(self):
        path = self._fixture([])
        wolgye = supply_forecast.lifestyle_change(
            {"district": "노원구", "legalDong": "월계동"}, today=self.today, path=path,
        )
        sanggye = supply_forecast.lifestyle_change(
            {"district": "노원구", "legalDong": "상계동"}, today=self.today, path=path,
        )
        gongneung = supply_forecast.lifestyle_change(
            {"district": "노원구", "legalDong": "공릉동"}, today=self.today, path=path,
        )
        nearby_other_dong = supply_forecast.lifestyle_change(
            {"district": "성북구", "legalDong": "석관동", "latitude": 37.619,
             "longitude": 127.064}, today=self.today, path=path,
        )
        far_same_dong = supply_forecast.lifestyle_change(
            {"district": "노원구", "legalDong": "월계동", "latitude": 37.65,
             "longitude": 127.064}, today=self.today, path=path,
        )

        self.assertEqual(wolgye["majorDevelopments"][0]["name"], "광운대역 물류부지 개발")
        self.assertEqual(sanggye["majorDevelopments"][0]["plannedTotalHouseholds"], 103000)
        self.assertEqual(gongneung["majorDevelopments"], [])
        self.assertEqual(nearby_other_dong["majorDevelopments"][0]["name"], "광운대역 물류부지 개발")
        self.assertEqual(far_same_dong["majorDevelopments"], [])

    def test_verified_large_complex_is_not_hidden_by_small_offered_count(self):
        import tempfile

        path = self._fixture([
            {"시도": "서울특별시", "자치구": "구로구", "법정동": "구로동",
             "대표단지명": "대단지 예시", "세대수": "200", "입주예정월": "2028-07"},
        ])
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "planned_complex_totals.json"
            metadata.write_text(json.dumps({"complexes": [{
                "name": "대단지 예시", "region": "구로구", "legalDong": "구로동",
                "offeredHouseholds": 200, "plannedTotalHouseholds": 5000,
                "sourceUrl": "https://example.com/official-notice",
            }]}), encoding="utf-8")
            with mock.patch.object(supply_forecast, "PLANNED_COMPLEX_TOTALS_PATH", metadata):
                result = supply_forecast.lifestyle_change(
                    {"district": "구로구", "legalDong": "구로동"}, today=self.today, path=path,
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["level"], "strong")
        self.assertEqual(result["totalHouseholds"], 200)
        self.assertEqual(result["complexes"][0]["plannedTotalHouseholds"], 5000)

    def test_lifestyle_change_omits_public_sale_and_non_downtown_dongs(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "산성동", "대표단지명": "산성역 헤리스톤", "세대수": "3487", "입주예정월": "2027-12"},
                {"시도": "경기도", "시군구": "성남중원구", "법정동": "중앙동", "대표단지명": "해링턴 스퀘어 신흥역", "세대수": "1319", "입주예정월": "2027-12"},
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "금토동", "대표단지명": "성남금토 A-4블록 신혼희망타운(공공분양)", "세대수": "766", "입주예정월": "2027-11"},
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "금토동", "대표단지명": "금토동 민간단지", "세대수": "1200", "입주예정월": "2027-11"},
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "", "대표단지명": "동네 미확인 단지", "세대수": "1200", "입주예정월": "2027-11"},
            ]
        )
        result = supply_forecast.lifestyle_change(
            {"name": "산성역 헤리스톤", "district": "성남수정구", "province": "경기도", "legalDong": "산성동"},
            today=self.today,
            path=path,
        )

        self.assertEqual(result["totalHouseholds"], 4806)
        self.assertEqual([row["name"] for row in result["complexes"]], [
            "산성역 헤리스톤", "해링턴 스퀘어 신흥역",
        ])

    def test_lifestyle_change_excludes_rental_like_supply(self):
        path = self._fixture(
            [
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "창곡동", "대표단지명": "성남 장기전세 행복주택", "세대수": "5000", "입주예정월": "2027-03"},
                {"시도": "경기도", "시군구": "성남수정구", "법정동": "산성동", "대표단지명": "산성역 헤리스톤", "세대수": "3487", "입주예정월": "2027-12"},
            ]
        )
        result = supply_forecast.lifestyle_change(
            {"name": "산성역 헤리스톤", "district": "성남수정구", "province": "경기도", "legalDong": "산성동"},
            today=self.today,
            path=path,
        )

        self.assertEqual(result["totalHouseholds"], 3487)
        self.assertNotIn("장기전세", " ".join(row["name"] for row in result["complexes"]))


class AdjustmentTest(unittest.TestCase):
    """조합원 분양분 보정이 적용되는지, 그리고 원본이 보존되는지 확인한다."""

    def setUp(self):
        self.today = datetime.date(2026, 7, 1)
        supply_forecast._CACHE.clear()

    def tearDown(self):
        supply_forecast._CACHE.clear()

    def _fixture(self, rows):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8"
        )
        handle.close()
        write_csv(handle.name, rows)
        return handle.name

    def test_offered_and_adjusted_are_both_reported(self):
        path = self._fixture(
            [{"시도": "경기도", "시군구": "평택시", "세대수": "1000", "입주예정월": "2027-03"}]
        )
        result = supply_forecast.outlook("평택시", today=self.today, path=path)

        self.assertEqual(result["offeredHouseholds"], 1000)
        self.assertEqual(
            result["totalHouseholds"],
            round(1000 * supply_forecast.ADJUSTMENT_FACTOR),
        )
        self.assertGreater(result["totalHouseholds"], result["offeredHouseholds"])

    def test_adjustment_can_change_the_level(self):
        """보정 전 notable 이던 물량이 보정 후 heavy 로 넘어갈 수 있다."""
        path = self._fixture(
            [{"시도": "서울특별시", "자치구": "노원구", "세대수": "2200", "입주예정월": "2027-03"}]
        )
        result = supply_forecast.outlook("노원구", today=self.today, path=path)

        self.assertLess(2200, supply_forecast.HEAVY_HOUSEHOLDS)
        self.assertGreaterEqual(result["totalHouseholds"], supply_forecast.HEAVY_HOUSEHOLDS)
        self.assertEqual(result["level"], "heavy")

    def test_sentence_shows_both_numbers(self):
        path = self._fixture(
            [{"시도": "경기도", "시군구": "평택시", "세대수": "4000", "입주예정월": "2027-03"}]
        )
        text = supply_forecast.sentence(
            supply_forecast.outlook("평택시", today=self.today, path=path)
        )
        self.assertIn("4,000세대", text)   # 공고된 원본
        self.assertIn("5,680세대", text)   # 보정 후
        self.assertIn("조합원", text)


class RealDataTest(unittest.TestCase):
    """실제 배포 CSV가 깨지지 않았는지 확인한다."""

    def setUp(self):
        supply_forecast._CACHE.clear()

    def test_bundled_csv_loads_and_has_usable_rows(self):
        rows = supply_forecast.load_rows()
        self.assertGreater(len(rows), 100)
        self.assertTrue(all(r["households"] > 0 for r in rows))
        self.assertTrue(all(1 <= r["month"] <= 12 for r in rows))


if __name__ == "__main__":
    unittest.main()
