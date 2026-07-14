"""후보 카드의 '한 줄 판단' 생성.

원칙: 카드 어디에도 이미 보이는 팩트(가격, 대출한도, 배지 숫자, 세대수)는
말하지 않는다. 우선순위는 ① 가격의 시간 맥락(지금 가격은 언제 가격인가)
→ ② 후보군 내 상대 포지션 → ③ 데이터 상태 해석. 전부 결정적 룰이라
숫자 환각이 없고 테스트 가능하다.
"""


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _signals(row):
    return row.get("signals") or {}


def _month_label(month_key):
    try:
        year, month = str(month_key).split("-")
        return f"{int(year)}년 {int(month)}월"
    except (ValueError, AttributeError):
        return ""


def _time_context(row):
    """지금 가격대의 시간적 위치. 카드에 없는 정보의 핵심."""
    signals = _signals(row)
    if signals.get("status") != "ok":
        return None
    spread = signals.get("priceSpreadPct")
    recovery = signals.get("recoveryPct")
    if spread is not None and spread <= 5:
        return "최근 2년간 시세 변동이 5% 이내로 눌려 있던 단지 — 흐름보다 개별 매물 협상이 더 중요함"
    if signals.get("isAtPeak"):
        return "지금 기준가는 최근 2년 내 최고가 구간 — 사면 신고가 부근에 사는 셈이라 조정 리스크를 감안해야 함"
    if signals.get("isAtTrough"):
        return "지금 기준가는 최근 2년 중 가장 낮은 구간 — 싸게 사는 기회인지 하락 진행인지 마지막 거래 시점 확인이 먼저"
    level_month = signals.get("priceLevelMonth")
    if level_month and recovery is not None:
        label = _month_label(level_month)
        drop = max(0, 100 - recovery)
        if label:
            return f"지금 기준가는 {label}에 처음 닿았던 가격대 — 2년 고점보다 {drop:.0f}% 낮게 사는 셈"
    return None


def _rank_suffix(row, ctx):
    if ctx.get("scoredCount", 0) >= 3 and ctx.get("signalRank", {}).get(id(row)) == 1:
        return " · 이번 결과 상승 시그널 1위"
    if ctx.get("count", 0) >= 3 and ctx.get("ppsmRank", {}).get(id(row)) == 1:
        return " · 이번 결과 ㎡당가 최저"
    return ""


def _rank_verdict(row, ctx):
    total = ctx.get("count", 0)
    if total >= 3 and ctx.get("ppsmRank", {}).get(id(row)) == 1:
        return f"이번 결과 {total}곳 중 ㎡당 가격이 가장 낮아 같은 예산에서 면적 효율 1위"
    scored = ctx.get("scoredCount", 0)
    if scored >= 3 and ctx.get("signalRank", {}).get(id(row)) == 1:
        return f"후보 {scored}곳 중 상승 시그널 1위 — 가격 흐름·거래량이 가장 좋은 조합"
    return None


def verdict_for(row, ctx):
    time_context = _time_context(row)
    if time_context:
        return time_context + _rank_suffix(row, ctx)
    rank = _rank_verdict(row, ctx)
    if rank:
        return rank
    if _signals(row).get("status") == "insufficient":
        return "최근 2년 거래 표본이 적어 시세 판단이 어려운 단지 — 호가와 인근 단지 시세를 함께 봐야 함"
    return None


def attach_verdicts(rows, budget_eok):
    ppsm_rows = sorted(
        [row for row in rows if _float(_signals(row).get("currentPpsm")) > 0],
        key=lambda row: _float(_signals(row).get("currentPpsm")),
    )
    scored_rows = sorted(
        [row for row in rows if _signals(row).get("score") is not None],
        key=lambda row: -_float(_signals(row).get("score")),
    )
    ctx = {
        "budgetEok": _float(budget_eok),
        "count": len(ppsm_rows),
        "scoredCount": len(scored_rows),
        "ppsmRank": {id(row): index + 1 for index, row in enumerate(ppsm_rows)},
        "signalRank": {id(row): index + 1 for index, row in enumerate(scored_rows)},
    }
    for row in rows:
        try:
            verdict = verdict_for(row, ctx)
        except Exception:
            verdict = None
        if verdict:
            row["verdict"] = verdict
