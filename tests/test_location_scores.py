import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import kakao_station_distances  # noqa: E402
import location_scores  # noqa: E402


class LocationScoresTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache_patch = mock.patch.object(
            kakao_station_distances,
            "CACHE_PATH",
            Path(self.temporary.name) / "station.json",
        )
        self.cache_patch.start()
        kakao_station_distances.reset_memory_cache()
        self.entity = {
            "name": "종합점수아파트",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "테스트동",
            "jibun": "1",
            "address": "서울특별시 테스트구 테스트동 1",
            "households": 1500,
            "dedupeKey": "location-score-test",
        }

    def tearDown(self):
        kakao_station_distances.reset_memory_cache()
        self.cache_patch.stop()
        self.temporary.cleanup()

    def test_score_contains_simple_breakdown(self):
        row = {
            "name": "종합점수아파트",
            "displayName": "종합점수아파트",
            "midPriceEok": 12,
            "latestDealPriceEok": 11.8,
            "currentEstimateMinPriceEok": 11.5,
            "currentEstimateMaxPriceEok": 12.5,
            "households": 1500,
            "buildingAge": 8,
            "buildYear": 2018,
            "transactionCount": 12,
            "recent3TradeCount": 14,
            "latestJeonseDepositEok": 7.4,
            "latestJeonseDate": "2026-07-03",
            "jeonseTransactionCount": 4,
            "jeonseRatioPct": 61.7,
            "jeonseSalePriceBasisEok": 12,
            "educationEnvironment": {
                "score": 76,
                "elementarySchoolNames": ["테스트초"],
                "elementaryDistanceMeters": 320,
            },
            "commuteMatched": True,
            "signals": {
                "status": "ok",
                "score": 68,
                "momentumPct": 2.5,
                "districtRelativePct": 1.5,
                "leaderRelativePct": -1.0,
                "recoveryPct": 88.0,
                "currentPpsm": 2000,
                "leaderReferencePpsm": 2400,
                "sampleConfidence": "medium",
            },
        }

        result = location_scores.score_for_candidate(row, self.entity)

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["score"], 60)
        self.assertEqual(result["scoreFormulaVersion"], "purchase-judgment-v4")
        self.assertEqual(result["title"], "현재 데이터 기준 종합 점수")
        self.assertEqual(
            [part["label"] for part in result["parts"]],
            ["가격 적정성", "전세가율·입주물량·투자금", "입지·실수요", "상품성·희소성", "거래 유동성·시장 신호"],
        )
        reasons = {part["label"]: part["reason"] for part in result["parts"]}
        self.assertEqual(reasons["가격 적정성"], "최근 거래가 예상 가격과 잘 맞아요")
        self.assertEqual(reasons["전세가율·입주물량·투자금"], "전세가율 61.7% · 전세금 비중이 높아 내 돈 부담이 낮은 편이에요")
        self.assertEqual(reasons["입지·실수요"], "입지는 무난하지만 세부 확인이 필요해요")
        self.assertEqual(reasons["상품성·희소성"], "단지 규모와 연식이 좋은 편이에요")
        self.assertEqual(reasons["거래 유동성·시장 신호"], "거래 흐름은 보통이에요")
        bases = {part["label"]: part.get("basis") for part in result["parts"]}
        self.assertEqual(bases["가격 적정성"], "산식: 반영 지표 4/4개 · 87/100 × 30점 = 26.1/30점")
        details = {
            part["label"]: {detail["label"]: detail for detail in part["details"]}
            for part in result["parts"]
        }
        self.assertEqual(details["상품성·희소성"]["세대수"]["reason"], "1,500세대 · 1,000~1,999세대 구간")
        self.assertEqual(details["상품성·희소성"]["준공연도"]["reason"], "2018년 사용승인")
        self.assertNotIn("주차·평면·브랜드", details["상품성·희소성"])
        self.assertEqual(details["입지·실수요"]["교육 접근성"]["reason"], "테스트초 · 320m 거리")
        self.assertEqual(details["입지·실수요"]["주변 정비사업 영향"]["score"], 50)
        self.assertEqual(
            details["입지·실수요"]["주변 정비사업 영향"]["analysis"]["neutralPoints"],
            2,
        )
        self.assertEqual(details["전세가율·입주물량·투자금"]["필요 투자금"]["reason"], "필요한 내 돈 4.6억원 · 매매가의 38.3%")
        self.assertEqual(result["areaAnalysis"]["parts"], [])
        self.assertTrue(any(
            detail["status"] == "missing"
            for part in result["parts"]
            for detail in part["details"]
        ))

    def test_jeonse_and_investment_gap_are_not_estimated_when_rent_data_is_missing(self):
        row = {
            "name": "전세미수집아파트",
            "displayName": "전세미수집아파트",
            "province": "서울특별시",
            "region": "성북구",
            "currentEstimateMidPriceEok": 10.0,
            "latestDealPriceEok": 9.8,
            "transactionCount": 6,
            "signals": {"status": "insufficient"},
        }

        result = location_scores.score_for_candidate(row, self.entity)

        self.assertNotIn("jeonseDataStatus", row)
        self.assertNotIn("jeonseRatioPct", row)
        self.assertNotIn("latestJeonseDepositEok", row)
        self.assertNotIn("jeonseSourceNote", row)
        parts = {part["key"]: part for part in result["parts"]}
        self.assertEqual(parts["jeonse"]["status"], "ok")
        self.assertNotIn("추정", parts["jeonse"]["reason"])
        details = {detail["key"]: detail for detail in parts["jeonse"]["details"]}
        self.assertEqual(details["jeonse_ratio"]["status"], "missing")
        self.assertEqual(details["investment_gap"]["status"], "missing")
        self.assertIn("전세 실거래 데이터 없음", details["jeonse_ratio"]["reason"])

    def test_region_status_price_reason_names_the_price_basis(self):
        row = {
            "name": "가격근거아파트",
            "midPriceEok": 8.6,
            "households": 800,
            "buildingAge": 12,
            "buildYear": 2014,
            "transactionCount": 6,
            "educationEnvironment": {"score": None},
            "signals": {"status": "insufficient"},
        }

        result = location_scores.score_for_candidate(row, self.entity)
        reasons = {part["label"]: part["reason"] for part in result["parts"]}

        self.assertIn("지역 안에서는 가격 부담이 있는 편이에요", reasons["가격 적정성"])
        product_details = {
            detail["label"]: detail
            for part in result["parts"] if part["label"] == "상품성·희소성"
            for detail in part["details"]
        }
        self.assertEqual(product_details["세대수"]["reason"], "800세대 · 500~999세대 구간")
        self.assertNotIn("8.6억원 가격대", reasons["가격 적정성"])
        self.assertNotIn("주차·평면·브랜드", product_details)

    def test_purchase_score_uses_fallback_data_for_recovery_and_commute_only_when_requested(self):
        row = {
            "name": "보강아파트",
            "midPriceEok": 9.4,
            "latestDealPriceEok": 9.4,
            "recentMaxPriceEok": 10.0,
            "households": 900,
            "buildingAge": 14,
            "buildYear": 2012,
            "transactionCount": 7,
            "recent3TradeCount": 5,
            "commuteAccessRequested": True,
            "commuteAccessScore": 50,
            "commuteAccessReason": "강남역 실제 경로는 미연결 · 권역 기준으로만 확인",
            "educationEnvironment": {"score": 72},
            "signals": {
                "status": "ok",
                "momentumPct": 3.0,
                "districtRelativePct": 1.0,
                "leaderPrice12m": 12.0,
                "sampleConfidence": "medium",
            },
        }

        result = location_scores.score_for_candidate(row, self.entity)
        details = {
            part["label"]: {detail["label"]: detail for detail in part["details"]}
            for part in result["parts"]
        }

        self.assertIn("지역 대장보다 21.7% 낮음", details["가격 적정성"]["대장 가격 차이"]["reason"])
        self.assertIn("최근 최고가 기준", details["가격 적정성"]["고점 회복률"]["reason"])
        self.assertEqual(details["입지·실수요"]["직장권 접근성"]["score"], 50)
        self.assertIn("권역 기준", details["입지·실수요"]["직장권 접근성"]["reason"])

    def test_purchase_score_hides_commute_metric_when_user_did_not_enter_commute(self):
        row = {
            "name": "직장권없음아파트",
            "midPriceEok": 8.8,
            "households": 1200,
            "buildingAge": 10,
            "buildYear": 2016,
            "transactionCount": 8,
            "educationEnvironment": {"score": 80},
            "signals": {"status": "ok", "momentumPct": 2.0, "districtRelativePct": 0.5},
        }

        result = location_scores.score_for_candidate(row, self.entity)
        demand_details = {
            detail["label"]
            for part in result["parts"] if part["label"] == "입지·실수요"
            for detail in part["details"]
        }

        self.assertNotIn("직장권 접근성", demand_details)

    def test_redevelopment_projects_are_structured_in_demand_details(self):
        row = {
            "name": "정비영향아파트",
            "midPriceEok": 8.8,
            "latitude": 37.5471,
            "longitude": 126.9609,
            "households": 1200,
            "buildingAge": 10,
            "buildYear": 2016,
            "transactionCount": 8,
            "educationEnvironment": {"score": 80},
            "signals": {"status": "ok", "momentumPct": 2.0, "districtRelativePct": 0.5},
        }

        result = location_scores.score_for_candidate(row, self.entity)
        details = {
            detail["label"]: detail
            for part in result["parts"] if part["label"] == "입지·실수요"
            for detail in part["details"]
        }
        redevelopment = details["주변 정비사업 영향"]

        self.assertEqual(redevelopment["status"], "ok")
        self.assertIn("analysis", redevelopment)
        self.assertTrue(redevelopment["analysis"]["projects"])
        self.assertLessEqual(redevelopment["analysis"]["projects"][0]["distanceMeters"], 1000)
        self.assertIn(redevelopment["analysis"]["projects"][0]["type"], location_scores.redevelopment_analysis.PROJECT_TYPES)

    def test_completed_redevelopment_zone_is_not_counted_as_active_project(self):
        path = Path(self.temporary.name) / "redevelopment_zones.geojson"
        path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "completed-zone",
                "properties": {
                    "name": "완료된 재정비구역",
                    "projectType": "재건축",
                    "stage": "준공",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [126.9600, 37.5460],
                        [126.9620, 37.5460],
                        [126.9620, 37.5480],
                        [126.9600, 37.5480],
                        [126.9600, 37.5460],
                    ]],
                },
            }],
        }), encoding="utf-8")
        with mock.patch.object(location_scores.redevelopment_analysis, "DATA_PATH", path):
            location_scores.redevelopment_analysis._CACHE.update({"mtime": None, "projects": []})
            projects, status = location_scores.redevelopment_analysis.nearby_projects(
                {"latitude": 37.5471, "longitude": 126.9609},
                self.entity,
            )

        self.assertEqual(status, "ok")
        self.assertEqual(projects, [])

    def test_presale_candidate_gets_composite_score(self):
        row = {
            "name": "분양권점수아파트",
            "midPriceEok": 11.0,
            "latestDealPriceEok": 11.0,
            "households": 3487,
            "status": "분양권",
            "transactionCount": 2,
            "recent3TradeCount": 2,
            "educationEnvironment": {
                "score": 70,
                "elementarySchoolNames": ["테스트초"],
                "elementaryDistanceMeters": 450,
            },
            "signals": {"status": "unavailable"},
        }

        result = location_scores.score_for_candidate(row, self.entity)
        reasons = {part["label"]: part["reason"] for part in result["parts"]}

        self.assertEqual(result["status"], "ok")
        self.assertIsInstance(result["score"], int)
        self.assertIn("신축 예정이라 연식은 좋은 편이에요", reasons["상품성·희소성"])
        market_details = {
            detail["label"]: detail
            for part in result["parts"] if part["label"] == "거래 유동성·시장 신호"
            for detail in part["details"]
        }
        self.assertEqual(market_details["최근 거래량"]["reason"], "최근 3개월 거래 2건")

    def test_region_status_uses_candidate_price_rank_when_peers_exist(self):
        rows = []
        for index, price in enumerate((20, 15, 10, 5), start=1):
            rows.append({
                "name": f"후보{index}아파트",
                "displayName": f"후보{index}아파트",
                "region": "테스트구",
                "legalDong": "테스트동",
                "midPriceEok": price,
                "households": 800,
                "buildingAge": 12,
                "buildYear": 2014,
                "transactionCount": 6,
                "educationEnvironment": {"score": None},
                "signals": {"status": "insufficient"},
            })

        location_scores.attach_scores(rows, lambda _row: self.entity)
        reasons = [
            {part["label"]: part["reason"] for part in row["locationScore"]["parts"]}["가격 적정성"]
            for row in rows
        ]

        self.assertIn("지역 안에서는 가격 부담이 있는 편이에요", reasons[0])
        self.assertIn("지역 안에서는 가격 부담이 낮은 편이에요", reasons[1])
        self.assertIn("지역 안에서는 가격 부담이 낮은 편이에요", reasons[3])
        self.assertNotIn("지역 최상위권", " ".join(reasons))

    def test_purchase_score_changes_when_selected_area_market_changes(self):
        base = {
            "name": "평형고정아파트",
            "displayName": "평형고정아파트",
            "midPriceEok": 10,
            "households": 1200,
            "buildingAge": 10,
            "buildYear": 2016,
            "educationEnvironment": {"score": 80},
        }
        small = {
            **base,
            "areaLabel": "전용 59㎡",
            "transactionCount": 20,
            "recent3TradeCount": 12,
            "signals": {
                "status": "ok",
                "score": 90,
                "momentumPct": 5.0,
                "currentPpsm": 1800,
                "isRegionalLeader": True,
            },
        }
        large = {
            **base,
            "areaLabel": "전용 84㎡",
            "transactionCount": 1,
            "recent3TradeCount": 1,
            "signals": {
                "status": "ok",
                "score": 30,
                "momentumPct": -3.0,
                "currentPpsm": 2300,
                "isRegionalLeader": False,
            },
        }

        small_result = location_scores.score_for_candidate(small, self.entity)
        large_result = location_scores.score_for_candidate(large, self.entity)

        self.assertNotEqual(small_result["score"], large_result["score"])
        small_reasons = {part["label"]: part["reason"] for part in small_result["parts"]}
        large_reasons = {part["label"]: part["reason"] for part in large_result["parts"]}
        self.assertNotEqual(
            small_reasons["거래 유동성·시장 신호"],
            large_reasons["거래 유동성·시장 신호"],
        )


if __name__ == "__main__":
    unittest.main()
