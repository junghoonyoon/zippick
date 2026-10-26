import json
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

import redevelopment_occupancy as occupancy
import search_server
import living_area_metro as metro


class RedevelopmentOccupancyTest(unittest.TestCase):
    def test_report_map_excludes_reviewed_occupied_boundaries(self):
        rows = json.loads(occupancy.OVERRIDES_PATH.read_text())["entries"]
        excluded = {row['zoneId'] for row in rows}
        for name in ('중화1구역', '이문3-1구역'):
            row = next(row for row in rows if row['zoneName'] == name)
            for projects in ([], metro.catalog()['projects']):
                with self.subTest(zone=name, matched=bool(projects)):
                    zones = metro.spatial(row, projects, date.today())['zones']
                    self.assertFalse(excluded.intersection(z['id'] for z in zones))
                    if name == '이문3-1구역':
                        self.assertNotIn('이문3-2구역', {z['name'] for z in zones})
                        self.assertIn('이문4구역', {z['name'] for z in zones})

    def test_report_map_refreshes_after_occupancy_registry_changes(self):
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        rows = json.loads(occupancy.OVERRIDES_PATH.read_text())["entries"]
        row = next(row for row in rows if row['zoneName'] == '보문5')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'occupancy.json'
            with patch.object(occupancy, 'OVERRIDES_PATH', path):
                path.write_text(json.dumps({'entries': []}))
                before = metro.spatial(row, [], date.today())['zones']
                self.assertIn(row['zoneId'], {z['id'] for z in before})
                path.write_text(json.dumps({'entries': [row]}))
                after = metro.spatial(row, [], date.today())['zones']
                self.assertNotIn(row['zoneId'], {z['id'] for z in after})

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
        for stage in ("입주", "입주 완료", "입주 중", "입주 진행중", "입주 개시", "입주 시작", "준공", "준공인가", "사용승인", "사업완료"):
            with self.subTest(stage=stage):
                self.assertTrue(occupancy.completed_stage(stage))
        for stage in ("착공", "준공 예정", "사용승인 예정", "입주 예정", "입주 시작 예정", "준공(일부)",
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
                zone = zones.get(row["zoneId"])
                if zone:
                    self.assertTrue(occupancy.occupancy_evidence(zone) == row or occupancy.completed_stage(zone.get("stage")))
                self.assertNotIn(row["zoneId"], served)
                if 'longitude' in row:
                    lng, lat = row['longitude'], row['latitude']
                else:
                    from shapely.geometry import shape
                    raw = next(z for z in metro.catalog()['ggBoundaries'] if f"gg-zone:{z['properties']['sourceLayer']}:{z['id']}"==row['zoneId'])
                    point = shape(raw['geometry']).representative_point()
                    lng, lat = point.x, point.y
                payload = search_server._redevelopment_zones_payload({
                    "bbox": [f"{lng-.005},{lat-.005},{lng+.005},{lat+.005}"], "limit": ["3000"],
                })
                self.assertNotIn(row["zoneId"], {z["id"] for z in payload["zones"]})

    def test_similar_names_and_changed_identity_are_not_hidden(self):
        zone = next(z for z in search_server._redevelopment_zones() if z["name"] == "수색6구역")
        zone = {**zone, "stage":"착공"}  # Isolate identity matching from the latest official completion.
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
                    self.assertEqual(search_server._redevelopment_zone_active(zone),
                                     not occupancy.completed_stage(zone.get("stage")))


if __name__ == "__main__":
    unittest.main()
