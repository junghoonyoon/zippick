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
            "households": 1500,
            "buildingAge": 8,
            "buildYear": 2018,
            "transactionCount": 12,
            "recent3TradeCount": 14,
            "educationEnvironment": {
                "score": 76,
                "elementarySchoolNames": ["테스트초"],
                "elementaryDistanceMeters": 320,
            },
            "signals": {
                "status": "ok",
                "score": 68,
                "momentumPct": 2.5,
                "currentPpsm": 2000,
                "leaderReferencePpsm": 2400,
            },
        }

        result = location_scores.score_for_candidate(row, self.entity)

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["score"], 60)
        self.assertEqual(result["scoreFormulaVersion"], "complex-score-v2")
        self.assertEqual(
            [part["label"] for part in result["parts"]],
            ["지역 위상", "단지 규모", "교통 접근성", "교육환경", "상품성"],
        )
        reasons = {part["label"]: part["reason"] for part in result["parts"]}
        self.assertEqual(reasons["지역 위상"], "1,500세대 · 지역에서 비교하기 좋은 대단지")
        self.assertEqual(reasons["단지 규모"], "1,500세대 · 1,000세대 이상")
        self.assertEqual(reasons["교육환경"], "테스트초 · 320m 거리")
        self.assertEqual(reasons["상품성"], "2018년 사용승인")
        area_reasons = {
            part["label"]: part["reason"]
            for part in result["areaAnalysis"]["parts"]
        }
        self.assertEqual(area_reasons["가격 위치"], "㎡당 2,000만원 · 대표 단지보다 낮은 가격 추정")
        self.assertEqual(area_reasons["거래 유동성"], "최근 3개월 거래 14건")
        self.assertEqual(area_reasons["최근 흐름"], "최근 6개월 +2.5% · 가격·거래 흐름")
        self.assertTrue(any(part["status"] == "missing" for part in result["parts"]))

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

        self.assertEqual(reasons["지역 위상"], "800세대 · 단지 규모 기준")
        area_reasons = {
            part["label"]: part["reason"]
            for part in result["areaAnalysis"]["parts"]
        }
        self.assertEqual(area_reasons["가격 위치"], "예상 매수가 8.6억원 기준")
        self.assertNotIn("8.6억원 가격대", area_reasons["가격 위치"])

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
        self.assertEqual(reasons["상품성"], "분양권 · 신축 예정")
        area_reasons = {
            part["label"]: part["reason"]
            for part in result["areaAnalysis"]["parts"]
        }
        self.assertEqual(area_reasons["거래 유동성"], "최근 3개월 거래 2건")

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
            {part["label"]: part["reason"] for part in row["locationScore"]["areaAnalysis"]["parts"]}["가격 위치"]
            for row in rows
        ]

        self.assertEqual(reasons[0], "지역 후보 1/4위 · 상위 25% · 상위권 가격")
        self.assertEqual(reasons[1], "지역 후보 2/4위 · 상위 50% · 중간권 가격")
        self.assertEqual(reasons[3], "지역 후보 4/4위 · 상위 100% · 낮은 가격")
        self.assertNotIn("지역 최상위권", " ".join(reasons))

    def test_composite_score_stays_same_when_only_selected_area_market_changes(self):
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

        self.assertEqual(small_result["score"], large_result["score"])
        self.assertNotEqual(
            small_result["areaAnalysis"]["parts"][1]["reason"],
            large_result["areaAnalysis"]["parts"][1]["reason"],
        )
        self.assertEqual(small_result["areaAnalysis"]["leaderLabel"], "지역 대표 가격 흐름")
        self.assertEqual(large_result["areaAnalysis"]["leaderLabel"], "")


if __name__ == "__main__":
    unittest.main()
