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

    def test_same_name_at_different_jibun_has_different_cache_identity(self):
        other = dict(self.entity, jibun="722", address="서울특별시 성동구 성수동1가 722")
        self.assertNotEqual(kakao_station_distances.entity_id(self.entity),
                            kakao_station_distances.entity_id(other))

    def test_existing_cache_record_is_reused_only_at_the_same_address(self):
        legacy_key = kakao_station_distances._legacy_entity_id(self.entity)
        record = {"apartmentName": self.entity["name"], "address": self.entity["address"],
                  "status": "ok", "nearestStationName": "서울숲역", "nearestStationDistance": 420}
        kakao_station_distances._merge_records({legacy_key: record})
        self.assertEqual(kakao_station_distances.cached_station(self.entity)["nearestStationName"], "서울숲역")
        other = dict(self.entity, jibun="722", address="서울특별시 성동구 성수동1가 722")
        self.assertIsNone(kakao_station_distances.cached_station(other))
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
                "meta": {"is_end": True},
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
        self.assertEqual(record["nearestStationDistance"], round(
            kakao_station_distances._distance_meters(37.544, 127.043, 37.543, 127.044), 1
        ))
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
            "nearest_subway_station_shared",
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
            "nearest_subway_station_shared",
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

    def test_nearby_apartments_share_station_query_and_identical_addresses_share_geocode(self):
        second = dict(self.entity, dedupeKey="second-apartment")
        third = dict(self.entity, dedupeKey="third-apartment", address="서울특별시 성동구 성수동1가 722")
        responses = [
            {"documents": [{"x": "127.043", "y": "37.544", "address_name": self.entity["address"]}]},
            {"meta": {"is_end": True}, "documents": [{
                "id": "123", "place_name": "서울숲역", "x": "127.044", "y": "37.543",
            }]},
            {"documents": [{"x": "127.0431", "y": "37.5441", "address_name": third["address"]}]},
        ]
        with mock.patch.object(kakao_station_distances, "_request_json", side_effect=responses) as request_json:
            first_record = kakao_station_distances.enrich_entity(self.entity)
            second_record = kakao_station_distances.enrich_entity(second)
            third_record = kakao_station_distances.enrich_entity(third)
        self.assertEqual(request_json.call_count, 3)
        self.assertEqual(first_record["status"], "ok")
        self.assertEqual(second_record["coordinateMatchType"], "address_cache")
        self.assertEqual(third_record["nearestStationName"], "서울숲역")
        self.assertNotEqual(first_record["nearestStationDistance"], third_record["nearestStationDistance"])

    def test_incomplete_nearby_station_query_is_not_reused(self):
        query = {"latitude": 37.544, "longitude": 127.043,
                 "documents": [{"name": "A역", "latitude": 37.543, "longitude": 127.044}],
                 "isEnd": False, "lastCenterDistance": 150}
        self.assertIsNone(kakao_station_distances._station_from_query(query, 127.045, 37.544))

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

    def test_record_merge_preserves_another_process_write_and_pending_geocode(self):
        first_id = kakao_station_distances.entity_id(self.entity)
        first = {"status": "ok", "nearestStationName": "첫번째역"}
        kakao_station_distances._merge_records({first_id: first})
        kakao_station_distances._queue_cache_update(
            "geocodes", "local-geocode", {"address": "테스트 주소", "latitude": 37.5, "longitude": 127.0},
        )

        other_id = "another-process-record"
        payload = json.loads(kakao_station_distances.CACHE_PATH.read_text(encoding="utf-8"))
        payload["records"][other_id] = {"status": "ok", "nearestStationName": "다른 프로세스역"}
        replacement = kakao_station_distances.CACHE_PATH.with_suffix(".other-process")
        replacement.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        replacement.replace(kakao_station_distances.CACHE_PATH)

        third_id = "this-process-record"
        kakao_station_distances._merge_records({
            third_id: {"status": "ok", "nearestStationName": "현재 프로세스역"},
        })
        saved = json.loads(kakao_station_distances.CACHE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(saved["records"]), {first_id, other_id, third_id})
        self.assertEqual(saved["geocodes"]["local-geocode"]["address"], "테스트 주소")

    def test_quota_error_stops_station_batch_without_saving_failure(self):
        entities = [
            self.entity,
            dict(self.entity, name="두번째단지", jibun="722"),
            dict(self.entity, name="세번째단지", jibun="723"),
        ]
        with mock.patch.object(
            kakao_station_distances,
            "configured",
            return_value=True,
        ), mock.patch.object(
            kakao_station_distances,
            "enrich_entity",
            side_effect=kakao_station_distances.KakaoQuotaError("429"),
        ) as enrich:
            summary = kakao_station_distances.enrich_entities(entities, workers=1)

        self.assertEqual(summary["haltedReason"], "quota")
        self.assertEqual(summary["failedCount"], 1)
        self.assertEqual(summary["readyCount"], 0)
        self.assertEqual(enrich.call_count, 1)
        saved = json.loads(kakao_station_distances.CACHE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["records"], {})

    def test_http_400_kakao_quota_code_is_classified_as_quota_without_retry(self):
        response = mock.Mock(status_code=400)
        response.json.return_value = {"msg": "API limit has been exceeded.", "code": -10}
        with mock.patch.object(kakao_station_distances.config, "KAKAO_REST_API_KEY", "test-key"), \
             mock.patch.object(kakao_station_distances.requests, "get", return_value=response) as request:
            with self.assertRaises(kakao_station_distances.KakaoQuotaError):
                kakao_station_distances._request_json("search/category.json", {"category_group_code": "SC4"})
        request.assert_called_once()

    def test_http_400_nonquota_error_stays_a_local_api_error(self):
        response = mock.Mock(status_code=400)
        response.json.return_value = {"msg": "invalid request", "code": -2}
        with mock.patch.object(kakao_station_distances.config, "KAKAO_REST_API_KEY", "test-key"), \
             mock.patch.object(kakao_station_distances.requests, "get", return_value=response) as request:
            with self.assertRaises(kakao_station_distances.KakaoLocalError) as raised:
                kakao_station_distances._request_json("search/category.json", {"category_group_code": "SC4"})
        self.assertNotIsInstance(raised.exception, kakao_station_distances.KakaoQuotaError)
        request.assert_called_once()

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

    def test_entities_for_region_includes_rankable_presale_statuses(self):
        entities = [
            dict(self.entity, name="일반단지", status="", dedupeKey="general"),
            dict(self.entity, name="분양단지", status="분양권", dedupeKey="presale"),
            dict(self.entity, name="준공단지", status="준공", dedupeKey="completed"),
            dict(self.entity, name="임대단지", status="공공임대", dedupeKey="rental"),
            dict(self.entity, name="집계단지", aggregate=True, dedupeKey="aggregate"),
        ]

        with mock.patch.object(kakao_station_distances.real_estate_search, "APARTMENT_MASTER", entities):
            rows = kakao_station_distances.entities_for_region("서울특별시", "성동구")

        self.assertEqual([row["name"] for row in rows], ["일반단지", "분양단지", "준공단지"])


if __name__ == "__main__":
    unittest.main()
