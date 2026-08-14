import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "앱화면" / "real-estate-search.html"


def _function_body(html, name):
    start = html.index(f"function {name}(")
    depth = 0
    for index in range(html.index("{", start), len(html)):
        if html[index] == "{":
            depth += 1
        elif html[index] == "}":
            depth -= 1
            if depth == 0:
                return html[start:index + 1]
    raise ValueError(f"{name} 본문을 찾지 못했어요")


class VerdictCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_verdict_card_is_not_rendered_in_the_score_table(self):
        body = _function_body(self.html, "locationScoreSheetHtml")
        self.assertNotIn("verdictCardHtml(item)", body)
        self.assertIn('class="location-score-hero"', body)

    def test_verdict_card_renders_inside_the_zippick_report(self):
        wrapper = _function_body(self.html, "zippickBreakevenHtml")
        report = _function_body(self.html, "candidateZippickReportHtml")
        self.assertIn("const card = verdictCardHtml(item);", wrapper)
        self.assertIn('aria-label="본전 상승률"', wrapper)
        self.assertIn("${zippickBreakevenHtml(item)}", report)
        self.assertLess(
            report.index("${zippickFundingHtml(item)}"),
            report.index("${zippickBreakevenHtml(item)}"),
        )

    def test_card_is_hidden_when_breakeven_is_missing(self):
        body = _function_body(self.html, "verdictCardHtml")
        self.assertIn('card.status !== "ok" || !card.breakeven', body)
        self.assertIn('return ""', body)

    def test_track_record_block_is_hidden_when_sample_is_missing(self):
        body = _function_body(self.html, "verdictRecordHtml")
        self.assertIn('record.status !== "ok"', body)
        self.assertIn('record.reason === "no_move_out_nearby"', body)

    def test_track_record_shows_counts_not_a_percentage(self):
        body = _function_body(self.html, "verdictRecordHtml")
        self.assertIn("record.outperformed", body)
        self.assertIn("record.total", body)
        # 비율은 확률로 오해되기 쉬워서 화면에 쓰지 않는다.
        self.assertNotIn("%`", body)
        self.assertNotIn("Percent", body.replace("worstDropPercent", ""))

    def test_estimated_amounts_are_marked(self):
        body = _function_body(self.html, "verdictCardHtml")
        self.assertIn("entry.estimated", body)
        self.assertIn("(약)", body)

    def test_card_never_promises_a_future_price(self):
        body = _function_body(self.html, "verdictCardHtml")
        self.assertIn("앞으로 오른다는 뜻이 아니에요", body)
        for banned in ("오를 거예요", "상승 예상", "예상 시세"):
            self.assertNotIn(banned, body)

    def test_excluded_costs_are_shown_to_the_user(self):
        body = _function_body(self.html, "verdictCardHtml")
        self.assertIn("breakeven.excludes", body)
        self.assertIn("breakeven.uncertainItems", body)

    def test_money_text_rounds_to_manwon(self):
        body = _function_body(self.html, "verdictMoneyText")
        self.assertIn("Math.round", body)
        self.assertIn("toLocaleString", body)

    def test_dot_chart_is_capped_and_labelled(self):
        body = _function_body(self.html, "verdictDotsHtml")
        self.assertIn("Math.min(60", body)
        self.assertIn('role="img"', body)
        self.assertIn("aria-label", body)

    def test_card_styles_exist(self):
        for selector in (
            ".verdict-card {",
            ".verdict-headline {",
            ".verdict-cost {",
            ".verdict-dots i.is-hit",
            ".verdict-risk {",
            ".verdict-pending {",
        ):
            self.assertIn(selector, self.html, selector)


if __name__ == "__main__":
    unittest.main()
