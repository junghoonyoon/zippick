#!/usr/bin/env python3
"""집픽 유료 진단 리포트 자동 생성기.

고객 주문서(JSON) → 라이브 집픽 API 호출 → 인쇄용 HTML 리포트.

사용법:
    python3 수익화/generate_report.py 수익화/주문/주문서예시.json
    python3 수익화/generate_report.py            # 주문 폴더 전체 처리

만들어진 파일: 수익화/리포트/<주문번호>_<이름>.html
브라우저에서 열고 ⌘P → PDF로 저장 → 고객 전달.

표준 라이브러리만 사용한다. 별도 설치 필요 없음.
"""

import datetime
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://maesuhalkkayo.exe.xyz"
TIMEOUT = 150

ROOT = Path(__file__).resolve().parent
ORDER_DIR = ROOT / "주문"
OUTPUT_DIR = ROOT / "리포트"

# 입주물량은 서버 API가 아니라 로컬 파이프라인에서 직접 계산한다.
sys.path.insert(0, str(ROOT.parent / "pipeline"))
try:
    import supply_forecast
except ImportError:  # 파이프라인 없이 리포트만 돌릴 때도 죽지 않게 한다.
    supply_forecast = None

OWNERSHIP_LABELS = {
    "no_home": "무주택",
    "conditional_one_home": "1주택 · 처분 예정",
    "one_home_keep": "1주택 · 기존 집 유지",
    "multi_home": "2주택 이상",
}

# 서버가 인식하는 평형 기준값. 이 값을 min_area로 넘기면 후보 전체가
# 같은 평형 실거래로만 비교된다. 비워 보내면 41㎡와 85㎡가 한 표에 섞인다.
AREA_CHOICES = {
    40: "전용 40㎡대 (약 12평)",
    50: "전용 50㎡대 (약 15평)",
    59: "전용 59㎡대 (약 18평)",
    74: "전용 74㎡대 (약 22평)",
    84: "전용 84㎡대 (약 25평)",
}


# ---------------------------------------------------------------- API 호출


def _get(path, params):
    query = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v not in (None, "")}
    )
    url = f"{BASE_URL}{path}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "zippick-report/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _profile_params(order):
    return {
        "home_ownership": order["보유주택"],
        "first_time": "true" if order.get("생애최초") else "false",
        "cash_eok": order["자기자금_억"],
        "annual_income": order["연소득_만원"],
        "monthly_debt_payment": order.get("월대출상환_만원", 0),
        "co_borrower": "true" if order.get("배우자합산") else "false",
        "spouse_annual_income": order.get("배우자연소득_만원", ""),
        "mortgage_rate": order.get("예상금리", 4.2),
        "loan_term_years": order.get("대출기간", 30),
        "purchase_cost_rate": order.get("부대비용률", 3),
    }


def fetch_purchase_power(order):
    return _get("/api/purchase-power", _profile_params(order))


def _requested_area(order):
    """희망 평형. 없으면 0. 0이면 평형이 섞이므로 리포트에서 경고한다."""
    try:
        value = int(float(order.get("희망평형") or order.get("최소면적") or 0))
    except (TypeError, ValueError):
        return 0
    return value if value in AREA_CHOICES else 0


def fetch_candidates(order, region, budget, limit=4):
    params = _profile_params(order)
    params.update(
        {
            "budget": budget,
            "region": region,
            "purpose": order.get("매수목적", "live"),
            "price_strategy": order.get("가격전략", "stretch"),
            "min_area": _requested_area(order) or "",
            "min_households": order.get("최소세대수", ""),
            "max_building_age": order.get("최대연식", ""),
            "limit": limit,
        }
    )
    return _get("/api/budget-candidates", params)


# ---------------------------------------------------------------- 서술 생성


def _eok(value):
    try:
        return f"{float(value):.1f}억"
    except (TypeError, ValueError):
        return "-"


def _pct(value, digits=1):
    try:
        return f"{float(value):+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _int(value):
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "-"


def verdict_for(candidate):
    """한 줄 판정 문구. 데이터가 없으면 없다고 쓴다."""
    signals = candidate.get("signals") or {}
    location = candidate.get("locationScore") or {}
    momentum = signals.get("momentumPct")
    score = location.get("score")
    reasons = []

    if isinstance(momentum, (int, float)):
        if momentum >= 8:
            reasons.append(f"최근 6개월 실거래가 {_pct(momentum)}로 뚜렷하게 올랐고")
        elif momentum >= 2:
            reasons.append(f"최근 6개월 실거래가 {_pct(momentum)}로 완만히 올랐고")
        elif momentum <= -2:
            reasons.append(f"최근 6개월 실거래가 {_pct(momentum)}로 내렸고")
        else:
            reasons.append("최근 6개월 가격은 거의 움직이지 않았고")

    turnover = signals.get("turnoverSmoothed")
    if isinstance(turnover, (int, float)):
        if turnover >= 1.3:
            reasons.append("거래량도 이전 구간보다 늘어 매수세가 살아 있습니다")
        elif turnover <= 0.7:
            reasons.append("거래량은 이전 구간보다 줄어 매수세가 식어 있습니다")
        else:
            reasons.append("거래량은 이전 구간과 비슷합니다")

    relative = signals.get("districtRelativePct")
    if isinstance(relative, (int, float)):
        if relative >= 3:
            reasons.append(f"같은 구 대표 단지보다 {relative:.1f}%p 더 올랐습니다")
        elif relative <= -3:
            reasons.append(f"같은 구 대표 단지보다 {abs(relative):.1f}%p 덜 올랐습니다")

    if not reasons:
        return "판정에 쓸 만한 최근 거래 데이터가 부족합니다."
    if len(reasons) > 2:
        body = ", ".join(reasons[:-1]) + ". " + reasons[-1]
    else:
        body = ", ".join(reasons)
    if not body.endswith("."):
        body += "."
    if isinstance(score, (int, float)):
        body += f" 종합 점수는 100점 만점에 {score:.0f}점입니다."
    return body.strip()


def _josa(word, with_batchim, without_batchim):
    """받침 유무에 따라 조사를 고른다. 단지명이 문장에 들어가면 꼭 필요하다."""
    word = str(word or "").strip()
    if not word:
        return word
    last = word[-1]
    if "가" <= last <= "힣":
        return word + (with_batchim if (ord(last) - 0xAC00) % 28 else without_batchim)
    # 단지명이 숫자로 끝나는 경우가 흔하다(예: 황골마을주공1). 읽는 소리로 판단한다.
    if last.isdigit():
        return word + (with_batchim if last in "013678" else without_batchim)
    return f"{word}{with_batchim}({without_batchim})"


def _eun(word):
    return _josa(word or "해당 지역", "은", "는")


def _eul(word):
    return _josa(word, "을", "를")


def _i(word):
    return _josa(word, "이", "가")


def _wa(word):
    return _josa(word, "과", "와")


def _price_range_text(candidate):
    text = str(candidate.get("priceRangeText") or "").strip()
    return text.replace("현재 예상 시세", "").strip() or "-"


def _num(candidate, key):
    value = candidate.get(key)
    return float(value) if isinstance(value, (int, float)) and value else None


