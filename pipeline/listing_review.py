"""계약 직전 특정 매물의 제시가격·자금·확인사항을 검토한다."""

import datetime
import math
import statistics
import uuid

import policy_evaluator


REVIEW_VERSION = "listing-review-v1"
DEFAULT_PURCHASE_COST_RATE_PERCENT = 3.0
DEFAULT_EMERGENCY_MONTHS = 6


def _float(value):
    return policy_evaluator._float(value)


def _round_money(value):
    return round(max(0, float(value or 0)), 2)


def _monthly_payment_manwon(principal_eok, annual_rate_percent, years):
    principal_manwon = max(0, float(principal_eok or 0)) * 10000
    months = max(1, int(float(years or 30)) * 12)
    monthly_rate = max(0, float(annual_rate_percent or 0)) / 100 / 12
    if not principal_manwon:
        return 0
    if not monthly_rate:
        return round(principal_manwon / months)
    payment = (
        principal_manwon
        * monthly_rate
        * (1 + monthly_rate) ** months
        / ((1 + monthly_rate) ** months - 1)
    )
    return round(payment)


def _profile_complete(raw_profile):
    if not isinstance(raw_profile, dict):
        return False
    co_borrower = str(raw_profile.get("co_borrower") or "false").lower()
    return bool(
        str(raw_profile.get("home_ownership") or "") in policy_evaluator.HOME_OWNERSHIP_LABELS
        and str(raw_profile.get("home_ownership") or "") != "unknown"
        and str(raw_profile.get("first_time", "")).lower() in {"true", "false"}
        and _float(raw_profile.get("cash_eok")) > 0
        and _float(raw_profile.get("annual_income")) > 0
        and _float(raw_profile.get("mortgage_rate")) > 0
        and (
            co_borrower not in {"1", "true", "yes", "on"}
            or _float(raw_profile.get("spouse_annual_income")) > 0
        )
    )


def _profile(raw_profile, purchase_cost_rate):
    raw_profile = raw_profile if isinstance(raw_profile, dict) else {}
    return policy_evaluator.user_profile(
        home_ownership=raw_profile.get("home_ownership") or "unknown",
        first_time=raw_profile.get("first_time") or False,
        cash_eok=raw_profile.get("cash_eok") or 0,
        annual_income=raw_profile.get("annual_income") or 0,
        monthly_debt_payment=raw_profile.get("monthly_debt_payment") or 0,
        co_borrower=raw_profile.get("co_borrower") or False,
        spouse_annual_income=raw_profile.get("spouse_annual_income") or 0,
        spouse_monthly_debt_payment=raw_profile.get("spouse_monthly_debt_payment") or 0,
        mortgage_rate=raw_profile.get("mortgage_rate") or 0,
        loan_term_years=raw_profile.get("loan_term_years") or 30,
        purchase_cost_rate=purchase_cost_rate,
    )


def _comparables(affordability):
    market = affordability.get("market") if isinstance(affordability, dict) else {}
    rows = market.get("adjustedTransactions") if isinstance(market, dict) else []
    comparables = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        price = _float(
            row.get("adjustedPriceEok")
            or row.get("originalPriceEok")
            or row.get("dealAmountEok")
            or row.get("priceEok")
        )
        if price <= 0:
            continue
        comparables.append({
            "dealDate": str(row.get("dealDate") or ""),
            "priceEok": _round_money(price),
            "originalPriceEok": _round_money(
                row.get("originalPriceEok")
                or row.get("dealAmountEok")
                or price
            ),
            "exclusiveArea": _float(row.get("exclusiveArea")) or None,
            "floor": str(row.get("floor") or ""),
            "adjustment": str(row.get("adjustment") or ""),
        })
    comparables.sort(key=lambda row: row["dealDate"], reverse=True)
    return comparables


def _market_reference(affordability, comparables):
    estimate = affordability.get("estimate") if isinstance(affordability, dict) else {}
    estimate = estimate if isinstance(estimate, dict) else {}
    prices = [row["priceEok"] for row in comparables if row["priceEok"] > 0]
    median = statistics.median(prices) if prices else 0
    low = _float(estimate.get("minPriceEok"))
    mid = _float(estimate.get("midPriceEok")) or median
    high = _float(estimate.get("maxPriceEok"))
    if not low and prices:
        ordered = sorted(prices)
        low = ordered[max(0, math.floor((len(ordered) - 1) * 0.1))]
    if not high and prices:
        ordered = sorted(prices)
        high = ordered[min(len(ordered) - 1, math.ceil((len(ordered) - 1) * 0.9))]
    if mid and not low:
        low = mid
    if mid and not high:
        high = mid
    return {
        "lowPriceEok": _round_money(min(low, high) if low and high else low or high),
        "midPriceEok": _round_money(mid),
        "highPriceEok": _round_money(max(low, high) if low and high else low or high),
        "sampleCount": int(_float(estimate.get("sampleCount")) or len(comparables)),
        "confidence": str(estimate.get("confidence") or "낮음"),
        "latestTradeDate": str(estimate.get("latestTradeDate") or ""),
        "latestTradeAgeDays": int(_float(estimate.get("latestTradeAgeDays"))),
        "method": str(estimate.get("method") or "최근 실거래 가격대"),
        "source": str(estimate.get("source") or "molit"),
    }


