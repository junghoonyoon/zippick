from __future__ import annotations

from math import ceil
from pathlib import Path

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "집픽_39000원_매수의견_리포트_샘플.pdf"
FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"

PAGE_W, PAGE_H = A4
MARGIN_X = 46
CONTENT_W = PAGE_W - MARGIN_X * 2

NAVY = HexColor("#17223B")
BLUE = HexColor("#2864DC")
BLUE_DARK = HexColor("#1947A3")
BLUE_LIGHT = HexColor("#EAF1FF")
CYAN_LIGHT = HexColor("#EEF8FA")
GREEN = HexColor("#16805B")
GREEN_LIGHT = HexColor("#E9F7F1")
AMBER = HexColor("#B66B10")
AMBER_LIGHT = HexColor("#FFF4DF")
RED = HexColor("#C74848")
RED_LIGHT = HexColor("#FDEEEE")
TEXT = HexColor("#202938")
MUTED = HexColor("#657083")
LINE = HexColor("#DCE2EA")
CANVAS = HexColor("#F4F6F9")
WHITE = HexColor("#FFFFFF")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Korean", FONT_PATH))


def text_width(text: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, "Korean", size)


def draw_text(
    c: Canvas,
    x: float,
    y: float,
    text: str,
    size: float = 10,
    color: Color = TEXT,
    bold: bool = False,
    align: str = "left",
) -> None:
    c.setFont("Korean", size)
    c.setFillColor(color)
    width = text_width(text, size)
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2
    c.drawString(x, y, text)
    if bold:
        c.drawString(x + 0.22, y, text)