def price_picture(candidate):
    """가격을 하나의 숫자로 단언하지 않고, 무엇을 재고 있는지 나눠서 보여준다.

    `현재 예상 시세`의 정체는 최근 6개월 거래의 가중 중앙값이다. 가격이
    오르는 구간에서는 과거 거래가 섞여 현재보다 낮게 나오고, 같은 평형
    안에서도 층·향 편차가 크면 더 끌려 내려간다. 그래서 이 값 하나만
    `현재 시세`라고 부르면 바로 아래 적힌 최근 실거래와 충돌해 리포트
    전체의 신뢰가 무너진다. 각 숫자가 무엇을 재는지 밝히고, 차이가 클 때는
    그 이유까지 문장으로 설명한다.
    """
    median6 = _num(candidate, "estimatedMidPriceEok") or _num(candidate, "recentMedianPriceEok")
    recent3 = _num(candidate, "recent3AveragePriceEok")
    prior3 = _num(candidate, "previous3AveragePriceEok")
    latest = _num(candidate, "latestDealPriceEok")
    low = _num(candidate, "minPriceEok")
    high = _num(candidate, "maxPriceEok")
    momentum = (candidate.get("signals") or {}).get("momentumPct")

    rows = []
    if recent3:
        rows.append(
            ("최근 3개월 거래 평균", recent3,
             f"{_int(candidate.get('recent3TradeCount'))}건 · 지금 시장에 가장 가까움", True)
        )
    if latest:
        rows.append(
            ("가장 최근 실거래", latest,
             f"{_esc(candidate.get('latestDealDate'))} · "
             f"{_esc(candidate.get('latestDealExclusiveArea'))}㎡ "
             f"{_esc(candidate.get('latestDealFloor'))}층 (단일 거래)", False)
        )
    if median6:
        rows.append(
            ("최근 6개월 거래 중앙값", median6,
             f"{_int(candidate.get('currentEstimateSampleCount'))}건 · 과거 거래가 함께 섞임", False)
        )
    if prior3:
        rows.append(("직전 3개월 거래 평균", prior3, "비교용 과거 구간", False))

    notes = []
    if median6 and latest:
        gap = latest - median6
        if abs(gap) >= max(0.3, median6 * 0.07):
            direction = "높습니다" if gap > 0 else "낮습니다"
            reason = (
                f"최근 6개월 {_pct(momentum)} 오른 구간이라 과거 거래가 섞인 중앙값이 "
                "현재 시장보다 낮게 나옵니다"
                if isinstance(momentum, (int, float)) and momentum >= 3
                else "최근 거래가 한두 건에 치우쳤을 수 있습니다"
            )
            notes.append(
                f"6개월 중앙값({_eok(median6)})보다 가장 최근 실거래({_eok(latest)})가 "
                f"{_eok(abs(gap))} {direction}. {reason}."
            )
    if low and high and low > 0 and (high - low) / low >= 0.4:
        notes.append(
            f"같은 평형인데도 6개월 거래가 {_eok(low)}~{_eok(high)}으로 벌어져 있습니다. "
            "층·향·수리 상태 차이가 커서 평균 하나로 가격을 정할 수 없는 단지입니다. "
            "반드시 개별 매물의 동·층을 확인하세요."
        )
    if recent3 and prior3 and prior3 > 0:
        change = (recent3 - prior3) / prior3 * 100
        if abs(change) >= 3:
            notes.append(
                f"직전 3개월 평균 {_eok(prior3)} → 최근 3개월 {_eok(recent3)}으로 "
                f"{_pct(change)} 움직였습니다."
            )

    anchor = recent3 or latest or median6
    return {"rows": rows, "notes": notes, "anchor": anchor}


REPORTING_LAG_MONTHS = 2.0
MAX_MONTHLY_RATE = 0.03


def asking_price_guide(candidate):
    """호가를 만났을 때 쓸 판단 기준을 만든다.

    실거래는 계약 후 신고까지 시차가 있고, 오르는 구간에서 호가는 실거래를
    앞서간다. 그래서 `최근 3개월 평균 5.2억`만 적어 놓으면 6억을 부르는
    현장에서 아무 쓸모가 없다.

    호가 자체는 가져올 수 없다. 네이버 부동산 매물 정보는 데이터베이스
    제작자의 권리로 보호되고 무단 수집은 손해배상 판결이 나온 영역이다.
    대신 실거래 추세로 `지금 계약되고 있을 값`을 추정하고, 어느 선을
    넘으면 근거를 따져야 하는지를 구간으로 제시한다. 호가를 알려주는 게
    아니라 호가를 평가할 자를 주는 것이다.
    """
    recent3 = _num(candidate, "recent3AveragePriceEok")
    prior3 = _num(candidate, "previous3AveragePriceEok")
    latest = _num(candidate, "latestDealPriceEok")
    high6 = _num(candidate, "maxPriceEok")
    if not recent3:
        return None

    monthly = 0.0
    if prior3 and prior3 > 0:
        monthly = (recent3 / prior3) ** (1 / 3) - 1
        monthly = max(-MAX_MONTHLY_RATE, min(MAX_MONTHLY_RATE, monthly))
    estimate = recent3 * ((1 + monthly) ** REPORTING_LAG_MONTHS)

    # 이미 그보다 높은 실거래가 찍혔다면 그게 더 현실에 가깝다.
    if latest and latest > estimate:
        estimate = (estimate + latest) / 2

    normal_top = max(latest or 0, estimate)
    stretch_top = high6 or normal_top * 1.08
    if stretch_top <= normal_top:
        stretch_top = normal_top * 1.05

    return {
        "estimate": estimate,
        "monthlyPct": monthly * 100,
        "normalTop": normal_top,
        "stretchTop": stretch_top,
        "recent3": recent3,
        "latest": latest,
        "high6": high6,
    }


def render_asking_guide(candidate):
    guide = asking_price_guide(candidate)
    if not guide:
        return ""
    estimate = guide["estimate"]
    normal_top = guide["normalTop"]
    stretch_top = guide["stretchTop"]
    monthly = guide["monthlyPct"]

    basis = f"최근 3개월 평균 {_eok(guide['recent3'])}"
    if abs(monthly) >= 0.2:
        basis += f"에 최근 상승 속도(월 {monthly:+.1f}%)와 신고 시차 약 2개월을 반영"
    else:
        basis += " · 최근 가격 변화가 크지 않아 그대로 사용"
    if guide["latest"] and guide["latest"] > guide["recent3"]:
        basis += f", 가장 최근 실거래 {_eok(guide['latest'])}을 함께 반영"

    return f"""
<h4>호가를 만났을 때 판단 기준</h4>
<div class="verdict" style="margin:12px 0;padding:18px 20px">
  <div class="label">오늘 계약한다면 이 정도로 추정</div>
  <div class="big">{_eok(estimate)}</div>
  <p class="note" style="margin:0">{_esc(basis)}</p>
</div>
<table>
<tr><th>호가 구간</th><th>어떻게 봐야 하나</th></tr>
<tr><td class="num">~{_eok(normal_top)}</td>
<td>최근 실거래 흐름 안입니다. 무리한 가격이 아니니 동·층·향을 보고 판단하세요.</td></tr>
<tr><td class="num">{_eok(normal_top)} ~ {_eok(stretch_top)}</td>
<td>최근 6개월 최고 거래({_eok(guide['high6'])})에 가까워집니다.
로열층·풀수리처럼 값을 정당화할 이유가 있는지 확인하세요.</td></tr>
<tr class="top"><td class="num">{_eok(stretch_top)} 초과</td>
<td>최근 6개월 어떤 거래보다도 높은 값입니다.
왜 그 가격인지 중개사에게 근거를 반드시 물어보세요. 근거가 없으면 협상 대상입니다.</td></tr>
</table>
<p class="note">이 추정은 신고된 실거래만으로 계산한 값이라 현장 호가와 다를 수 있습니다.
호가가 위 구간을 크게 벗어나면 시장이 빠르게 움직이는 중이거나 그 매물에 특별한 사정이 있다는
뜻이니, 같은 단지 다른 매물 두세 개를 함께 비교해 보세요.</p>"""


def render_jeonse(candidate, region_supply=None, is_first=False):
    """전세는 갭 계산과 하방 지지를 보는 핵심 지표다.

    다만 이 단지들 대부분은 전세 실거래 신고가 0건이고, 앱이 보여주는
    `전세가율 60%`는 매매가에 상수를 곱해 되돌린 값이다. 전세가율 60%를
    가정해 전세가를 만들고 그 전세가로 다시 전세가율이 60%라고 말하는
    순환이라 정보가 아니다. 그래서 실거래가 없을 때는 숫자를 단언하지 않고,
    고객이 호가를 확인해 대입할 수 있는 구간표를 준다.
    """
    ratio = _num(candidate, "jeonseRatioPct")
    count = candidate.get("jeonseTransactionCount") or 0
    estimated = (candidate.get("jeonseDataStatus") or "") == "estimated"
    guide = asking_price_guide(candidate)
    base = (guide or {}).get("estimate") or _num(candidate, "recent3AveragePriceEok")
    policy = candidate.get("policyImpact") or {}
    if not base:
        return ""

    supply_line = ""
    if (region_supply or {}).get("level") == "heavy":
        peak = region_supply["peak"]
        supply_line = (
            f"<p class='note'>{_esc(region_supply['region'])}는 {peak['label']}에 "
            f"{peak['households']:,}세대가 입주할 예정입니다. 그 시기 전세는 약세로 갈 수 있어 "
            "실제 전세가율은 지금 확인한 값보다 낮아질 수 있습니다.</p>"
        )

    caution = (
        "<p class='note'>규제지역이라 대출에 전입 의무 같은 조건이 붙을 수 있습니다. "
        "전입 의무가 있으면 전세를 끼고 매수하는 방식 자체가 불가능하니, "
        "계약 전 은행과 중개사에 반드시 확인하세요.</p>"
        if policy.get("isRegulated")
        else ""
    )

    if count and not estimated and ratio:
        deposit = _num(candidate, "medianJeonseDepositEok")
        gap = base - (deposit or 0)
        return f"""
<h4>전세로 보면</h4>
<table>
<tr><th>최근 전세 실거래</th><td class="num">{_eok(deposit)} ({_int(count)}건)</td></tr>
<tr><th>전세가율</th><td class="num">{ratio:.0f}%</td></tr>
<tr><th>매매가와의 갭</th><td class="num">{_eok(gap)}</td></tr>
</table>
{supply_line}{caution}"""

    rows = "".join(
        "<tr>"
        + f"<td class='num'>{_eok(base * pct / 100)}</td>"
        + f"<td class='num'>{pct}%</td>"
        + f"<td class='num'>{_eok(base - base * pct / 100)}</td></tr>"
        for pct in (50, 55, 60, 65, 70)
    )
    # 같은 설명을 후보마다 반복하면 유료 리포트가 분량 채우기로 읽힌다.
    # 이유는 1순위에서 한 번만 말하고, 이후에는 대입할 표만 준다.
    # 전세가율이 아예 안 잡히는 단지도 있다. 없는 숫자를 포맷하면 죽는다.
    ratio_example = f"`전세가율 {ratio:.0f}%`" if ratio else "`전세가율 60%`"

    if is_first:
        lead = f"""
<p><b>이 단지는 최근 전세 실거래 신고가 없습니다.</b>
그래서 실제 전세가율을 계산할 수 없습니다. 다른 곳에서 보시는
{ratio_example} 같은 값은 매매가에 상수를 곱해 되돌린 추정치라
실제와 다를 수 있습니다. 숫자를 지어내는 대신 확인 방법을 드립니다.</p>
<p class="note">네이버 부동산에서 같은 평형 <b>전세 호가</b>를 확인한 뒤,
아래 표에서 그 금액에 해당하는 줄을 보세요.
기준 매매가는 앞에서 추정한 {_eok(base)}입니다.</p>"""
        tail = """
<p class="note">전세가율이 높을수록 내 돈이 적게 들지만, 전세금은 나중에 돌려줘야 할
빚입니다. 전세가율이 너무 높으면 다음 세입자를 못 구할 때 위험이 커집니다.
아래 후보들도 전세 실거래가 없으면 같은 방식으로 보시면 됩니다.</p>"""
    else:
        lead = (
            f"<p class='note'>전세 실거래 신고가 없어 전세가율을 계산할 수 없습니다. "
            f"1순위에서 설명한 방식대로, 네이버 부동산에서 전세 호가를 확인해 "
            f"아래 표에 대입하세요. 기준 매매가 {_eok(base)}.</p>"
        )
        tail = ""

    return f"""
<h4>전세로 보면</h4>
{lead}
<table>
<tr><th>전세보증금</th><th>전세가율</th><th>전세 끼고 살 때 내 돈</th></tr>
{rows}
</table>
{tail}
{supply_line}{caution}"""


