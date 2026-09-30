"""최대 구매 가능 주택가격 계산 엔진.

정책 숫자는 `data/housing_policy_snapshot.json`에서만 읽는다. 이 파일의 함수는
화면과 서버 핸들러에서 분리된 순수 계산이며, 금액 단위는 억원(대출·가격)과
만원(소득·월 상환액)을 쓴다.
"""
import json
import math
from functools import lru_cache

import config
import policy_evaluator

REGIONS_PATH = config.ROOT / "data" / "purchase_regions.json"

# 입력값이 이보다 크면 잘못 입력한 것으로 본다.
MAX_CASH_EOK = 1000
MAX_ANNUAL_INCOME_MANWON = 1_000_000
MAX_MONTHLY_DEBT_MANWON = 100_000
MAX_MORTGAGE_RATE_PERCENT = 30

RATE_TYPE_LABELS = {
    "periodic": "주기형 (5년마다 금리 재산정)",
    "mixed": "혼합형 (5년 고정 후 변동)",
    "variable": "변동형",
}

CONSTRAINT_LABELS = {
    "LTV": "LTV",
    "DSR": "DSR",
    "MORTGAGE_CAP": "주담대 총액한도",
    "OWN_CAPITAL": "자기자금",
    "EXISTING_DEBT": "기존대출",
    "OWNER_RESTRICTION": "유주택자 대출제한",
}


@lru_cache(maxsize=1)
def load_purchase_regions():
    with REGIONS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["regions"]


def _finite(value):
    return value is not None and math.isfinite(value)


def floor_price_eok(value):
    """집값은 100만원 단위로 내린다."""
    return math.floor(max(0, float(value)) * 100 + 1e-9) / 100


def floor_manwon_eok(value):
    """대출·비용은 만원 단위로 내린다."""
    return math.floor(max(0, float(value)) * 10000 + 1e-9) / 10000


def format_korean_money(eok):
    """억원 금액을 '6억 6,600만원'처럼 읽기 쉽게 바꾼다."""
    manwon = int(round(max(0, float(eok)) * 10000))
    eok_part, man_part = divmod(manwon, 10000)
    if eok_part and man_part:
        return f"{eok_part}억 {man_part:,}만원"
    if eok_part:
        return f"{eok_part}억원"
    return f"{man_part:,}만원"


# 구매력 입력용 큰 지역 묶음. 상세 지역은 집 조건에서 고르고, 후보 카드는 단지별로
# 다시 판정한다. 규제지역 여부는 정책 설정의 규제지역 목록에서 가져온다.
PURCHASE_REGION_GROUPS = [
    {"regionCode": "seoul", "label": "서울", "province": "서울특별시", "isCapitalArea": True, "regulated": "allSeoul"},
    {"regionCode": "gyeonggi_regulated", "label": "경기 규제지역", "province": "경기도", "isCapitalArea": True, "regulated": True},
    {"regionCode": "gyeonggi_general", "label": "경기 비규제지역", "province": "경기도", "isCapitalArea": True, "regulated": False},
    {"regionCode": "incheon", "label": "인천", "province": "인천광역시", "isCapitalArea": True, "regulated": False},
]


def purchase_region_groups(snapshot=None):
    """화면에 보여 줄 큰 지역 묶음과 각 묶음의 정책 판단값."""
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    regulated = snapshot["regulatedRegions"]
    gyeonggi_regulated = list(regulated.get("gyeonggi", []))
    groups = []
    for group in PURCHASE_REGION_GROUPS:
        is_regulated = bool(regulated.get("allSeoul")) if group["regulated"] == "allSeoul" else bool(group["regulated"])
        if group["regionCode"] == "gyeonggi_regulated":
            description = ", ".join(gyeonggi_regulated)
        elif group["regionCode"] == "gyeonggi_general":
            description = "경기 규제지역을 뺀 나머지 시·군·구"
        elif group["regionCode"] == "seoul":
            description = "서울 25개 구 전체가 규제지역이에요" if is_regulated else "서울 전체"
        else:
            description = "인천 전체"
        groups.append({
            "regionCode": group["regionCode"],
            "province": group["province"],
            "district": group["label"],
            "label": group["label"],
            "description": description,
            "isCapitalArea": group["isCapitalArea"],
            "isRegulatedArea": is_regulated,
        })
    return groups