def wrap_lines(text: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        proposed = word if not current else f"{current} {word}"
        if text_width(proposed, size) <= width:
            current = proposed
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    c: Canvas,
    x: float,
    y: float,
    text: str,
    width: float,
    size: float = 10,
    leading: float | None = None,
    color: Color = TEXT,
    bold: bool = False,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.55
    lines = wrap_lines(text, size, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        draw_text(c, x, y, line, size=size, color=color, bold=bold)
        y -= leading
    return y


def round_rect(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: Color = WHITE,
    stroke: Color | None = LINE,
    radius: float = 12,
) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1 if stroke else 0)


def pill(c: Canvas, x: float, y: float, text: str, fill: Color, color: Color, w: float | None = None) -> float:
    width = w or text_width(text, 8.5) + 18
    round_rect(c, x, y, width, 22, fill=fill, stroke=None, radius=11)
    draw_text(c, x + width / 2, y + 7, text, 8.5, color=color, bold=True, align="center")
    return width


def section_title(c: Canvas, y: float, kicker: str, title: str, subtitle: str | None = None) -> float:
    draw_text(c, MARGIN_X, y, kicker, 8.5, BLUE, bold=True)
    y -= 27
    draw_text(c, MARGIN_X, y, title, 20, NAVY, bold=True)
    y -= 23
    if subtitle:
        y = draw_paragraph(c, MARGIN_X, y, subtitle, CONTENT_W, 9.5, 15, MUTED)
    return y - 10


def header(c: Canvas, page_num: int, section: str) -> None:
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    draw_text(c, MARGIN_X, PAGE_H - 30, "집픽", 11, BLUE, bold=True)
    draw_text(c, MARGIN_X + 38, PAGE_H - 30, section, 8, MUTED)
    draw_text(c, PAGE_W - MARGIN_X, PAGE_H - 30, f"{page_num:02d}", 8.5, MUTED, align="right")
    c.setStrokeColor(LINE)
    c.line(MARGIN_X, PAGE_H - 40, PAGE_W - MARGIN_X, PAGE_H - 40)
    pill(c, PAGE_W - MARGIN_X - 87, 20, "시연용 가상 데이터", AMBER_LIGHT, AMBER, 87)


def page_footer(c: Canvas, text: str = "분석 기준 2026.07.29 · 유효기간 14일") -> None:
    draw_text(c, MARGIN_X, 28, text, 7.5, MUTED)


def bullet(c: Canvas, x: float, y: float, text: str, width: float, color: Color = TEXT, size: float = 9.5) -> float:
    c.setFillColor(BLUE)
    c.circle(x + 3, y + 4, 2.1, fill=1, stroke=0)
    return draw_paragraph(c, x + 14, y, text, width - 14, size, size * 1.5, color)


def score_bar(c: Canvas, x: float, y: float, w: float, score: int, color: Color = BLUE) -> None:
    c.setFillColor(LINE)
    c.roundRect(x, y, w, 7, 3.5, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, y, w * score / 100, 7, 3.5, fill=1, stroke=0)


def money_bar(c: Canvas, x: float, y: float, w: float, label: str, value: float, max_value: float, color: Color) -> None:
    draw_text(c, x, y + 10, label, 8.5, MUTED)
    draw_text(c, x + w, y + 10, f"{value:.2f}억", 9.5, TEXT, bold=True, align="right")
    c.setFillColor(LINE)
    c.roundRect(x, y - 5, w, 9, 4.5, fill=1, stroke=0)
    c.setFillColor(color)
    c.roundRect(x, y - 5, min(w, w * value / max_value), 9, 4.5, fill=1, stroke=0)


def line_chart(c: Canvas, x: float, y: float, w: float, h: float, values: list[float], color: Color = BLUE) -> None:
    lo = min(values) - 0.08
    hi = max(values) + 0.08
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    for i in range(4):
        yy = y + i * h / 3
        c.line(x, yy, x + w, yy)
    pts: list[tuple[float, float]] = []
    for i, value in enumerate(values):
        px = x + i * w / (len(values) - 1)
        py = y + (value - lo) / (hi - lo) * h
        pts.append((px, py))
    c.setStrokeColor(color)
    c.setLineWidth(2)
    p = c.beginPath()
    p.moveTo(*pts[0])
    for px, py in pts[1:]:
        p.lineTo(px, py)
    c.drawPath(p, stroke=1, fill=0)
    c.setFillColor(color)
    for px, py in pts:
        c.circle(px, py, 2.7, fill=1, stroke=0)
    labels = ["2월", "3월", "4월", "5월", "6월", "7월"]
    for i, label in enumerate(labels):
        draw_text(c, x + i * w / 5, y - 15, label, 7.5, MUTED, align="center")


def key_value(c: Canvas, x: float, y: float, label: str, value: str, w: float, accent: Color | None = None) -> None:
    draw_text(c, x, y, label, 8.5, MUTED)
    draw_text(c, x + w, y, value, 10.5, accent or TEXT, bold=True, align="right")


def cover(c: Canvas) -> None:
    c.setFillColor(CANVAS)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 265, PAGE_W, 265, fill=1, stroke=0)
    draw_text(c, MARGIN_X, PAGE_H - 55, "집픽", 13, WHITE, bold=True)
    pill(c, PAGE_W - MARGIN_X - 84, PAGE_H - 63, "PREMIUM REPORT", Color(1, 1, 1, alpha=0.12), WHITE, 84)
    draw_text(c, MARGIN_X, PAGE_H - 112, "김OO님의", 15, HexColor("#B9CBF7"))
    draw_text(c, MARGIN_X, PAGE_H - 148, "매수 의견 리포트", 30, WHITE, bold=True)
    draw_text(c, MARGIN_X, PAGE_H - 180, "후보를 늘어놓지 않고, 지금 할 일을 정리했습니다.", 11, HexColor("#D8E2F8"))
    draw_text(c, MARGIN_X, PAGE_H - 222, "분석 기준 2026.07.29", 8.5, HexColor("#AFC0E3"))
    draw_text(c, PAGE_W - MARGIN_X, PAGE_H - 222, "유효기간 14일", 8.5, HexColor("#AFC0E3"), align="right")

    round_rect(c, MARGIN_X, PAGE_H - 485, CONTENT_W, 178, fill=WHITE, stroke=None, radius=18)
    pill(c, MARGIN_X + 20, PAGE_H - 345, "가장 먼저 드리는 의견", BLUE_LIGHT, BLUE)
    draw_text(c, MARGIN_X + 20, PAGE_H - 386, "지금은 1순위만 현장 확인하세요", 20, NAVY, bold=True)
    draw_paragraph(
        c,
        MARGIN_X + 20,
        PAGE_H - 415,
        "생활시간과 가격 방어력을 함께 보면 북서울센트럴파크가 가장 균형이 좋습니다.",
        CONTENT_W - 40,
        10.5,
        17,
        TEXT,
    )
    c.setStrokeColor(LINE)
    c.line(MARGIN_X + 20, PAGE_H - 445, PAGE_W - MARGIN_X - 20, PAGE_H - 445)
    draw_text(c, MARGIN_X + 20, PAGE_H - 470, "계약 상한", 8.5, MUTED)
    draw_text(c, MARGIN_X + 92, PAGE_H - 473, "7억 4,800만원", 16, BLUE, bold=True)
    draw_text(c, PAGE_W - MARGIN_X - 20, PAGE_H - 470, "포기 가격  7억 6,000만원", 9, RED, bold=True, align="right")

    y = PAGE_H - 530
    for title, desc in [
        ("1순위", "북서울센트럴파크 · 먼저 방문"),
        ("협상선", "7억 3,500만~7억 4,800만원"),
        ("멈춤선", "비상자금 3,000만원이 줄면 중단"),
    ]:
        round_rect(c, MARGIN_X, y - 52, CONTENT_W, 52, fill=WHITE, stroke=LINE, radius=12)
        draw_text(c, MARGIN_X + 16, y - 22, title, 9, BLUE, bold=True)
        draw_text(c, MARGIN_X + 78, y - 23, desc, 10.5, TEXT, bold=True)
        y -= 64

    pill(c, MARGIN_X, 30, "시연용 가상 데이터", AMBER_LIGHT, AMBER)
    draw_text(c, PAGE_W - MARGIN_X, 36, "단지명과 수치는 실제가 아닙니다.", 7.5, MUTED, align="right")
    c.showPage()


def page_2(c: Canvas) -> None:
    header(c, 2, "먼저 결론")
    y = section_title(
        c,
        PAGE_H - 73,
        "01 · ANSWER FIRST",
        "후보는 세 곳이지만, 행동은 하나입니다",
        "1순위를 먼저 확인하고 가격이 맞지 않을 때만 2순위로 이동하세요.",
    )
    cards = [
        ("1", "먼저 방문", "북서울센트럴파크", "7억 4,800만원 이하", BLUE, BLUE_LIGHT),
        ("2", "가격 맞으면 비교", "갈매역그린시티", "6억 8,500만원 이하", GREEN, GREEN_LIGHT),
        ("3", "지금은 기다림", "다산리버포레", "6억 3,500만원 이하", AMBER, AMBER_LIGHT),
    ]
    for num, action, name, limit, color, fill in cards:
        round_rect(c, MARGIN_X, y - 100, CONTENT_W, 88, fill=WHITE, stroke=LINE, radius=14)
        c.setFillColor(fill)
        c.circle(MARGIN_X + 31, y - 56, 19, fill=1, stroke=0)
        draw_text(c, MARGIN_X + 31, y - 61, num, 14, color, bold=True, align="center")
        draw_text(c, MARGIN_X + 63, y - 39, action, 8.5, color, bold=True)
        draw_text(c, MARGIN_X + 63, y - 62, name, 14, NAVY, bold=True)
        draw_text(c, PAGE_W - MARGIN_X - 18, y - 59, limit, 11.5, color, bold=True, align="right")
        y -= 102

    y -= 2
    round_rect(c, MARGIN_X, y - 150, CONTENT_W, 145, fill=NAVY, stroke=None, radius=16)
    draw_text(c, MARGIN_X + 20, y - 34, "왜 1순위인가요?", 13, WHITE, bold=True)
    yy = y - 65
    for line in [
        "시청역 기준 출근시간이 약 38분으로 가장 짧아요.",
        "최근 거래가 18건이라 가격 기준을 잡기 쉬워요.",
        "주변 새 아파트 입주 부담이 세 후보 중 가장 낮아요.",
    ]:
        c.setFillColor(HexColor("#7FA6FF"))
        c.circle(MARGIN_X + 24, yy + 3, 2.4, fill=1, stroke=0)
        draw_text(c, MARGIN_X + 37, yy, line, 9.5, WHITE)
        yy -= 25

    y -= 178
    draw_text(c, MARGIN_X, y, "다만, 아래 조건이면 사지 않습니다", 12, NAVY, bold=True)
    y -= 28
    for line in [
        "가격이 7억 6,000만원을 넘어요.",
        "비상자금 3,000만원을 남길 수 없어요.",
        "소음과 평일 출근시간을 직접 확인하지 못했어요.",
    ]:
        y = bullet(c, MARGIN_X, y, line, CONTENT_W, color=TEXT)
        y -= 7
    page_footer(c)
    c.showPage()