def render_price_picture(candidate):
    picture = price_picture(candidate)
    if not picture["rows"]:
        return ""
    body = "".join(
        ("<tr class='top'>" if strong else "<tr>")
        + f"<td>{_esc(label)}</td>"
        + f"<td class='num'><b>{_eok(value)}</b></td>"
        + f"<td class='note'>{note}</td></tr>"
        for label, value, note, strong in picture["rows"]
    )
    notes = "".join(f"<li>{_esc(text)}</li>" for text in picture["notes"])
    notes_html = f"<ul>{notes}</ul>" if notes else ""
    return f"""
<h4>가격을 어떻게 봐야 하나</h4>
<table><tr><th>기준</th><th>금액</th><th>설명</th></tr>{body}</table>
{notes_html}
<p class="note">위 숫자는 모두 이미 신고된 과거 거래입니다.
지금 현장에서 만날 호가는 아래 기준으로 판단하세요.</p>"""


def cautions_for(candidate):
    """확인 전 반드시 짚어야 할 항목. 리포트 신뢰의 핵심."""
    items = []
    age = candidate.get("buildingAge")
    if isinstance(age, (int, float)) and age >= 30:
        items.append(
            f"준공 {int(age)}년차입니다. 배관·주차·엘리베이터 상태와 "
            "정비사업 추진 단계(조합 유무, 사업시행인가 여부)를 직접 확인하세요."
        )
    if (candidate.get("jeonseDataStatus") or "") == "estimated":
        items.append(
            "전세가율은 실거래가 아니라 추정치입니다. "
            "네이버 부동산에서 같은 평형 전세 호가를 직접 확인하세요."
        )
    count = candidate.get("transactionCount")
    if isinstance(count, (int, float)) and count < 10:
        items.append(
            f"최근 6개월 거래가 {int(count)}건뿐입니다. "
            "표본이 적어 가격 신뢰도가 낮으니 호가와 반드시 대조하세요."
        )
    policy = candidate.get("policyImpact") or {}
    if policy.get("isRegulated"):
        items.append(
            f"{_eun(policy.get('regionLabel') or '해당 지역')} 규제지역입니다. "
            f"LTV {policy.get('ltvRate', '-')}%, 주택가격 상한 "
            f"{_eok(policy.get('priceCapEok'))} 기준이 적용되고 전입 의무가 붙을 수 있습니다."
        )
    gap = policy.get("cashGapEok")
    if isinstance(gap, (int, float)) and gap > 0:
        items.append(
            f"현재 자기자금 기준으로 약 {_eok(gap)}이 부족합니다. "
            "가격 협상, 추가 자금, 또는 더 낮은 가격대 검토가 필요합니다."
        )
    spread = (candidate.get("signals") or {}).get("priceSpreadPct")
    if isinstance(spread, (int, float)) and spread >= 30:
        items.append(
            f"같은 단지 안에서도 거래가 편차가 {spread:.0f}%로 큽니다. "
            "동·층·향·수리 상태에 따라 가격이 크게 갈리니 개별 매물 비교가 필수입니다."
        )
    area_label = candidate.get("areaLabel") or ""
    deal_area = candidate.get("latestDealExclusiveArea")
    if area_label and isinstance(deal_area, (int, float)):
        bounds = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", area_label)]
        if len(bounds) == 2 and not (bounds[0] <= deal_area <= bounds[1]):
            items.append(
                f"표기 평형은 {area_label}인데 가장 최근 거래는 {deal_area}㎡입니다. "
                "해당 평형의 최신 거래가 아직 신고되지 않았을 수 있으니 "
                "호가를 볼 때 평형을 반드시 다시 확인하세요."
            )
    if not items:
        items.append(
            "현재 데이터 기준으로 특별히 걸리는 항목은 없습니다. 개별 매물 상태는 직접 확인하세요."
        )
    return items


def _cash_surplus(candidate):
    """자기자금 여유분. 양수면 남고 음수면 모자란다.

    서버의 `cashGapEok`은 `보유현금 - 필요현금`이라 부족분이 아니라
    여유분이다. 이름만 보고 부족분으로 읽으면 판정이 통째로 뒤집힌다.
    실제로 여유 1.6억인 단지를 `1.6억 부족`으로 표시해 후보에서 빼고,
    가장 빠듯한 곳을 1순위로 올리는 사고가 났다.
    """
    value = (candidate.get("policyImpact") or {}).get("cashGapEok")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _budget_use(candidate, budget):
    """예산을 얼마나 쓰는지. 상한이 6.2억인데 5.2억을 사면 1억이 남는다."""
    anchor = price_picture(candidate)["anchor"]
    if not anchor or not budget:
        return None
    return anchor / budget * 100


def _cash_text(surplus):
    if surplus >= 0.05:
        return f"{surplus:.1f}억 여유"
    if surplus <= -0.05:
        return f"{abs(surplus):.1f}억 부족"
    return "딱 맞음"


def jeonse_is_estimated(candidate):
    """전세가율이 실거래가 아니라 상수에서 되돌아온 추정치인지."""
    if (candidate.get("jeonseDataStatus") or "").strip() == "estimated":
        return True
    try:
        return int(float(candidate.get("jeonseTransactionCount") or 0)) <= 0
    except (TypeError, ValueError):
        return True


def scoring_parts(candidate):
    """채점에 실제로 쓸 항목과, 근거가 없어 뺀 항목을 나눈다.

    전세 실거래가 0건이면 `전세가율 58%`는 매매가에 상수를 곱해 되돌린 값이다.
    본문에서는 그 숫자를 믿지 말라고 하면서 배점 20점 중 12점을 그 숫자로
    주면, 근거 없는 12점이 1·2순위를 가르게 된다. 그래서 근거가 없을 때는
    항목을 배점에서 통째로 빼고 남은 항목만으로 100점을 다시 만든다.
    """
    parts = (candidate.get("locationScore") or {}).get("parts") or []
    if not jeonse_is_estimated(candidate):
        return parts, None
    used, dropped = [], None
    for part in parts:
        if part.get("key") == "jeonse":
            dropped = part
        else:
            used.append(part)
    return (used, dropped) if used else (parts, None)


def _score(candidate):
    """종합 점수. 근거 없는 항목을 뺀 뒤 100점 만점으로 재환산한다."""
    used, dropped = scoring_parts(candidate)
    if dropped is not None:
        earned = sum(
            float(p["points"])
            for p in used
            if isinstance(p.get("points"), (int, float))
        )
        total = sum(
            float(p["maxPoints"])
            for p in used
            if isinstance(p.get("maxPoints"), (int, float))
        )
        if total > 0:
            return earned / total * 100
    value = (candidate.get("locationScore") or {}).get("score")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _momentum(candidate):
    value = (candidate.get("signals") or {}).get("momentumPct")
    return float(value) if isinstance(value, (int, float)) else None