def resolve_region_policy(region_code, snapshot=None):
    """큰 지역 묶음 코드나 시·군·구 코드로 수도권·규제지역 여부를 판단한다."""
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    code = str(region_code or "").strip()
    group = next((item for item in purchase_region_groups(snapshot) if item["regionCode"] == code), None)
    if group:
        return {key: group[key] for key in ("regionCode", "province", "district", "label", "isCapitalArea", "isRegulatedArea")}
    region = next((item for item in load_purchase_regions() if item["code"] == code), None)
    if not region:
        return None
    context = policy_evaluator._region_context(
        {"region": region["district"]},
        {"city": region["province"], "district": region["district"]},
    )
    return {
        "regionCode": code,
        "province": region["province"],
        "district": region["district"],
        "label": f"{region['province']} {region['district']}",
        "isCapitalArea": bool(context["isCapitalRegion"]),
        "isRegulatedArea": bool(policy_evaluator._is_regulated(context, snapshot)),
    }


def resolve_ltv_policy(region_policy, home_ownership, first_time_buyer, snapshot=None):
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    rate, basis = policy_evaluator._ltv(
        {"homeOwnership": home_ownership, "firstTimeBuyer": bool(first_time_buyer)},
        {"isCapitalRegion": region_policy["isCapitalArea"]},
        region_policy["isRegulatedArea"],
        snapshot,
    )
    return {"rate": float(rate), "basis": basis}


def resolve_stress_rate(capital_or_regulated, rate_type=None, snapshot=None):
    """지역 기준 스트레스 금리에 금리 유형별 반영 비율을 곱한다."""
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    kind = rate_type if rate_type in RATE_TYPE_LABELS else snapshot.get("defaultMortgageRateType", "variable")
    base = float(snapshot["stressRatePercent"] if capital_or_regulated else snapshot["nonCapitalStressRatePercent"])
    ratios = snapshot.get("stressRateRatios", {}).get("capitalOrRegulated" if capital_or_regulated else "nonCapital", {})
    ratio = float(ratios.get(kind, 1.0))
    return {
        "rateType": kind,
        "rateTypeLabel": RATE_TYPE_LABELS[kind],
        "basePercent": base,
        "ratio": ratio,
        "percent": round(base * ratio, 4),
    }


def get_housing_policy(region_policy, home_ownership, first_time_buyer, snapshot=None, lender="bank", rate_type=None):
    """지역·보유 주택·생애최초·금리 유형에 맞는 정책값을 한 번에 돌려준다."""
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    capital_or_regulated = region_policy["isCapitalArea"] or region_policy["isRegulatedArea"]
    stress = resolve_stress_rate(capital_or_regulated, rate_type, snapshot)
    ltv = resolve_ltv_policy(region_policy, home_ownership, first_time_buyer, snapshot)
    caps = []
    if capital_or_regulated:
        lower = 0.0
        for band in snapshot["capitalRegionMortgageCaps"]:
            upper = band.get("maxHomePriceEok")
            caps.append({
                "minPriceExclusiveEok": lower,
                "maxPriceEok": float(upper) if upper is not None else None,
                "loanCapEok": float(band["maxLoanEok"]),
            })
            lower = float(upper) if upper is not None else lower
    restriction = ""
    if ltv["rate"] <= 0:
        restriction = "수도권·규제지역에서 1주택을 유지하거나 2주택 이상이면 주택구입 목적 주담대를 받을 수 없어요."
    return {
        "ltv": ltv["rate"],
        "ltvBasis": ltv["basis"],
        "dsr": float(snapshot["nonBankDsrRate"] if lender == "non_bank" else snapshot["bankDsrRate"]),
        "stressRatePercent": stress["percent"],
        "stressBasePercent": stress["basePercent"],
        "stressRatio": stress["ratio"],
        "rateType": stress["rateType"],
        "rateTypeLabel": stress["rateTypeLabel"],
        "maxTermYears": int(
            snapshot["capitalRegionMaxLoanTermYears"] if capital_or_regulated else snapshot["nonCapitalMaxLoanTermYears"]
        ),
        "mortgageAbsoluteLimits": caps,
        "firstTimeLoanCapEok": float(snapshot["firstTimeMaxLoanEok"]) if first_time_buyer else None,
        "moveInRequirementMonths": int(snapshot["moveInMonths"]) if capital_or_regulated else None,
        "disposalRequirementMonths": (
            int(snapshot["conditionalDisposalMonths"])
            if home_ownership == "conditional_one_home" and capital_or_regulated
            else None
        ),
        "restrictionReason": restriction,
        "policyDate": snapshot.get("policyDate") or snapshot.get("asOf"),
    }


