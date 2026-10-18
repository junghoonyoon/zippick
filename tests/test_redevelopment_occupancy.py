import json
import shutil
import subprocess
import unittest
from pathlib import Path

import redevelopment_occupancy as occupancy
import search_server


class RedevelopmentOccupancyTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_map_and_report_use_the_same_conservative_stage_filter(self):
        html = (Path(__file__).resolve().parents[1] / "앱화면/real-estate-search.html").read_text()
        functions = []
        for name in ("zippickDevelopmentCompletedOfficialZone", "isPriceRelevantRedevelopmentZone"):
            functions.append("function " + name + html.split("function " + name, 1)[1].split("\n    function ", 1)[0])
        stages = ["착공", "입주", "입주 완료", "준공", "준공 예정", "준공(일부)",
                  "임시사용승인", "입주자 모집공고 완료", "입주 진행중", "입주 예정"]
        script = "\n".join(functions) + "\nconsole.log(JSON.stringify(" + json.dumps(stages) + ".map(stage => [zippickDevelopmentCompletedOfficialZone({stage}), isPriceRelevantRedevelopmentZone({stage})])));"
        result = subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
        for stage, (completed, visible) in zip(stages, json.loads(result.stdout)):
            with self.subTest(stage=stage):
                self.assertEqual(completed, occupancy.completed_stage(stage))
                self.assertEqual(visible, not completed)

    def test_only_finished_stages_are_completed(self):
        for stage in ("입주", "입주 완료", "준공", "준공인가", "사용승인", "사업완료"):
            with self.subTest(stage=stage):
                self.assertTrue(occupancy.completed_stage(stage))
        for stage in ("착공", "준공 예정", "사용승인 예정", "입주 예정", "입주 중",
                      "입주 진행중", "입주 개시", "입주 시작", "준공(일부)",
                      "부분 준공", "임시사용승인", "입주자 모집공고 완료", "미준공",
                      "준공인가 신청", "사용승인 심사중", "준공 미완료"):
            with self.subTest(stage=stage):
                self.assertFalse(occupancy.completed_stage(stage))
                self.assertTrue(search_server._redevelopment_zone_active({
                    "name": "진행 중인 사업", "projectType": "재개발", "stage": stage,
                }))

    def test_all_reviewed_boundaries_are_absent_from_full_and_viewport_api(self):
        rows = json.loads(occupancy.OVERRIDES_PATH.read_text())["entries"]
        zones = {z["id"]: z for z in search_server._redevelopment_zones()}
        served = {z["id"] for z in search_server._redevelopment_zones_payload({"limit": ["3000"]})["zones"]}
        for row in rows:
            with self.subTest(zone=row["zoneName"]):
                zone = zones[row["zoneId"]]
                self.assertEqual(occupancy.occupancy_evidence(zone), row)
                self.assertNotIn(row["zoneId"], served)
                lng, lat = row["longitude"], row["latitude"]
                payload = search_server._redevelopment_zones_payload({
                    "bbox": [f"{lng-.005},{lat-.005},{lng+.005},{lat+.005}"], "limit": ["3000"],
                })
                self.assertNotIn(row["zoneId"], {z["id"] for z in payload["zones"]})

    def test_similar_names_and_changed_identity_are_not_hidden(self):
        zone = next(z for z in search_server._redevelopment_zones() if z["name"] == "수색6구역")
        self.assertIsNotNone(occupancy.occupancy_evidence(zone))
        for key in ("id", "name", "districtCode", "projectType"):
            with self.subTest(key=key):
                changed = {**zone, key: "다른 값"}
                self.assertIsNone(occupancy.occupancy_evidence(changed))
                self.assertTrue(search_server._redevelopment_zone_active(changed))

    def test_unverified_and_ongoing_projects_are_preserved(self):
        data = json.loads(occupancy.OVERRIDES_PATH.read_text())
        names = {r["zoneName"] for r in data["retainedForReview"]}
        names.update({"공덕1", "방배삼익", "장위6구역", "노량진6구역", "용답동"})
        zones = search_server._redevelopment_zones()
        matched = {z["name"] for z in zones if z["name"] in names}
        self.assertEqual(matched, names)
        for zone in zones:
            if zone["name"] in names:
                with self.subTest(zone=zone["name"]):
                    self.assertIsNone(occupancy.occupancy_evidence(zone))
                    self.assertTrue(search_server._redevelopment_zone_active(zone))


if __name__ == "__main__":
    unittest.main()