TOO_CHEAP_RATIO = 0.6


def classify(candidates, budget=None):
    """살 수 있는 것, 참고할 것, 볼 이유가 없는 것을 나눈다.

    세 가지를 섞으면 리포트가 `못 사는 집 목록`이 된다.

    - 실질 후보: 자금이 남거나, 모자라도 0.5억 이내. 협상으로 닿는 범위다.
    - 참고: 자금이 0.5억 넘게 모자란 곳.
    - 제외: 예산의 60%도 안 되는 곳. 6.2억을 살 수 있는 사람에게
      1.8억짜리를 후보라고 내미는 건 분석이 아니다. 평형 조건만 맞으면
      딸려 들어오기 때문에 여기서 끊는다.
    """
    reachable, reference, too_cheap = [], [], []
    floor = (budget or 0) * TOO_CHEAP_RATIO
    for candidate in candidates:
        anchor = price_picture(candidate)["anchor"] or 0
        if floor and anchor and anchor < floor:
            too_cheap.append(candidate)
        elif _cash_surplus(candidate) >= -0.5:
            reachable.append(candidate)
        else:
            reference.append(candidate)
    reachable.sort(key=lambda c: (-_score(c), -_cash_surplus(c)))
    reference.sort(key=lambda c: -_cash_surplus(c))
    too_cheap.sort(key=lambda c: -_score(c))
    return reachable, reference, too_cheap


def budget_use_note(reachable, budget):
    """1순위가 예산을 크게 남기면 그걸 짚어준다.

    상한 6.2억인 사람에게 5.2억짜리를 1순위로 내밀면 `1억을 왜 안 쓰지`가
    된다. 남긴 게 나쁜 건 아니지만, 남겼다는 사실과 그 돈으로 무엇을 더
    볼 수 있었는지는 말해줘야 한다.
    """
    if not reachable or not budget:
        return ""
    top = reachable[0]
    use = _budget_use(top, budget)
    if use is None or use >= 92:
        return ""
    anchor = price_picture(top)["anchor"] or 0
    spare = budget - anchor
    better = [
        c for c in reachable[1:]
        if (_budget_use(c, budget) or 0) >= 92
    ]
    tail = ""
    if better:
        names = ", ".join(
            f"{c.get('displayName')}({_eok(price_picture(c)['anchor'])})"
            for c in better[:3]
        )
        tail = (
            f" 예산을 거의 다 쓰는 선택지로는 {names}이 있습니다. "
            "같은 지역에서 더 좋은 동·층이나 더 넓은 평형을 볼 수 있다는 뜻이니 "
            "함께 비교해 보세요."
        )
    else:
        tail = (
            f" 지금 고른 평형에서는 이 지역에 {_eok(budget)}에 가까운 매물이 "
            "많지 않습니다. 예산을 다 쓰고 싶다면 한 단계 넓은 평형을 "
            "함께 검토하시는 편이 낫습니다."
        )
    return (
        f"1순위 {_eun(top.get('displayName'))} 매수 가능 상한 {_eok(budget)}의 "
        f"{use:.0f}%만 씁니다. {_eok(spare)}이 남는다는 뜻입니다.{tail}"
    )


def tradeoff_sentences(reachable):
    """지역·연식·가격이 만드는 실제 선택지를 문장으로 뽑는다.

    데이터에 다 들어 있는데 연결해주지 않으면 독자가 스스로 해야 한다.
    """
    lines = []
    if len(reachable) < 2:
        return lines

    ages = [(c, c.get("buildingAge")) for c in reachable]
    ages = [(c, a) for c, a in ages if isinstance(a, (int, float))]
    if len(ages) >= 2:
        oldest = max(ages, key=lambda x: x[1])
        newest = min(ages, key=lambda x: x[1])
        if oldest[1] - newest[1] >= 15:
            lines.append(
                f"연식 차이가 {int(oldest[1] - newest[1])}년까지 벌어집니다. "
                f"{_eun(oldest[0].get('displayName'))} 준공 {int(oldest[1])}년차, "
                f"{_eun(newest[0].get('displayName'))} {int(newest[1])}년차입니다. "
                "같은 예산에서 위치를 살 것인지 새 집을 살 것인지의 문제이고, "
                "이건 데이터로 정해지지 않습니다."
            )

    regulated = [c for c in reachable if (c.get("policyImpact") or {}).get("isRegulated")]
    free = [c for c in reachable if not (c.get("policyImpact") or {}).get("isRegulated")]
    if regulated and free:
        lines.append(
            f"규제지역 {len(regulated)}곳, 비규제지역 {len(free)}곳이 섞여 있습니다. "
            "규제지역은 대출 한도가 깎이고 전입 의무가 붙을 수 있어서, "
            "같은 가격이라도 실제로 필요한 현금이 다릅니다."
        )

    cash = [(c, _cash_surplus(c)) for c in reachable]
    easiest = max(cash, key=lambda x: x[1])
    hardest = min(cash, key=lambda x: x[1])
    if easiest[1] - hardest[1] >= 0.3:
        lines.append(
            f"자금 여유 차이가 {easiest[1] - hardest[1]:.1f}억입니다. "
            f"{_eun(easiest[0].get('displayName'))} 계약 후에도 "
            f"{easiest[1]:.1f}억이 남고, {_eun(hardest[0].get('displayName'))} "
            f"{_cash_text(hardest[1])}입니다. 남는 돈은 이사비·수리비·예비비로 "
            "쓰이니 여유가 있는 쪽이 실제로는 훨씬 편합니다."
        )

    moves = [(c, _momentum(c)) for c in reachable]
    moves = [(c, m) for c, m in moves if m is not None]
    if len(moves) >= 2:
        hot = max(moves, key=lambda x: x[1])
        cold = min(moves, key=lambda x: x[1])
        if hot[1] - cold[1] >= 5:
            lines.append(
                f"최근 6개월 가격 흐름도 갈립니다. {_eun(hot[0].get('displayName'))} "
                f"{_pct(hot[1])}, {_eun(cold[0].get('displayName'))} {_pct(cold[1])}입니다. "
                "많이 오른 곳은 이미 반영된 가격일 수 있고, 덜 오른 곳은 "
                "이유가 있을 수 있으니 둘 다 확인이 필요합니다."
            )
    return lines


def headline_reason(candidate, runner_up=None, excluded_higher=()):
    """1순위로 꼽은 이유를 설명한다.

    점수만 나열하면 표에 더 높은 점수가 보일 때 독자가 바로 의심한다.
    `점수가 더 높은데 왜 안 골랐는지`를 먼저 밝히고, 그다음 2순위와의
    차이를 말한다.
    """
    parts, _ = scoring_parts(candidate)
    best = sorted(
        (p for p in parts if isinstance(p.get("points"), (int, float))),
        key=lambda p: (p.get("points") or 0) / max(1, p.get("maxPoints") or 1),
        reverse=True,
    )
    bits = [f"{p.get('label')} {p.get('points')}/{p.get('maxPoints')}점" for p in best[:2]]

    surplus = _cash_surplus(candidate)
    lines = []
    if excluded_higher:
        names = ", ".join(
            f"{c.get('displayName')}({_score(c):.0f}점 · {_cash_text(_cash_surplus(c))})"
            for c in excluded_higher[:3]
        )
        lines.append(
            f"점수만 보면 {names}처럼 더 높은 곳도 있습니다. 그런데 지금 자기자금으로는 "
            "계약까지 갈 수 없어 1순위에서 뺐습니다. 살 수 없는 집은 후보가 아닙니다."
        )
    cash_text = (
        f"계약하고도 {surplus:.1f}억이 남아 자금에 여유가 있고"
        if surplus >= 0.05
        else f"자금이 {abs(surplus):.1f}억 모자라지만 가격 협상으로 닿는 범위이고"
        if surplus < 0
        else "자금이 딱 맞고"
    )
    lines.append(
        f"{cash_text}, 실제로 살 수 있는 곳 중에서는 종합 {_score(candidate):.0f}점으로 "
        f"가장 높습니다. {', '.join(bits)}이 특히 높게 나왔습니다."
    )
    if runner_up is not None:
        diff = _score(candidate) - _score(runner_up)
        if abs(diff) < 5:
            lines.append(
                f"다만 2순위 {_wa(runner_up.get('displayName'))} {abs(diff):.0f}점 차이라 "
                "확정적인 우위는 아닙니다. 두 곳을 함께 보시길 권합니다."
            )
    return " ".join(lines)