def resolve_mortgage_absolute_limit(price_eok, housing_policy):
    """주택가격에 따른 주담대 절대한도(없으면 None)."""
    limits = []
    for band in housing_policy["mortgageAbsoluteLimits"]:
        upper = band["maxPriceEok"]
        if price_eok > band["minPriceExclusiveEok"] and (upper is None or price_eok <= upper):
            limits.append(band["loanCapEok"])
            break
    if housing_policy.get("firstTimeLoanCapEok") is not None:
        limits.append(housing_policy["firstTimeLoanCapEok"])
    return min(limits) if limits else None


def calculate_dsr_capacity(annual_income_manwon, monthly_debt_manwon, dsr_rate):
    """간편 추정: 연소득 × DSR − 기존 월 상환액 × 12."""
    limit = max(0.0, float(annual_income_manwon)) * float(dsr_rate)
    existing = max(0.0, float(monthly_debt_manwon)) * 12
    return {
        "annualLimitManwon": round(limit, 2),
        "existingAnnualManwon": round(existing, 2),
        "availableAnnualManwon": round(max(0.0, limit - existing), 2),
        "isExhausted": limit - existing <= 0,
    }


def calculate_mortgage_principal_from_payment(monthly_payment, annual_rate_percent, years):
    """원리금균등상환에서 월 상환액으로 갚을 수 있는 최대 원금을 역산한다.

    원금 단위는 월 상환액 단위와 같다.
    """
    payment = max(0.0, float(monthly_payment))
    months = max(1, int(years) * 12)
    rate = max(0.0, float(annual_rate_percent)) / 100 / 12
    if payment == 0:
        return 0.0
    if rate == 0:
        return payment * months
    return payment * (1 - (1 + rate) ** -months) / rate


def calculate_monthly_payment(principal, annual_rate_percent, years):
    principal = max(0.0, float(principal))
    months = max(1, int(years) * 12)
    rate = max(0.0, float(annual_rate_percent)) / 100 / 12
    if principal == 0:
        return 0.0
    if rate == 0:
        return principal / months
    return principal * rate / (1 - (1 + rate) ** -months)


def _price_segments(housing_policy):
    """주담대 절대한도가 바뀌는 가격 구간. 한도가 없으면 한 구간이다."""
    first_time_cap = housing_policy.get("firstTimeLoanCapEok")
    bands = housing_policy["mortgageAbsoluteLimits"]
    if not bands:
        return [{"id": "all", "minPriceExclusiveEok": 0.0, "maxPriceEok": None, "loanCapEok": first_time_cap}]
    segments = []
    for index, band in enumerate(bands):
        cap = band["loanCapEok"]
        if first_time_cap is not None:
            cap = min(cap, first_time_cap)
        segments.append({
            "id": f"band_{index + 1}",
            "minPriceExclusiveEok": band["minPriceExclusiveEok"],
            "maxPriceEok": band["maxPriceEok"],
            "loanCapEok": cap,
        })
    return segments


