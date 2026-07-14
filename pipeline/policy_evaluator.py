"""현재 시행 중인 주택 정책을 후보와 사용자 조건에 맞춰 설명한다."""
import json
import re
from functools import lru_cache

import config


POLICY_SNAPSHOT_PATH = config.ROOT / "data" / "housing_policy_snapshot.json"

HOME_OWNERSHIP_LABELS = {
    "unknown": "보유 주택 미입력",
    "no_home": "무주택",
    "conditional_one_home": "1주택 처분 예정",
    "one_home_keep": "1주택 유지",
    "multi_home": "다주택",
}


def _compact(value):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def _float(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _money(value):
    amount_manwon = int(round(float(value or 0) * 10000))
    eok, remainder = divmod(abs(amount_manwon), 10000)
    sign = "-" if amount_manwon < 0 else ""
    if eok and remainder:
        return f"{sign}{eok}억 {remainder:,}만원"
    if eok:
        return f"{sign}{eok}억"
    return f"{sign}{remainder:,}만원"


@lru_cache(maxsize=1)
def load_policy_snapshot():
    with POLICY_SNAPSHOT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _annuity_principal_eok(annual_payment_manwon, annual_rate_percent, years):
    monthly_payment = max(0, annual_payment_manwon) / 12
    months = max(1, int(years) * 12)
    monthly_rate = max(0, annual_rate_percent) / 100 / 12
    if monthly_rate == 0:
        principal_manwon = monthly_payment * months
    else:
        principal_manwon = monthly_payment * (1 - (1 + monthly_rate) ** -months) / monthly_rate
    return round(principal_manwon / 10000, 2)


def user_profile(
    home_ownership="unknown",
    first_time=False,
    cash_eok=0,
    annual_income=0,
    monthly_debt_payment=0,
    co_borrower=False,
    spouse_annual_income=0,
    spouse_monthly_debt_payment=0,
    mortgage_rate=0,
    loan_term_years=30,
    purchase_cost_rate=0,
):
    ownership = home_ownership if home_ownership in HOME_OWNERSHIP_LABELS else "unknown"
    joint = str(co_borrower).strip().lower() in {"1", "true", "yes", "y", "on"}
    borrower_income = max(0, _float(annual_income))
    borrower_debt = max(0, _float(monthly_debt_payment))
    spouse_income = max(0, _float(spouse_annual_income)) if joint else 0
    spouse_debt = max(0, _float(spouse_monthly_debt_payment)) if joint else 0
    combined_income = borrower_income + spouse_income
    combined_debt = borrower_debt + spouse_debt
    dsr_room = max(0, round(combined_income * 0.4 - combined_debt * 12)) if combined_income else None
    base_rate = max(0, _float(mortgage_rate))
    term_years = max(10, min(50, int(_float(loan_term_years) or 30)))
    stress_rate = _float(load_policy_snapshot().get("stressRatePercent"))
    dsr_loan_limit = (
        _annuity_principal_eok(dsr_room, base_rate + stress_rate, term_years)
        if dsr_room is not None and base_rate
        else None
    )
    return {
        "homeOwnership": ownership,
        "homeOwnershipLabel": HOME_OWNERSHIP_LABELS[ownership],
        "firstTimeBuyer": str(first_time).strip().lower() in {"1", "true", "yes", "y", "on"},
        "cashEok": max(0, _float(cash_eok)),
        "annualIncomeManwon": borrower_income,
        "monthlyDebtPaymentManwon": borrower_debt,
        "coBorrower": joint,
        "spouseAnnualIncomeManwon": spouse_income,
        "spouseMonthlyDebtPaymentManwon": spouse_debt,
        "combinedIncomeManwon": combined_income,
        "combinedMonthlyDebtPaymentManwon": combined_debt,
        "dsrAnnualRoomManwon": dsr_room,
        "dsrLoanLimitEok": dsr_loan_limit,
        "mortgageRatePercent": base_rate,
        "loanTermYears": term_years,
        "purchaseCostRatePercent": max(0, min(15, _float(purchase_cost_rate))),
    }


def _region_context(candidate, entity=None):
    entity = entity or {}
    row_region = str(candidate.get("region") or "").strip()
    city = str(entity.get("city") or "").strip()
    district = str(entity.get("district") or "").strip()
    legal_dong = str(entity.get("legalDong") or "").strip()
    values = [value for value in (city, district, legal_dong, row_region) if value]
    joined = " ".join(values)
    compact = _compact(joined)

    seoul_districts = {
        "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
        "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
        "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
    }
    is_seoul = "서울" in compact or (not city and row_region in seoul_districts)
    gyeonggi_markers = (
        "경기", "과천", "광명", "의왕", "하남", "구리", "성남", "수원", "안양", "용인", "화성",
        "고양", "남양주", "부천", "김포", "파주", "의정부", "군포", "안산", "시흥", "평택",
    )
    is_gyeonggi = any(marker in compact for marker in gyeonggi_markers)
    is_capital = is_seoul or is_gyeonggi

    display = row_region or district or city or "지역 확인 필요"
    if city and district and _compact(city) not in _compact(district):
        display = f"{city} {district}"
    return {
        "display": display,
        "compact": compact,
        "isSeoul": is_seoul,
        "isGyeonggi": is_gyeonggi,
        "isCapitalRegion": is_capital,
    }


def _is_regulated(region, snapshot):
    if region["isSeoul"] and snapshot["regulatedRegions"].get("allSeoul"):
        return True
    compact = region["compact"]
    for name in snapshot["regulatedRegions"].get("gyeonggi", []):
        key = _compact(name)
        if key in compact or compact in key:
            return True
        # 데이터가 '성남분당구'처럼 시·구를 붙여 보관하는 경우를 지원한다.
        parts = [_compact(part) for part in name.split()]
        if parts and all(part in compact for part in parts):
            return True
    return False


def _price_cap(price_eok, snapshot):
    for band in snapshot.get("capitalRegionMortgageCaps", []):
        ceiling = band.get("maxHomePriceEok")
        if ceiling is None or price_eok <= ceiling:
            return float(band["maxLoanEok"])
    return 0.0


def _ltv(profile, region, regulated, snapshot):
    ownership = profile["homeOwnership"]
    rates = snapshot["ltv"]
    if region["isCapitalRegion"] and ownership in {"one_home_keep", "multi_home"}:
        return float(rates["additionalHomeInCapital"]), "수도권 추가 주택 구입"
    if profile["firstTimeBuyer"] and region["isCapitalRegion"]:
        return float(rates["capitalFirstTime"]), "생애최초 수도권 기준"
    if regulated:
        return float(rates["regulatedGeneral"]), "규제지역 일반 기준"
    if region["isCapitalRegion"]:
        return float(rates["capitalGeneral"]), "수도권 일반 기준"
    return 0.7, "비수도권 일반 기준"


def evaluate_candidate(candidate, entity=None, profile=None):
    snapshot = load_policy_snapshot()
    profile = profile or user_profile()
    region = _region_context(candidate, entity)
    regulated = _is_regulated(region, snapshot)
    min_price = _float(candidate.get("minPriceEok"))
    max_price = _float(candidate.get("maxPriceEok"))
    price = _float(candidate.get("midPriceEok") or max_price or min_price)
    ltv_rate, ltv_basis = _ltv(profile, region, regulated, snapshot)
    ltv_limit = round(price * ltv_rate, 2)
    price_cap = _price_cap(price, snapshot) if region["isCapitalRegion"] else None
    loan_limits = [ltv_limit]
    if price_cap is not None:
        loan_limits.append(price_cap)
    if profile.get("dsrLoanLimitEok") is not None:
        loan_limits.append(profile["dsrLoanLimitEok"])
    estimated_loan = min(loan_limits)
    estimated_loan = max(0, round(estimated_loan, 2))
    purchase_cost = round(price * profile.get("purchaseCostRatePercent", 0) / 100, 2)
    required_cash = max(0, round(price + purchase_cost - estimated_loan, 2))
    cash = profile["cashEok"]
    cash_gap = round(cash - required_cash, 2) if cash else None

    def financing_at(range_price):
        if range_price <= 0:
            return None
        range_limits = [round(range_price * ltv_rate, 2)]
        range_cap = _price_cap(range_price, snapshot) if region["isCapitalRegion"] else None
        if range_cap is not None:
            range_limits.append(range_cap)
        if profile.get("dsrLoanLimitEok") is not None:
            range_limits.append(profile["dsrLoanLimitEok"])
        range_loan = max(0, round(min(range_limits), 2))
        range_cost = round(range_price * profile.get("purchaseCostRatePercent", 0) / 100, 2)
        return {
            "priceEok": range_price,
            "loanLimitEok": range_loan,
            "requiredCashEok": max(0, round(range_price + range_cost - range_loan, 2)),
        }

    low_financing = financing_at(min_price)
    high_financing = financing_at(max_price)

    missing = []
    warnings = []
    obligations = []
    if profile["homeOwnership"] == "unknown":
        missing.append("보유 주택 수")
        warnings.append("보유 주택 수에 따라 LTV와 추가 주택 대출 가능 여부가 달라져요.")
    if not profile["annualIncomeManwon"]:
        missing.append("연소득")
    if profile["homeOwnership"] in {"one_home_keep", "multi_home"} and region["isCapitalRegion"]:
        warnings.append("수도권 추가 주택 구입 목적 주담대는 LTV 0% 적용 대상이에요.")
    if profile["homeOwnership"] == "conditional_one_home":
        obligations.append("기존 주택 처분 조건과 기한을 금융회사에서 확인해야 해요.")
    if region["isCapitalRegion"] and estimated_loan > 0:
        obligations.append(f"구입 목적 주담대 이용 시 원칙적으로 실행일로부터 {snapshot['moveInMonths']}개월 내 전입 대상이에요.")
    if regulated:
        obligations.append("규제지역의 신용대출·전세대출 보유 여부에 따른 제한을 확인해야 해요.")

    dsr_room = profile.get("dsrAnnualRoomManwon")
    if dsr_room is None:
        warnings.append("DSR을 반영하지 않은 담보·가격 한도예요. 연소득을 입력하면 상환 여력을 함께 볼 수 있어요.")
    else:
        warnings.append(f"DSR 40% 기준 연간 추가 원리금 여력 약 {int(dsr_room):,}만원 · 추정 대출원금 {profile.get('dsrLoanLimitEok') or 0:.2f}억원 · 실제 한도는 금융회사 심사 필요")

    if cash_gap is None:
        status = "needs_input"
        status_label = "자기자금 입력 필요"
        missing.append("보유 현금")
    elif cash_gap >= 0:
        status = "possible"
        status_label = "정책상 자금 범위"
    else:
        status = "short"
        status_label = f"추가 자금 {_money(abs(cash_gap))} 필요"

    if ltv_rate == 0 and cash and cash >= price:
        status = "possible"
        status_label = "대출 없이 자금 범위"
    elif ltv_rate == 0 and (not cash or cash < price):
        status = "restricted"
        status_label = "주담대 제한 확인"

    primary_sources = snapshot.get("sources", [])[:3]
    return {
        "asOf": snapshot["asOf"],
        "version": snapshot["version"],
        "regionLabel": region["display"],
        "isCapitalRegion": region["isCapitalRegion"],
        "isRegulated": regulated,
        "regulationLabel": "규제지역" if regulated else "비규제지역",
        "ltvRate": int(round(ltv_rate * 100)),
        "ltvBasis": ltv_basis,
        "ltvLimitEok": ltv_limit,
        "priceCapEok": price_cap,
        "estimatedLoanLimitEok": estimated_loan,
        "dsrLoanLimitEok": profile.get("dsrLoanLimitEok"),
        "purchaseCostEok": purchase_cost,
        "purchaseCostRatePercent": profile.get("purchaseCostRatePercent", 0),
        "requiredCashEok": required_cash,
        "minRequiredCashEok": low_financing["requiredCashEok"] if low_financing else required_cash,
        "maxRequiredCashEok": high_financing["requiredCashEok"] if high_financing else required_cash,
        "minPriceLoanLimitEok": low_financing["loanLimitEok"] if low_financing else estimated_loan,
        "maxPriceLoanLimitEok": high_financing["loanLimitEok"] if high_financing else estimated_loan,
        "cashGapEok": cash_gap,
        "dsrAnnualRoomManwon": dsr_room,
        "stressRatePercent": snapshot.get("stressRatePercent"),
        "status": status,
        "statusLabel": status_label,
        "warnings": warnings[:3],
        "obligations": obligations[:3],
        "missingInputs": list(dict.fromkeys(missing)),
        "sources": primary_sources,
        "disclaimer": "담보·가격 기준의 참고 한도이며 DSR, 소득, 담보평가와 금융회사 심사에 따라 달라질 수 있어요.",
    }


def estimated_purchase_ceiling(profile, regions=None, max_price_eok=30):
    regions = regions or ["서울시", "경기도"]
    best = 0.0
    for region in regions:
        for step in range(1, int(max_price_eok * 10) + 1):
            price = step / 10
            impact = evaluate_candidate({"region": region, "midPriceEok": price}, profile=profile)
            if impact.get("cashGapEok") is not None and impact["cashGapEok"] >= 0:
                best = max(best, price)
    return round(best, 1)


def summarize(impacts, profile):
    snapshot = load_policy_snapshot()
    counts = {"possible": 0, "short": 0, "restricted": 0, "needs_input": 0}
    for impact in impacts:
        status = impact.get("status")
        if status in counts:
            counts[status] += 1
    return {
        "asOf": snapshot["asOf"],
        "version": snapshot["version"],
        "homeOwnership": profile["homeOwnership"],
        "homeOwnershipLabel": profile["homeOwnershipLabel"],
        "firstTimeBuyer": profile["firstTimeBuyer"],
        "cashEok": profile["cashEok"],
        "combinedIncomeManwon": profile.get("combinedIncomeManwon", 0),
        "coBorrower": profile.get("coBorrower", False),
        "dsrLoanLimitEok": profile.get("dsrLoanLimitEok"),
        "mortgageRatePercent": profile.get("mortgageRatePercent", 0),
        "loanTermYears": profile.get("loanTermYears", 30),
        "purchaseCostRatePercent": profile.get("purchaseCostRatePercent", 0),
        "counts": counts,
        "sources": snapshot.get("sources", []),
        "note": "현재 시행 중인 공식 정책을 후보 지역과 사용자 조건에 대입한 참고 결과예요.",
    }