def page_3(c: Canvas) -> None:
    header(c, 3, "구매력")
    y = section_title(
        c,
        PAGE_H - 73,
        "02 · BUYING POWER",
        "살 수 있는 가격과 편안한 가격은 다릅니다",
        "대출이 된다고 모두 쓰지 않습니다. 생활비와 비상자금을 먼저 지킵니다.",
    )
    col_w = (CONTENT_W - 12) / 2
    round_rect(c, MARGIN_X, y - 124, col_w, 116, fill=BLUE_LIGHT, stroke=None, radius=14)
    draw_text(c, MARGIN_X + 18, y - 39, "금융회사 심사 전 참고 상한", 9, BLUE_DARK)
    draw_text(c, MARGIN_X + 18, y - 78, "8억 2,500만원", 23, BLUE, bold=True)
    draw_text(c, MARGIN_X + 18, y - 102, "쓸 수 있는 돈의 끝", 8.5, MUTED)

    x2 = MARGIN_X + col_w + 12
    round_rect(c, x2, y - 124, col_w, 116, fill=GREEN_LIGHT, stroke=None, radius=14)
    draw_text(c, x2 + 18, y - 39, "생활비를 지키는 편안한 가격", 9, GREEN)
    draw_text(c, x2 + 18, y - 78, "7억 6,000만원", 23, GREEN, bold=True)
    draw_text(c, x2 + 18, y - 102, "집픽이 권하는 목표선", 8.5, MUTED)
    y -= 151

    round_rect(c, MARGIN_X, y - 110, CONTENT_W, 102, fill=WHITE, stroke=LINE, radius=14)
    draw_text(c, MARGIN_X + 18, y - 32, "입력한 조건", 11, NAVY, bold=True)
    vals = [
        ("자기자금", "3억 6,000만원"),
        ("부부 연소득", "8,400만원"),
        ("기존 대출", "없음"),
        ("가정 금리", "연 4.1% · 30년"),
    ]
    cell_w = (CONTENT_W - 36) / 4
    for i, (label, value) in enumerate(vals):
        xx = MARGIN_X + 18 + i * cell_w
        draw_text(c, xx, y - 61, label, 8, MUTED)
        draw_text(c, xx, y - 83, value, 10, TEXT, bold=True)
    y -= 138

    draw_text(c, MARGIN_X, y, "1순위를 살 때 돈의 흐름", 13, NAVY, bold=True)
    y -= 31
    round_rect(c, MARGIN_X, y - 169, CONTENT_W, 162, fill=CANVAS, stroke=None, radius=14)
    yy = y - 33
    for label, value, max_value, color in [
        ("매매가격", 7.45, 8.5, BLUE),
        ("취득·중개·등기·이사", 0.22, 8.5, AMBER),
        ("투입 자기자금", 3.60, 8.5, GREEN),
        ("예상 대출", 4.07, 8.5, BLUE_DARK),
    ]:
        money_bar(c, MARGIN_X + 18, yy, CONTENT_W - 36, label, value, max_value, color)
        yy -= 35
    y -= 196

    round_rect(c, MARGIN_X, y - 103, CONTENT_W, 95, fill=WHITE, stroke=LINE, radius=14)
    key_value(c, MARGIN_X + 18, y - 32, "현재 가정 월 원리금", "약 197만원", CONTENT_W - 36, BLUE)
    c.setStrokeColor(LINE)
    c.line(MARGIN_X + 18, y - 48, PAGE_W - MARGIN_X - 18, y - 48)
    key_value(c, MARGIN_X + 18, y - 74, "금리가 1.5%p 오를 때", "약 230만원", CONTENT_W - 36, RED)
    y -= 128
    round_rect(c, MARGIN_X, y - 52, CONTENT_W, 52, fill=AMBER_LIGHT, stroke=None, radius=12)
    draw_text(c, MARGIN_X + 16, y - 31, "꼭 기억하세요", 8.5, AMBER, bold=True)
    draw_text(c, MARGIN_X + 92, y - 31, "매수 상한은 목표 가격이 아닙니다.", 10.5, TEXT, bold=True)
    page_footer(c)
    c.showPage()


