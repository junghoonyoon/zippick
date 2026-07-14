import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import budget_candidates  # noqa: E402


class BudgetCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.live_price_patch = mock.patch.object(
            budget_candidates.molit_transactions,
            "enabled",
            return_value=False,
        )
        self.live_price_patch.start()

    def tearDown(self):
        self.live_price_patch.stop()

    def test_missing_purchase_power_inputs_are_rejected(self):
        result = budget_candidates.budget_candidates("예산 미정")
        self.assertEqual(result["status"], 400)
        self.assertIn("자기자금", result["error"])

    def test_city_name_matches_district_price_rows(self):
        result = budget_candidates.budget_candidates(
            "20억",
            region="성남시",
            purpose="live",
            priority="transport",
            commute="강남역",
            move_timing="within_1y",
            limit=3,
        )

        names = [row["name"] for row in result["candidates"]]
        self.assertGreaterEqual(len(names), 1)
        self.assertIn("산성역 포레스티아", names)
        forestia = next(row for row in result["candidates"] if row["name"] == "산성역 포레스티아")
        self.assertEqual(forestia["households"], 4089)
        self.assertEqual(result["purposeLabel"], "실거주")
        self.assertEqual(result["moveTimingLabel"], "1년 안")

    def test_candidate_explains_commute_and_data_limit(self):
        result = budget_candidates.budget_candidates(
            "20억",
            region="성남시",
            purpose="live",
            priority="transport",
            commute="강남역",
            move_timing="within_1y",
            limit=1,
        )
        candidate = result["candidates"][0]

        self.assertTrue(candidate["commuteMatched"])
        self.assertTrue(any("권역 기준" in item for item in candidate["reasons"]))
        self.assertTrue(any("실제 출근 시간" in item for item in candidate["risks"]))
        self.assertEqual(candidate["priceSource"], "molit_reference")

    def test_recent_deal_gap_adds_a_cautious_review_comment(self):
        candidate = budget_candidates._decision_support(
            {
                "_budgetEok": 12,
                "midPriceEok": 10.0,
                "latestDealPriceEok": 10.0,
                "recentMedianPriceEok": 8.5,
                "transactionCount": 8,
                "priceSource": "molit",
            },
            {}, "", "", "", "", "stretch", "",
        )

        self.assertTrue(any("18% 차이" in item and "신중 검토" in item for item in candidate["risks"]))

    def test_stale_manual_prices_without_a_last_deal_are_not_used_as_budget_candidates(self):
        result = budget_candidates.budget_candidates(
            "20억",
            region="성남수정구",
            purpose="live",
            limit=6,
        )

        self.assertGreater(result["noLastDealCount"], 0)
        self.assertTrue(all(row["priceSource"] in budget_candidates.VERIFIED_PRICE_SOURCES for row in result["candidates"]))

    def test_forestia_recent_84_price_is_not_a_twelve_eok_candidate(self):
        result = budget_candidates.budget_candidates(
            "12억",
            region="성남수정구",
            purpose="live",
            limit=6,
        )

        self.assertNotIn("산성역 포레스티아", [row["name"] for row in result["candidates"]])
        forestia = next(row for row in budget_candidates._load_price_bands() if row["name"] == "산성역 포레스티아")
        self.assertEqual(forestia["minPriceEok"], 15.5)
        self.assertEqual(forestia["midPriceEok"], 16.55)
        self.assertEqual(forestia["maxPriceEok"], 17.0)

    def test_seoul_nine_eok_uses_official_small_apartment_trades(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            purpose="live",
            priority="transport",
            commute="광화문",
            move_timing="within_1y",
            limit=3,
        )

        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["livePriceCount"], 3)
        self.assertTrue(all(row["priceSource"] == "molit_csv" for row in result["candidates"]))
        self.assertTrue(all(row["transactionCount"] >= 3 for row in result["candidates"]))
        self.assertTrue(all(row["fitStatus"] != "제외" for row in result["candidates"]))

    def test_investment_profile_shows_missing_cost_inputs(self):
        result = budget_candidates.budget_candidates(
            "20억",
            region="성남시",
            purpose="invest",
            priority="price_buffer",
            move_timing="flexible",
            limit=1,
        )
        candidate = result["candidates"][0]

        self.assertEqual(result["purposeLabel"], "투자 검토")
        self.assertTrue(any("전세가율" in item for item in candidate["risks"]))

    def test_complex_name_is_not_mistaken_for_its_region(self):
        self.assertFalse(budget_candidates._matches_region(
            {"name": "강남팰리스", "region": "송파구"},
            {"city": "서울특별시", "district": "송파구", "legalDong": "가락동"},
            "강남구",
        ))

    def test_seoul_filter_rejects_gyeonggi_general_districts(self):
        self.assertFalse(budget_candidates._matches_region(
            {"name": "산성역 포레스티아", "region": "성남수정구"},
            {"province": "경기도", "city": "성남시", "district": "성남수정구"},
            "서울시",
        ))
        self.assertFalse(budget_candidates._matches_region(
            {"name": "수원역푸르지오자이", "region": "수원팔달구"},
            {"province": "경기도", "city": "수원시", "district": "수원팔달구"},
            "서울시",
        ))

    def test_seoul_filter_accepts_seoul_city_and_district_fallback(self):
        self.assertTrue(budget_candidates._matches_region(
            {"name": "서울 단지", "region": "강남구"},
            {"province": "서울특별시", "city": "서울시", "district": "강남구"},
            "서울시",
        ))
        self.assertTrue(budget_candidates._matches_region(
            {"name": "서울 단지", "region": "중랑구"},
            None,
            "서울시",
        ))

    def test_gyeonggi_filter_accepts_province_and_region_fallback(self):
        self.assertTrue(budget_candidates._matches_region(
            {"name": "경기 단지", "region": "성남수정구"},
            {"province": "경기도", "city": "성남시", "district": "성남수정구"},
            "경기도",
        ))
        self.assertTrue(budget_candidates._matches_region(
            {"name": "경기 단지", "region": "수원팔달구"},
            None,
            "경기도",
        ))
        self.assertFalse(budget_candidates._matches_region(
            {"name": "서울 단지", "region": "강남구"},
            {"province": "서울특별시", "city": "서울시", "district": "강남구"},
            "경기도",
        ))

    def test_condition_profile_exposes_filters_and_score_evidence(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            purpose="live",
            priority="transport",
            commute="광화문",
            price_strategy="balanced",
            min_area="59",
            min_households="1000",
            max_building_age="30",
            limit=3,
        )

        self.assertEqual(result["priceStrategy"], "balanced")
        self.assertGreater(result["eligibleCount"], 0)
        self.assertGreater(result["filterSummary"]["households"], 0)
        candidate = result["candidates"][0]
        self.assertGreater(candidate["matchScore"], 0)
        self.assertTrue(any(item["kind"] == "confidence" for item in candidate["scoreBreakdown"]))
        self.assertIn(candidate["matchLabel"], {"매우 잘 맞아요", "대체로 잘 맞아요", "보통이에요", "조건을 더 확인해보세요"})
        self.assertTrue(candidate["matchSummary"])
        self.assertGreaterEqual(candidate["buildingAge"], 1)

    def test_unverified_priority_is_not_presented_as_a_match(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            purpose="live",
            priority="school",
            limit=1,
        )

        candidate = result["candidates"][0]
        self.assertFalse(any("학군 우선 조건" in item for item in candidate["reasons"]))
        self.assertTrue(any("학군" in item and "반영하지" in item for item in candidate["risks"]))

    def test_policy_impact_is_attached_to_each_candidate(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            home_ownership="no_home",
            cash_eok="8",
            limit=1,
        )

        candidate = result["candidates"][0]
        self.assertTrue(candidate["policyImpact"]["isRegulated"])
        self.assertEqual(candidate["policyImpact"]["asOf"], "2026-07-12")
        self.assertEqual(result["policySnapshot"]["cashEok"], 8)

    def test_multiple_purposes_priorities_and_commutes_are_combined(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            purpose="live,move",
            priority="transport,price_buffer",
            commute="광화문,여의도",
            limit=1,
        )

        self.assertEqual(result["purposeLabel"], "실거주 · 갈아타기")
        self.assertEqual(result["priorityLabel"], "교통·접근성 · 예산 여유")
        self.assertIn("광화문", result["commute"])
        self.assertTrue(any(item["label"] == "생활권" for item in result["candidates"][0]["scoreBreakdown"]))

    def test_empty_priority_remains_neutral(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            purpose="live",
            priority="",
            limit=1,
        )

        self.assertEqual(result["priority"], "")
        self.assertEqual(result["priorityLabel"], "")

    def test_multiple_regions_use_or_matching(self):
        result = budget_candidates.budget_candidates(
            "12억",
            region="서울시,성남시",
            purpose="live",
            limit=6,
        )

        self.assertGreater(len(result["candidates"]), 0)
        self.assertEqual(result["region"], "서울시,성남시")

    def test_cash_short_candidates_are_excluded_from_default_results(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            home_ownership="no_home",
            cash_eok="1",
            limit=6,
        )

        self.assertEqual(result["candidates"], [])
        self.assertGreater(result["policyExcludedCount"], 0)
        self.assertGreater(len(result["policyExcludedCandidates"]), 0)
        self.assertTrue(all(row["policyImpact"]["status"] != "possible" for row in result["policyExcludedCandidates"]))
        self.assertIn("통과한 후보가 없", result["message"])

    def test_cash_sufficient_candidates_remain_in_default_results(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            home_ownership="no_home",
            cash_eok="8",
            limit=3,
        )

        self.assertEqual(len(result["candidates"]), 3)
        self.assertTrue(all(row["policyImpact"]["status"] == "possible" for row in result["candidates"]))

    def test_candidate_has_naver_property_search_link_with_location(self):
        result = budget_candidates.budget_candidates(
            "9억",
            region="서울시",
            home_ownership="no_home",
            limit=1,
        )

        candidate = result["candidates"][0]
        kind = candidate.get("naverLinkKind")
        if kind == "complex":
            self.assertTrue(candidate["naverPropertyUrl"].startswith("https://new.land.naver.com/complexes/"))
        else:
            self.assertTrue(candidate["naverPropertyUrl"].startswith("https://fin.land.naver.com/search?q="))
            decoded = unquote(candidate["naverPropertyUrl"])
            self.assertIn(candidate["naverPropertyQuery"], decoded)

    def test_naver_link_uses_unique_name_without_internal_region_tokens(self):
        entity = budget_candidates._find_entity("산성역 헤리스톤", "성남수정구")
        link = budget_candidates._naver_property_link(
            {"name": "산성역 헤리스톤", "region": "성남수정구"},
            entity,
        )

        self.assertEqual(link["naverPropertyQuery"], "산성역 헤리스톤")

    def test_naver_link_disambiguates_generic_name_and_removes_floor_marker(self):
        generic = budget_candidates._naver_property_link(
            {"name": "현대", "region": "구로구"},
            {"legalDong": "개봉동"},
        )
        floor = budget_candidates._naver_property_link(
            {"name": "상계주공3(고층)", "region": "노원구"},
            {"legalDong": "상계동"},
        )

        self.assertEqual(generic["naverPropertyQuery"], "개봉동 현대")
        self.assertEqual(floor["naverPropertyQuery"], "상계주공3단지")

    def test_naver_link_restores_numbered_complex_suffix_and_trailing_quote(self):
        link = budget_candidates._naver_property_link(
            {"name": '관악산벽산타운5"', "region": "금천구"},
            {"legalDong": "시흥동"},
        )

        self.assertEqual(link["naverPropertyQuery"], "관악산벽산타운5단지")

    def test_naver_link_adds_location_to_short_name_with_apartment_suffix(self):
        link = budget_candidates._naver_property_link(
            {"name": "계룡아파트", "region": "금천구"},
            {"legalDong": "시흥동"},
        )

        self.assertEqual(link["naverPropertyQuery"], "시흥동 계룡아파트")

    def test_naver_link_uses_canonical_name_for_public_data_alias(self):
        link = budget_candidates._naver_property_link(
            {"name": "대우디오빌", "region": "강남구"},
            {"name": "대우양재디오빌", "legalDong": "도곡동"},
        )

        self.assertEqual(link["naverPropertyQuery"], "대우양재디오빌")

    def test_ambiguous_public_data_alias_is_not_used_as_candidate(self):
        matches = budget_candidates._find_entities("대우디오빌", "강남구")
        self.assertGreater(len(matches), 1)

        result = budget_candidates.budget_candidates(
            "20억",
            region="강남구",
            home_ownership="no_home",
            limit=20,
        )
        result_names = [
            row["name"]
            for row in [*result["candidates"], *result.get("policyExcludedCandidates", [])]
        ]

        self.assertNotIn("대우디오빌", result_names)
        self.assertGreater(result["filterSummary"]["identity"], 0)

    def test_generic_complex_display_name_includes_location_without_jibun(self):
        entity = budget_candidates._find_entity("벽산", "금천구")
        display_name = budget_candidates._candidate_display_name(
            {"name": "벽산", "region": "금천구"},
            entity,
        )

        self.assertEqual(display_name, "시흥동 벽산아파트")

    def test_complex_aliases_are_deduplicated_by_master_identity(self):
        rows = [
            {"name": "삼부컨비니언", "region": "성북구", "legalDong": "길음동", "jibun": "1276"},
            {"name": "돈암2-1 삼부아파트", "region": "성북구", "legalDong": "길음동", "jibun": "1276"},
        ]

        self.assertEqual(len(budget_candidates._dedupe_candidate_rows(rows)), 1)

    def test_budget_is_automatically_derived_when_not_entered(self):
        result = budget_candidates.budget_candidates(
            "",
            region="서울시",
            home_ownership="no_home",
            cash_eok="3",
            annual_income="8000",
            mortgage_rate="4.2",
            loan_term_years="30",
            purchase_cost_rate="4",
            limit=3,
        )

        self.assertEqual(result["budgetSource"], "calculated")
        self.assertLess(result["budgetEok"], 15)
        self.assertEqual(result["policySnapshot"]["estimatedPurchaseCeilingEok"], result["budgetEok"])

    def test_input_purchase_power_is_adjusted_to_selected_region_policy(self):
        result = budget_candidates.budget_candidates(
            "8.9억",
            region="은평구",
            home_ownership="no_home",
            cash_eok="5",
            annual_income="8000",
            mortgage_rate="4.2",
            loan_term_years="30",
            purchase_cost_rate="0",
            limit=3,
        )

        self.assertEqual(result["budgetSource"], "region_adjusted")
        self.assertLess(result["budgetEok"], 8.9)
        self.assertEqual(result["policySnapshot"]["estimatedPurchaseCeilingEok"], result["budgetEok"])


if __name__ == "__main__":
    unittest.main()