def unique_cautions(candidate):
    """단지마다 다른 것만 남긴다. 모두에게 해당하는 말은 뒤에서 한 번만 한다."""
    items = []
    age = candidate.get("buildingAge")
    if isinstance(age, (int, float)) and age >= 30:
        items.append(
            f"준공 {int(age)}년차. 배관·주차·엘리베이터 상태와 정비사업 추진 단계를 확인하세요."
        )
    count = candidate.get("transactionCount")
    if isinstance(count, (int, float)) and count < 10:
        items.append(f"최근 6개월 거래 {int(count)}건. 표본이 적어 가격 신뢰도가 낮습니다.")
    spread = (candidate.get("signals") or {}).get("priceSpreadPct")
    if isinstance(spread, (int, float)) and spread >= 30:
        items.append(
            f"같은 단지 안 거래가 편차 {spread:.0f}%. 동·층·향에 따라 가격이 크게 갈립니다."
        )
    estimate_mid = candidate.get("estimatedMaxPriceEok")
    latest = candidate.get("latestDealPriceEok")
    if isinstance(estimate_mid, (int, float)) and isinstance(latest, (int, float)):
        if latest > estimate_mid * 1.05:
            items.append(
                f"최근 거래 {_eok(latest)}이 예상 시세 상단({_eok(estimate_mid)})을 넘었습니다. "
                "시세가 올라가는 중이거나 특이 거래일 수 있어 호가 확인이 특히 중요합니다."
            )
    policy = candidate.get("policyImpact") or {}
    surplus = _cash_surplus(candidate)
    if surplus < 0:
        items.append(
            f"필요 현금 {_eok(policy.get('requiredCashEok'))} 중 "
            f"{abs(surplus):.1f}억이 모자랍니다."
        )
    elif surplus < 0.3:
        items.append(
            f"필요 현금 {_eok(policy.get('requiredCashEok'))}을 내고 나면 "
            f"{surplus:.1f}억밖에 안 남습니다. 이사비·수리비·중개보수를 빼면 "
            "예비비가 거의 없으니 자금 계획을 다시 보세요."
        )
    area_label = candidate.get("areaLabel") or ""
    deal_area = candidate.get("latestDealExclusiveArea")
    if area_label and isinstance(deal_area, (int, float)):
        bounds = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", area_label)]
        if len(bounds) == 2 and not (bounds[0] <= deal_area <= bounds[1]):
            items.append(
                f"표기 평형은 {area_label}인데 최근 거래는 {deal_area}㎡입니다. "
                "해당 평형 최신 거래가 아직 신고되지 않았을 수 있습니다."
            )
    return items


CSS = """
:root{--ink:#101418;--muted:#5f6b76;--line:#e3e8ee;--bg:#fff;--accent:#0b57d0;--warn:#b3261e;--ok:#0f7b3f;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
color:var(--ink);background:#f4f6f8;line-height:1.65;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
.page{max-width:860px;margin:0 auto;background:var(--bg);padding:56px 60px;}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-0.5px;}
h2{font-size:20px;margin:46px 0 14px;padding-bottom:9px;border-bottom:2px solid var(--ink);letter-spacing:-0.3px;}
h3{font-size:17px;margin:26px 0 8px;letter-spacing:-0.2px;}
h4{font-size:14px;margin:18px 0 6px;}
p{margin:0 0 11px;}
.sub{color:var(--muted);font-size:13px;margin-bottom:26px;}
.meta{display:grid;grid-template-columns:repeat(2,1fr);border:1px solid var(--line);border-radius:8px;overflow:hidden;}
.meta div{padding:10px 14px;border-bottom:1px solid var(--line);font-size:13px;}
.meta div:nth-child(odd){background:#fafbfc;border-right:1px solid var(--line);}
.meta b{color:var(--muted);font-weight:500;margin-right:10px;}
.verdict{background:#f0f5ff;border:1px solid #c8d9f7;border-left:5px solid var(--accent);
padding:24px 26px;border-radius:0 10px 10px 0;margin:22px 0;}
.verdict .label{font-size:12px;color:var(--accent);font-weight:700;letter-spacing:0.5px;}
.verdict .big{font-size:26px;font-weight:700;letter-spacing:-0.6px;margin:6px 0 10px;}
.verdict p{font-size:15px;margin-bottom:0;}
.stat{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0;}
.stat div{border:1px solid var(--line);border-radius:8px;padding:14px 16px;}
.stat .k{font-size:12px;color:var(--muted);}
.stat .v{font-size:20px;font-weight:700;letter-spacing:-0.4px;margin-top:2px;}
table{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0;}
th,td{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top;}
th{background:#f7f9fb;font-weight:600;color:var(--muted);white-space:nowrap;font-size:12px;}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
tr.top td{background:#f0f5ff;font-weight:600;}
.card{border:1px solid var(--line);border-radius:10px;padding:22px 24px;margin:18px 0;}
.card.first{border:2px solid var(--accent);}
.rank{display:inline-block;background:var(--ink);color:#fff;font-size:12px;font-weight:700;
padding:3px 11px;border-radius:20px;}
.rank.gold{background:var(--accent);}
.card h3{margin:8px 0 2px;font-size:21px;}
.tagrow{margin:10px 0 14px;}
.tag{display:inline-block;font-size:12px;padding:3px 10px;border-radius:20px;background:#eef1f4;
color:var(--muted);margin:0 6px 6px 0;}
.tag.up{background:#e6f4ec;color:var(--ok);}
.tag.warn{background:#fdecea;color:var(--warn);}
.tag.area{background:var(--ink);color:#fff;font-weight:600;}
ul{margin:6px 0 10px;padding-left:20px;}
li{margin-bottom:6px;font-size:14px;}
ol{margin:6px 0 10px;padding-left:22px;}
ol li{margin-bottom:9px;}
.note{font-size:12px;color:var(--muted);}
.disclaimer{margin-top:46px;padding:20px 22px;background:#fafbfc;border:1px solid var(--line);
border-radius:8px;font-size:12px;color:var(--muted);}
.disclaimer h4{margin:0 0 8px;font-size:13px;color:var(--ink);}
.disclaimer li{font-size:12px;margin-bottom:5px;}
table.chart th,table.chart td{border:none;padding:5px 8px;vertical-align:middle;}
table.chart td:first-child{white-space:nowrap;color:var(--muted);font-size:12px;}
.empty{padding:18px;background:#fdf6e3;border:1px solid #f0e0b0;border-radius:8px;font-size:14px;}
@media print{body{background:#fff;}.page{padding:0;max-width:none;}
.card,.verdict,table{break-inside:avoid;}h2{break-after:avoid;}}
"""


def _esc(value):
    return html.escape(str(value if value is not None else "-"))


def _compare_row(candidate, index, klass="", budget=None):
    policy = candidate.get("policyImpact") or {}
    surplus = _cash_surplus(candidate)
    momentum = _momentum(candidate)
    use = _budget_use(candidate, budget)
    return (
        f"<tr class='{klass}'>"
        f"<td class='num'>{index}</td>"
        f"<td>{_esc(candidate.get('displayName'))}<br>"
        f"<span class='note'>{_esc(candidate.get('region'))}</span></td>"
        f"<td class='num'>{_eok(price_picture(candidate)['anchor'])}</td>"
        f"<td class='num'>{f'{use:.0f}%' if use else '-'}</td>"
        f"<td class='num'>{_eok(policy.get('requiredCashEok'))}</td>"
        f"<td class='num'>{_cash_text(surplus)}</td>"
        f"<td class='num'>{_esc(candidate.get('buildYear'))}년</td>"
        f"<td class='num'>{_pct(momentum) if momentum is not None else '-'}</td>"
        f"<td class='num'>{_score(candidate):.0f}점</td>"
        f"</tr>"
    )


COMPARE_HEADER = (
    "<tr><th>#</th><th>단지</th><th>최근 3개월</th><th>예산 활용</th>"
    "<th>필요 현금</th><th>자금</th><th>준공</th><th>6개월</th><th>종합</th></tr>"
)


def render_compare_table(reachable, reference, budget=None):
    """살 수 있는 곳과 없는 곳을 절대 한 표에 섞지 않는다.

    섞어 놓으면 종합 점수가 높은 `못 사는 집`이 상위에 보여서 1순위 선정이
    틀린 것처럼 읽힌다. 표를 나누고, 각 표가 무엇인지 먼저 말한다.
    """
    blocks = []
    if reachable:
        body = "".join(
            _compare_row(c, i + 1, "top" if i == 0 else "", budget)
            for i, c in enumerate(reachable)
        )
        blocks.append(
            "<h3>지금 자금으로 계약까지 갈 수 있는 곳</h3>"
            f"<table>{COMPARE_HEADER}{body}</table>"
        )
    if reference:
        body = "".join(
            _compare_row(c, i + 1, "", budget) for i, c in enumerate(reference)
        )
        blocks.append(
            "<h3>조건은 맞지만 지금 자금으로는 어려운 곳</h3>"
            "<p class='note'>종합 점수가 높아도 계약을 못 하면 후보가 아닙니다. "
            "자금이 더 모였을 때 다시 보시라고 남겨 둡니다.</p>"
            f"<table>{COMPARE_HEADER}{body}</table>"
        )
    return "".join(blocks) + (
        "<p class='note'>예산 활용은 매수 가능 상한 대비 가격 비율입니다. "
        "낮으면 예산이 남는다는 뜻이라, 같은 돈으로 더 나은 조건을 볼 수 있었다는 "
        "신호일 수 있습니다. 필요 현금은 예상 대출 한도와 부대비용을 뺀 값입니다.</p>"
    )


