import datetime
import sys
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
                return [_deal(m, 1500) for m in (1, 2, 3, 7, 8, 9)]
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
        self.assertIsInstance(chaser["score"], int)
        self.assertGreater(chaser["districtRelativePct"], 0)
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
        self.assertEqual(signals["leaderBasis"], "district_households")
        self.assertFalse(signals["isRegionalLeader"])
        self.assertAlmostEqual(signals["leaderGapPct"], 25.0, delta=0.1)

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


if __name__ == "__main__":
    unittest.main()