def _checklist(listing):
    tenancy = str(listing.get("tenancy") or "unknown")
    condition = str(listing.get("condition") or "unknown")
    rows = [
        {
            "category": "권리",
            "title": "계약 당일 최신 등기부등본 다시 확인",
            "detail": "소유자, 근저당·압류·가압류와 계약 상대방의 신분을 대조하세요.",
        },
        {
            "category": "권리",
            "title": "세금·관리비 체납과 전입세대 확인",
            "detail": "잔금 전 말소 조건과 체납 정산 주체를 특약에 적으세요.",
        },
        {
            "category": "가격",
            "title": "같은 평형 최근 거래의 동·층 차이 확인",
            "detail": "저층·특수관계·수리 여부가 다른 거래는 그대로 비교하지 마세요.",
        },
        {
            "category": "현장",
            "title": "누수·결로·층간소음·주차를 현장에서 확인",
            "detail": "낮과 저녁에 한 번씩 보고 수리비가 생기면 협상가격에 반영하세요.",
        },
        {
            "category": "일정",
            "title": "계약금·중도금·잔금과 대출 실행일 연결",
            "detail": "대출 승인 전 무리한 계약금 지급을 피하고 해제 조건을 확인하세요.",
        },
    ]
    if tenancy == "occupied":
        rows.insert(2, {
            "category": "일정",
            "title": "기존 임차인의 보증금·퇴거일 확인",
            "detail": "보증금 반환과 명도 완료를 잔금 지급 조건에 연결하세요.",
        })
    elif tenancy == "unknown":
        rows.insert(2, {
            "category": "일정",
            "title": "세입자 점유 여부와 실제 입주 가능일 확인",
            "detail": "점유 관계가 확인되기 전에는 입주일을 확정하지 마세요.",
        })
    if condition in {"original", "partial"}:
        rows.append({
            "category": "현장",
            "title": "수리 범위와 견적을 계약 전에 확정",
            "detail": "샷시·배관·전기·욕실처럼 큰 비용 항목을 별도 견적으로 확인하세요.",
        })
    return rows


def _risks(listing, pricing, financing):
    rows = []
    asking = pricing["askingPriceEok"]
    high = pricing["marketHighPriceEok"]
    if high and asking > high:
        rows.append({
            "level": "high",
            "title": "제시가격이 실거래 검토 범위 상단보다 높아요.",
            "detail": f"상단 대비 {round((asking - high) * 10000):,}만원 높습니다.",
        })
    if pricing["sampleCount"] < 5:
        rows.append({
            "level": "medium",
            "title": "같은 평형의 최근 거래 표본이 적어요.",
            "detail": "몇 건의 특수 거래가 기준가격을 흔들 수 있어 현재 매물과 직접 비교해야 합니다.",
        })
    if pricing["latestTradeAgeDays"] >= 120:
        rows.append({
            "level": "medium",
            "title": "마지막 실거래가 4개월보다 오래됐어요.",
            "detail": "현재 호가와 최근 지역 흐름을 함께 확인해야 합니다.",
        })
    if financing.get("profileComplete") and financing.get("cashGapEok", 0) < 0:
        rows.append({
            "level": "high",
            "title": "현재 자기자금과 예상 대출만으로는 부족해요.",
            "detail": f"약 {round(abs(financing['cashGapEok']) * 10000):,}만원의 추가 자금이 필요합니다.",
        })
    if not str(listing.get("floor") or "").strip():
        rows.append({
            "level": "low",
            "title": "동·층 정보가 없어 실거래 가격 차이를 설명하기 어려워요.",
            "detail": "정확한 동과 층을 입력하거나 계약 전에 확인하세요.",
        })
    if str(listing.get("orientation") or "unknown") == "unknown":
        rows.append({
            "level": "low",
            "title": "향과 일조 조건을 확인하지 않았어요.",
            "detail": "같은 평형에서도 향·조망·소음에 따라 실제 체감가가 달라집니다.",
        })
    if str(listing.get("tenancy") or "unknown") == "occupied":
        rows.append({
            "level": "medium",
            "title": "세입자 보증금과 퇴거 일정 확인이 필요해요.",
            "detail": "보증금 반환과 명도 완료를 잔금 조건에 연결하세요.",
        })
    return rows[:6]