def page_4(c: Canvas) -> None:
    header(c, 4, "후보 비교")
    y = section_title(
        c,
        PAGE_H - 73,
        "03 · SHORTLIST",
        "세 후보를 같은 기준으로 비교했습니다",
        "점수보다 중요한 것은 각 후보가 이기는 조건과 포기할 조건입니다.",
    )
    names = ["북서울센트럴파크", "갈매역그린시티", "다산리버포레"]
    prices = ["7.45억", "6.95억", "6.55억"]
    scores = [82, 78, 72]
    colors = [BLUE, GREEN, AMBER]
    card_w = (CONTENT_W - 20) / 3
    for i in range(3):
        xx = MARGIN_X + i * (card_w + 10)
        round_rect(c, xx, y - 135, card_w, 127, fill=WHITE, stroke=LINE, radius=14)
        pill(c, xx + 12, y - 39, f"{i + 1}순위", [BLUE_LIGHT, GREEN_LIGHT, AMBER_LIGHT][i], colors[i])
        draw_text(c, xx + 12, y - 68, names[i], 10.5, NAVY, bold=True)
        draw_text(c, xx + 12, y - 95, prices[i], 16, colors[i], bold=True)
        draw_text(c, xx + 12, y - 119, f"종합 {scores[i]}점", 8.5, MUTED)
        score_bar(c, xx + 68, y - 116, card_w - 80, scores[i], colors[i])
    y -= 160

    rows = [
        ("계약 상한", "7.48억", "6.85억", "6.35억"),
        ("월 원리금", "197만원", "172만원", "152만원"),
        ("출근시간", "38분", "47분", "55분"),
        ("최근 거래", "18건", "14건", "21건"),
        ("초등학교", "420m", "310m", "520m"),
        ("주변 공급", "낮음", "보통", "높음"),
        ("되팔기 쉬움", "좋음", "보통", "보통"),
    ]
    row_h = 39
    label_w = 92
    table_h = row_h * (len(rows) + 1)
    round_rect(c, MARGIN_X, y - table_h, CONTENT_W, table_h, fill=WHITE, stroke=LINE, radius=12)
    c.setFillColor(CANVAS)
    c.roundRect(MARGIN_X, y - row_h, CONTENT_W, row_h, 12, fill=1, stroke=0)
    draw_text(c, MARGIN_X + 12, y - 25, "비교 항목", 8.5, MUTED, bold=True)
    for i, label in enumerate(["1순위", "2순위", "3순위"]):
        cx = MARGIN_X + label_w + (i + 0.5) * (CONTENT_W - label_w) / 3
        draw_text(c, cx, y - 25, label, 8.5, colors[i], bold=True, align="center")
    yy = y - row_h
    for ridx, row in enumerate(rows):
        yy -= row_h
        if ridx < len(rows) - 1:
            c.setStrokeColor(LINE)
            c.line(MARGIN_X, yy, PAGE_W - MARGIN_X, yy)
        draw_text(c, MARGIN_X + 12, yy + 14, row[0], 8.5, MUTED)
        for i in range(3):
            cx = MARGIN_X + label_w + (i + 0.5) * (CONTENT_W - label_w) / 3
            value_color = RED if row[0] == "주변 공급" and i == 2 else TEXT
            draw_text(c, cx, yy + 14, row[i + 1], 9.5, value_color, bold=True, align="center")
    y -= table_h + 23

    round_rect(c, MARGIN_X, y - 70, CONTENT_W, 66, fill=BLUE_LIGHT, stroke=None, radius=12)
    draw_text(c, MARGIN_X + 16, y - 28, "선택 기준", 8.5, BLUE, bold=True)
    draw_paragraph(
        c,
        MARGIN_X + 82,
        y - 25,
        "1순위보다 5,000만원 이상 싸고 출근이 견딜 만할 때만 2순위를 선택합니다.",
        CONTENT_W - 100,
        9.5,
        15,
        TEXT,
        bold=True,
    )
    page_footer(c)
    c.showPage()


def candidate_page(
    c: Canvas,
    page_num: int,
    rank: int,
    name: str,
    region: str,
    verdict: str,
    limit: str,
    color: Color,
    light: Color,
    values: list[float],
    stats: list[tuple[str, str]],
    good: list[str],
    caution: list[str],
    pricing: list[tuple[str, str]],
) -> None:
    header(c, page_num, f"후보 {rank}")
    y = section_title(c, PAGE_H - 73, f"0{rank + 3} · CANDIDATE {rank}", f"{rank}순위 · {name}", region)
    round_rect(c, MARGIN_X, y - 105, CONTENT_W, 96, fill=light, stroke=None, radius=15)
    pill(c, MARGIN_X + 16, y - 41, "매수 의견", WHITE, color)
    draw_text(c, MARGIN_X + 16, y - 72, verdict, 15, NAVY, bold=True)
    draw_text(c, PAGE_W - MARGIN_X - 16, y - 72, limit, 12, color, bold=True, align="right")
    y -= 132

    col_w = (CONTENT_W - 14) / 2
    round_rect(c, MARGIN_X, y - 176, col_w, 168, fill=WHITE, stroke=LINE, radius=14)
    draw_text(c, MARGIN_X + 15, y - 33, "최근 가격 흐름", 11, NAVY, bold=True)
    line_chart(c, MARGIN_X + 22, y - 139, col_w - 44, 78, values, color)
    draw_text(c, MARGIN_X + 22, y - 160, "최근 6개월 중위가격 · 억원", 7.5, MUTED)

    x2 = MARGIN_X + col_w + 14
    round_rect(c, x2, y - 176, col_w, 168, fill=WHITE, stroke=LINE, radius=14)
    draw_text(c, x2 + 15, y - 33, "단지 핵심 숫자", 11, NAVY, bold=True)
    yy = y - 62
    for label, value in stats:
        key_value(c, x2 + 15, yy, label, value, col_w - 30)
        yy -= 28
    y -= 202

    draw_text(c, MARGIN_X, y, "좋은 점", 12, GREEN, bold=True)
    draw_text(c, MARGIN_X + col_w + 14, y, "조심할 점", 12, RED, bold=True)
    yy_left = y - 27
    yy_right = y - 27
    for line in good:
        yy_left = bullet(c, MARGIN_X, yy_left, line, col_w, size=9)
        yy_left -= 8
    for line in caution:
        c.setFillColor(RED)
        c.circle(MARGIN_X + col_w + 17, yy_right + 4, 2.1, fill=1, stroke=0)
        yy_right = draw_paragraph(c, MARGIN_X + col_w + 28, yy_right, line, col_w - 14, 9, 14, TEXT)
        yy_right -= 8
    y = min(yy_left, yy_right) - 14

    round_rect(c, MARGIN_X, y - 124, CONTENT_W, 116, fill=CANVAS, stroke=None, radius=14)
    draw_text(c, MARGIN_X + 16, y - 31, "가격 협상선", 11, NAVY, bold=True)
    yy = y - 59
    for label, value in pricing:
        key_value(c, MARGIN_X + 16, yy, label, value, CONTENT_W - 32, color if "상한" in label else None)
        yy -= 25
    y -= 147
    round_rect(c, MARGIN_X, y - 62, CONTENT_W, 56, fill=AMBER_LIGHT, stroke=None, radius=12)
    draw_text(c, MARGIN_X + 15, y - 26, "현장에서", 8.5, AMBER, bold=True)
    draw_text(c, MARGIN_X + 76, y - 26, "같은 단지라도 동·층·소음에 따라 적정가격은 달라집니다.", 9.5, TEXT, bold=True)
    draw_text(c, MARGIN_X + 76, y - 44, "좋은 매물 하나보다 조건이 다른 매물 세 곳을 비교하세요.", 8.5, MUTED)
    page_footer(c)
    c.showPage()