def calculate_max_purchase_price(own_capital_eok, dsr_limit_eok, housing_policy, purchase_cost_rate=0.0):
    """P + 부대비용 <= 자기자금 + min(LTV×P, DSR한도, 절대한도(P))인 가장 큰 P.

    절대한도가 가격 구간마다 달라서 구간별로 닫힌 식을 풀고 가장 큰 값을 고른다.
    구간 안에서는 두 제약만 남는다.
      LTV:  P × (1 + 비용률 − LTV) <= 자기자금
      고정: P × (1 + 비용률) <= 자기자금 + min(DSR한도, 구간 절대한도)
    """
    cash = max(0.0, float(own_capital_eok))
    dsr_limit = max(0.0, float(dsr_limit_eok))
    cost_rate = max(0.0, float(purchase_cost_rate))
    ltv = max(0.0, float(housing_policy["ltv"]))
    best = None
    for segment in _price_segments(housing_policy):
        cap = segment["loanCapEok"]
        fixed_limit = dsr_limit if cap is None else min(dsr_limit, cap)
        if ltv <= 0:
            fixed_limit = 0.0
        own_share = 1 + cost_rate - ltv
        price_by_ltv = cash / own_share if own_share > 0 else math.inf
        price_by_fixed = (cash + fixed_limit) / (1 + cost_rate)
        price = min(price_by_ltv, price_by_fixed)
        upper = segment["maxPriceEok"]
        clipped = upper is not None and price > upper
        if clipped:
            price = upper
        price = floor_price_eok(price)
        if price <= segment["minPriceExclusiveEok"]:
            continue
        if best is None or price > best["priceEok"]:
            best = {
                "segmentId": segment["id"],
                "priceEok": price,
                "clippedAtSegmentTop": clipped,
                "priceByLtvEok": price_by_ltv if math.isfinite(price_by_ltv) else None,
                "priceByFixedLimitEok": price_by_fixed,
                "segmentLoanCapEok": cap,
            }
    if best is None:
        return None
    price = best["priceEok"]
    purchase_cost = floor_manwon_eok(price * cost_rate)
    loan = floor_manwon_eok(max(0.0, price + purchase_cost - cash))
    absolute_limit = resolve_mortgage_absolute_limit(price, housing_policy)
    best.update({
        "purchaseCostEok": purchase_cost,
        "loanEok": loan,
        "ownCapitalUsedEok": floor_manwon_eok(min(cash, price + purchase_cost)),
        "ltvLimitEok": floor_manwon_eok(price * ltv),
        "dsrLimitEok": dsr_limit,
        "absoluteLimitEok": absolute_limit,
        "purchaseCostRate": cost_rate,
    })
    return best


def calculate_constraint_reason(result, housing_policy, dsr_capacity):
    """어떤 규제가 최종 금액을 막았는지 사람이 읽을 수 있는 문장으로 만든다."""
    ltv_percent = round(housing_policy["ltv"] * 100)
    if housing_policy["ltv"] <= 0:
        kind = "OWNER_RESTRICTION"
        message = f"{housing_policy['restrictionReason']} 자기자금으로만 계산했어요."
    elif dsr_capacity["isExhausted"]:
        kind = "EXISTING_DEBT"
        message = "현재 입력한 기존 대출 상환액 기준으로는 추가 주택담보대출 여력이 없는 것으로 추정됩니다."
    elif result["clippedAtSegmentTop"]:
        kind = "MORTGAGE_CAP"
        message = (
            f"주담대 총액한도 때문에 {format_korean_money(result['priceEok'])}에서 멈춰요. "
            "이보다 비싼 집은 받을 수 있는 대출 한도가 더 작아져요."
        )
    elif result["priceByLtvEok"] is not None and result["priceByLtvEok"] <= result["priceByFixedLimitEok"] + 1e-9:
        kind = "LTV"
        message = (
            f"현재는 DSR보다 LTV가 먼저 제한돼요. 대출은 집값의 {ltv_percent}%까지만 나와서, "
            f"나머지 {100 - ltv_percent}%를 자기자금으로 채울 수 있는 금액까지 살 수 있어요."
        )
    else:
        cap = result["segmentLoanCapEok"]
        if cap is not None and cap < result["dsrLimitEok"]:
            kind = "MORTGAGE_CAP"
            message = f"현재는 주담대 총액한도({format_korean_money(cap)})가 먼저 제한돼요."
        elif dsr_capacity["existingAnnualManwon"] > 0:
            kind = "EXISTING_DEBT"
            message = (
                "현재는 DSR이 먼저 제한돼요. 기존 대출 상환액 때문에 새로 받을 수 있는 대출이 "
                f"{format_korean_money(result['dsrLimitEok'])}로 줄었어요."
            )
        else:
            kind = "DSR"
            message = (
                "현재는 LTV보다 DSR이 먼저 제한돼요. 연소득으로 갚을 수 있는 대출이 "
                f"{format_korean_money(result['dsrLimitEok'])}까지예요."
            )
    return {"type": kind, "label": CONSTRAINT_LABELS[kind], "message": message}