def render_candidate(candidate, rank, is_first=False, region_supply=None):
    signals = candidate.get("signals") or {}
    policy = candidate.get("policyImpact") or {}
    location = candidate.get("locationScore") or {}
    education = candidate.get("educationEnvironment") or {}

    tags = []
    area_label = candidate.get("areaLabel") or candidate.get("displayAreaLabel") or ""
    if area_label:
        tags.append(f'<span class="tag area">{_esc(area_label)}</span>')
    momentum = _momentum(candidate)
    if momentum is not None:
        tone = "up" if momentum > 0 else "warn" if momentum < 0 else ""
        tags.append(f'<span class="tag {tone}">최근 6개월 {_pct(momentum)}</span>')
    if candidate.get("households"):
        tags.append(f'<span class="tag">{_int(candidate["households"])}세대</span>')
    if candidate.get("buildYear"):
        tags.append(f'<span class="tag">{_esc(candidate["buildYear"])}년 준공</span>')
    if policy.get("isRegulated"):
        tags.append('<span class="tag warn">규제지역</span>')

    stat = f"""
<div class="stat">
  <div><div class="k">오늘 기준 추정</div><div class="v">{_eok((asking_price_guide(candidate) or {}).get("estimate") or price_picture(candidate)["anchor"])}</div></div>
  <div><div class="k">필요 현금</div><div class="v">{_eok(policy.get('requiredCashEok'))}</div></div>
  <div><div class="k">종합 점수</div><div class="v">{_score(candidate):.0f}점</div></div>
</div>"""

    rows = [
        ("최근 6개월 거래", f"{_int(candidate.get('transactionCount'))}건"),
        (
            "대출·자금",
            f"예상 한도 {_eok(policy.get('estimatedLoanLimitEok'))} · "
            f"부대비용 {_eok(policy.get('purchaseCostEok'))}",
        ),
        (
            "초등학교",
            f"{_int(education.get('elementaryDistanceMeters'))}m"
            if education.get("elementaryDistanceMeters")
            else "데이터 없음",
        ),
    ]
    table = "".join(f"<tr><th>{_esc(k)}</th><td>{v}</td></tr>" for k, v in rows)

    parts, dropped = scoring_parts(candidate)
    score_rows = "".join(
        f"<tr><td>{_esc(p.get('label'))}</td>"
        f"<td class='num'>{_esc(p.get('points'))} / {_esc(p.get('maxPoints'))}</td>"
        f"<td>{_esc(p.get('reason'))}</td></tr>"
        for p in parts
    )
    dropped_note = ""
    if dropped is not None and score_rows:
        total_max = sum(
            float(p["maxPoints"])
            for p in parts
            if isinstance(p.get("maxPoints"), (int, float))
        )
        score_rows += (
            f"<tr><td>{_esc(dropped.get('label'))}</td>"
            f"<td class='num'>채점 제외</td>"
            f"<td>전세 실거래가 없어 근거를 만들 수 없습니다</td></tr>"
        )
        dropped_note = (
            f"<p class='note'>이 단지는 전세 실거래 신고가 없어 "
            f"{_esc(dropped.get('label'))} 항목({_esc(dropped.get('maxPoints'))}점)을 "
            f"채점에서 뺐습니다. 위 점수는 남은 {total_max:.0f}점을 100점으로 "
            "환산한 값입니다. 추정 전세가율로 점수를 만들면 근거 없는 숫자가 "
            "순위를 가르게 되기 때문입니다.</p>"
        )
    # `가격 적정성`은 6개월 중앙값 대비 현재 위치를 본다. 그래서 오르는
    # 단지일수록 낮게 나온다. 이 설명이 없으면 `+8.9% 올랐는데 왜 가격
    # 점수가 낮냐`는 모순으로 읽힌다.
    price_part = next(
        (p for p in parts if p.get("key") == "price"), {}
    )
    price_note = ""
    if (
        isinstance(price_part.get("points"), (int, float))
        and isinstance(price_part.get("maxPoints"), (int, float))
        and price_part["points"] / max(1, price_part["maxPoints"]) < 0.65
        and isinstance(momentum, (int, float))
        and momentum >= 5
    ):
        price_note = (
            "<p class='note'>가격 적정성이 낮게 나온 것은 이 단지가 나쁘다는 뜻이 아닙니다. "
            "이 항목은 최근 6개월 중앙값 대비 지금 가격이 어디쯤인지를 보기 때문에, "
            f"{_pct(momentum)} 오른 단지는 구조적으로 낮게 나옵니다. "
            "이미 오른 값을 지불하게 된다는 뜻으로 읽으시면 됩니다.</p>"
        )
    score_table = (
        f"<h4>점수 항목별 근거</h4>"
        f"<table><tr><th>항목</th><th>배점</th><th>근거</th></tr>{score_rows}</table>"
        f"{dropped_note}{price_note}"
        if score_rows
        else ""
    )

    cautions = unique_cautions(candidate)
    caution_html = (
        "<h4>이 단지에서만 걸리는 점</h4><ul>"
        + "".join(f"<li>{_esc(x)}</li>" for x in cautions)
        + "</ul>"
        if cautions
        else ""
    )
    naver = candidate.get("naverPropertyUrl") or ""
    naver_link = (
        f'<p class="note"><a href="{_esc(naver)}">네이버 부동산에서 현재 매물 보기</a></p>'
        if naver
        else ""
    )
    rank_class = "rank gold" if is_first else "rank"
    rank_text = "1순위" if is_first else f"{rank}순위"

    return f"""
<div class="card{' first' if is_first else ''}">
  <span class="{rank_class}">{rank_text}</span>
  <h3>{_esc(candidate.get('displayName'))}</h3>
  <p class="note">{_esc(candidate.get('displayRegion'))}</p>
  <div class="tagrow">{''.join(tags)}</div>
  <p>{_esc(verdict_for(candidate))}</p>
  {stat}
  {render_price_picture(candidate)}
  {render_asking_guide(candidate)}
  {render_jeonse(candidate, region_supply, is_first=is_first)}
  <table>{table}</table>
  {score_table}
  {caution_html}
  {naver_link}
</div>"""


def render_supply(regions, jeonse_ratios):
    """지역별 입주 예정 물량. 리포트에서 유일하게 미래를 다루는 부분이다."""
    if supply_forecast is None:
        return ""
    blocks = []
    for region in regions:
        result = supply_forecast.outlook(region)
        rows = supply_forecast.summary_rows(result, limit=6)
        chart = ""
        if rows:
            peak = max(r["households"] for r in rows)
            bars = "".join(
                f"<tr><td>{_esc(r['label'])}</td>"
                f"<td style='width:60%'><div style='background:var(--accent);height:16px;"
                f"border-radius:3px;width:{max(3, round(r['households'] / peak * 100))}%'></div></td>"
                f"<td class='num'>{r['households']:,}세대</td>"
                f"<td class='num note'>{r['complexCount']}개 단지</td></tr>"
                for r in rows
            )
            chart = f"<table class='chart'>{bars}</table>"
        blocks.append(
            f"<h3>{_esc(region)}</h3>"
            f"<p>{_esc(supply_forecast.sentence(result))}</p>"
            f"{chart}"
        )

    caveat = ""
    if jeonse_ratios:
        average = sum(jeonse_ratios) / len(jeonse_ratios)
        caveat = (
            f"<p class='note'>참고로 이 리포트의 전세가율(평균 {average:.0f}%)은 "
            "현재 시점 추정값입니다. 위 입주 시기에는 전세가 눌릴 수 있어 "
            "그때의 전세가율은 지금보다 낮아질 가능성이 있습니다. "
            "전세를 끼고 매수하실 계획이라면 이 점을 반드시 감안하세요.</p>"
        )

    return f"""
<h2>4. 앞으로 들어올 입주 물량</h2>
<p class="note">입주 물량은 전세에 먼저 오고 매매가 따라옵니다.
지금 가격만큼 언제 공급이 몰리는지가 매수 시점 판단에 중요합니다.</p>
{''.join(blocks)}
{caveat}
<p class="note">출처: {_esc(supply_forecast.SOURCE_LABEL)} ·
<a href="{_esc(supply_forecast.SOURCE_URL)}">데이터 원본</a></p>"""


def _monthly_payment(principal_eok, annual_rate_pct, years):
    """원리금균등상환 월 납입액(원). 계산이 불가능하면 None."""
    try:
        principal = float(principal_eok) * 100_000_000
        rate = float(annual_rate_pct) / 100 / 12
        months = int(float(years)) * 12
    except (TypeError, ValueError):
        return None
    if principal <= 0 or months <= 0:
        return None
    if rate <= 0:
        return principal / months
    factor = (1 + rate) ** months
    return principal * rate * factor / (factor - 1)