def page_8(c: Canvas) -> None:
    header(c, 8, "위험 비교")
    y = section_title(
        c,
        PAGE_H - 73,
        "07 · RISK CHECK",
        "좋은 점보다 나쁜 상황을 먼저 계산했습니다",
        "가격이 내려가거나 금리가 올라도 버틸 수 있는지를 확인합니다.",
    )
    round_rect(c, MARGIN_X, y - 134, CONTENT_W, 126, fill=NAVY, stroke=None, radius=16)
    draw_text(c, MARGIN_X + 18, y - 35, "금리가 1.5%p 오를 때 월 원리금", 11, WHITE, bold=True)
    vals = [
        ("북서울센트럴", "230만원", 230, BLUE),
        ("갈매역그린", "201만원", 201, GREEN),
        ("다산리버", "178만원", 178, AMBER),
    ]
    yy = y - 65
    for label, value, amount, color in vals:
        draw_text(c, MARGIN_X + 18, yy, label, 8.5, HexColor("#C7D2E9"))
        c.setFillColor(HexColor("#35415A"))
        c.roundRect(MARGIN_X + 105, yy - 2, CONTENT_W - 188, 8, 4, fill=1, stroke=0)
        c.setFillColor(color)
        c.roundRect(MARGIN_X + 105, yy - 2, (CONTENT_W - 188) * amount / 240, 8, 4, fill=1, stroke=0)
        draw_text(c, PAGE_W - MARGIN_X - 18, yy, value, 9.5, WHITE, bold=True, align="right")
        yy -= 25
    y -= 160

    scenarios = [
        ("가격이 10% 내려가면", "1순위의 장부상 가치는 약 7,450만원 줄어듭니다.", RED_LIGHT, RED),
        ("6개월 안 팔리면", "대출과 관리비를 계속 낼 수 있는 현금 여유가 필요합니다.", AMBER_LIGHT, AMBER),
        ("한 사람 소득이 멈추면", "월 원리금 197만원과 생활비를 6개월 버틸 예비비가 필요합니다.", BLUE_LIGHT, BLUE),
    ]
    for title, desc, fill, color in scenarios:
        round_rect(c, MARGIN_X, y - 75, CONTENT_W, 68, fill=fill, stroke=None, radius=13)
        draw_text(c, MARGIN_X + 16, y - 29, title, 10.5, color, bold=True)
        draw_paragraph(c, MARGIN_X + 16, y - 50, desc, CONTENT_W - 32, 8.7, 13, TEXT)
        y -= 80

    y -= 8
    draw_text(c, MARGIN_X, y, "후보별 위험 신호", 12, NAVY, bold=True)
    y -= 25
    rows = [
        ("가격 부담", "보통", "낮음", "낮음"),
        ("출근 피로", "낮음", "보통", "높음"),
        ("주변 공급", "낮음", "보통", "높음"),
        ("거래 끊김", "낮음", "보통", "보통"),
        ("금리 충격", "높음", "보통", "낮음"),
    ]
    label_w = 96
    row_h = 29
    for ridx, row in enumerate(rows):
        yy = y - ridx * row_h
        if ridx % 2 == 0:
            c.setFillColor(CANVAS)
            c.rect(MARGIN_X, yy - 20, CONTENT_W, row_h, fill=1, stroke=0)
        draw_text(c, MARGIN_X + 10, yy - 10, row[0], 8.2, MUTED)
        for i in range(3):
            cx = MARGIN_X + label_w + (i + 0.5) * (CONTENT_W - label_w) / 3
            val = row[i + 1]
            color = RED if val == "높음" else AMBER if val == "보통" else GREEN
            draw_text(c, cx, yy - 10, val, 8.7, color, bold=True, align="center")

    y -= len(rows) * row_h + 17
    round_rect(c, MARGIN_X, y - 59, CONTENT_W, 54, fill=GREEN_LIGHT, stroke=None, radius=12)
    draw_text(c, MARGIN_X + 16, y - 31, "버틸 수 있을 때만 삽니다", 10.5, GREEN, bold=True)
    draw_text(c, PAGE_W - MARGIN_X - 16, y - 31, "최소 보유 계획 5년 · 비상자금 3,000만원", 9, TEXT, align="right")
    page_footer(c)
    c.showPage()


