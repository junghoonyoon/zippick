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
        self.overlay_path = Path(self.temporary.name) / "overlay.json"
        self.records_path = Path(self.temporary.name) / "education-cache.json"
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
        self.overlay_patch = mock.patch.object(
            education_environment,
            "OVERLAY_PATH",
            self.overlay_path,
        )
        self.records_patch = mock.patch.object(
            education_environment,
            "RECORDS_PATH",
            self.records_path,
        )
        self.data_patch.start()
        self.station_patch.start()
        self.overlay_patch.start()
        self.records_patch.start()
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
        self.records_patch.stop()
        self.overlay_patch.stop()
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

        cached = json.loads(self.records_path.read_text(encoding="utf-8"))["records"]
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

    def test_incheon_is_supported_for_nearby_school_access(self):
        self.assertTrue(education_environment._region_supported({
            "province": "인천광역시",
        }))


    def test_base_overlay_and_shared_records_merge_with_newest_value_first(self):
        self.data_path.write_text(json.dumps({
            "dataThrough": "2026-10-01",
            "source": "공식 학구 자료",
            "sourceUrl": "https://example.test/schools",
            "records": {"same": {"score": 60}, "base": {"score": 70}},
            "zones": [{"name": "기준 학구"}],
            "schools": [{"code": "S1", "name": "기준 학교"}],
        }), encoding="utf-8")
        self.overlay_path.write_text(json.dumps({
            "dataThrough": "2026-10-31",
            "records": {"same": {"score": 75}, "local-only": {"score": 82}},
        }), encoding="utf-8")
        education_environment.reset_memory_cache()
        education_environment._save_precomputed_record(
            "same",
            {"status": "ok", "score": 91, "basis": "nearby_school_access"},
        )
        dataset = education_environment._load_dataset()
        self.assertEqual(dataset["records"]["base"]["score"], 70)
        self.assertEqual(dataset["records"]["local-only"]["score"], 82)
        self.assertEqual(dataset["records"]["same"]["score"], 91)
        self.assertEqual(dataset["records"]["same"]["scoreFormulaVersion"],
                         education_environment.SCORE_FORMULA_VERSION)
        self.assertEqual(dataset["zones"], [{"name": "기준 학구"}])
        self.assertIn("S1", dataset["schools"])
        self.assertEqual(dataset["dataThrough"], "2026-10-31")

    def test_legacy_release_records_migrate_to_shared_cache_once(self):
        releases = Path(self.temporary.name) / "releases"
        old_release = releases / "old"
        new_release = releases / "new"
        old_data = old_release / "data" / self.data_path.name
        old_data.parent.mkdir(parents=True)
        new_release.mkdir(parents=True)
        old_data.write_text(json.dumps({
            "dataThrough": "2026-10-30",
            "scoreFormulaVersion": education_environment.SCORE_FORMULA_VERSION,
            "records": {"kept": {"score": 88}},
        }), encoding="utf-8")
        education_environment._migrate_legacy_release_records(releases, new_release)
        self.assertEqual(
            json.loads(self.records_path.read_text(encoding="utf-8"))["records"]["kept"]["score"],
            88,
        )
        old_data.write_text(json.dumps({"records": {"later": {"score": 99}}}), encoding="utf-8")
        education_environment._migrate_legacy_release_records(releases, new_release)
        self.assertNotIn("later", json.loads(self.records_path.read_text(encoding="utf-8"))["records"])

    def test_quota_error_halts_batch_and_does_not_save_failed_record(self):
        entities = [
            {"name": "첫번째단지", "province": "서울특별시", "district": "양천구"},
            {"name": "두번째단지", "province": "경기도", "district": "고양시"},
        ]
        station = {"latitude": 37.5, "longitude": 126.9}
        with (
            mock.patch.object(kakao_station_distances, "configured", return_value=True),
            mock.patch.object(kakao_station_distances, "cached_station", return_value=station),
            mock.patch.object(
                education_environment,
                "_score_from_nearby_places",
                side_effect=kakao_station_distances.KakaoQuotaError("429"),
            ) as score,
        ):
            summary = education_environment.enrich_entities(entities, workers=1)
        self.assertEqual(summary["haltedReason"], "quota")
        self.assertEqual(summary["failedCount"], 1)
        self.assertEqual(summary["savedCount"], 0)
        self.assertEqual(score.call_count, 1)
        self.assertFalse(self.records_path.exists())

    def test_successful_no_school_result_is_saved_and_skipped_next_time(self):
        entity = {"name": "주변학교없는단지", "province": "서울특별시", "district": "양천구"}
        station = {"latitude": 37.5, "longitude": 126.9}
        with (
            mock.patch.object(kakao_station_distances, "configured", return_value=True),
            mock.patch.object(kakao_station_distances, "cached_station", return_value=station),
            mock.patch.object(education_environment, "_score_from_nearby_places", return_value=None) as score,
        ):
            first = education_environment.enrich_entities([entity], workers=1)
            second = education_environment.enrich_entities([entity], workers=1)
        self.assertEqual(first["savedCount"], 1)
        self.assertEqual(first["noSchoolCount"], 1)
        self.assertEqual(second["pendingCount"], 0)
        self.assertEqual(second["noSchoolCount"], 1)
        score.assert_called_once()


if __name__ == "__main__":
    unittest.main()
