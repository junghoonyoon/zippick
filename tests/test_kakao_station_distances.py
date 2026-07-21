import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import kakao_station_distances  # noqa: E402


class KakaoStationDistancesTest(unittest.TestCase):
    def test_region_matching_does_not_mix_yangju_into_namyangju(self):
        self.assertFalse(kakao_station_distances._region_matches("양주시", "남양주시"))
        self.assertTrue(kakao_station_distances._region_matches("성남분당구", "분당구"))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache_path_patch = mock.patch.object(
            kakao_station_distances,
            "CACHE_PATH",
            Path(self.temporary.name) / "station-distances.json",
        )
        self.cache_path_patch.start()
        kakao_station_distances.reset_memory_cache()
        self.entity = {
            "name": "테스트아파트",
            "province": "서울특별시",
            "district": "성동구",
            "legalDong": "성수동1가",
            "jibun": "721",
            "address": "서울특별시 성동구 성수동1가 721",
            "dedupeKey": "test-apartment",
        }

    def tearDown(self):
        kakao_station_distances.reset_memory_cache()
        self.cache_path_patch.stop()
        self.temporary.cleanup()

    def test_entity_address_uses_full_address_or_builds_jibun_address(self):
        self.assertEqual(
            kakao_station_distances.entity_address(self.entity),
            "서울특별시 성동구 성수동1가 721",
        )
        entity = dict(self.entity, address="")
        self.assertEqual(
            kakao_station_distances.entity_address(entity),
            "서울특별시 성동구 성수동1가 721",
        )

    def test_enrich_entity_combines_geocode_and_nearest_station(self):
        responses = [
            {
                "documents": [{
                    "x": "127.043",
                    "y": "37.544",
                    "address_name": "서울 성동구 성수동1가 721",
                    "road_address": {"address_name": "서울 성동구 서울숲길 25"},
                }],
            },
            {
                "documents": [{
                    "id": "123",
                    "place_name": "서울숲역",
                    "distance": "418",
                    "x": "127.044",
                    "y": "37.543",
                }],
            },
        ]
        with mock.patch.object(
            kakao_station_distances,
            "_request_json",
            side_effect=responses,
        ) as request_json:
            record = kakao_station_distances.enrich_entity(self.entity)

        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["nearestStationName"], "서울숲역")
        self.assertEqual(record["nearestStationDistance"], 418.0)
        self.assertEqual(record["stationDistanceType"], "straight_line")
        self.assertEqual(request_json.call_count, 2)
        self.assertEqual(
            request_json.call_args_list[1].args[1]["category_group_code"],
            "SW8",
        )

    def test_enrich_entity_falls_back_to_apartment_keyword_for_block_address(self):
        entity = dict(
            self.entity,
            name="테스트 센트럴자이",
            address="경기도 성남분당구 대장동 BL-1",
        )
        with mock.patch.object(
            kakao_station_distances,
            "geocode_address",
            return_value=None,
        ), mock.patch.object(
            kakao_station_distances,
            "_request_json",
            return_value={"documents": [{
                "place_name": "테스트센트럴자이아파트",
                "category_name": "부동산 > 주거시설 > 아파트",
                "address_name": "경기 성남시 분당구 대장동 123",
                "road_address_name": "경기 성남시 분당구 대장로 1",
                "x": "127.1",
                "y": "37.4",
            }]},
        ), mock.patch.object(
            kakao_station_distances,
            "nearest_subway_station",
            return_value={
                "nearestStationName": "테스트역",
                "nearestStationDistance": 500,
            },
        ):
            record = kakao_station_distances.enrich_entity(entity)

        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["matchedAddress"], "경기 성남시 분당구 대장로 1")
        self.assertEqual(record["coordinateMatchType"], "apartment_keyword")

    def test_no_station_within_radius_is_cached_as_a_distance_lower_bound(self):
        coordinates = {"latitude": 37.0, "longitude": 127.0, "matchedAddress": "주소"}
        with mock.patch.object(
            kakao_station_distances,
            "geocode_address",
            return_value=coordinates,
        ), mock.patch.object(
            kakao_station_distances,
            "nearest_subway_station",
            return_value=None,
        ):
            record = kakao_station_distances.enrich_entity(self.entity)
        kakao_station_distances._merge_records({
            kakao_station_distances.entity_id(self.entity): record,
        })

        cached = kakao_station_distances.cached_station(self.entity)
        self.assertEqual(record["status"], "station_not_found")
        self.assertEqual(cached["stationDistanceLowerBound"], 20000)
        self.assertEqual(cached["stationDistanceType"], "straight_line_lower_bound")

    def test_batch_saves_and_reuses_cached_distance(self):
        record = {
            "apartmentId": kakao_station_distances.entity_id(self.entity),
            "apartmentName": "테스트아파트",
            "address": self.entity["address"],
            "status": "ok",
            "source": kakao_station_distances.SOURCE_NAME,
            "fetchedAt": "2026-07-20T00:00:00+00:00",
            "latitude": 37.544,
            "longitude": 127.043,
            "nearestStationName": "서울숲역",
            "nearestStationDistance": 418.0,
            "nearestStationLatitude": 37.543,
            "nearestStationLongitude": 127.044,
            "stationDistanceType": "straight_line",
        }
        with mock.patch.object(
            kakao_station_distances.config,
            "KAKAO_REST_API_KEY",
            "test-key",
        ), mock.patch.object(
            kakao_station_distances,
            "enrich_entity",
            return_value=record,
        ) as enrich:
            first = kakao_station_distances.enrich_entities([self.entity])
            second = kakao_station_distances.enrich_entities([self.entity])

        self.assertEqual(first["readyCount"], 1)
        self.assertEqual(second["cachedCount"], 1)
        enrich.assert_called_once_with(self.entity)
        cached = kakao_station_distances.cached_station(self.entity)
        self.assertEqual(cached["nearestStationName"], "서울숲역")
        self.assertEqual(cached["nearestStationDistance"], 418.0)
        payload = json.loads(
            kakao_station_distances.CACHE_PATH.read_text(encoding="utf-8"),
        )
        self.assertEqual(payload["version"], 1)

    def test_memory_cache_reloads_after_another_process_replaces_file(self):
        first_record = {
            "apartmentId": kakao_station_distances.entity_id(self.entity),
            "status": "ok",
            "nearestStationName": "첫번째역",
            "nearestStationDistance": 700,
        }
        kakao_station_distances.CACHE_PATH.write_text(
            json.dumps({
                "version": 1,
                "source": kakao_station_distances.SOURCE_NAME,
                "updatedAt": "2026-07-20T00:00:00+00:00",
                "records": {first_record["apartmentId"]: first_record},
            }),
            encoding="utf-8",
        )
        self.assertEqual(
            kakao_station_distances.cached_station(self.entity)["nearestStationName"],
            "첫번째역",
        )

        second_record = dict(
            first_record,
            nearestStationName="두번째역",
            nearestStationDistance=300,
        )
        replacement = kakao_station_distances.CACHE_PATH.with_suffix(".replacement")
        replacement.write_text(
            json.dumps({
                "version": 1,
                "source": kakao_station_distances.SOURCE_NAME,
                "updatedAt": "2026-07-20T01:00:00+00:00",
                "records": {second_record["apartmentId"]: second_record},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        replacement.replace(kakao_station_distances.CACHE_PATH)

        cached = kakao_station_distances.cached_station(self.entity)
        self.assertEqual(cached["nearestStationName"], "두번째역")
        self.assertEqual(cached["nearestStationDistance"], 300)

    def test_batch_without_key_reports_configuration_error(self):
        with mock.patch.object(
            kakao_station_distances.config,
            "KAKAO_REST_API_KEY",
            "",
        ):
            with self.assertRaises(kakao_station_distances.KakaoLocalError):
                kakao_station_distances.enrich_entities([self.entity])
            preview = kakao_station_distances.enrich_entities(
                [self.entity],
                dry_run=True,
            )

        self.assertEqual(preview["pendingCount"], 1)
        self.assertFalse(preview["configured"])


if __name__ == "__main__":
    unittest.main()