def page_9(c: Canvas) -> None:
    header(c, 9, "생활 적합도")
    y = section_title(
        c,
        PAGE_H - 73,
        "08 · DAILY LIFE",
        "가격이 비슷하면 매일 쓰는 시간을 봅니다",
        "실거주자는 집 안보다 출근, 주차, 소음에서 더 오래 영향을 받습니다.",
    )
    weights = [("예산 안정", 40, BLUE), ("출근시간", 25, GREEN), ("가족생활", 20, AMBER), ("시장 안정", 15, BLUE_DARK)]
    round_rect(c, MARGIN_X, y - 103, CONTENT_W, 95, fill=WHITE, stroke=LINE, radius=14)
    draw_text(c, MARGIN_X + 16, y - 30, "이번 고객의 우선순위", 10.5, NAVY, bold=True)
    xx = MARGIN_X + 16
    bar_y = y - 61
    available = CONTENT_W - 32
    for label, weight, color in weights:
        ww = available * weight / 100
        c.setFillColor(color)
        c.rect(xx, bar_y, ww, 15, fill=1, stroke=0)
        if ww > 70:
            draw_text(c, xx + ww / 2, bar_y + 4, f"{label} {weight}%", 7.2, WHITE, bold=True, align="center")
        xx += ww
    y -= 134

    rows = [
        ("출근", "38분 · 환승 1회", "47분 · 환승 1회", "55분 · 버스 변수"),
        ("초등학교", "420m", "310m", "520m"),
        ("평일 주차", "확인 필요", "보통", "좋음"),
        ("큰 도로 소음", "동별 차이 큼", "일부 동 주의", "낮음"),
        ("공원·산책", "보통", "좋음", "매우 좋음"),
        ("생활 편의", "매우 좋음", "좋음", "좋음"),
    ]
    col_w = (CONTENT_W - 105) / 3
    table_top = y
    c.setFillColor(CANVAS)
    c.rect(MARGIN_X, table_top - 38, CONTENT_W, 38, fill=1, stroke=0)
    draw_text(c, MARGIN_X + 10, table_top - 24, "생활 항목", 8.5, MUTED, bold=True)
    for i, label in enumerate(["북서울", "갈매", "다산"]):
        draw_text(c, MARGIN_X + 105 + col_w * (i + 0.5), table_top - 24, label, 8.5, [BLUE, GREEN, AMBER][i], bold=True, align="center")
    yy = table_top - 38
    for ridx, row in enumerate(rows):
        yy -= 33
        c.setStrokeColor(LINE)
        c.line(MARGIN_X, yy, PAGE_W - MARGIN_X, yy)
        draw_text(c, MARGIN_X + 10, yy + 11, row[0], 8.2, MUTED)
        for i in range(3):
            draw_text(c, MARGIN_X + 105 + col_w * (i + 0.5), yy + 11, row[i + 1], 8.2, TEXT, bold=True, align="center")
    y = yy - 30

    draw_text(c, MARGIN_X, y, "한 번에 확인하는 토요일 동선", 12, NAVY, bold=True)
    y -= 32
    steps = [
        ("09:00", "북서울", "역에서 단지까지 걸으며 소음 확인"),
        ("10:00", "매물 3곳", "저층·중층·고층을 나란히 비교"),
        ("12:00", "갈매", "1순위보다 5,000만원 이상 싼지 확인"),
        ("15:00", "정리", "가격·동·층·소음을 한 표에 기록"),
    ]
    for idx, (time, place, desc) in enumerate(steps):
        if idx < len(steps) - 1:
            c.setStrokeColor(LINE)
            c.line(MARGIN_X + 23, y - 43, MARGIN_X + 23, y - 57)
        c.setFillColor(BLUE_LIGHT)
        c.circle(MARGIN_X + 23, y - 24, 17, fill=1, stroke=0)
        draw_text(c, MARGIN_X + 23, y - 27, str(idx + 1), 9, BLUE, bold=True, align="center")
        draw_text(c, MARGIN_X + 53, y - 14, f"{time} · {place}", 9.2, NAVY, bold=True)
        draw_text(c, MARGIN_X + 53, y - 34, desc, 8.2, MUTED)
        y -= 55
    page_footer(c)
    c.showPage()


