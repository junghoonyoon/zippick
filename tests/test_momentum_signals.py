import datetime
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import momentum_signals  # noqa: E402


def _deal(months_ago, ppsm, area=84.9):
    today = datetime.date.today()
    year, month = today.year, today.month - months_ago
    while month <= 0:
        year -= 1
        month += 12
    return {
        "dealDate": f"{year}-{month:02d}-15",
        "exclusiveArea": area,
        "dealAmountManwon": ppsm * area,
    }


def _rising_deals():
    # 직전 6개월(7~12개월 전) ㎡당 1000만원 x 4건, 최근 6개월 1100만원 x 6건
    return [_deal(m, 1000) for m in (7, 8, 9, 10)] + [_deal(m, 1100) for m in (1, 1, 2, 3, 4, 5)]


class MomentumSignalsTest(unittest.TestCase):
    def test_attach_signals_marks_unavailable_when_api_is_not_configured(self):
        candidates = [{"name": "설정없는단지", "region": "강동구"}]

        with mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=False):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["status"], "unavailable")
        self.assertIsNone(signals["score"])
        self.assertEqual(signals["scoreFormulaVersion"], momentum_signals.SCORE_FORMULA_VERSION)

    def test_attach_signals_calculates_candidate_raw_signals_in_parallel(self):
        candidates = [
            {"name": f"병렬후보{index}", "region": "테스트구"}
            for index in range(4)
        ]
        active = 0
        max_active = 0
        active_lock = threading.Lock()

        def slow_raw(*_args, **_kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with active_lock:
                active -= 1
            return {"status": "insufficient", "dealCount": 2}

        with mock.patch.object(
            momentum_signals.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            momentum_signals,
            "raw_signals",
            side_effect=slow_raw,
        ), mock.patch.object(
            momentum_signals,
            "_district_benchmark",
            return_value={"momentumPct": None, "count": 0},
        ), mock.patch.object(
            momentum_signals,
            "_absolute_leader",
            return_value=(None, None, None),
        ):
            momentum_signals.attach_signals(candidates)

        self.assertGreaterEqual(max_active, 2)
        self.assertTrue(all(row["signals"]["status"] == "insufficient" for row in candidates))

    def test_rising_complex_scores_positive_momentum(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=_rising_deals()):
            signals = momentum_signals.raw_signals("상승단지", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertAlmostEqual(signals["momentumPct"], 10.0, delta=0.2)
        self.assertEqual(signals["turnoverRatio"], 1.5)
        self.assertEqual(signals["recent3Pct"], 0.0)
        self.assertIsNotNone(signals["recoveryPct"])

    def test_insufficient_sample_gets_no_score(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=[_deal(1, 1000)] * 3):
            signals = momentum_signals.raw_signals("표본부족", region="강동구")
        self.assertEqual(signals["status"], "insufficient")

    def test_attach_signals_sets_leader_gap_and_badges(self):
        def fake_tx(name, **kwargs):
            if name == "대장":
                return (
                    [_deal(m, 1500) for m in (1, 2, 3, 4, 5, 6)]
                    + [_deal(m, 1200) for m in (7, 8, 9, 10, 11, 12)]
                )
            return _rising_deals()  # current ppsm ~1100 → 갭 약 27%

        candidates = [
            {"name": "대장", "region": "강동구", "households": 3000},
            {"name": "추격", "region": "강동구", "households": 1000},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", [
                 {"name": "대장", "district": "강동구", "households": 3000},
                 {"name": "추격", "district": "강동구", "households": 1000},
             ]), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        chaser = candidates[1]["signals"]
        self.assertEqual(chaser["status"], "ok")
        self.assertGreater(chaser["leaderGapPct"], 20)
        self.assertEqual(chaser["leaderName"], "대장")
        self.assertEqual(chaser["leaderRegion"], "강동구")
        self.assertFalse(chaser["isRegionalLeader"])
        self.assertEqual(chaser["leaderBasis"], "district_representative_area_adjusted_price_v8")
        self.assertEqual(chaser["leaderFormulaVersion"], momentum_signals.LEADER_FORMULA_VERSION)
        self.assertEqual(chaser["leaderPricePoints"], 100)
        self.assertEqual(chaser["leaderLeadershipPoints"], 100)
        self.assertIsNone(chaser["leaderStationPoints"])
        self.assertIsInstance(chaser["score"], int)
        self.assertAlmostEqual(chaser["districtRelativePct"], -15.0, delta=0.2)
        self.assertEqual(set(chaser["scoreBreakdown"]), {
            "priceMomentum", "turnover", "districtRelative", "recentPersistence",
        })
        kinds = {badge["kind"] for badge in chaser["badges"]}
        self.assertIn("momentum", kinds)
        self.assertIn("leaderGap", kinds)
        leader_badge = next(badge for badge in chaser["badges"] if badge["kind"] == "leaderGap")
        self.assertEqual(leader_badge["label"], "강동구 대장 대비 -27%")
        # 대장 단지 자신에게는 leaderGap이 없다
        self.assertIsNone(candidates[0]["signals"]["leaderGapPct"])
        self.assertTrue(candidates[0]["signals"]["isRegionalLeader"])

    def test_leader_is_fixed_from_entire_district_when_not_in_search_results(self):
        def fake_tx(name, **kwargs):
            if name == "구전체대장":
                return [_deal(m, 1600) for m in (1, 2, 3, 7, 8, 9)]
            return [_deal(m, 1200) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [{"name": "검색후보", "region": "강동구", "households": 2000}]
        district_master = [
            {"name": "구전체대장", "district": "강동구", "households": 5000},
            {"name": "검색후보", "district": "강동구", "households": 2000},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "구전체대장")
        self.assertEqual(signals["leaderHouseholds"], 5000)
        self.assertEqual(signals["leaderBasis"], "district_representative_area_adjusted_price_v8")
        self.assertFalse(signals["isRegionalLeader"])
        self.assertAlmostEqual(signals["leaderGapPct"], 25.0, delta=0.1)

    def test_leader_metadata_is_attached_for_every_candidate_signal_status(self):
        def fake_tx(name, **kwargs):
            if name == "조회실패":
                raise RuntimeError("temporary failure")
            if name == "표본부족":
                return [_deal(1, 1000)] * 3
            if name == "거래오래됨":
                return [_deal(m, 1100) for m in (5, 6, 7, 8, 9, 10)]
            return [_deal(m, 1500) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [
            {"name": "표본부족", "region": "강동구", "households": 800},
            {"name": "거래오래됨", "region": "강동구", "households": 900},
            {"name": "조회실패", "region": "강동구", "households": 1000},
        ]
        district_master = [
            {"name": "지역대장", "district": "강동구", "households": 3000},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        self.assertEqual(
            [row["signals"]["status"] for row in candidates],
            ["insufficient", "stale", "error"],
        )
        for row in candidates:
            signals = row["signals"]
            self.assertEqual(signals["leaderName"], "지역대장")
            self.assertEqual(signals["leaderRegion"], "강동구")
            self.assertFalse(signals["isRegionalLeader"])
            self.assertIsNone(signals.get("leaderGapPct"))

    def test_market_leader_is_not_just_the_largest_complex(self):
        def fake_tx(name, **kwargs):
            if name == "가격거래대장":
                return (
                    [_deal(m, 1600) for m in (1, 2, 3, 4, 5, 6)]
                    + [_deal(m, 1600) for m in (7, 8, 9, 10, 11, 12)]
                )
            return [_deal(m, 1200) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [{"name": "검색후보", "region": "강동구", "households": 800}]
        district_master = [
            {"name": "최대세대수", "district": "강동구", "households": 5000},
            {"name": "가격거래대장", "district": "강동구", "households": 1000},
            {"name": "검색후보", "district": "강동구", "households": 800},
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "가격거래대장")
        self.assertEqual(signals["leaderHouseholds"], 1000)
        self.assertEqual(signals["leaderPricePoints"], 100)
        self.assertEqual(signals["leaderLiquidityPoints"], 100)
        self.assertGreater(signals["leaderScore"], 80)

    def test_locality_general_leader_includes_wide_representative_complex(self):
        def fake_tx(name, **kwargs):
            if name == "한양아파트":
                return [_deal(m, 2700) for m in range(1, 13) for _ in range(2)]
            if name == "파크뷰":
                return [_deal(m, 2200, area=139.7) for m in (1, 2, 3, 4, 7, 8, 9, 10)]
            return [_deal(m, 1800) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [{
            "name": "정자동후보",
            "region": "성남분당구",
            "legalDong": "정자동",
            "households": 800,
        }]
        district_master = [
            {
                "name": "한양아파트",
                "district": "성남분당구",
                "legalDong": "서현동",
                "households": 2419,
            },
            {
                "name": "파크뷰",
                "aliases": ["정자동 파크뷰"],
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 1829,
            },
            {
                "name": "정자동후보",
                "district": "성남분당구",
                "legalDong": "정자동",
                "households": 800,
            },
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "파크뷰")
        self.assertEqual(signals["leaderRegion"], "정자동")
        self.assertEqual(signals["leaderBasis"], "locality_representative_area_adjusted_price_v8")
        self.assertFalse(signals["isRegionalLeader"])

    def test_common_adjustment_target_does_not_change_price_order(self):
        small = {"exclusiveArea": 59.8, "dealAmountManwon": 150000}
        large = {"exclusiveArea": 84.8, "dealAmountManwon": 190000}
        order_at_59 = momentum_signals.apartment_leaders._leader_adjusted_price(small, 59) > momentum_signals.apartment_leaders._leader_adjusted_price(large, 59)
        order_at_84 = momentum_signals.apartment_leaders._leader_adjusted_price(small, 84) > momentum_signals.apartment_leaders._leader_adjusted_price(large, 84)

        self.assertEqual(order_at_59, order_at_84)

    def test_leader_reference_price_uses_most_traded_representative_area_band(self):
        deals = [
            _deal(1, 3000, area=84.9),
            _deal(2, 2900, area=84.9),
            _deal(1, 2100, area=139.7),
            _deal(2, 2200, area=139.7),
            _deal(3, 2150, area=139.7),
        ]

        ppsm, area_band, count = momentum_signals._leader_reference_price(deals)

        self.assertEqual(ppsm, 2150)
        self.assertEqual(area_band, 13)
        self.assertEqual(count, 3)

    def test_locality_leader_excludes_other_dong_and_presale(self):
        def fake_tx(name, **kwargs):
            prices = {
                "다른동고가": 4000,
                "같은동분양권": 5000,
                "같은동준공대장": 2500,
                "검색후보": 1800,
            }
            return [_deal(m, prices[name]) for m in (1, 2, 3, 7, 8, 9)]

        candidates = [{
            "name": "검색후보",
            "region": "테스트구",
            "legalDong": "가동",
            "households": 800,
        }]
        master = [
            {
                "name": "다른동고가",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 3000,
            },
            {
                "name": "같은동분양권",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 2500,
                "status": "분양권",
            },
            {
                "name": "같은동준공대장",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 1200,
            },
            {
                "name": "검색후보",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 800,
            },
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "같은동준공대장")
        self.assertEqual(signals["leaderRegion"], "가동")
        self.assertEqual(signals["leaderCandidateCount"], 2)

    def test_attach_signals_includes_distinct_district_leader(self):
        def fake_tx(name, **kwargs):
            prices = {
                "검색후보": 1800,
                "가동대장": 2400,
                "나동구대장": 3200,
            }
            return [_deal(month, prices[name]) for month in (1, 2, 3, 7, 8, 9)]

        candidates = [{
            "name": "검색후보",
            "region": "테스트구",
            "legalDong": "가동",
            "households": 800,
        }]
        master = [
            {
                "name": "검색후보",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 800,
            },
            {
                "name": "가동대장",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 1200,
            },
            {
                "name": "나동구대장",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 2000,
            },
        ]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["leaderName"], "가동대장")
        self.assertEqual(signals["leaderRegion"], "가동")
        self.assertEqual(signals["districtLeaderName"], "나동구대장")
        self.assertEqual(signals["districtLeaderRegion"], "테스트구")
        self.assertEqual(signals["districtLeaderBasis"], "district_representative_area_adjusted_price_v8")
        self.assertFalse(signals["isDistrictLeader"])

    def test_locality_leader_considers_all_eligible_complexes(self):
        master = [
            {
                "name": f"대단지{index}",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 2000 - index,
            }
            for index in range(20)
        ] + [{
            "name": "고가중형단지",
            "district": "테스트구",
            "legalDong": "가동",
            "households": 300,
        }]

        def fake_tx(name, **kwargs):
            ppsm = 4000 if name == "고가중형단지" else 1500
            return [_deal(m, ppsm) for m in (1, 2, 3, 7, 8, 9)]

        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_INDEX", None), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_ENTITY_SIGNALS_CACHE", {}):
            entity, _signals, details = momentum_signals._absolute_leader(
                "테스트구",
                [],
                legal_dong="가동",
            )

        self.assertEqual(entity["name"], "고가중형단지")
        self.assertEqual(details["candidateCount"], 21)

    def test_large_cheap_complex_cannot_beat_clear_price_leader(self):
        master = [
            {
                "name": "가격대장",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 800,
            },
            {
                "name": "대형저가단지",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 3000,
            },
        ]

        def fake_tx(name, **kwargs):
            ppsm = 2000 if name == "가격대장" else 1200
            months = (1, 2, 3, 4, 7, 8, 9, 10) if name == "가격대장" else range(1, 13)
            return [_deal(month, ppsm) for month in months]

        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", master), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_INDEX", None), \
             mock.patch.object(momentum_signals, "_LEADER_SCOPE_ENTITY_SIGNALS_CACHE", {}):
            entity, _signals, details = momentum_signals._absolute_leader(
                "테스트구",
                [],
                legal_dong="가동",
            )

        self.assertEqual(entity["name"], "가격대장")
        self.assertEqual(details["eligibleCandidateCount"], 2)
        self.assertIsNone(details["priceFinalistCount"])

    def test_missing_metrics_are_scored_neutral_not_zero(self):
        # 결측 항목은 0점(최악)이 아니라 중립값으로 간주한다.
        # momentum 만점 40 + 거래량 중립 8 + 구 비교 중립 10 + 지속성 중립 8 = 66.
        # 결측을 만점 기준으로 재정규화해 100점이 되지도 않아야 한다.
        signals = {"status": "ok", "momentumPct": 10.0, "turnoverRatio": None,
                   "districtRelativePct": None, "recent3Pct": None}
        details = momentum_signals._score_details(signals)
        self.assertEqual(details["score"], 66)
        district = details["breakdown"]["districtRelative"]
        self.assertFalse(district["available"])
        self.assertTrue(district["neutral"])
        self.assertEqual(district["points"], 10)

    def test_full_strength_scores_100(self):
        signals = {"status": "ok", "momentumPct": 10.0, "turnoverRatio": 2.0,
                   "districtRelativePct": 5.0, "recent3Pct": 5.0}
        details = momentum_signals._score_details(signals)
        self.assertEqual(details["score"], 100)
        self.assertEqual(details["rawScore"], 100)
        self.assertEqual(sum(row["points"] for row in details["breakdown"].values()), 100)

    def test_no_recent_rise_caps_score_at_69(self):
        signals = {"status": "ok", "momentumPct": 10.0, "turnoverRatio": 2.0,
                   "districtRelativePct": 5.0, "recent3Pct": None}
        details = momentum_signals._score_details(signals)
        self.assertEqual(details["rawScore"], 93)  # 85 + 지속성 중립 8
        self.assertEqual(details["score"], 69)
        self.assertIn("recent_rise_unconfirmed", {item["code"] for item in details["caps"]})

    def test_weak_price_and_volume_caps_score_at_44(self):
        signals = {"status": "ok", "momentumPct": 0.0, "turnoverRatio": 1.0,
                   "districtRelativePct": 5.0, "recent3Pct": 5.0}
        details = momentum_signals._score_details(signals)
        self.assertEqual(details["score"], 44)
        self.assertIn("price_and_volume_weak", {item["code"] for item in details["caps"]})

    def test_area_mix_shift_does_not_fake_momentum(self):
        # 직전 6개월엔 59㎡(㎡당 1300), 최근 6개월엔 84㎡(㎡당 1000)만 거래.
        # 단지 시세는 평형별로 전혀 안 움직였는데, 전체 평균 비교면
        # ㎡당가가 -23% 하락한 것처럼 보인다. 밴드 매칭은 겹치는 평형이
        # 없으므로 전체 중앙값 폴백 + matched=False로 표시해야 한다.
        deals = [_deal(m, 1300, area=59.9) for m in (7, 8, 9, 10)] \
              + [_deal(m, 1000, area=84.9) for m in (1, 2, 3, 4)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("평형혼합", region="강동구")
        self.assertFalse(signals["momentumBandMatched"])

        # 같은 평형(84㎡) 거래가 양쪽에 있으면 그 평형끼리만 비교한다.
        # 59㎡ 고가 거래가 직전 구간에 섞여도 momentum은 84㎡ 기준 +10%.
        deals = [_deal(m, 1300, area=59.9) for m in (7, 8)] \
              + [_deal(m, 1000, area=84.9) for m in (7, 8, 9)] \
              + [_deal(m, 1100, area=84.9) for m in (1, 2, 3)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("평형매칭", region="강동구")
        self.assertTrue(signals["momentumBandMatched"])
        self.assertAlmostEqual(signals["momentumPct"], 10.0, delta=0.2)

    def test_current_partial_month_is_excluded_from_windows(self):
        # 진행 중인 달(m=0)의 거래는 신고 지연으로 과소 집계되므로
        # 최근/직전 비교 창 어디에도 포함되면 안 된다.
        deals = _rising_deals() + [_deal(0, 1100), _deal(0, 1100)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("이번달거래", region="강동구")
        self.assertEqual(signals["recentDealCount"], 6)
        self.assertEqual(signals["priorDealCount"], 4)
        self.assertAlmostEqual(signals["momentumPct"], 10.0, delta=0.2)

    def test_recent_surge_sets_warning_flag_and_badge(self):
        # 최근 3개월 +12% 급등 → isRecentSurge와 급등 배지.
        deals = [_deal(m, 1000) for m in (7, 8, 9)] \
              + [_deal(m, 1000) for m in (4, 5, 6)] \
              + [_deal(m, 1120) for m in (1, 2, 3)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("급등단지", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertGreaterEqual(signals["recent3Pct"], 10.0)
        self.assertTrue(signals["isRecentSurge"])
        kinds = {badge["kind"] for badge in momentum_signals._badges(signals)}
        self.assertIn("surge", kinds)

    def test_moderate_rise_does_not_trigger_surge(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=_rising_deals()):
            signals = momentum_signals.raw_signals("완만상승", region="강동구")
        self.assertFalse(signals["isRecentSurge"])

    def test_steady_rise_pattern(self):
        # 10개월 연속, 월 2건씩, 매달 약 +1%씩 계단식 상승 → 꾸준한 상승.
        deals = []
        for m in range(1, 11):
            ppsm = round(1000 * (1.01 ** (10 - m)), 1)
            deals += [_deal(m, ppsm), _deal(m, ppsm)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("계단상승", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertFalse(signals["isRecentSurge"])
        self.assertEqual(signals["risePattern"], "steady_rise")
        self.assertEqual(signals["patternUpCount"], signals["patternChangeCount"])
        kinds = {badge["kind"] for badge in momentum_signals._badges(signals)}
        self.assertIn("pattern", kinds)

    def test_choppy_pattern(self):
        # 매달 ±5%씩 출렁이는 시장 → 등락 반복.
        deals = []
        for m in range(1, 11):
            ppsm = 1050 if m % 2 else 1000
            deals += [_deal(m, ppsm), _deal(m, ppsm)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("등락반복", region="강동구")
        self.assertEqual(signals["risePattern"], "choppy")

    def test_sparse_months_get_no_pattern(self):
        # 월 1건씩이면 유효 월이 없어 패턴을 판정하지 않는다.
        deals = [_deal(m, 1000) for m in (1, 2, 3, 4, 5, 6, 7, 8, 9)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("표본희소", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertIsNone(signals["risePattern"])

    def test_turnover_smoothing_discounts_small_samples(self):
        # 2건→4건과 20건→40건은 원시 배수가 똑같이 2.0이지만,
        # 점수에 쓰는 스무딩 배수는 소표본일수록 1에 가깝게 눌려야 한다.
        small = {"status": "ok", "momentumPct": 0.0, "turnoverRatio": 2.0,
                 "turnoverSmoothed": round((4 + 3) / (2 + 3), 2),
                 "districtRelativePct": None, "recent3Pct": None}
        large = {"status": "ok", "momentumPct": 0.0, "turnoverRatio": 2.0,
                 "turnoverSmoothed": round((40 + 3) / (20 + 3), 2),
                 "districtRelativePct": None, "recent3Pct": None}
        small_points = momentum_signals._score_details(small)["breakdown"]["turnover"]["points"]
        large_points = momentum_signals._score_details(large)["breakdown"]["turnover"]["points"]
        self.assertLess(small_points, large_points)
        self.assertEqual(large_points, 23)  # 1.87배 → 만점(25)에 근접하되 미달

    def test_raw_signals_reports_smoothed_turnover_and_confidence(self):
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=_rising_deals()):
            signals = momentum_signals.raw_signals("상승단지", region="강동구")
        # 최근 6건, 직전 4건 → 스무딩 (6+3)/(4+3)
        self.assertAlmostEqual(signals["turnoverSmoothed"], 1.29, delta=0.01)
        # 12개월 창 10건 → 신뢰도 낮음
        self.assertEqual(signals["sampleConfidence"], "low")

    def test_sample_confidence_tiers(self):
        # 12개월 창 32건 + 평형 매칭 → 높음
        deals = [_deal(m, 1000) for m in (7, 8, 9, 10, 11, 12) for _ in range(3)] \
              + [_deal(m, 1050) for m in (1, 2, 3, 4, 5, 6) for _ in range(3)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("대단지", region="강동구")
        self.assertEqual(signals["sampleConfidence"], "high")

    def test_price_outlier_is_excluded_from_score(self):
        # 84㎡ 정상 거래 10건(㎡당 1000~1100) 사이에 시세 -40%짜리
        # '중개거래 신고' 특수거래 1건. 중앙값 ±30% 필터로 제외돼야 하고,
        # momentum은 정상 거래 기준 +10%를 유지해야 한다.
        deals = _rising_deals() + [_deal(1, 600)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("이상치포함", region="강동구")
        self.assertEqual(signals["status"], "ok")
        self.assertEqual(signals["outlierExcludedCount"], 1)
        self.assertEqual(signals["dealCount"], 10)
        self.assertAlmostEqual(signals["momentumPct"], 10.0, delta=0.2)

    def test_sustained_price_level_shift_is_not_filtered_as_an_outlier(self):
        # 직전 6개월 대비 최근 6개월 가격이 크게 올랐어도 최근 거래가 여러 건
        # 같은 수준에서 체결됐다면 시장 변화이지 이상거래가 아니다.
        deals = (
            [_deal(m, 1000) for m in (7, 8, 9, 10, 11, 12)]
            + [_deal(m, 1700) for m in (1, 1, 2, 2, 3, 3, 4, 5, 6)]
        )
        with mock.patch.object(
            momentum_signals.molit_transactions,
            "transactions_for_apartment",
            return_value=deals,
        ):
            signals = momentum_signals.raw_signals("급격한가격상승", region="분당구")

        self.assertEqual(signals["status"], "ok")
        self.assertEqual(signals["outlierExcludedCount"], 0)
        self.assertEqual(signals["latestDealDate"], _deal(1, 1700)["dealDate"])
        self.assertAlmostEqual(signals["momentumPct"], 70.0, delta=0.2)

    def test_small_band_sample_is_not_outlier_filtered(self):
        # 표본 5건 미만 밴드는 무엇이 정상가인지 판별이 불안정하므로 필터하지 않는다.
        deals = [_deal(m, 1000) for m in (1, 2, 7)] + [_deal(3, 600)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("소표본", region="강동구")
        self.assertEqual(signals["outlierExcludedCount"], 0)

    def test_outlier_does_not_distort_peak_recovery(self):
        # 이상 고가 1건이 월별 중앙값의 전고점이 되면 recoveryPct가 왜곡된다.
        # 필터 후에는 정상 거래만으로 고점을 계산해 회복률 100% 부근이어야 한다.
        deals = [_deal(m, 1000) for m in (1, 2, 3, 7, 8, 9, 10)] + [_deal(5, 1500)]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", return_value=deals):
            signals = momentum_signals.raw_signals("고점왜곡", region="강동구")
        self.assertEqual(signals["outlierExcludedCount"], 1)
        self.assertGreaterEqual(signals["recoveryPct"], 99.0)

    def test_district_relative_uses_fixed_benchmark_not_search_results(self):
        # 구 마스터에 대표 단지 3곳(전부 보합) + 검색 후보 1곳(+10%).
        # 검색 결과에 무엇이 잡히든 기준은 대표 단지 중앙값(0%)이어야 한다.
        def fake_tx(name, **kwargs):
            if name == "검색후보":
                return _rising_deals()
            return [_deal(m, 1200) for m in (1, 2, 3, 7, 8, 9)]

        district_master = [
            {"name": "대표1", "district": "강동구", "households": 5000},
            {"name": "대표2", "district": "강동구", "households": 4000},
            {"name": "대표3", "district": "강동구", "households": 3000},
            {"name": "검색후보", "district": "강동구", "households": 1000},
        ]
        candidates = [{"name": "검색후보", "region": "강동구", "households": 1000}]
        with mock.patch.object(momentum_signals.molit_transactions, "transactions_for_apartment", side_effect=fake_tx), \
             mock.patch.object(momentum_signals.molit_transactions, "configured", return_value=True), \
             mock.patch.object(momentum_signals.real_estate_search, "APARTMENT_MASTER", district_master), \
             mock.patch.object(momentum_signals, "_DISTRICT_LEADER_INDEX", None), \
             mock.patch.object(momentum_signals, "_DISTRICT_MOMENTUM_CACHE", {}), \
             mock.patch.object(momentum_signals, "_DISTRICT_ENTITY_SIGNALS_CACHE", {}):
            momentum_signals.attach_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["districtBasis"], "district_top_households")
        self.assertGreaterEqual(signals["districtComparisonCount"], 3)
        self.assertAlmostEqual(signals["districtMomentumPct"], 0.0, delta=0.2)
        self.assertAlmostEqual(signals["districtRelativePct"], 10.0, delta=0.4)

    def test_peak_and_leader_discount_do_not_change_score(self):
        base = {"status": "ok", "momentumPct": 5.0, "turnoverRatio": 1.5,
                "districtRelativePct": 2.0, "recent3Pct": 2.0}
        discounted = {**base, "leaderGapPct": 30.0, "recoveryPct": 70.0}
        expensive = {**base, "leaderGapPct": 0.0, "recoveryPct": 100.0}
        self.assertEqual(
            momentum_signals._composite_score(discounted),
            momentum_signals._composite_score(expensive),
        )

    def test_district_index_sources_use_fixed_large_complexes(self):
        district_index = {
            momentum_signals.real_estate_search.compact("성남시 수정구"): [
                {"name": "대형단지", "district": "성남시 수정구", "households": 3000},
                {"name": "검색단지", "district": "성남시 수정구", "households": 2000},
            ],
        }
        with mock.patch.object(
            momentum_signals,
            "_district_leader_index",
            return_value=district_index,
        ):
            rows = momentum_signals.district_index_source_candidates(
                "경기도 성남시 수정구 산성동",
                exclude_name="검색단지",
            )

        self.assertEqual(rows, [{
            "name": "대형단지",
            "region": "성남시 수정구",
            "households": 3000,
        }])

    def test_cached_signal_attachment_never_calls_live_transaction_loader(self):
        candidates = [{"name": "캐시단지", "region": "강동구", "households": 1000}]
        with mock.patch.object(
            momentum_signals.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            momentum_signals.molit_transactions,
            "transactions_for_apartment_cached",
            return_value=_rising_deals(),
        ) as cached, mock.patch.object(
            momentum_signals.molit_transactions,
            "transactions_for_apartment",
            side_effect=AssertionError("live loader must not run"),
        ) as live:
            momentum_signals.attach_cached_signals(candidates)

        signals = candidates[0]["signals"]
        self.assertEqual(signals["status"], "ok")
        self.assertIsInstance(signals["score"], int)
        self.assertEqual(
            signals["scoreFormulaVersion"],
            momentum_signals.SCORE_FORMULA_VERSION,
        )
        cached.assert_called_once_with(
            "캐시단지",
            region="강동구",
            area_label="",
            lookback_months=momentum_signals.LOOKBACK_MONTHS,
        )
        live.assert_not_called()

    def test_cached_signal_attachment_uses_selected_area(self):
        candidates = [{
            "name": "평형단지",
            "region": "강동구",
            "areaLabel": "전용 84~85㎡",
            "households": 1000,
        }]
        with mock.patch.object(
            momentum_signals.molit_transactions,
            "configured",
            return_value=True,
        ), mock.patch.object(
            momentum_signals.molit_transactions,
            "transactions_for_apartment_cached",
            return_value=_rising_deals(),
        ) as cached:
            momentum_signals.attach_cached_signals(candidates)

        cached.assert_called_once_with(
            "평형단지",
            region="강동구",
            area_label="전용 84~85㎡",
            lookback_months=momentum_signals.LOOKBACK_MONTHS,
        )


if __name__ == "__main__":
    unittest.main()