def _manwon(value):
    try:
        return f"{int(round(float(value) / 10_000)):,}만원"
    except (TypeError, ValueError):
        return "-"


def _gross_monthly_income(order):
    """세전 월소득(원). 배우자 합산일 때만 배우자 소득을 더한다."""
    try:
        total = float(order.get("연소득_만원") or 0)
    except (TypeError, ValueError):
        return None
    if order.get("배우자합산"):
        try:
            total += float(order.get("배우자연소득_만원") or 0)
        except (TypeError, ValueError):
            pass
    return total * 10_000 / 12 if total > 0 else None


STRESS_POINTS = 1.5  # 금리 스트레스 폭(%p)


def render_repayment(order, snapshot):
    """상한까지 대출을 당겼을 때 매달 나가는 돈.

    매수 상한만 보여주면 `살 수 있다`로 읽힌다. 상한은 은행이 빌려줄 수 있는
    최대치이지 감당할 수 있는 금액이 아니라는 걸 월 단위 숫자로 보여준다.
    """
    limit = snapshot.get("estimatedLoanLimitEok")
    rate = order.get("예상금리", 4.2)
    years = order.get("대출기간", 30)
    now = _monthly_payment(limit, rate, years)
    if now is None:
        return ""
    stressed = _monthly_payment(limit, float(rate) + STRESS_POINTS, years)

    rows = [
        f"<tr><th>지금 가정 금리 (연 {_esc(rate)}% · {_esc(years)}년)</th>"
        f"<td class='num'>{_manwon(now)}</td></tr>"
    ]
    if stressed is not None:
        rows.append(
            f"<tr><th>금리가 {STRESS_POINTS}%p 오를 때 "
            f"(연 {float(rate) + STRESS_POINTS:.1f}%)</th>"
            f"<td class='num'>{_manwon(stressed)}</td></tr>"
        )

    income_note = ""
    monthly_income = _gross_monthly_income(order)
    if monthly_income:
        share = now / monthly_income * 100
        income_note = (
            f" 세전 월소득 {_manwon(monthly_income)} 기준으로 "
            f"원리금이 {share:.0f}%를 차지합니다. 실수령 기준으로는 이보다 더 높습니다."
        )

    return f"""
<h3>상한까지 당겨 받으면 매달 나가는 돈</h3>
<table>
  <tr><th>기준 대출 원금</th><td class="num">{_eok(limit)}</td></tr>
  {''.join(rows)}
</table>
<p class="note">위 매수 가능 상한은 <b>금융회사가 빌려줄 수 있는 최대치이지
감당할 수 있는 금액이 아닙니다.</b>{income_note}
여기에 관리비·재산세·수리비가 따로 붙습니다. 이 금액을 6개월간 실제로 따로 떼어
저축해 보시고, 견딜 만할 때 상한 근처를 검토하세요.</p>
<p class="note">원리금균등상환 기준으로 계산한 참고값입니다. 거치기간·중도상환·우대금리에 따라
실제 납입액은 달라지며, 최종 금리는 금융회사의 개별 심사 결과에 따릅니다.</p>"""


COMMON_CHECKLIST = [
    "네이버 부동산에서 위 단지들의 현재 매물 호가를 확인하고, 각 단지의 최근 3개월 "
    "거래 평균과 비교하세요. 그 차이가 협상 여지입니다.",
    "중개사에게 최근 실제 계약된 동·층·가격을 물어보세요. 공개 실거래는 신고까지 "
    "최대 한 달 시차가 있어서 지금 시장이 아닙니다.",
    "은행 두 곳 이상에서 실제 대출 한도를 확인하세요. 이 리포트의 한도는 공개 기준으로 "
    "계산한 참고값이고, 실제 심사 결과는 다릅니다.",
    "같은 평형 전세 호가를 확인해 실제 전세가율을 계산하세요. 이 리포트의 전세가율은 "
    "전세 실거래가 없어 추정한 값입니다.",
    "관심 단지의 향후 2년 인근 입주 물량을 확인하세요. 공급이 몰리면 전세부터 눌리고 "
    "매매가 따라갑니다.",
]


# 리포트가 데이터로 못 보는 것들. 같은 단지 같은 평형이라도 여기서 값이 갈린다.
FIELD_CHECKLIST = [
    ("평일 출근", "지도 앱 예상시간 말고 평일 오전 7시 30분에 실제 경로로 한 번 가보세요."),
    ("평일 밤 주차", "밤 9시 이후 빈자리와 이중주차 상태를 보세요. 세대당 주차대수도 확인하세요."),
    ("소음", "거실 창을 열고 3분간 들어보세요. 도로·철도·상가 소음은 같은 단지에서도 동마다 다릅니다."),
    ("집 상태", "수압, 배관 녹물, 곰팡이, 누수 흔적, 창호와 단열을 직접 확인하세요."),
    ("관리비", "최근 1년 관리비 고지서와 장기수선충당금 적립 상태를 요청해서 보세요."),
    ("같은 동 비교", "같은 단지 안에서 저층·중층·고층 매물을 최소 세 곳 비교하세요."),
    ("매도 사유", "왜 파는지, 잔금 희망일과 이사 일정이 언제인지 물어보세요."),
    ("등기부등본", "소유자, 근저당, 가압류, 신탁 여부를 계약 전과 잔금 전 두 번 확인하세요."),
]


STOP_CONDITIONS = [
    "등기부등본과 관리비 체납 여부를 확인하지 못했습니다.",
    "은행에서 확정한 실제 대출 한도가 이 리포트의 참고값보다 크게 적게 나왔습니다.",
    "계약·이사·수리비를 빼고 나면 예비비가 남지 않습니다.",
    "오늘 안에 계약해야 한다는 압박을 받고 있습니다.",
    "현장에 한 번도 가보지 않았거나, 같은 단지 다른 매물을 비교하지 않았습니다.",
]


def render_field_checklist(budget=None):
    rows = "".join(
        f"<tr><th>{_esc(name)}</th><td>{_esc(text)}</td></tr>"
        for name, text in FIELD_CHECKLIST
    )
    stops = list(STOP_CONDITIONS)
    if budget:
        stops.insert(
            0,
            f"가격이 매수 가능 상한 {_eok(budget)}을 넘습니다. "
            "이건 취향의 문제가 아니라 자금이 닿지 않는 구간입니다.",
        )
    stop_items = "".join(f"<li>{_esc(x)}</li>" for x in stops)
    return f"""
<h2>5. 계약 전 현장에서 확인할 것</h2>
<p class="note">여기까지는 데이터로 좁힌 결과입니다. 아래 항목은 실거래가로는 알 수 없고
현장과 서류에서만 확인됩니다. 같은 단지 같은 평형이라도 여기서 값이 갈립니다.</p>
<table>{rows}</table>

<h3>이 조건이면 계약을 멈추세요</h3>
<div class="empty"><ul>{stop_items}</ul></div>
<p class="note">가격이 합의돼도 최소 하루는 두고 결정하세요.
좋은 매물을 놓치는 손해보다, 확인이 끝나지 않은 매물을 잡는 손해가 큽니다.</p>"""