def _josa(word, with_final, without_final):
    """받침이 있으면 앞의 조사, 없으면 뒤의 조사를 붙인다."""
    last = word[-1] if word else ""
    has_final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 > 0
    return word + (with_final if has_final else without_final)


def _number(raw, name, errors, *, required=False, minimum=0.0, maximum=None, positive=False, label=""):
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if not text:
        if required:
            errors.append(f"{_josa(label, '을', '를')} 입력해 주세요.")
        return None
    try:
        value = float(text)
    except ValueError:
        errors.append(f"{_josa(label, '은', '는')} 숫자로 입력해 주세요.")
        return None
    if not math.isfinite(value):
        errors.append(f"{label} 값을 확인해 주세요.")
        return None
    if value < minimum:
        errors.append(f"{_josa(label, '은', '는')} 0보다 작을 수 없어요.")
        return None
    if positive and value <= 0:
        errors.append(f"{_josa(label, '은', '는')} 0보다 커야 해요.")
        return None
    if maximum is not None and value > maximum:
        errors.append(f"{_josa(label, '이', '가')} 너무 커요. 단위를 확인해 주세요.")
        return None
    return value


def validate_purchase_inputs(raw):
    """서버로 들어온 입력을 검사한다. 오류 문장 목록과 정리된 값을 돌려준다."""
    errors = []
    region_policy = None
    if not str(raw.get("purchase_region") or "").strip():
        errors.append("구매 희망지역을 선택해주세요")
    else:
        region_policy = resolve_region_policy(raw.get("purchase_region"))
        if not region_policy:
            errors.append("구매 희망지역을 다시 선택해 주세요.")
    ownership = str(raw.get("home_ownership") or "").strip()
    if ownership not in {"no_home", "conditional_one_home", "one_home_keep", "multi_home"}:
        errors.append("보유 주택을 선택해 주세요.")
    first_time = str(raw.get("first_time") or "").strip().lower()
    if first_time not in {"true", "false"}:
        errors.append("생애최초 여부를 선택해 주세요.")
    elif first_time == "true" and ownership and ownership != "no_home":
        errors.append("생애최초는 보유 주택을 '무주택'으로 선택한 경우에만 '예'로 적용할 수 있어요.")
    cash = _number(raw.get("cash_eok"), "cash_eok", errors, required=True, positive=True, maximum=MAX_CASH_EOK, label="자기자금")
    income = _number(raw.get("annual_income"), "annual_income", errors, required=True, positive=True, maximum=MAX_ANNUAL_INCOME_MANWON, label="연소득")
    reserve = _number(raw.get("reserve_cash_eok"), "reserve_cash_eok", errors, maximum=MAX_CASH_EOK, label="남겨둘 돈")
    if cash is not None and reserve is not None and reserve >= cash:
        errors.append("남겨둘 돈은 자기자금보다 적어야 해요.")
    debt = _number(raw.get("monthly_debt_payment"), "monthly_debt_payment", errors, maximum=MAX_MONTHLY_DEBT_MANWON, label="월 대출 상환액")
    rate = _number(raw.get("mortgage_rate"), "mortgage_rate", errors, positive=False, maximum=MAX_MORTGAGE_RATE_PERCENT, label="예상 금리")
    term = _number(raw.get("loan_term_years"), "loan_term_years", errors, maximum=50, label="대출 기간")
    rate_type = str(raw.get("rate_type") or "").strip()
    if rate_type and rate_type not in RATE_TYPE_LABELS:
        errors.append("금리 유형을 다시 선택해 주세요.")
    for key, label in (("spouse_annual_income", "배우자 연소득"), ("spouse_monthly_debt_payment", "배우자 월 대출 상환액")):
        _number(raw.get(key), key, errors, maximum=MAX_ANNUAL_INCOME_MANWON, label=label)
    return errors, {
        "regionPolicy": region_policy,
        "cashEok": cash,
        "reserveCashEok": reserve or 0.0,
        "annualIncomeManwon": income,
        "monthlyDebtManwon": debt or 0.0,
        "mortgageRatePercent": rate if rate and rate > 0 else None,
        "loanTermYears": int(term) if term else None,
        "rateType": rate_type or None,
    }


