#!/usr/bin/env python3
"""집을 사고 되팔 때 드는 돈으로 '본전 상승률'을 계산한다.

집픽은 실거래만 가지고 있어서 미래 가격을 예측하지 않는다.
대신 "얼마나 올라야 손해를 안 보는지"를 계산해서 보여준다.
이 값은 예측이 아니라 세금 규칙으로 정해지는 계산값이다.
"""

MANWON = 10000  # 1만원. 이 파일의 모든 금액 단위는 '원'이다.
EOK = 100000000

# 국민주택 규모. 이보다 크면 농어촌특별세가 붙는다.
NATIONAL_HOUSING_SQM = 85.0

# 1세대 1주택 양도세 비과세 기준 금액과 보유 기간.
CGT_EXEMPT_PRICE = 12 * EOK
CGT_EXEMPT_YEARS = 2

# 공시가격은 시세보다 낮게 잡힌다. 보유세를 어림잡을 때만 쓰는 값이다.
PUBLIC_PRICE_RATIO = 0.69
# 재산세 과세표준을 정할 때 곱하는 비율.
FAIR_MARKET_RATIO = 0.6


def _round_manwon(value):
    """만원 단위로 반올림한다. 화면에 만원 단위로만 보여주기 때문이다."""
    return int(round(value / MANWON)) * MANWON


def acquisition_tax(price, area_sqm=None, owned_houses=1):
    """취득세를 계산한다. 지방교육세와 농어촌특별세를 포함한다.

    2주택 이상 중과세율은 지역과 시점에 따라 자주 바뀌어서 계산하지 않고
    None을 돌려준다. 화면에서는 '조건에 따라 달라져요'로 보여준다.
    """
    if not price or price <= 0:
        return None
    if owned_houses and owned_houses > 1:
        return None

    if price <= 6 * EOK:
        base_rate = 0.01
    elif price <= 9 * EOK:
        # 6억~9억 구간은 계단이 아니라 기울기다.
        base_rate = (price / EOK * (2 / 3) - 3) / 100
    else:
        base_rate = 0.03

    # 지방교육세는 취득세율의 10분의 1이다.
    local_education_rate = base_rate * 0.1
    # 85㎡를 넘는 집에는 농어촌특별세 0.2%가 붙는다.
    rural_rate = 0.002 if area_sqm and area_sqm > NATIONAL_HOUSING_SQM else 0.0

    total_rate = base_rate + local_education_rate + rural_rate
    return {
        "amount": _round_manwon(price * total_rate),
        "rate": round(total_rate, 5),
        "label": "취득세",
    }


def brokerage_fee(price):
    """서울 주택 매매 중개보수 상한을 계산한다.

    실제로는 깎아서 내는 경우가 많지만, 상한으로 계산해야 본전선을
    낙관적으로 잡지 않는다.
    """
    if not price or price <= 0:
        return None
    if price < 5000 * MANWON:
        rate = 0.006
    elif price < 2 * EOK:
        rate = 0.005
    elif price < 9 * EOK:
        rate = 0.004
    elif price < 12 * EOK:
        rate = 0.005
    elif price < 15 * EOK:
        rate = 0.006
    else:
        rate = 0.007
    return {"amount": _round_manwon(price * rate), "rate": rate}


def property_tax_estimate(price, years):
    """보유 기간 동안 낼 재산세를 어림잡는다.

    공시가격과 세율 구간을 모두 반영한 정확한 세액이 아니다.
    화면에서는 반드시 '약'을 붙여서 보여준다.
    """
    if not price or price <= 0 or not years or years <= 0:
        return None
    public_price = price * PUBLIC_PRICE_RATIO
    tax_base = public_price * FAIR_MARKET_RATIO

    # 주택 재산세 누진 구간
    if tax_base <= 6000 * MANWON:
        yearly = tax_base * 0.001
    elif tax_base <= 15000 * MANWON:
        yearly = 60000 + (tax_base - 6000 * MANWON) * 0.0015
    elif tax_base <= 30000 * MANWON:
        yearly = 195000 + (tax_base - 15000 * MANWON) * 0.0025
    else:
        yearly = 570000 + (tax_base - 30000 * MANWON) * 0.004

    # 지방교육세는 재산세의 20%다.
    yearly *= 1.2
    return {
        "amount": _round_manwon(yearly * years),
        "yearly": _round_manwon(yearly),
        "estimated": True,
    }


def capital_gains_note(price, years, owned_houses=1):
    """양도세를 낼지 안 낼지만 판단한다. 세액은 계산하지 않는다."""
    if owned_houses and owned_houses > 1:
        return {"amount": None, "note": "집이 여러 채면 조건에 따라 달라져요"}
    if years is not None and years < CGT_EXEMPT_YEARS:
        return {"amount": None, "note": f"{CGT_EXEMPT_YEARS}년을 채우기 전에 팔면 세금이 붙어요"}
    if price and price > CGT_EXEMPT_PRICE:
        return {"amount": None, "note": "12억이 넘는 부분에는 세금이 붙어요"}
    return {"amount": 0, "note": "1주택으로 2년을 채우면 안 내요"}


def calculate(price, years=3, area_sqm=None, owned_houses=1):
    """본전 상승률을 계산한다.

    price: 살 때 가격(원)
    years: 몇 년 뒤에 팔 것인가
    area_sqm: 전용면적. 농어촌특별세 판단에 쓴다.
    owned_houses: 이 집을 포함한 보유 주택 수

    돌려주는 값의 rate는 '이만큼 올라야 본전'이라는 비율이다.
    """
    if not price or price <= 0:
        return None

    items = []
    uncertain = []

    tax = acquisition_tax(price, area_sqm, owned_houses)
    if tax:
        items.append({"key": "acquisition", "label": "취득세", "amount": tax["amount"]})
    else:
        uncertain.append("취득세")

    buy_fee = brokerage_fee(price)
    sell_fee = brokerage_fee(price)
    if buy_fee and sell_fee:
        items.append({
            "key": "brokerage",
            "label": "중개비 (살 때·팔 때)",
            "amount": buy_fee["amount"] + sell_fee["amount"],
        })

    holding = property_tax_estimate(price, years)
    if holding:
        items.append({
            "key": "property_tax",
            "label": f"{years}년치 보유세",
            "amount": holding["amount"],
            "estimated": True,
        })

    gains = capital_gains_note(price, years, owned_houses)
    if gains["amount"] == 0:
        items.append({"key": "capital_gains", "label": "양도세", "amount": 0, "note": gains["note"]})
    else:
        uncertain.append("양도세")

    total = sum(item["amount"] for item in items)
    rate = total / price

    return {
        "price": price,
        "years": years,
        "items": items,
        "totalAmount": total,
        "rate": round(rate, 4),
        "ratePercent": round(rate * 100, 1),
        # 계산에서 뺀 항목. 화면에 반드시 같이 보여줘야 한다.
        "uncertainItems": uncertain,
        "capitalGainsNote": gains["note"],
        # 대출 이자는 넣지 않았다. 전세로 살 때도 돈이 들기 때문에
        # 이자를 그대로 더하면 본전선이 실제보다 높아진다.
        "excludes": ["대출 이자", "이사비", "수리비"],
        "headline": f"{years}년 안에 {round(rate * 100, 1)}%는 올라야 손해를 안 봐요",
    }