def render_report(order, power, region_results):
    today = datetime.date.today().isoformat()
    snapshot = power.get("snapshot") or {}
    budget = power.get("budgetEok")
    area = _requested_area(order)

    all_candidates = []
    empty_regions = []
    for region, payload in region_results:
        found = payload.get("candidates") or []
        if found:
            all_candidates.extend(found)
        else:
            empty_regions.append((region, payload))

    reachable, reference, too_cheap = classify(all_candidates, budget)
    top = reachable[0] if reachable else None
    runner_up = reachable[1] if len(reachable) > 1 else None
    # 점수는 더 높은데 자금 때문에 뺀 곳. 이걸 안 밝히면 1순위 선정이 틀려 보인다.
    excluded_higher = [c for c in reference if _score(c) > _score(top)] if top else []
    excluded_higher.sort(key=lambda c: -_score(c))

    ownership = OWNERSHIP_LABELS.get(order["보유주택"], order["보유주택"])
    meta = f"""
<div class="meta">
  <div><b>주문번호</b>{_esc(order.get('주문번호'))}</div>
  <div><b>작성일</b>{today}</div>
  <div><b>보유 주택</b>{_esc(ownership)}{' · 생애최초' if order.get('생애최초') else ''}</div>
  <div><b>검토 지역</b>{_esc(', '.join(order['검토지역']))}</div>
  <div><b>자기자금</b>{_eok(order['자기자금_억'])}</div>
  <div><b>연소득</b>{_int(order['연소득_만원'])}만원</div>
  <div><b>희망 평형</b>{_esc(AREA_CHOICES.get(area, '지정 안 함'))}</div>
  <div><b>비교 기준</b>{'같은 평형 실거래만' if area else '전 평형 혼합'}</div>
</div>"""

    area_warning = (
        ""
        if area
        else """<div class="empty" style="margin-top:14px">
<b>희망 평형을 지정하지 않아 평형이 다른 단지가 함께 비교되었습니다.</b><br>
전용 41㎡와 85㎡가 같은 표에 들어가면 가격 비교의 의미가 없습니다.
희망 평형을 알려주시면 같은 평형 실거래만으로 다시 계산해 드립니다.
</div>"""
    )

    # ---- 결론 먼저 ----
    if top:
        verdict = f"""
<div class="verdict">
  <div class="label">이 리포트의 결론</div>
  <div class="big">{_esc(top.get('displayName'))}</div>
  <p>검토한 {len(all_candidates)}곳 중 예산에 맞는 {len(reachable) + len(reference)}곳을 비교했고,
  그중 지금 자금으로 실제 계약까지 갈 수 있는 곳은 <b>{len(reachable)}곳</b>입니다. 그중 {_esc(_eul(top.get('displayName')))} 1순위로 봅니다.
  {_esc(headline_reason(top, runner_up, excluded_higher))}</p>
</div>"""
    else:
        verdict = """
<div class="empty">
<b>지금 조건으로 계약까지 갈 수 있는 단지가 없습니다.</b><br>
아래에 왜 그런지와 무엇을 바꾸면 후보가 열리는지 정리했습니다.
</div>"""

    tradeoffs = tradeoff_sentences(reachable)
    note = budget_use_note(reachable, budget)
    if note:
        tradeoffs.insert(0, note)
    tradeoff_html = (
        "<h3>이 예산에서 반드시 마주치는 선택</h3><ul>"
        + "".join(f"<li>{_esc(x)}</li>" for x in tradeoffs)
        + "</ul>"
        if tradeoffs
        else ""
    )

    reference_note = ""
    if too_cheap:
        names = ", ".join(f"{c.get('displayName')}" for c in too_cheap[:6])
        reference_note = (
            f"<p class='note'>평형 조건은 맞지만 예산({_eok(budget)})의 60%에도 못 미쳐 "
            f"비교에서 뺀 곳이 {len(too_cheap)}곳 있습니다. {_esc(names)}. "
            "가격대가 크게 달라 같은 선상에서 비교하는 의미가 적습니다.</p>"
        )

    supply_by_region = {}
    if supply_forecast is not None:
        for candidate in reachable[:5]:
            name = str(candidate.get("region") or "")
            if name and name not in supply_by_region:
                supply_by_region[name] = supply_forecast.outlook(name)
    detail = "".join(
        render_candidate(
            c, i + 1,
            is_first=(i == 0),
            region_supply=supply_by_region.get(str(c.get("region") or "")),
        )
        for i, c in enumerate(reachable[:5])
    )

    empty_html = ""
    if empty_regions:
        blocks = []
        for region, payload in empty_regions:
            summary = payload.get("filterSummary") or {}
            blocks.append(
                f"<li><b>{_esc(region)}</b> — 검토 대상 "
                f"{_int(payload.get('liveSeedCount'))}개 단지 중 가격 조건에서 "
                f"{_int(summary.get('price'))}개, 최근 거래 부족으로 "
                f"{_int(summary.get('noLastDeal'))}개가 걸러져 통과가 없습니다.</li>"
            )
        empty_html = (
            "<h2>후보가 나오지 않은 지역</h2><ul>"
            + "".join(blocks)
            + "</ul><p class='note'>이 지역을 원하신다면 자기자금을 늘리거나, "
            "더 작은 평형 또는 인접 지역으로 범위를 넓혀야 합니다.</p>"
        )

    jeonse_ratios = [
        float(c["jeonseRatioPct"])
        for c in reachable
        if isinstance(c.get("jeonseRatioPct"), (int, float))
    ]
    supply_html = render_supply(order["검토지역"], jeonse_ratios)

    repayment_html = render_repayment(order, snapshot)
    field_check_html = render_field_checklist(budget)

    checklist = "".join(f"<li>{_esc(x)}</li>" for x in COMMON_CHECKLIST)
    sources = snapshot.get("sources") or []
    source_items = "".join(
        f"<li>{_esc(s.get('agency'))} · {_esc(s.get('title'))} "
        f"({_esc(s.get('publishedAt'))}) <a href='{_esc(s.get('url'))}'>원문</a></li>"
        for s in sources
    )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>집픽 매수 진단 리포트 · {_esc(order.get('주문번호'))}</title>
<style>{CSS}</style></head><body><div class="page">

<h1>집픽 매수 진단 리포트</h1>
<p class="sub">국토교통부 실거래가와 금융위원회 정책 기준으로 계산한 개인 맞춤 분석 · {today} 기준</p>
{meta}
{area_warning}
{verdict}
{tradeoff_html}

<h2>1. 지금 살 수 있는 가격</h2>
<div class="stat">
  <div><div class="k">매수 가능 상한</div><div class="v">{_eok(budget)}</div></div>
  <div><div class="k">예상 대출 한도</div><div class="v">{_eok(snapshot.get('estimatedLoanLimitEok'))}</div></div>
  <div><div class="k">보유 현금</div><div class="v">{_eok(snapshot.get('cashEok'))}</div></div>
</div>
<table>
  <tr><th>DSR 기준 대출 한도</th><td class="num">{_eok(snapshot.get('dsrLoanLimitEok'))}</td></tr>
  <tr><th>주택가격 상한 기준</th><td class="num">{_eok(snapshot.get('priceCapEok'))}</td></tr>
  <tr><th>부대비용 반영률</th><td class="num">{_esc(snapshot.get('purchaseCostRatePercent'))}%</td></tr>
</table>
<p class="note">DSR, LTV, 주택가격별 대출 상한, 부대비용을 함께 반영했습니다.
세 기준 중 가장 낮은 값이 실제 한도가 됩니다. 계약 전 은행 두 곳 이상에서 확인하세요.</p>
{repayment_html}

<h2>2. 검토한 단지 한눈에 비교</h2>
{render_compare_table(reachable, reference, budget)}
{reference_note}

<h2>3. 실질 후보 상세</h2>
{detail if detail else "<p>지금 자금으로 계약까지 갈 수 있는 단지가 없습니다.</p>"}

{supply_html}

{empty_html}

{field_check_html}

<h2>다음에 하실 일</h2>
<ol>{checklist}</ol>

<h2>계산에 사용한 정책 기준</h2>
<p class="note">정책 기준일 {_esc(snapshot.get('asOf'))} · 버전 {_esc(snapshot.get('version'))}</p>
<ul>{source_items}</ul>

<div class="disclaimer">
<h4>이 리포트를 읽기 전에 반드시 확인해 주세요</h4>
<ul>
<li>이 리포트는 공개된 실거래가와 정부 정책 자료를 정리·분석한 <b>정보 제공 자료</b>입니다.
특정 매물의 매매를 알선하거나 중개하지 않으며, 투자를 권유하지 않습니다.</li>
<li>매수 여부와 그 결과에 대한 판단과 책임은 전적으로 이용자 본인에게 있습니다.
집픽은 매수 결과로 발생한 손익에 대해 책임지지 않습니다.</li>
<li>가격은 국토교통부 실거래가 공개 자료 기준이며, 신고 시차로 최신 거래가 빠져 있을 수 있습니다.
현재 호가와는 다를 수 있으므로 반드시 직접 확인하세요.</li>
<li>대출 한도와 정책 판정은 공개된 기준에 따른 참고값입니다.
실제 한도는 금융회사의 개별 심사 결과에 따릅니다.</li>
<li>이 리포트는 수익이나 가격 상승을 보장하지 않습니다.</li>
<li>리포트 작성에 사용한 고객 정보는 전달 완료 후 파기합니다.</li>
</ul>
</div>

</div></body></html>"""


def build(order_path):
    order = json.loads(Path(order_path).read_text(encoding="utf-8"))
    print(f"[{order.get('주문번호')}] 구매력 계산 중...")
    power = fetch_purchase_power(order)
    if power.get("error"):
        raise SystemExit(f"구매력 계산 실패: {power['error']}")
    budget = power["budgetEok"]
    print(f"  매수 상한 {budget}억")

    results = []
    for region in order["검토지역"]:
        print(f"  {region} 후보 검색 중...")
        payload = fetch_candidates(order, region, budget)
        results.append((region, payload))
        print(f"    후보 {len(payload.get('candidates') or [])}곳")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{order.get('주문번호', 'report')}_{order.get('고객명', '')}.html"
    out = OUTPUT_DIR / name
    out.write_text(render_report(order, power, results), encoding="utf-8")
    print(f"완료 → {out}")
    return out


def main():
    paths = sys.argv[1:]
    if not paths:
        paths = sorted(str(p) for p in ORDER_DIR.glob("*.json"))
    if not paths:
        raise SystemExit(f"주문서가 없습니다. {ORDER_DIR}에 JSON을 넣어주세요.")
    for path in paths:
        build(path)


if __name__ == "__main__":
    main()