def calculate_purchase_capacity(
    *,
    region_policy,
    home_ownership,
    first_time_buyer,
    own_capital_eok,
    annual_income_manwon,
    monthly_debt_manwon,
    mortgage_rate_percent=None,
    loan_term_years=None,
    purchase_cost_rate=None,
    rate_type=None,
    snapshot=None,
):
    """입력 조건으로 정책상 최대 구매가와 부대비용을 고려한 예상 구매가를 계산한다."""
    snapshot = snapshot or policy_evaluator.load_policy_snapshot()
    housing_policy = get_housing_policy(region_policy, home_ownership, first_time_buyer, snapshot, rate_type=rate_type)
    rate_default = snapshot["mortgageRateDefault"]
    rate = float(mortgage_rate_percent) if mortgage_rate_percent else float(rate_default["value"])
    term = min(int(loan_term_years), housing_policy["maxTermYears"]) if loan_term_years else housing_policy["maxTermYears"]
    cost_rate = float(snapshot["purchaseCostRate"] if purchase_cost_rate is None else purchase_cost_rate)
    stressed_rate = rate + housing_policy["stressRatePercent"]
    dsr_capacity = calculate_dsr_capacity(annual_income_manwon, monthly_debt_manwon, housing_policy["dsr"])
    dsr_limit = floor_manwon_eok(
        calculate_mortgage_principal_from_payment(
            dsr_capacity["availableAnnualManwon"] / 12, stressed_rate, term
        ) / 10000
    )

    def with_repayment(result):
        if not result:
            return None
        monthly = calculate_monthly_payment(result["loanEok"] * 10000, rate, term)
        stressed_monthly = calculate_monthly_payment(result["loanEok"] * 10000, stressed_rate, term)
        income = max(1e-9, float(annual_income_manwon))
        result["monthlyPaymentManwon"] = round(monthly, 2)
        result["dsrPercent"] = round((stressed_monthly * 12 + dsr_capacity["existingAnnualManwon"]) / income * 100, 1)
        return result

    policy_max = with_repayment(calculate_max_purchase_price(own_capital_eok, dsr_limit, housing_policy, 0.0))
    cost_adjusted = with_repayment(calculate_max_purchase_price(own_capital_eok, dsr_limit, housing_policy, cost_rate))
    constraint = calculate_constraint_reason(policy_max, housing_policy, dsr_capacity) if policy_max else None
    return {
        "policyDate": housing_policy["policyDate"],
        "region": region_policy,
        "housingPolicy": housing_policy,
        "mortgageRate": {
            "valuePercent": rate,
            "isDefault": not mortgage_rate_percent,
            "asOf": rate_default["asOf"],
            "source": rate_default["source"],
            "sourceUrl": rate_default.get("sourceUrl"),
        },
        "stressedRatePercent": round(stressed_rate, 2),
        "loanTermYears": term,
        "dsrCapacity": dsr_capacity,
        "dsrLimitEok": dsr_limit,
        "maxPurchase": policy_max,
        "costAdjusted": cost_adjusted,
        "purchaseCostRate": cost_rate,
        "constraint": constraint,
        "isEstimate": True,
    }
