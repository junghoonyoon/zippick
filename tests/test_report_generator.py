"""유료 리포트 생성기 회귀 테스트.

여기서 잡는 것은 계산 오류가 아니라 **의미를 거꾸로 읽는 사고**다.
실제로 `cashGapEok`(여유분)을 부족분으로 읽어서, 자금이 1.6억 남는 신축을
`1.6억 부족`으로 표시해 후보에서 빼고 가장 빠듯한 구축을 1순위로 올린 적이
있다. 숫자는 다 맞는데 결론만 정반대였다.
"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "수익화"))

import generate_report as gr  # noqa: E402


def candidate(name, price, required_cash, cash, score=70, **extra):
    """서버 응답 모양을 최소한으로 흉내낸다."""
    row = {
        "displayName": name,
        "name": name,
        "region": extra.pop("region", "노원구"),
        "recent3AveragePriceEok": price,
        "previous3AveragePriceEok": extra.pop("prior3", price),
        "latestDealPriceEok": extra.pop("latest", price),
        "minPriceEok": price * 0.9,
        "maxPriceEok": price * 1.1,
        "buildYear": extra.pop("buildYear", 2000),
        "policyImpact": {
            "requiredCashEok": required_cash,
            # 서버 정의: 보유현금 - 필요현금. 남으면 양수다.
            "cashGapEok": round(cash - required_cash, 2),
            "estimatedLoanLimitEok": price - required_cash,
        },
        "locationScore": {"score": score, "parts": []},
        "signals": {},
    }
    row.update(extra)
    return row


class CashSurplusTest(unittest.TestCase):
    def test_surplus_is_positive_when_cash_is_enough(self):
        c = candidate("여유단지", 5.0, required_cash=2.0, cash=3.0)
        self.assertAlmostEqual(gr._cash_surplus(c), 1.0)

    def test_surplus_is_negative_when_cash_is_short(self):
        c = candidate("부족단지", 6.0, required_cash=4.0, cash=3.0)
        self.assertAlmostEqual(gr._cash_surplus(c), -1.0)

    def test_cash_text_never_calls_surplus_a_shortfall(self):
        """여유를 `부족`이라고 쓰면 고객이 살 수 있는 집을 포기한다."""
        self.assertIn("여유", gr._cash_text(1.0))
        self.assertNotIn("부족", gr._cash_text(1.0))
        self.assertIn("부족", gr._cash_text(-1.0))
        self.assertNotIn("여유", gr._cash_text(-1.0))
        self.assertEqual(gr._cash_text(0.0), "딱 맞음")


class ClassifyTest(unittest.TestCase):
    def test_candidate_with_spare_cash_is_reachable(self):
        rich = candidate("자금여유", 4.2, required_cash=1.4, cash=3.0, score=67)
        reachable, reference, _cheap = gr.classify([rich], budget=6.2)

        self.assertIn(rich, reachable)
        self.assertEqual(reference, [])

    def test_candidate_short_on_cash_goes_to_reference(self):
        poor = candidate("자금부족", 6.0, required_cash=4.5, cash=3.0, score=90)
        reachable, reference, _cheap = gr.classify([poor], budget=6.2)

        self.assertEqual(reachable, [])
        self.assertIn(poor, reference)

    def test_small_shortfall_stays_reachable(self):
        """0.5억 이내는 가격 협상으로 닿는 범위로 본다."""
        near = candidate("살짝부족", 5.5, required_cash=3.3, cash=3.0)
        reachable, _reference, _cheap = gr.classify([near], budget=6.2)
        self.assertIn(near, reachable)

    def test_top_pick_is_not_the_tightest_one(self):
        """점수가 같다면 자금 여유가 큰 쪽이 앞에 와야 한다."""
        tight = candidate("빠듯", 5.4, required_cash=2.9, cash=3.0, score=70)
        roomy = candidate("여유", 4.2, required_cash=1.4, cash=3.0, score=70)
        reachable, _r, _c = gr.classify([tight, roomy], budget=6.2)

        self.assertEqual(reachable[0]["displayName"], "여유")

    def test_far_below_budget_is_dropped(self):
        """6.2억을 살 수 있는 사람에게 1.8억짜리는 후보가 아니다."""
        cheap = candidate("초저가", 1.8, required_cash=0.6, cash=3.0, score=95)
        normal = candidate("정상", 5.2, required_cash=2.4, cash=3.0, score=60)
        reachable, _reference, too_cheap = gr.classify([cheap, normal], budget=6.2)

        self.assertIn(cheap, too_cheap)
        self.assertIn(normal, reachable)


class BudgetUseTest(unittest.TestCase):
    """상한 6.2억인 사람에게 5.2억짜리를 1순위로 내밀면 1억을 왜 안 쓰는지
    설명이 있어야 한다."""

    def test_budget_use_percent(self):
        c = candidate("단지", 5.2, required_cash=2.0, cash=3.0)
        self.assertAlmostEqual(gr._budget_use(c, 6.2), 5.2 / 6.2 * 100, places=3)

    def test_note_appears_when_top_pick_leaves_budget_unused(self):
        low = candidate("저가1순위", 5.2, required_cash=2.0, cash=3.0, score=72)
        high = candidate("예산근접", 6.0, required_cash=3.0, cash=3.0, score=61)
        note = gr.budget_use_note([low, high], 6.2)

        self.assertIn("84%", note)
        self.assertIn("예산근접", note)
        self.assertIn("6.0억", note)

    def test_no_note_when_budget_is_well_used(self):
        top = candidate("예산근접", 6.0, required_cash=3.0, cash=3.0, score=72)
        self.assertEqual(gr.budget_use_note([top], 6.2), "")


class HeadlineTest(unittest.TestCase):
    def test_headline_mentions_surplus_not_shortage(self):
        top = candidate("1순위", 5.0, required_cash=2.0, cash=3.0, score=72)
        text = gr.headline_reason(top)

        self.assertIn("남아", text)
        self.assertNotIn("부족", text)

    def test_headline_explains_higher_scoring_exclusions(self):
        """표에 더 높은 점수가 보이는데 설명이 없으면 선정이 틀려 보인다."""
        top = candidate("1순위", 5.0, required_cash=2.0, cash=3.0, score=70)
        excluded = candidate("점수높음", 6.1, required_cash=4.2, cash=3.0, score=88)
        text = gr.headline_reason(top, None, [excluded])

        self.assertIn("점수높음", text)
        self.assertIn("88점", text)
        self.assertIn("살 수 없는 집은 후보가 아닙니다", text)


class PricePictureTest(unittest.TestCase):
    def test_anchor_uses_recent_three_months(self):
        c = candidate("단지", 5.2, required_cash=2.0, cash=3.0, prior3=4.7, latest=5.8)
        self.assertAlmostEqual(gr.price_picture(c)["anchor"], 5.2)

    def test_rising_market_estimate_is_above_recent_average(self):
        """신고 시차 때문에 오늘 값은 최근 3개월 평균보다 위여야 한다."""
        c = candidate("상승단지", 5.2, required_cash=2.0, cash=3.0, prior3=4.7, latest=5.8)
        guide = gr.asking_price_guide(c)

        self.assertGreater(guide["estimate"], 5.2)
        self.assertLessEqual(guide["estimate"], 6.0)

    def test_flat_market_estimate_stays_put(self):
        c = candidate("보합단지", 5.8, required_cash=2.0, cash=3.0, prior3=5.79, latest=5.8)
        guide = gr.asking_price_guide(c)
        self.assertAlmostEqual(guide["estimate"], 5.8, delta=0.15)

    def test_monthly_rate_is_capped(self):
        """폭등 구간에서 추정치가 무한히 튀어 오르면 안 된다."""
        c = candidate("폭등단지", 8.0, required_cash=2.0, cash=3.0, prior3=4.0, latest=8.0)
        guide = gr.asking_price_guide(c)

        self.assertLessEqual(guide["monthlyPct"], gr.MAX_MONTHLY_RATE * 100 + 1e-9)


if __name__ == "__main__":
    unittest.main()
