import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import redevelopment_analysis as ra  # noqa: E402
import redevelopment_track_record as rtr  # noqa: E402


class StageMappingTest(unittest.TestCase):
    def test_pending_union_is_not_treated_as_approved(self):
        self.assertEqual(ra._stage("조합설립인가 추진중(연번부여)"), "추진위원회")
        self.assertEqual(ra._stage("조합설립추진중"), "추진위원회")

    def test_approved_union_stays_approved(self):
        self.assertEqual(ra._stage("조합설립인가"), "조합설립인가")

    def test_design_review_is_its_own_stage_before_approval(self):
        self.assertEqual(ra._stage("건축심의"), "건축심의")
        self.assertLess(
            ra.STAGE_PROGRESS["건축심의"],
            ra.STAGE_PROGRESS["사업시행인가"],
        )

    def test_candidate_selection_is_early_even_when_pending(self):
        self.assertEqual(ra._stage("대상지선정(추진중)"), "검토·후보지")

    def test_management_disposal_maps_to_its_stage(self):
        self.assertEqual(ra._stage("관리처분계획인가"), "관리처분인가")

    def test_finished_projects_map_to_done(self):
        for raw in ("준공", "준공(일부)", "사용승인", "사업완료", "입주"):
            self.assertEqual(ra._stage(raw), "완료", raw)

    def test_unknown_stage_is_excluded_from_progress(self):
        self.assertEqual(ra._stage("단계 확인 필요"), ra.STAGE_UNKNOWN)
        self.assertNotIn(ra.STAGE_UNKNOWN, ra.STAGE_PROGRESS)


class ProjectTypeTest(unittest.TestCase):
    def test_fast_track_projects_are_recognised(self):
        self.assertEqual(ra._project_type("신속통합기획"), "신속통합기획")
        self.assertIn("신속통합기획", ra.PROJECT_TYPES)

    def test_small_scale_projects_are_recognised(self):
        self.assertEqual(ra._project_type("자율주택정비사업"), "가로주택정비")
        self.assertEqual(ra._project_type("소규모재건축사업"), "재건축")
        self.assertEqual(ra._project_type("소규모재개발사업"), "재개발")

    def test_station_and_market_projects_map_to_mixed_use(self):
        self.assertEqual(ra._project_type("역세권 활성화"), "주거복합")
        self.assertEqual(ra._project_type("시장정비사업"), "주거복합")

    def test_preserved_zones_are_dropped(self):
        self.assertIsNone(ra._project_type("존치관리구역"))
        self.assertIsNone(ra._project_type("존치정비구역"))

    def test_public_rental_projects_are_dropped(self):
        self.assertIsNone(ra._project_type("청년안심주택"))
        self.assertIsNone(ra._project_type("역세권청년주택"))
        self.assertIsNone(ra._project_type("장기전세주택"))
        self.assertIsNone(ra._project_type("공공임대주택"))
        self.assertIsNone(ra._project_type("미리내집"))


class LoadedDataTest(unittest.TestCase):
    def test_official_dataset_keeps_more_zones_than_before(self):
        projects = ra._load_projects()
        # 매핑을 고치기 전에는 1,549곳만 통과했다.
        self.assertGreater(len(projects), 1600)

    def test_household_count_is_never_invented(self):
        with (ROOT / "data" / "redevelopment_zones.geojson").open(encoding="utf-8") as handle:
            payload = json.load(handle)
        has_field = any(
            "plannedHouseholds" in (feature.get("properties") or {})
            for feature in payload.get("features") or []
        )
        if has_field:
            self.skipTest("세대수가 채워진 데이터라 검증할 필요가 없어요")
        for project in ra._load_projects():
            self.assertIsNone(project["plannedHouseholds"])

    def test_supply_penalty_is_skipped_when_household_count_is_unknown(self):
        row = {"latitude": 37.5079, "longitude": 126.9268}
        _, _, detail = ra.influence_score(row, None)
        self.assertFalse(detail["supplyHouseholdsKnown"])
        self.assertIsNone(detail["supplyHouseholds"])


class TrackRecordTest(unittest.TestCase):
    def test_missing_history_never_shows_a_number(self):
        row = {"latitude": 37.5079, "longitude": 126.9268}
        result = rtr.summary(row, None)
        self.assertEqual(result["status"], "missing")
        self.assertNotIn("total", result)

    def test_small_sample_is_hidden(self):
        self.assertGreaterEqual(rtr.MIN_SAMPLE, 30)

    def test_alert_and_evidence_use_the_same_distance(self):
        # 알림 기준과 사례 집계 기준이 다르면 말만 꺼내고 근거는 못 보여준다.
        self.assertEqual(rtr.NEARBY_METERS, ra.MOVE_OUT_NEARBY_METERS)

    def test_move_out_alert_stays_within_the_distance(self):
        row = {"latitude": 37.5079, "longitude": 126.9268}
        _, _, detail = ra.influence_score(row, None)
        for project in detail["moveOutNearby"]:
            self.assertLessEqual(project["distanceMeters"], ra.MOVE_OUT_NEARBY_METERS)


if __name__ == "__main__":
    unittest.main()
