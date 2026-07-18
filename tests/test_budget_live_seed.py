import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import budget_candidates  # noqa: E402


class BudgetLiveSeedTest(unittest.TestCase):
    def test_fast_mode_uses_broad_region_seed_without_signal_enrichment(self):
        entity = {
            "name": "서울전체빠른후보",
            "city": "서울시",
            "district": "송파구",
            "legalDong": "가락동",
            "households": 900,
            "approvedAt": "2000-01-01",
        }
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", [entity]), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "cached_price_band_for_apartment", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "cached_price_band_for_apartment_min_area", return_value=None), \
             mock.patch.object(budget_candidates.momentum_signals, "attach_signals") as attach:
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "9억", region="서울시", min_area="59", all_matches=True, fast_mode=True,
            )

        self.assertTrue(result["initialStage"])
        self.assertEqual(result["liveSeedCount"], 1)
        self.assertEqual([row["name"] for row in result["candidates"]], ["서울전체빠른후보"])
        attach.assert_not_called()

    def tearDown(self):
        budget_candidates._ENTITY_LOOKUP = None

    def test_molit_enabled_uses_apartment_master_as_live_price_seed(self):
        entity = {
            "name": "분당테스트아파트",
            "aliases": ["분당테스트"],
            "city": "성남시",
            "district": "성남분당구",
            "legalDong": "정자동",
            "category": "성남분당구 아파트",
            "households": 1200,
            "approvedAt": "2023-01-01",
        }

        def fake_price_band(name, region="", area_label="", lookback_months=None):
            if name != "분당테스트아파트":
                return None
            return {
                "name": name,
                "region": region,
                "areaLabel": area_label,
                "minPriceEok": 8.0,
                "midPriceEok": 9.0,
                "maxPriceEok": 10.0,
                "transactionCount": 5,
                "latestDealDate": "2026-06-01",
                "sourceNote": "국토부 실거래가 테스트",
            }

        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", [entity]), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", side_effect=fake_price_band), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억",
                region="성남시",
                purpose="live",
                min_area="59",
                min_households="1000",
                max_building_age="10",
                limit=6,
            )

        self.assertEqual(result["liveSeedCount"], 1)
        self.assertEqual(result["eligibleCount"], 1)
        self.assertEqual(result["candidates"][0]["name"], "분당테스트아파트")
        self.assertEqual(result["candidates"][0]["region"], "성남분당구")
        self.assertEqual(result["candidates"][0]["displayRegion"], "성남분당구 정자동")
        self.assertEqual(result["candidates"][0]["areaLabel"], "전용 59~60㎡")
        self.assertEqual(result["candidates"][0]["displayAreaLabel"], "전용 59㎡")
        self.assertEqual(result["candidates"][0]["priceSource"], "molit")

    def test_all_matches_excludes_complexes_without_any_transaction(self):
        entities = [
            {
                "name": f"조건일치아파트{index}",
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1200 + index,
                "approvedAt": "2023-01-01",
            }
            for index in range(8)
        ]
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", entities), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "latest_transaction_for_apartment", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억",
                region="성남시",
                min_area="59",
                min_households="1000",
                max_building_age="10",
                limit=2,
                all_matches=True,
            )

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["noLastDealCount"], 8)
        self.assertEqual(result["filterSummary"]["noLastDeal"], 8)

    def test_all_matches_limits_live_price_enrichment_work(self):
        entities = [
            {
                "name": f"대량조회아파트{index}",
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1200 + index,
                "approvedAt": "2023-01-01",
            }
            for index in range(120)
        ]
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", entities), \
             mock.patch.object(budget_candidates.config, "MOLIT_TRANSACTION_ALL_MATCHES_ENRICH_LIMIT", 7), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", return_value=None) as lookup, \
             mock.patch.object(budget_candidates.molit_transactions, "latest_transaction_for_apartment", return_value=None) as last_lookup, \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억",
                region="성남시",
                min_area="59",
                all_matches=True,
            )

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["noLastDealCount"], 120)
        self.assertEqual(lookup.call_count, 7)
        self.assertEqual(last_lookup.call_count, 7)

    def test_rental_and_lh_complexes_are_excluded_before_live_price_lookup(self):
        entities = [
            {
                "name": "매수가능아파트",
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1200,
                "approvedAt": "2023-01-01",
            },
            {
                "name": "공공임대단지",
                "aliases": ["공공임대단지(임대)"],
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1200,
                "approvedAt": "2023-01-01",
            },
            {
                "name": "LH행복주택",
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1200,
                "approvedAt": "2023-01-01",
            },
        ]
        live = {
            "areaLabel": "전용 60㎡",
            "minPriceEok": 8.5,
            "midPriceEok": 8.8,
            "maxPriceEok": 9.0,
            "latestDealPriceEok": 8.8,
            "transactionCount": 1,
            "latestDealDate": "2026-05-01",
            "sourceNote": "국토부",
        }

        # 실제 price_band_for_apartment 응답처럼 조회 범위(lookbackMonths)를
        # 함께 돌려준다. 이 필드가 없으면 12개월 확장 조회 결과를 6개월로
        # 오인해 같은 확장 조회가 한 번 더 나간다.
        def fake_price_band(name, **kwargs):
            payload = dict(live)
            payload["lookbackMonths"] = int(kwargs.get("lookback_months") or 6)
            return payload

        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", entities), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", side_effect=fake_price_band) as lookup, \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억", region="성남시", min_area="59", all_matches=True,
            )

        self.assertEqual([row["name"] for row in result["candidates"]], ["매수가능아파트"])
        self.assertEqual(result["rentalExcludedCount"], 2)
        self.assertEqual(result["filterSummary"]["rental"], 2)
        # 표본이 3건 미만이면 같은 매수 후보에 한해 12개월 범위를 한 번 더
        # 조회한다. 임대/LH 후보는 두 조회 모두에서 제외되어야 한다.
        self.assertEqual(lookup.call_count, 2)
        self.assertTrue(all(call.args[0] == "매수가능아파트" for call in lookup.call_args_list))
        self.assertEqual(lookup.call_args_list[1].kwargs.get("lookback_months"), 12)

    def test_old_last_deal_metadata_remains_a_reference_price(self):
        row = {
            "lastObservedDealDate": "2025-04-15",
            "lastObservedDealPriceEok": 7.7,
        }

        budget_candidates._apply_fit(row, 12)

        self.assertEqual(row["priceRangeText"], "마지막 실거래 7억 7,000만원")
        self.assertEqual(row["fitStatus"], "가격 확인 필요")
        self.assertEqual(row["midPriceEok"], 0)
        self.assertEqual(row["budgetGapEok"], 4.3)
        self.assertEqual(row["budgetOverPercent"], 0)

    def test_static_price_range_is_replaced_with_the_latest_deal(self):
        entity = {
            "name": "최근거래아파트",
            "city": "서울시",
            "district": "금천구",
            "legalDong": "독산동",
            "households": 800,
            "approvedAt": "2020-01-01",
        }
        static_row = {
            "name": "최근거래아파트",
            "region": "금천구",
            "areaLabel": "전용 60~60㎡",
            "minPriceEok": 7.5,
            "midPriceEok": 7.8,
            "maxPriceEok": 8.2,
            "priceSource": "molit_csv",
            "transactionCount": 18,
            "latestDealDate": "2026-06-18",
        }
        live = {
            "areaLabel": "전용 60~60㎡",
            "minPriceEok": 7.5,
            "midPriceEok": 7.8,
            "maxPriceEok": 8.4,
            "latestDealPriceEok": 8.37,
            "latestDealExclusiveArea": 59.86,
            "latestDealFloor": "11",
            "transactionCount": 16,
            "latestDealDate": "2026-06-18",
            "sourceNote": "국토부",
            "currentEstimateMinPriceEok": 7.8,
            "currentEstimateMidPriceEok": 8.0,
            "currentEstimateMaxPriceEok": 8.2,
            "currentEstimateSampleCount": 16,
            "currentEstimateTrimmedCount": 2,
            "currentEstimateMethod": "최근 거래 가중 중앙값 · 가중 25~75백분위",
        }
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[static_row]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", [entity]), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", return_value=live), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "10억", region="금천구", min_area="59", all_matches=True,
            )

        candidate = result["candidates"][0]
        self.assertEqual(candidate["latestDealPriceEok"], 8.37)
        self.assertEqual(candidate["priceRangeText"], "현재 예상 시세 7.8억~8.2억")
        self.assertEqual(candidate["estimatedPriceConfidence"], "높음")

    def test_static_molit_csv_without_latest_price_is_labeled_as_price_band(self):
        row = {
            "minPriceEok": 7.9,
            "midPriceEok": 8.32,
            "maxPriceEok": 8.98,
            "priceSource": "molit_csv",
            "transactionCount": 10,
            "latestDealDate": "2026-06-18",
        }

        budget_candidates._apply_fit(row, 10)

        self.assertEqual(row["priceRangeText"], "현재 예상 시세 8.1억~8.6억")
        self.assertEqual(row["estimatedPriceConfidence"], "보통")
        self.assertTrue(row["estimatedPriceUsesAggregateBand"])

    def test_static_molit_csv_with_latest_price_uses_latest_deal(self):
        row = {
            "minPriceEok": 7.9,
            "midPriceEok": 8.32,
            "maxPriceEok": 8.98,
            "latestDealPriceEok": 8.65,
            "priceSource": "molit_csv",
            "transactionCount": 10,
            "latestDealDate": "2026-06-18",
        }

        budget_candidates._apply_fit(row, 10)

        self.assertEqual(row["priceRangeText"], "현재 예상 시세 8.1억~8.6억")
        self.assertEqual(row["estimatedMidPriceEok"], 8.32)

    def test_stale_verified_trade_is_not_used_as_a_current_price(self):
        row = {
            "minPriceEok": 7.9,
            "midPriceEok": 8.32,
            "maxPriceEok": 8.98,
            "priceSource": "molit_csv",
            "transactionCount": 10,
            "latestDealDate": "2025-06-18",
        }

        budget_candidates._apply_fit(row, 10)

        self.assertEqual(row["priceRangeText"], "마지막 실거래 8억 3,200만원")
        self.assertEqual(row["fitStatus"], "가격 확인 필요")
        self.assertNotIn("estimatedMidPriceEok", row)

    def test_generic_complex_name_is_concise_and_uses_full_address_below(self):
        entity = {
            "name": "현대아파트",
            "province": "서울특별시",
            "district": "구로구",
            "legalDong": "개봉동",
            "address": "서울특별시 구로구 개봉동 481",
        }
        row = {"name": "현대", "region": "구로구", "legalDong": "개봉동", "jibun": "481"}

        self.assertEqual(budget_candidates._candidate_display_name(row, entity), "개봉동 현대아파트")
        self.assertEqual(budget_candidates._display_region(row, entity), "서울특별시 구로구 개봉동 481")

    def test_all_matches_keeps_last_deal_within_five_percent_of_purchase_ceiling(self):
        entities = [
            {
                "name": name,
                "city": "성남시",
                "district": "성남분당구",
                "legalDong": "정자동",
                "address": f"경기도 성남시 분당구 정자동 {index}",
                "households": 1200,
                "approvedAt": "2023-01-01",
            }
            for index, name in enumerate(
                ("상한초과아파트", "상한근접아파트", "상한안아파트"),
                start=1,
            )
        ]

        def last_deal(name, **_kwargs):
            prices = {
                "상한초과아파트": 12.7,
                "상한근접아파트": 12.1,
                "상한안아파트": 11.8,
            }
            return {
                "latestDealPriceEok": prices[name],
                "latestDealDate": "2025-05-16",
                "latestDealExclusiveArea": 59.8,
                "latestDealFloor": "8",
                "sourceNote": "국토부 실거래가 확장 조회",
            }

        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", entities), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "latest_transaction_for_apartment", side_effect=last_deal), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억", region="성남시", min_area="59", all_matches=True,
            )

        self.assertEqual(
            {row["name"] for row in result["candidates"]},
            {"상한근접아파트", "상한안아파트"},
        )
        near = next(row for row in result["candidates"] if row["name"] == "상한근접아파트")
        self.assertEqual(near["priceRangeText"], "마지막 실거래 12억 1,000만원")
        self.assertEqual(near["lastObservedDealDate"], "2025-05-16")
        self.assertEqual(near["budgetGapEok"], -0.1)
        self.assertEqual(near["budgetOverPercent"], 0.8)
        self.assertEqual(result["lastDealOverBudgetCount"], 1)

    def test_all_matches_excludes_verified_price_far_above_budget(self):
        entity = {
            "name": "고가아파트",
            "city": "서울시",
            "district": "송파구",
            "legalDong": "가락동",
            "households": 900,
            "approvedAt": "2000-01-01",
        }
        live = {
            "areaLabel": "전용 60㎡",
            "minPriceEok": 16.9,
            "midPriceEok": 16.9,
            "maxPriceEok": 16.9,
            "latestDealPriceEok": 16.9,
            "transactionCount": 1,
            "latestDealDate": "2026-05-01",
            "sourceNote": "국토부",
        }
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", [entity]), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", return_value=live), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "8.9억", region="송파구", min_area="59", all_matches=True,
            )

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["excludedCount"], 1)

    def test_broad_region_enriches_region_balanced_live_seeds_within_limit(self):
        entities = [
            {
                "name": f"{district}라이브시드{index}",
                "city": "서울시",
                "district": district,
                "legalDong": "테스트동",
                "households": 900 + index,
                "approvedAt": "2000-01-01",
            }
            for district in ("송파구", "노원구")
            for index in range(2)
        ]

        def fake_price_band(name, region="", area_label="", **_kwargs):
            return {
                "name": name,
                "region": region,
                "areaLabel": area_label,
                "minPriceEok": 8.0,
                "midPriceEok": 8.5,
                "maxPriceEok": 9.0,
                "latestDealPriceEok": 8.5,
                "transactionCount": 3,
                "latestDealDate": "2026-06-01",
                "lookbackMonths": 12,
                "sourceNote": "국토부 실거래가 테스트",
            }

        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", entities), \
             mock.patch.object(budget_candidates.config, "BUDGET_BROAD_REGION_LIVE_SEED_LIMIT", 2), \
             mock.patch.object(budget_candidates.config, "MOLIT_TRANSACTION_ALL_MATCHES_ENRICH_LIMIT", 2), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(budget_candidates.molit_transactions, "cached_price_band_for_apartment", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "cached_price_band_for_apartment_min_area", return_value=None), \
             mock.patch.object(budget_candidates.molit_transactions, "price_band_for_apartment", side_effect=fake_price_band) as lookup, \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억", region="서울시", min_area="59", all_matches=True,
            )

        self.assertEqual(result["liveSeedCount"], 2)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual({row["region"] for row in result["candidates"]}, {"송파구", "노원구"})
        self.assertEqual(lookup.call_count, 2)

    def test_numbered_complex_parent_is_not_returned_or_used_as_alias(self):
        parent = {
            "name": "통합그랑메종",
            "aliases": ["통합그랑메종1단지", "통합그랑메종2단지"],
            "aggregate": True,
            "city": "성남시",
            "district": "성남중원구",
            "households": 2200,
            "approvedAt": "2023-01-01",
        }
        children = [
            {
                "name": f"통합그랑메종{index}단지",
                "city": "성남시",
                "district": "성남중원구",
                "households": 1100,
                "approvedAt": "2023-01-01",
            }
            for index in (1, 2)
        ]
        with mock.patch.object(budget_candidates, "_load_price_bands", return_value=[]), \
             mock.patch.object(budget_candidates.real_estate_search, "APARTMENT_MASTER", [parent, *children]), \
             mock.patch.object(budget_candidates.molit_transactions, "enabled", return_value=True), \
             mock.patch.object(
                 budget_candidates.molit_transactions,
                 "price_band_for_apartment",
                 return_value={
                     "areaLabel": "전용 60㎡",
                     "minPriceEok": 8.0,
                     "midPriceEok": 8.5,
                     "maxPriceEok": 9.0,
                     "latestDealPriceEok": 8.5,
                     "transactionCount": 1,
                     "latestDealDate": "2026-05-01",
                     "sourceNote": "국토부",
                 },
             ), \
             mock.patch.object(budget_candidates.molit_transactions, "last_error", return_value=""):
            budget_candidates._ENTITY_LOOKUP = None
            result = budget_candidates.budget_candidates(
                "12억", region="성남시", min_households="1000", all_matches=True,
            )
            child_matches = budget_candidates._find_entities("통합그랑메종1단지", "성남중원구")

        self.assertEqual({row["name"] for row in result["candidates"]}, {child["name"] for child in children})
        self.assertEqual([row["name"] for row in child_matches], ["통합그랑메종1단지"])


if __name__ == "__main__":
    unittest.main()
