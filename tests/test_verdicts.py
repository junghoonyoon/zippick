import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import verdicts  # noqa: E402


def _row(signal_overrides=None, **kwargs):
    signals = {
        "status": "ok", "score": 50, "currentPpsm": 1000,
        "momentumPct": 1.0, "turnoverRatio": 1.0, "recoveryPct": 90,
        "priceSpreadPct": 20.0, "isAtPeak": False, "isAtTrough": False,
        "priceLevelMonth": None,
    }
    signals.update(signal_overrides or {})
    base = {"name": "단지", "midPriceEok": 9.0, "signals": signals}
    base.update(kwargs)
    return base


class VerdictsTest(unittest.TestCase):
    def test_rollback_price_names_the_month(self):
        row = _row({"priceLevelMonth": "2025-01", "recoveryPct": 83.0})
        verdicts.attach_verdicts([row], budget_eok=10)
        self.assertIn("2025년 1월", row["verdict"])
        self.assertIn("17% 낮게", row["verdict"])

    def test_peak_zone_warns_new_high(self):
        row = _row({"isAtPeak": True, "recoveryPct": 99.0})
        verdicts.attach_verdicts([row], budget_eok=10)
        self.assertIn("신고가", row["verdict"])

    def test_trough_zone_asks_falling_or_bargain(self):
        row = _row({"isAtTrough": True, "recoveryPct": 70.0})
        verdicts.attach_verdicts([row], budget_eok=10)
        self.assertIn("가장 낮은 구간", row["verdict"])

    def test_flat_market_redirects_to_negotiation(self):
        row = _row({"priceSpreadPct": 3.0})
        verdicts.attach_verdicts([row], budget_eok=10)
        self.assertIn("협상", row["verdict"])

    def test_rank_suffix_appended_to_time_context(self):
        rows = [
            _row({"priceLevelMonth": "2025-01", "recoveryPct": 85.0, "score": 90, "currentPpsm": 900}, name="일위"),
            _row({"score": 40, "currentPpsm": 1000}, name="이위"),
            _row({"score": 30, "currentPpsm": 1200}, name="삼위"),
        ]
        verdicts.attach_verdicts(rows, budget_eok=20)
        self.assertIn("최근 가격·거래 흐름 1위", rows[0]["verdict"])
        self.assertIn("2025년 1월", rows[0]["verdict"])

    def test_rank_only_when_no_time_context(self):
        rows = [
            _row({"currentPpsm": 800, "score": 10}, name="싼곳"),
            _row({"currentPpsm": 1000, "score": 20}, name="중간"),
            _row({"currentPpsm": 1200, "score": 30}, name="비싼곳"),
        ]
        verdicts.attach_verdicts(rows, budget_eok=20)
        self.assertIn("면적 효율 1위", rows[0]["verdict"])

    def test_insufficient_sample_message(self):
        row = _row({"status": "insufficient", "score": None, "currentPpsm": None})
        verdicts.attach_verdicts([row], budget_eok=20)
        self.assertIn("표본", row["verdict"])

    def test_funding_facts_never_repeated(self):
        # 정책 박스에 이미 있는 추가 자금 문구는 verdict에 나오면 안 됨
        row = _row({"priceLevelMonth": "2024-09", "recoveryPct": 80.0},
                   policyImpact={"status": "short", "cashGapEok": 0.05})
        verdicts.attach_verdicts([row], budget_eok=10)
        self.assertNotIn("자금", row["verdict"])
        self.assertIn("2024년 9월", row["verdict"])


if __name__ == "__main__":
    unittest.main()
