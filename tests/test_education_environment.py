import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import education_environment  # noqa: E402
import kakao_station_distances  # noqa: E402


class EducationEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temporary.name) / "education.json"
        self.station_path = Path(self.temporary.name) / "station.json"
        self.data_patch = mock.patch.object(
            education_environment,
            "DATA_PATH",
            self.data_path,
        )
        self.station_patch = mock.patch.object(
            kakao_station_distances,
            "CACHE_PATH",
            self.station_path,
        )
        self.data_patch.start()
        self.station_patch.start()
        education_environment.reset_memory_cache()
        kakao_station_distances.reset_memory_cache()
        self.entity = {
            "name": "교육테스트아파트",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "테스트동",
            "jibun": "1",
            "address": "서울특별시 테스트구 테스트동 1",
            "dedupeKey": "education-test",
        }

    def tearDown(self):
        education_environment.reset_memory_cache()
        kakao_station_distances.reset_memory_cache()
        self.station_patch.stop()
        self.data_patch.stop()
        self.temporary.cleanup()

    def _write_station_cache(self, latitude=37.5, longitude=127.0):
        apartment_id = kakao_station_distances.entity_id(self.entity)
        self.station_path.write_text(json.dumps({
            "version": 1,
            "records": {
                apartment_id: {
                    "status": "ok",
                    "latitude": latitude,
                    "longitude": longitude,
                },
            },
        }), encoding="utf-8")

    def test_uses_precomputed_apartment_record(self):
        apartment_id = kakao_station_distances.entity_id(self.entity)
        self.data_path.write_text(json.dumps({
            "dataThrough": "2026-03-20",
            "records": {
                apartment_id: {
                    "score": 82,
                    "elementarySchoolNames": ["테스트초"],
                    "middleZoneName": "테스트중학군",
                    "academyCount1km": 42,
                },
            },
        }), encoding="utf-8")

        result = education_environment.education_environment_for_entity(self.entity)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["score"], 82)
        self.assertEqual(result["scoreFormulaVersion"], "education-env-v1")
        self.assertEqual(result["dataThrough"], "2026-03-20")

    def test_scores_matching_school_zones_from_coordinates(self):
        self._write_station_cache()
        self.data_path.write_text(json.dumps({
            "dataThrough": "2026-03-20",
            "schools": [{
                "code": "S1",
                "name": "테스트초",
                "latitude": 37.501,
                "longitude": 127.001,
            }],
            "zones": [
                {
                    "level": "elementary",
                    "name": "테스트초통학구역",
                    "schoolCodes": ["S1"],
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [126.99, 37.49],
                            [127.01, 37.49],
                            [127.01, 37.51],
                            [126.99, 37.51],
                            [126.99, 37.49]
                        ]],
                    },
                },
                {
                    "level": "middle",
                    "name": "테스트중학군",
                    "schoolNames": ["테스트중"],
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [126.98, 37.48],
                            [127.02, 37.48],
                            [127.02, 37.52],
                            [126.98, 37.52],
                            [126.98, 37.48]
                        ]],
                    },
                },
            ],
        }), encoding="utf-8")

        result = education_environment.education_environment_for_entity(self.entity)

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["score"], 90)
        self.assertEqual(result["elementarySchoolNames"], ["테스트초"])
        self.assertEqual(result["middleZoneName"], "테스트중학군")

    def test_scores_nearby_school_access_when_school_zones_are_empty(self):
        self._write_station_cache()
        self.data_path.write_text(json.dumps({
            "dataThrough": "2026-03-20",
            "records": {},
            "schools": [],
            "zones": [],
        }), encoding="utf-8")

        def fake_request(path, params):
            self.assertEqual(path, "search/category.json")
            if params["category_group_code"] == "SC4":
                return {
                    "documents": [
                        {
                            "id": "E1",
                            "place_name": "테스트초등학교",
                            "category_name": "교육,학문 > 학교 > 초등학교",
                            "distance": "420",
                        },
                        {
                            "id": "M1",
                            "place_name": "테스트중학교",
                            "category_name": "교육,학문 > 학교 > 중학교",
                            "distance": "900",
                        },
                    ],
                    "meta": {"is_end": True},
                }
            return {
                "documents": [
                    {"id": f"A{index}", "place_name": f"테스트학원{index}", "distance": str(100 + index)}
                    for index in range(12)
                ],
                "meta": {"is_end": True},
            }

        with mock.patch.object(kakao_station_distances, "configured", return_value=True), \
             mock.patch.object(kakao_station_distances, "_request_json", side_effect=fake_request):
            result = education_environment.education_environment_for_entity(self.entity)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["basis"], "nearby_school_access")
        self.assertEqual(result["elementarySchoolNames"][0], "테스트초등학교")
        self.assertEqual(result["middleSchoolNames"][0], "테스트중학교")
        self.assertEqual(result["academyCount1km"], 12)
        self.assertGreater(result["score"], 60)

        cached = json.loads(self.data_path.read_text(encoding="utf-8"))["records"]
        self.assertEqual(len(cached), 1)
        self.assertEqual(next(iter(cached.values()))["basis"], "nearby_school_access")

    def test_remote_lookup_can_be_disabled_for_fast_candidate_search(self):
        self._write_station_cache()
        self.data_path.write_text(json.dumps({
            "dataThrough": "2026-03-20",
            "records": {},
            "schools": [],
            "zones": [],
        }), encoding="utf-8")

        with mock.patch.object(kakao_station_distances, "_request_json") as request_json:
            result = education_environment.education_environment_for_entity(
                self.entity,
                allow_remote_lookup=False,
            )

        self.assertEqual(result["status"], "not_precomputed")
        self.assertIsNone(result["score"])
        request_json.assert_not_called()

    def test_unsupported_region_has_no_score(self):
        result = education_environment.education_environment_for_entity({
            **self.entity,
            "province": "부산광역시",
        })

        self.assertEqual(result["status"], "unsupported_region")
        self.assertIsNone(result["score"])


if __name__ == "__main__":
    unittest.main()