def build_review(arguments, affordability):
    """특정 매물의 검토 결과를 JSON 직렬화 가능한 구조로 반환한다."""
    name = str(arguments.get("name") or "").strip()
    region = str(arguments.get("region") or "").strip()
    asking_price = _float(arguments.get("asking_price_eok"))
    if len(name) < 2 or len(region) < 2:
        raise ValueError("단지명과 지역을 확인해 주세요.")
    if asking_price <= 0:
        raise ValueError("매도인이 제시한 매물가격을 입력해 주세요.")

    listing = {
        "askingPriceEok": _round_money(asking_price),
        "area": str(arguments.get("area") or affordability.get("selectedArea") or "").strip(),
        "building": str(arguments.get("building") or "").strip(),
        "floor": str(arguments.get("floor") or "").strip(),
        "orientation": str(arguments.get("orientation") or "unknown").strip(),
        "condition": str(arguments.get("condition") or "unknown").strip(),
        "repairCostManwon": round(max(0, _float(arguments.get("repair_cost_manwon")))),
        "tenancy": str(arguments.get("tenancy") or "unknown").strip(),
        "moveInDate": str(arguments.get("move_in_date") or "").strip(),
        "notes": str(arguments.get("notes") or "").strip()[:500],
    }
    comparables = _comparables(affordability)
    market = _market_reference(affordability, comparables)
    raw_profile = arguments.get("profile")
    profile_complete = _profile_complete(raw_profile)
    selected_cost_rate = _float(
        raw_profile.get("purchase_cost_rate")
        if isinstance(raw_profile, dict)
        else 0
    )
    purchase_cost_rate = max(
        DEFAULT_PURCHASE_COST_RATE_PERCENT,
        selected_cost_rate,
    )
    profile = _profile(raw_profile, purchase_cost_rate)

    listing_candidate = {
        "name": name,
        "region": region,
        "minPriceEok": asking_price,
        "midPriceEok": asking_price,
        "maxPriceEok": asking_price,
        "latestDealPriceEok": asking_price,
    }
    impact = (
        policy_evaluator.evaluate_candidate(listing_candidate, profile=profile)
        if profile_complete
        else None
    )
    purchase_cost = _round_money(asking_price * purchase_cost_rate / 100)
    repair_cost = _round_money(listing["repairCostManwon"] / 10000)
    total_cash_cost = _round_money(asking_price + purchase_cost + repair_cost)

    combined_income = profile.get("combinedIncomeManwon", 0)
    emergency_fund = _round_money(
        combined_income / 12 * DEFAULT_EMERGENCY_MONTHS / 10000
    )
    loan_limit = _round_money((impact or {}).get("estimatedLoanLimitEok"))
    cash = _round_money(profile.get("cashEok"))
    required_loan = _round_money(max(0, total_cash_cost - cash))
    financed_loan = _round_money(min(required_loan, loan_limit))
    cash_gap = (
        round(cash + loan_limit - total_cash_cost, 2)
        if profile_complete
        else None
    )
    cash_after_purchase = (
        round(cash - max(0, total_cash_cost - financed_loan), 2)
        if profile_complete
        else None
    )
    safe_cash = max(0, cash - emergency_fund)
    safe_budget = (
        _round_money((safe_cash + loan_limit) / (1 + purchase_cost_rate / 100))
        if profile_complete
        else 0
    )
    monthly_payment = _monthly_payment_manwon(
        financed_loan,
        profile.get("mortgageRatePercent"),
        profile.get("loanTermYears"),
    )
    stress_monthly_payment = _monthly_payment_manwon(
        financed_loan,
        profile.get("mortgageRatePercent", 0) + 1,
        profile.get("loanTermYears"),
    )
    monthly_income = combined_income / 12 if combined_income else 0
    payment_ratio = (
        round(monthly_payment / monthly_income * 100, 1)
        if monthly_income
        else None
    )

    market_mid = market["midPriceEok"] or asking_price
    market_high = market["highPriceEok"] or market_mid
    market_low = market["lowPriceEok"] or market_mid
    repair_discount = repair_cost if listing["condition"] in {"original", "partial"} else 0
    market_ceiling = max(market_low, market_high - repair_discount)
    review_ceiling = (
        min(market_ceiling, safe_budget)
        if profile_complete and safe_budget > 0
        else market_ceiling
    )
    review_ceiling = _round_money(review_ceiling)
    negotiation_start = _round_money(
        max(market_low, min(market_mid - repair_discount, review_ceiling * 0.98))
    )
    premium_eok = round(asking_price - market_mid, 2)
    premium_percent = (
        round(premium_eok / market_mid * 100, 1)
        if market_mid
        else None
    )

    financing = {
        "profileComplete": profile_complete,
        "cashEok": cash if profile_complete else None,
        "combinedIncomeManwon": combined_income if profile_complete else None,
        "loanLimitEok": loan_limit if profile_complete else None,
        "requiredLoanEok": required_loan if profile_complete else None,
        "financedLoanEok": financed_loan if profile_complete else None,
        "purchaseCostRatePercent": purchase_cost_rate,
        "purchaseCostEok": purchase_cost,
        "repairCostEok": repair_cost,
        "totalCashCostEok": total_cash_cost,
        "cashGapEok": cash_gap,
        "cashAfterPurchaseEok": cash_after_purchase,
        "emergencyFundEok": emergency_fund if profile_complete else None,
        "safeBudgetEok": safe_budget if profile_complete else None,
        "monthlyPaymentManwon": monthly_payment if profile_complete else None,
        "stressMonthlyPaymentManwon": stress_monthly_payment if profile_complete else None,
        "monthlyPaymentRatioPercent": payment_ratio,
        "mortgageRatePercent": profile.get("mortgageRatePercent") if profile_complete else None,
        "loanTermYears": profile.get("loanTermYears") if profile_complete else None,
        "policyImpact": impact,
    }
    pricing = {
        "askingPriceEok": _round_money(asking_price),
        "marketLowPriceEok": market_low,
        "marketMidPriceEok": market_mid,
        "marketHighPriceEok": market_high,
        "premiumEok": premium_eok,
        "premiumPercent": premium_percent,
        "negotiationStartPriceEok": negotiation_start,
        "reviewCeilingPriceEok": review_ceiling,
        "sampleCount": market["sampleCount"],
        "confidence": market["confidence"],
        "latestTradeDate": market["latestTradeDate"],
        "latestTradeAgeDays": market["latestTradeAgeDays"],
        "method": market["method"],
        "source": market["source"],
    }
    risks = _risks(listing, pricing, financing)

    if profile_complete and cash_gap is not None and cash_gap < 0:
        verdict = {
            "code": "funding_short",
            "label": "추가 자금 필요",
            "tone": "danger",
            "summary": "현재 자기자금과 예상 대출만으로는 계약하기 어려워요.",
        }
    elif asking_price > review_ceiling + 0.01:
        verdict = {
            "code": "negotiate",
            "label": "가격 협상 필요",
            "tone": "warning",
            "summary": "제시가격 그대로보다 검토 상한 안으로 협상하는 편이 안전해요.",
        }
    elif market["sampleCount"] < 3 or market["latestTradeAgeDays"] >= 180:
        verdict = {
            "code": "check_more",
            "label": "추가 확인 후 결정",
            "tone": "neutral",
            "summary": "실거래 근거가 부족해 현장 조건과 최신 호가 확인이 먼저예요.",
        }
    elif asking_price <= market_mid and (not profile_complete or cash_gap >= 0):
        verdict = {
            "code": "reviewable",
            "label": "검토 가능",
            "tone": "good",
            "summary": "최근 실거래 범위와 현재 자금 조건 안에서 검토할 수 있어요.",
        }
    else:
        verdict = {
            "code": "conditional",
            "label": "조건부 검토",
            "tone": "neutral",
            "summary": "가격과 현장 조건을 확인한 뒤 계약 여부를 결정하세요.",
        }

    today = datetime.date.today().isoformat()
    return {
        "id": uuid.uuid4().hex[:16],
        "version": REVIEW_VERSION,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "asOf": today,
        "apartment": {
            "name": name,
            "region": region,
            "areaBasis": affordability.get("areaBasis") or "",
        },
        "listing": listing,
        "verdict": verdict,
        "pricing": pricing,
        "financing": financing,
        "risks": risks,
        "checklist": _checklist(listing),
        "comparables": comparables[:10],
        "sources": {
            "price": market["source"],
            "priceMethod": market["method"],
            "policyAsOf": (impact or {}).get("asOf"),
        },
        "disclaimer": (
            "실거래와 입력 조건을 바탕으로 한 계약 전 참고자료이며 감정평가, "
            "대출 승인, 법률·세무 자문을 대신하지 않습니다."
        ),
    }