def page_10(c: Canvas) -> None:
    header(c, 10, "현장·계약 확인")
    y = section_title(
        c,
        PAGE_H - 73,
        "09 · CHECKLIST",
        "좋은 집보다 확인이 끝난 집을 고릅니다",
        "현장과 서류에서 아래 항목을 하나씩 확인하세요.",
    )
    checks = [
        ("01", "평일 출근", "오전 7시 30분 실제 경로 이용"),
        ("02", "평일 주차", "밤 9시 빈자리와 이중주차 확인"),
        ("03", "소음", "거실 창을 열고 3분 동안 듣기"),
        ("04", "집 상태", "수압·결로·곰팡이·누수 흔적 확인"),
        ("05", "관리비", "최근 1년과 장기수선계획 확인"),
        ("06", "가격", "같은 동 저층·중층·고층 비교"),
        ("07", "매도 사유", "잔금 희망일과 이사 일정 확인"),
        ("08", "등기부", "소유자·근저당·가압류 확인"),
    ]
    col_w = (CONTENT_W - 12) / 2
    card_h = 63
    for idx, (num, title, desc) in enumerate(checks):
        col = idx % 2
        row = idx // 2
        xx = MARGIN_X + col * (col_w + 12)
        yy = y - row * (card_h + 10)
        round_rect(c, xx, yy - card_h, col_w, card_h, fill=WHITE, stroke=LINE, radius=12)
        draw_text(c, xx + 13, yy - 25, num, 8, BLUE, bold=True)
        draw_text(c, xx + 46, yy - 25, title, 10, NAVY, bold=True)
        draw_text(c, xx + 46, yy - 46, desc, 8.2, MUTED)
    y -= 4 * (card_h + 10) + 11

    round_rect(c, MARGIN_X, y - 188, CONTENT_W, 180, fill=RED_LIGHT, stroke=None, radius=15)
    draw_text(c, MARGIN_X + 17, y - 34, "이 조건이면 계약을 멈춥니다", 13, RED, bold=True)
    yy = y - 65
    for line in [
        "1순위 가격이 7억 6,000만원을 넘습니다.",
        "은행 확정 대출이 예상보다 3,000만원 이상 적습니다.",
        "등기부와 관리비 체납 여부를 확인하지 못했습니다.",
        "오늘 계약해야 한다는 압박을 받습니다.",
        "비상자금 3,000만원을 남길 수 없습니다.",
    ]:
        c.setFillColor(RED)
        c.circle(MARGIN_X + 21, yy + 3, 2.2, fill=1, stroke=0)
        draw_text(c, MARGIN_X + 34, yy, line, 9.2, TEXT, bold=True)
        yy -= 25
    y -= 214

    round_rect(c, MARGIN_X, y - 72, CONTENT_W, 66, fill=NAVY, stroke=None, radius=13)
    draw_text(c, MARGIN_X + 17, y - 29, "24시간 규칙", 9, HexColor("#8CB0FF"), bold=True)
    draw_text(c, MARGIN_X + 91, y - 29, "가격이 합의돼도 최소 하루 쉬고 결정하세요.", 10, WHITE, bold=True)
    draw_text(c, MARGIN_X + 91, y - 49, "급한 매물보다 확인이 끝난 매물이 안전합니다.", 8.5, HexColor("#CBD7EF"))
    page_footer(c)
    c.showPage()


def page_11(c: Canvas) -> None:
    header(c, 11, "7일 행동계획")
    y = section_title(
        c,
        PAGE_H - 73,
        "10 · NEXT ACTION",
        "이번 주에는 이 순서로 움직이세요",
        "검색을 더 하지 말고 1순위의 가격과 생활조건부터 확인합니다.",
    )
    days = [
        ("1~2일", "대출 확정선 받기", "은행 두 곳에서 가능금액·금리·중도상환 조건을 확인합니다.", BLUE),
        ("2~3일", "매물 세 곳 예약", "저층·중층·고층, 도로 가까운 동과 먼 동을 함께 봅니다.", GREEN),
        ("3~4일", "출근·주차 확인", "평일 아침 출근과 밤 9시 주차를 직접 경험합니다.", AMBER),
        ("5일", "첫 가격 제안", "7억 3,500만원부터 시작하고 7억 4,800만원에서 멈춥니다.", BLUE_DARK),
        ("6~7일", "서류 확인 후 하루 쉬기", "등기부와 관리비 자료를 본 뒤 최소 하루 후 결정합니다.", RED),
    ]
    for idx, (day, title, desc, color) in enumerate(days):
        round_rect(c, MARGIN_X, y - 91, CONTENT_W, 82, fill=WHITE, stroke=LINE, radius=14)
        pill(c, MARGIN_X + 14, y - 54, day, CANVAS, color, 54)
        draw_text(c, MARGIN_X + 84, y - 37, title, 11.5, NAVY, bold=True)
        draw_text(c, MARGIN_X + 84, y - 62, desc, 8.8, MUTED)
        y -= 96

    y -= 2
    round_rect(c, MARGIN_X, y - 119, CONTENT_W, 111, fill=BLUE_LIGHT, stroke=None, radius=14)
    draw_text(c, MARGIN_X + 16, y - 32, "이번 주 목표", 9, BLUE, bold=True)
    draw_text(c, MARGIN_X + 16, y - 64, "계약이 아니라 판단 근거를 완성하는 것", 16, NAVY, bold=True)
    draw_text(c, MARGIN_X + 16, y - 91, "가격·동·층·소음·대출 다섯 칸이 채워지면 결정이 쉬워집니다.", 9.2, TEXT)
    page_footer(c)
    c.showPage()


def page_12(c: Canvas) -> None:
    header(c, 12, "기준과 한계")
    y = section_title(
        c,
        PAGE_H - 73,
        "11 · BASIS",
        "무엇을 보고 의견을 만들었나요?",
        "값의 출처와 확인 시점을 함께 보여줘야 의견을 다시 검증할 수 있습니다.",
    )
    sources = [
        ("실거래", "정상 매매·전세 거래, 취소 거래 제외", "매일"),
        ("대출·정책", "LTV·DSR·가격 상한·전입 조건", "정책 변경 시"),
        ("단지", "세대수·준공·면적·주차·관리 정보", "월 1회"),
        ("생활", "대중교통 경로·학교·생활시설", "월 1회"),
        ("공급", "분양·입주 예정 물량", "월 1회"),
        ("현재 매물", "사람이 직접 확인한 공개 호가", "리포트 작성일"),
    ]
    round_rect(c, MARGIN_X, y - 280, CONTENT_W, 272, fill=WHITE, stroke=LINE, radius=14)
    draw_text(c, MARGIN_X + 15, y - 31, "자료", 8.5, MUTED, bold=True)
    draw_text(c, MARGIN_X + 112, y - 31, "확인 내용", 8.5, MUTED, bold=True)
    draw_text(c, PAGE_W - MARGIN_X - 15, y - 31, "갱신", 8.5, MUTED, bold=True, align="right")
    yy = y - 50
    for title, desc, refresh in sources:
        c.setStrokeColor(LINE)
        c.line(MARGIN_X + 15, yy - 31, PAGE_W - MARGIN_X - 15, yy - 31)
        draw_text(c, MARGIN_X + 15, yy - 13, title, 9.2, NAVY, bold=True)
        draw_text(c, MARGIN_X + 112, yy - 13, desc, 8.6, TEXT)
        draw_text(c, PAGE_W - MARGIN_X - 15, yy - 13, refresh, 8.4, MUTED, align="right")
        yy -= 38
    y -= 307

    round_rect(c, MARGIN_X, y - 104, CONTENT_W, 96, fill=AMBER_LIGHT, stroke=None, radius=14)
    draw_text(c, MARGIN_X + 16, y - 31, "이 리포트가 대신할 수 없는 것", 11, AMBER, bold=True)
    draw_paragraph(
        c,
        MARGIN_X + 16,
        y - 56,
        "실제 대출 심사, 집 내부 상태, 등기와 계약 문서, 고객의 최종 결정을 대신하지 않습니다.",
        CONTENT_W - 32,
        9.3,
        15,
        TEXT,
    )
    y -= 132

    round_rect(c, MARGIN_X, y - 146, CONTENT_W, 138, fill=NAVY, stroke=None, radius=16)
    draw_text(c, MARGIN_X + 18, y - 38, "집픽의 역할", 9, HexColor("#8CB0FF"), bold=True)
    draw_text(c, MARGIN_X + 18, y - 75, "결정을 대신하지 않고,", 18, WHITE, bold=True)
    draw_text(c, MARGIN_X + 18, y - 104, "결정에 필요한 순서를 정리합니다.", 18, WHITE, bold=True)
    draw_text(c, MARGIN_X + 18, y - 128, "특정 매물을 알선하거나 수익을 보장하지 않습니다.", 8.5, HexColor("#CBD7EF"))
    y -= 177
    draw_text(c, MARGIN_X, y, "샘플 리포트 문의", 8, MUTED)
    draw_text(c, MARGIN_X, y - 22, "집픽 · 내 조건의 매수 후보 3곳", 11, BLUE, bold=True)
    page_footer(c, "시연용 샘플 · 모든 단지명과 수치는 가상입니다.")
    c.showPage()


def build() -> Path:
    register_fonts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(OUTPUT), pagesize=A4)
    c.setTitle("집픽 39,000원 매수 의견 리포트 샘플")
    c.setAuthor("집픽")
    cover(c)
    page_2(c)
    page_3(c)
    page_4(c)
    candidate_page(
        c,
        5,
        1,
        "북서울센트럴파크",
        "서울 노원구 월계동 · 전용 59㎡ · 2018년 · 1,142세대",
        "7억 4,800만원 이하라면 먼저 검토",
        "계약 상한 7.48억",
        BLUE,
        BLUE_LIGHT,
        [7.18, 7.22, 7.28, 7.31, 7.39, 7.45],
        [("최근 12개월 거래", "18건"), ("전세가율", "61.7%"), ("출근시간", "약 38분"), ("초등학교", "약 420m")],
        ["출근시간이 가장 짧아요.", "거래가 꾸준해 가격 비교가 쉬워요.", "주변 입주 부담이 낮아요."],
        ["큰 도로 가까운 동은 소음 차이가 커요.", "호가가 실거래보다 최대 3,000만원 높아요.", "평일 밤 주차를 확인해야 해요."],
        [("최근 확인 거래", "7.38억 · 7.45억 · 7.52억"), ("첫 제안가", "7억 3,500만원"), ("계약 상한", "7억 4,800만원")],
    )
    candidate_page(
        c,
        6,
        2,
        "갈매역그린시티",
        "경기 구리시 갈매동 · 전용 59㎡ · 2017년 · 1,018세대",
        "6억 8,500만원 이하면 함께 비교",
        "계약 상한 6.85억",
        GREEN,
        GREEN_LIGHT,
        [6.72, 6.73, 6.78, 6.82, 6.88, 6.95],
        [("최근 12개월 거래", "14건"), ("전세가율", "61.2%"), ("출근시간", "약 47분"), ("초등학교", "약 310m")],
        ["학교와 공원이 가까워요.", "1순위보다 대출을 줄일 수 있어요.", "전세 거래가 꾸준해요."],
        ["환승 대기까지 보면 50분을 넘을 수 있어요.", "역과 도로 거리에 따라 가격 차이가 커요.", "6.9억을 넘으면 1순위 대비 장점이 줄어요."],
        [("최근 확인 거래", "6.78억 · 6.90억 · 6.95억"), ("첫 제안가", "6억 7,800만원"), ("계약 상한", "6억 8,500만원")],
    )
    candidate_page(
        c,
        7,
        3,
        "다산리버포레",
        "경기 남양주시 다산동 · 전용 59㎡ · 2020년 · 1,267세대",
        "6억 3,500만원 아니면 기다림",
        "계약 상한 6.35억",
        AMBER,
        AMBER_LIGHT,
        [6.48, 6.49, 6.50, 6.50, 6.53, 6.55],
        [("최근 12개월 거래", "21건"), ("전세가율", "58.8%"), ("출근시간", "약 55분"), ("초등학교", "약 520m")],
        ["준공연도가 가장 최근이에요.", "월 원리금이 가장 낮아요.", "단지 보행환경이 좋아요."],
        ["주변 입주 물량이 가격을 누를 수 있어요.", "출근시간 변동이 커요.", "최근 가격 반등 힘은 약해요."],
        [("최근 확인 거래", "6.45억 · 6.52억 · 6.55억"), ("첫 제안가", "6억 2,500만원"), ("계약 상한", "6억 3,500만원")],
    )
    page_8(c)
    page_9(c)
    page_10(c)
    page_11(c)
    page_12(c)
    c.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
