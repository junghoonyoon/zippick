"""Budget-based apartment candidate filtering for the real estate MVP."""
import csv
import datetime
import re

import config
import molit_transactions
import momentum_signals
import naver_complex
import verdicts
import policy_evaluator
import real_estate_search

PRICE_BANDS_CSV = config.ROOT / "data" / "apartment_price_bands.csv"
MOLIT_PRICE_BANDS_CSV = config.ROOT / "data" / "seoul_small_apartment_price_bands.csv"
PRICE_BAND_CSV_PATHS = [PRICE_BANDS_CSV, MOLIT_PRICE_BANDS_CSV]
VERIFIED_PRICE_SOURCES = {"molit", "molit_csv", "molit_reference"}
_ENTITY_LOOKUP = None
GENERIC_APARTMENT_NAMES = {
    "현대", "삼성", "한신", "우성", "대우", "대림", "동아", "한양", "극동",
    "한마을", "주공", "신동아", "두산", "벽산", "쌍용", "롯데",
}
RENTAL_APARTMENT_MARKERS = (
    "임대", "lh", "엘에이치", "행복주택", "국민임대", "영구임대", "공공임대",
    "민간임대", "공공지원", "매입임대", "전세임대", "장기전세", "엔에이치에프",
)

SEOUL_DISTRICTS = {
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
}
GYEONGGI_REGIONS = {
    "가평군", "고양덕양구", "고양일산동구", "고양일산서구", "고양시", "과천시", "광명시", "광주시",
    "구리시", "군포시", "김포시", "남양주시", "동두천시", "부천소사구", "부천오정구", "부천원미구",
    "부천시", "성남분당구", "성남수정구", "성남중원구", "성남시", "수원권선구", "수원영통구",
    "수원장안구", "수원팔달구", "수원시", "시흥시", "안산단원구", "안산상록구", "안산시",
    "안성시", "안양동안구", "안양만안구", "안양시", "양주시", "양평군", "여주시", "연천군",
    "오산시", "용인기흥구", "용인수지구", "용인처인구", "용인시", "의왕시", "의정부시",
    "이천시", "파주시", "평택시", "포천시", "하남시", "화성시",
}
GYEONGGI_REGION_KEYS = {real_estate_search.compact(item) for item in GYEONGGI_REGIONS}

PURPOSE_LABELS = {
    "live": "실거주",
    "move": "갈아타기",
    "invest": "투자 검토",
}

PRIORITY_LABELS = {
    "transport": "교통·접근성",
    "school": "학군",
    "newer": "신축·브랜드",
    "price_buffer": "예산 여유",
    "undervalued": "예산 여유",
}

PRICE_STRATEGY_LABELS = {
    "balanced": "예산 균형",
    "buffer": "예산 여유",
    "stretch": "상한 활용",
}

MOVE_TIMING_LABELS = {
    "within_1y": "1년 안",
    "within_3y": "3년 안",
    "flexible": "시기 미정",
}

# 지도 경로 API가 없는 첫 MVP에서 사용하는 권역 단위의 1차 적합도다.
# 실제 이동시간처럼 보이지 않도록 결과에도 '권역 기준'과 재확인 문구를 함께 노출한다.
COMMUTE_AFFINITY = [
    {
        "aliases": ("강남", "강남역", "역삼", "선릉", "삼성", "판교"),
        "regions": {
            "강남구": 12, "성남분당구": 11, "성남수정구": 8, "송파구": 8,
            "강동구": 6, "서초구": 9, "화성시": 4,
        },
    },
    {
        "aliases": ("광화문", "종로", "서울역", "시청", "을지로"),
        "regions": {
            "종로구": 12, "마포구": 9, "성동구": 8, "용산구": 10,
            "양천구": 5, "동대문구": 7,
        },
    },
    {
        "aliases": ("여의도", "마포", "공덕"),
        "regions": {
            "마포구": 12, "영등포구": 12, "용산구": 8, "양천구": 8,
            "종로구": 7, "광명시": 7,
        },
    },
    {
        "aliases": ("잠실", "송파"),
        "regions": {
            "송파구": 12, "강동구": 10, "성남수정구": 8, "성남분당구": 7,
            "광진구": 7, "화성시": 4,
        },
    },
]


def _float_value(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _budget_eok(value):
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    number_match = re.search(r"[0-9]+(?:\.[0-9]+)?", text.replace(",", ""))
    if not number_match:
        return 0.0
    number = float(number_match.group(0))
    if "억" in text:
        return number
    if "만" in text:
        return number / 10000
    if number >= 10000:
        return number / 10000
    return number


def _price_text(value):
    if not value:
        return "-"
    if value == int(value):
        return f"{int(value)}억"
    return f"{value:.1f}억"


def _deal_price_text(value):
    amount_manwon = int(round(_float_value(value) * 10000))
    if amount_manwon <= 0:
        return "-"
    eok, remainder = divmod(amount_manwon, 10000)
    if eok and remainder:
        return f"{eok}억 {remainder:,}만원"
    if eok:
        return f"{eok}억"
    return f"{remainder:,}만원"


def _deal_date_is_recent(value, months=config.MOLIT_TRANSACTION_LOOKBACK_MONTHS):
    """Whether a transaction date belongs to the current comparison window.

    A price range from an old source file must not quietly become a "current"
    estimate just because it has a minimum and maximum price.
    """
    try:
        deal_date = datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return False
    today = datetime.date.today()
    cutoff_year = today.year
    cutoff_month = today.month - int(months or 0)
    while cutoff_month <= 0:
        cutoff_year -= 1
        cutoff_month += 12
    return deal_date >= datetime.date(cutoff_year, cutoff_month, 1)


def _deal_age_days(value):
    try:
        deal_date = datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
    return max(0, (datetime.date.today() - deal_date).days)


def _apply_recent_trade_estimate(row):
    """Expose a conservative current-price range from recent same-complex deals.

    This deliberately does not use asking prices. The range is available only
    when at least two same-area market transactions were observed in the recent
    window, so sparse or old trade data remains reference data rather than an
    apparently precise current price.
    """
    count = _int_value(row.get("transactionCount"))
    latest_date = row.get("latestDealDate")
    low = _float_value(row.get("currentEstimateMinPriceEok"))
    middle = _float_value(row.get("currentEstimateMidPriceEok"))
    high = _float_value(row.get("currentEstimateMaxPriceEok"))
    uses_aggregate_band = False
    if not (low and middle and high) and row.get("priceSource") == "molit_csv":
        raw_low = _float_value(row.get("minPriceEok"))
        raw_middle = _float_value(row.get("midPriceEok"))
        raw_high = _float_value(row.get("maxPriceEok"))
        if raw_low and raw_middle and raw_high:
            # The imported MOLIT CSV stores the 10th/50th/90th percentiles.
            # Interpolate toward the median to approximate the central 50%
            # instead of relabelling the factual outer band as an estimate.
            low = raw_low + (raw_middle - raw_low) * 0.375
            middle = raw_middle
            high = raw_middle + (raw_high - raw_middle) * 0.375
            uses_aggregate_band = True
    if count < 2 or not latest_date or not _deal_date_is_recent(latest_date) or not low or not middle or not high:
        row.pop("estimatedMinPriceEok", None)
        row.pop("estimatedMidPriceEok", None)
        row.pop("estimatedMaxPriceEok", None)
        row.pop("estimatedPriceConfidence", None)
        row.pop("estimatedPriceAgeDays", None)
        row.pop("estimatedPriceMethod", None)
        row.pop("estimatedPriceTrimmedCount", None)
        row.pop("estimatedPriceUsesAggregateBand", None)
        return row
    age_days = _deal_age_days(latest_date)
    if uses_aggregate_band:
        confidence = "보통" if count >= 5 and age_days is not None and age_days <= 90 else "낮음"
    else:
        confidence = "높음" if count >= 5 and age_days is not None and age_days <= 30 else "보통" if count >= 3 and age_days is not None and age_days <= 90 else "낮음"
    row.update({
        "estimatedMinPriceEok": round(min(low, high), 2),
        "estimatedMidPriceEok": round(middle, 2),
        "estimatedMaxPriceEok": round(max(low, high), 2),
        "estimatedPriceConfidence": confidence,
        "estimatedPriceAgeDays": age_days,
        "estimatedPriceMethod": (
            "최근 실거래 10~90백분위에서 중간 50% 구간 근사"
            if uses_aggregate_band
            else row.get("currentEstimateMethod") or "최근 거래일수록 크게 반영한 가중 시세"
        ),
        "estimatedPriceTrimmedCount": _int_value(row.get("currentEstimateTrimmedCount")),
        "estimatedPriceUsesAggregateBand": uses_aggregate_band,
    })
    return row


def _price_band_text(row):
    min_price = _float_value(row.get("minPriceEok"))
    max_price = _float_value(row.get("maxPriceEok"))
    if not min_price and not max_price:
        return "가격 확인 필요"
    if abs(max_price - min_price) < 0.01:
        return _deal_price_text(min_price)
    return f"{_price_text(min_price)}~{_price_text(max_price)}"


def _int_value(value):
    try:
        return int(float(str(value or "").replace(",", "").strip()))
    except ValueError:
        return 0


def _area_range(area_label):
    values = [float(value) for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", str(area_label or ""))]
    if not values:
        return (0.0, 0.0)
    return (min(values), max(values))


def _display_area_label(area_label):
    low, high = _area_range(area_label)
    if not low:
        return str(area_label or "").strip()
    value = int(low) if low == int(low) else round(low, 1)
    return f"전용 {value}㎡"


def _display_region(row, entity=None):
    entity = entity or {}
    address = str(entity.get("address") or row.get("address") or "").strip()
    if address:
        return address
    region = str(row.get("region") or entity.get("district") or entity.get("city") or "").strip()
    legal_dong = str(row.get("legalDong") or entity.get("legalDong") or "").strip()
    if region and legal_dong and real_estate_search.compact(legal_dong) not in real_estate_search.compact(region):
        return f"{region} {legal_dong}"
    return region or legal_dong


def _apartment_name_base(name):
    return re.sub(r"(?:아파트|apt)$", "", real_estate_search.compact(name), flags=re.IGNORECASE)


def _is_generic_apartment_name(name):
    base = _apartment_name_base(name)
    return bool(base) and base in GENERIC_APARTMENT_NAMES


def _is_rental_apartment(row, entity=None):
    """Exclude rental/LH complexes from purchase-candidate discovery.

    The source master keeps tenure hints in either the official complex name or
    one of its aliases (for example, ``단지명(임대)``).  LH is intentionally
    included as a requested conservative rule because its complexes are often
    rental-only and do not have a normal sale transaction market.
    """
    entity = entity or {}
    values = [
        row.get("name", ""), row.get("sourceNote", ""), row.get("priceSource", ""),
        entity.get("name", ""), entity.get("category", ""), *(entity.get("aliases") or []),
    ]
    text = real_estate_search.compact(" ".join(str(value or "") for value in values))
    return any(marker in text for marker in RENTAL_APARTMENT_MARKERS)


def _entity_jibun(entity):
    address = str((entity or {}).get("address") or "").strip()
    if not address:
        return ""
    tail = address.split()[-1]
    return tail if re.search(r"\d", tail) else ""


def _candidate_display_name(row, entity=None):
    entity = entity or {}
    row_name = str(row.get("name") or "").strip()
    entity_name = str(entity.get("name") or "").strip()
    display_name = row_name
    if entity_name and (
        _is_generic_apartment_name(row_name)
        or len(real_estate_search.compact(entity_name)) > len(real_estate_search.compact(row_name))
    ):
        display_name = entity_name
    if _is_generic_apartment_name(display_name):
        if not display_name.endswith("아파트"):
            display_name = f"{display_name}아파트"
        legal_dong = str(row.get("legalDong") or entity.get("legalDong") or "").strip()
        if legal_dong and real_estate_search.compact(legal_dong) not in real_estate_search.compact(display_name):
            display_name = f"{legal_dong} {display_name}"
    return display_name or row_name


def _candidate_identity_key(row):
    """Return a stable complex identity for result-list de-duplication.

    Public transaction feeds may use a complex's official name or one of its
    aliases. Both resolve to the same master entity, so de-duplicate them by
    the entity key rather than by the raw feed name. For rows that cannot be
    resolved safely, use the physical address and finally the old name/region
    fallback so unrelated complexes are never silently merged.
    """
    entity = _find_entity(
        row.get("name", ""),
        row.get("region", ""),
        row.get("legalDong", ""),
        row.get("jibun", ""),
    )
    entity_key = str((entity or {}).get("dedupeKey") or "").strip()
    if entity_key:
        return ("entity", entity_key)

    address_key = tuple(
        real_estate_search.compact(row.get(field, ""))
        for field in ("region", "legalDong", "jibun")
    )
    if any(address_key[1:]):
        return ("address", *address_key)
    return (
        "name",
        real_estate_search.compact(row.get("name", "")),
        real_estate_search.compact(row.get("region", "")),
    )


def _dedupe_candidate_rows(rows):
    """Keep the highest-ranked row for each actual apartment complex."""
    unique_rows = []
    seen_keys = set()
    for row in rows:
        identity_key = _candidate_identity_key(row)
        if identity_key in seen_keys:
            continue
        seen_keys.add(identity_key)
        unique_rows.append(row)
    return unique_rows


def _building_profile(entity):
    approved_at = str((entity or {}).get("approvedAt") or "")
    match = re.match(r"(\d{4})", approved_at)
    if not match:
        return {"approvedAt": approved_at, "buildYear": 0, "buildingAge": 0}
    build_year = int(match.group(1))
    return {
        "approvedAt": approved_at,
        "buildYear": build_year,
        "buildingAge": max(0, datetime.date.today().year - build_year),
    }


def _naver_property_link(row, entity):
    entity = entity or {}
    name = str(row.get("name") or "").strip()
    # 네이버부동산 검색은 내부 행정구역 문자열을 길게 붙이면 오히려 검색되지 않는다.
    # 고유한 단지명은 그대로 보내고, 짧고 흔한 이름에만 법정동을 붙인다.
    search_name = re.sub(r"\s*\((?:고층|중층|저층)\)\s*$", "", name).strip()
    search_name = re.sub(r"(?:상가동|유치원동).*$", "", search_name).strip()
    search_name = re.sub(r'''[\s"'“”‘’]+$''', "", search_name).strip()
    # 공공데이터 별칭은 네이버의 등록 단지명과 다를 수 있다. 주소로 단지가
    # 식별된 경우에는 마스터의 대표 단지명을 우선 사용한다.
    canonical_name = str(entity.get("name") or "").strip()
    if canonical_name and real_estate_search.compact(canonical_name) != real_estate_search.compact(search_name):
        search_name = canonical_name
    # 공공 데이터는 번호형 단지의 끝말인 '단지'를 생략하는 경우가 많지만,
    # 네이버부동산 검색은 공식 단지명에 가까운 표기를 요구한다.
    if re.search(r"\d+$", search_name) and not search_name.endswith("단지"):
        search_name = f"{search_name}단지"
    name_key = real_estate_search.compact(search_name)
    generic_key = re.sub(r"(?:아파트|apt)$", "", name_key, flags=re.IGNORECASE)
    needs_location = len(generic_key) <= 4 or generic_key in GENERIC_APARTMENT_NAMES
    location = str(entity.get("legalDong") or "").strip()
    if not location:
        location = str(row.get("region") or entity.get("district") or "").strip()
        location = re.sub(r"^(성남|수원|용인|고양|안양|안산|부천)(?=.+구$)", "", location)
    query = f"{location} {search_name}".strip() if needs_location and location else search_name
    query = query or name
    return {
        "naverPropertyQuery": query,
        "naverPropertyUrl": naver_complex.search_url(query),
    }


def _region_terms(region):
    return [term.strip() for term in re.split(r"[,/\n]+", str(region or "")) if term.strip()]


def _multi_values(value):
    return [term.strip() for term in re.split(r"[,/\n]+", str(value or "")) if term.strip()]


def _multi_label(value, labels, fallback):
    names = [labels.get(term, term) for term in _multi_values(value)]
    return " · ".join(names) if names else fallback


def _load_price_bands():
    rows = []
    for path in PRICE_BAND_CSV_PATHS:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                rows.append({
                    "name": name,
                    "region": str(row.get("region") or "").strip(),
                    "legalDong": str(row.get("legal_dong") or "").strip(),
                    "jibun": str(row.get("jibun") or "").strip(),
                    "minPriceEok": _float_value(row.get("min_price_억")),
                    "midPriceEok": _float_value(row.get("mid_price_억")),
                    "maxPriceEok": _float_value(row.get("max_price_억")),
                    "areaLabel": str(row.get("area_label") or "").strip(),
                    "updatedAt": str(row.get("updated_at") or "").strip(),
                    "sourceNote": str(row.get("source_note") or "").strip(),
                    "priceSource": str(row.get("price_source") or "manual").strip(),
                    "transactionCount": int(_float_value(row.get("transaction_count"))),
                    "latestDealDate": str(row.get("latest_deal_date") or "").strip(),
                    "latestDealPriceEok": _float_value(row.get("latest_deal_price_억") or row.get("latest_deal_price_eok")),
                    "sourceUrl": str(row.get("source_url") or "").strip(),
                })
    return rows


def _apply_fit(row, budget_eok):
    _apply_recent_trade_estimate(row)
    estimated_mid = _float_value(row.get("estimatedMidPriceEok"))
    stale_verified_trade = (
        row.get("priceSource") in VERIFIED_PRICE_SOURCES
        and bool(row.get("latestDealDate"))
        and not _deal_date_is_recent(row.get("latestDealDate"))
    )
    if stale_verified_trade:
        row.setdefault("lastObservedDealDate", row.get("latestDealDate"))
        row.setdefault(
            "lastObservedDealPriceEok",
            _float_value(row.get("latestDealPriceEok")) or _float_value(row.get("midPriceEok")),
        )
    mid_price = 0 if stale_verified_trade else estimated_mid or row.get("midPriceEok") or row.get("maxPriceEok") or row.get("minPriceEok")
    if not mid_price:
        has_last_deal = bool(row.get("lastObservedDealDate"))
        last_price = _float_value(row.get("lastObservedDealPriceEok"))
        row.update({
            "midPriceEok": 0,
            "priceRangeText": f"마지막 실거래 {_deal_price_text(last_price)}" if last_price else ("6개월 내 거래 없음" if has_last_deal else "최근 거래 없음"),
            "budgetGapEok": 0,
            "fitStatus": "가격 확인 필요",
            "fitClass": "wait",
            "action": "마지막 실거래와 현재 매물가 차이를 확인해 주세요." if has_last_deal else "최근 실거래 또는 현재 매물가를 확인해 주세요.",
            "_fitRank": 4,
        })
        return row
    status, status_class, fit_rank = _fit_status(mid_price, budget_eok)
    latest_price = _float_value(row.get("latestDealPriceEok"))
    estimated_low = _float_value(row.get("estimatedMinPriceEok"))
    estimated_high = _float_value(row.get("estimatedMaxPriceEok"))
    row.update({
        "midPriceEok": mid_price,
        "priceRangeText": (
            f"현재 예상 시세 {_price_text(estimated_low)}~{_price_text(estimated_high)}"
            if estimated_low and estimated_high
            else
            f"최근 실거래 {_deal_price_text(latest_price)}"
            if latest_price
            else f"실거래 가격대 {_price_band_text(row)}"
            if row.get("priceSource") == "molit_csv" and row.get("latestDealDate")
            else "최신 실거래가 확인 필요"
            if row.get("priceSource") == "molit" and row.get("latestDealDate")
            else f"{_price_text(row.get('minPriceEok'))}~{_price_text(row.get('maxPriceEok'))}"
        ),
        "budgetGapEok": round(budget_eok - mid_price, 2),
        "fitStatus": status,
        "fitClass": status_class,
        "action": _action(status),
        "_fitRank": fit_rank,
    })
    return row


def _preferred_area_label(min_area):
    minimum = _float_value(min_area)
    bands = {
        40: "전용 40~40㎡",
        50: "전용 50~50㎡",
        59: "전용 59~60㎡",
        74: "전용 74~75㎡",
        84: "전용 84~85㎡",
    }
    return bands.get(int(minimum), "") if minimum else ""


def _apply_live_price(row, preferred_min_area=0):
    minimum = _float_value(preferred_min_area)
    if minimum:
        live = molit_transactions.price_band_for_apartment(
            row["name"],
            region=row.get("region", ""),
            area_label=_preferred_area_label(minimum),
        )
        if not live:
            live = molit_transactions.price_band_for_apartment_min_area(
                row["name"],
                region=row.get("region", ""),
                min_area=minimum,
            )
    else:
        live = molit_transactions.price_band_for_apartment(
            row["name"],
            region=row.get("region", ""),
            area_label=row.get("areaLabel", ""),
        )
    if not live:
        return row
    latest_price = _float_value(live.get("latestDealPriceEok")) or _float_value(live.get("midPriceEok"))
    row.update({
        "areaLabel": live.get("areaLabel") or row.get("areaLabel", ""),
        "recentMinPriceEok": live["minPriceEok"],
        "recentMedianPriceEok": live["midPriceEok"],
        "recentMaxPriceEok": live["maxPriceEok"],
        "currentEstimateMinPriceEok": live.get("currentEstimateMinPriceEok"),
        "currentEstimateMidPriceEok": live.get("currentEstimateMidPriceEok"),
        "currentEstimateMaxPriceEok": live.get("currentEstimateMaxPriceEok"),
        "currentEstimateSampleCount": live.get("currentEstimateSampleCount", 0),
        "currentEstimateTrimmedCount": live.get("currentEstimateTrimmedCount", 0),
        "currentEstimateMethod": live.get("currentEstimateMethod", ""),
        "minPriceEok": live["minPriceEok"],
        "midPriceEok": live["midPriceEok"],
        "maxPriceEok": live["maxPriceEok"],
        "latestDealPriceEok": latest_price,
        "latestDealExclusiveArea": live.get("latestDealExclusiveArea"),
        "latestDealFloor": live.get("latestDealFloor", ""),
        "transactionCount": live["transactionCount"],
        "latestDealDate": live["latestDealDate"],
        "sourceNote": live["sourceNote"],
        "priceSource": "molit",
    })
    return _apply_recent_trade_estimate(row)


def _apply_last_observed_deal(row, preferred_min_area=0):
    """Attach the latest matching transaction outside the recent-trade window.

    This remains reference information: it is not treated as today's asking price
    or as a policy-evaluation price. It is, however, sufficient to exclude a
    complex whose most recent known transaction already exceeds the purchase
    ceiling.
    """
    area_label = _preferred_area_label(preferred_min_area) if _float_value(preferred_min_area) else row.get("areaLabel", "")
    last_deal = molit_transactions.latest_transaction_for_apartment(
        row["name"],
        region=row.get("region", ""),
        area_label=area_label,
        skip_months=config.MOLIT_TRANSACTION_LOOKBACK_MONTHS,
    )
    last_price = _float_value((last_deal or {}).get("latestDealPriceEok"))
    if not last_price:
        return row
    row.update({
        "lastObservedDealPriceEok": last_price,
        "lastObservedDealExclusiveArea": last_deal.get("latestDealExclusiveArea"),
        "lastObservedDealFloor": last_deal.get("latestDealFloor", ""),
        "lastObservedDealDate": last_deal.get("latestDealDate", ""),
        "lastObservedDealNote": last_deal.get("sourceNote", ""),
    })
    return row


def _candidate_from_entity(entity, region, min_area, budget_eok, purpose, priority, commute, price_strategy):
    if entity.get("aggregate"):
        return None
    name = str(entity.get("name") or "").strip()
    if not name:
        return None
    area_label = _preferred_area_label(min_area)
    seed_region = entity.get("district") or entity.get("city") or ""
    seed_row = {"name": name, "region": seed_region, "areaLabel": area_label}
    if not _matches_region(seed_row, entity, region):
        return None
    households = real_estate_search._int_value(entity.get("households"))
    building = _building_profile(entity)
    area_min, area_max = _area_range(area_label)
    scope = region or entity.get("district") or entity.get("city") or seed_region
    candidate = {
        "name": name,
        "region": seed_region,
        "legalDong": entity.get("legalDong", ""),
        "jibun": _entity_jibun(entity),
        "areaLabel": area_label,
        "minPriceEok": 0,
        "midPriceEok": 0,
        "maxPriceEok": 0,
        "households": households,
        "searchQuery": real_estate_search._region_apartment_search_query(entity, scope),
        "updatedAt": "",
        "sourceNote": "",
        "priceSource": "molit_lookup",
        "transactionCount": 0,
        "latestDealDate": "",
        "sourceUrl": "",
        "areaMin": area_min,
        "areaMax": area_max,
        **building,
        **_naver_property_link(seed_row, entity),
        "_budgetEok": budget_eok,
        "_liveLookup": True,
    }
    candidate["fitStatus"] = "정보 필요"
    candidate["fitClass"] = "mention"
    candidate["budgetGapEok"] = 0
    candidate["_fitRank"] = 2
    candidate["_score"] = _candidate_score(candidate, entity, purpose, priority, commute, price_strategy)
    return candidate


def _entity_alias_keys(entity):
    # Numbered complexes are separate legal/market entities. A synthetic parent
    # (for example, "... 그랑메종") must not claim its 1~6 complexes as
    # aliases or their prices and household counts will be mixed together.
    values = [entity.get("name", "")]
    if not entity.get("aggregate"):
        values.extend(entity.get("aliases") or [])
    return {real_estate_search.compact(value) for value in values if real_estate_search.compact(value)}


def _find_entities(name, region="", legal_dong="", jibun=""):
    global _ENTITY_LOOKUP
    key = real_estate_search.compact(name)
    if not key:
        return []
    if _ENTITY_LOOKUP is None:
        lookup = {}
        for entity in real_estate_search.APARTMENT_MASTER:
            rank = (
                _float_value(entity.get("households")),
                bool(entity.get("district")),
                bool(entity.get("city")),
            )
            for alias_key in _entity_alias_keys(entity):
                lookup.setdefault(alias_key, []).append((rank, entity))
        _ENTITY_LOOKUP = {
            alias_key: [value[1] for value in sorted(values, key=lambda value: value[0], reverse=True)]
            for alias_key, values in lookup.items()
        }
    matches = _ENTITY_LOOKUP.get(key) or []
    if region:
        region_key = real_estate_search.compact(region)
        regional_matches = []
        for entity in matches:
            entity_regions = {
                real_estate_search.compact(entity.get("district")),
                real_estate_search.compact(entity.get("city")),
            }
            if region_key in entity_regions:
                regional_matches.append(entity)
        matches = regional_matches
    if legal_dong:
        dong_key = real_estate_search.compact(legal_dong)
        matches = [
            entity for entity in matches
            if real_estate_search.compact(entity.get("legalDong")) == dong_key
        ]
    if jibun:
        jibun_key = real_estate_search.compact(jibun)
        matches = [
            entity for entity in matches
            if real_estate_search.compact(entity.get("address")).endswith(jibun_key)
        ]
    return matches


def _find_entity(name, region="", legal_dong="", jibun=""):
    matches = _find_entities(name, region, legal_dong, jibun)
    return matches[0] if matches else None


def _matches_region(row, entity, region):
    terms = _region_terms(region)
    if not terms:
        return True
    return any(_matches_one_region(row, entity, term) for term in terms)


def _matches_one_region(row, entity, region):
    region_key = real_estate_search.compact(region)
    if region_key in {"서울", "서울시", "서울특별시"}:
        province_key = real_estate_search.compact((entity or {}).get("province") or "")
        city_key = real_estate_search.compact((entity or {}).get("city") or "")
        if province_key:
            return province_key in {"서울", "서울시", "서울특별시"}
        if city_key:
            return city_key in {"서울", "서울시", "서울특별시"}
        return str(row.get("region") or "").strip() in SEOUL_DISTRICTS
    if region_key in {"경기", "경기도"}:
        province_key = real_estate_search.compact((entity or {}).get("province") or "")
        city_key = real_estate_search.compact((entity or {}).get("city") or "")
        district_key = real_estate_search.compact((entity or {}).get("district") or "")
        if province_key:
            return province_key in {"경기", "경기도"}
        if city_key in GYEONGGI_REGION_KEYS:
            return True
        if district_key in GYEONGGI_REGION_KEYS:
            return True
        return str(row.get("region") or "").strip() in GYEONGGI_REGIONS
    region_variants = {region_key}
    if region_key.endswith(("시", "구", "군")) and len(region_key) > 2:
        region_variants.add(region_key[:-1])
    # 단지명에 들어간 지명(예: 송파구의 '강남팰리스')을 실제 소재지로
    # 오인하지 않도록 지역 필드는 행정구역 정보만 비교한다.
    row_values = [row.get("region", "")]
    entity_values = []
    if entity:
        entity_values = [
            entity.get("province", ""),
            entity.get("city", ""),
            entity.get("district", ""),
            entity.get("legalDong", ""),
            entity.get("category", ""),
        ]
    for value in [*row_values, *entity_values]:
        key = real_estate_search.compact(value)
        if not key:
            continue
        key_variants = {key}
        if key.endswith(("시", "구", "군")) and len(key) > 2:
            key_variants.add(key[:-1])
        if any(
            left == right or (len(left) >= 2 and left in right) or (len(right) >= 2 and right in left)
            for left in region_variants
            for right in key_variants
        ):
            return True
    return False


def _fit_status(mid_price, budget):
    if not budget:
        return ("정보 필요", "mention", 99)
    ratio = mid_price / budget if mid_price else 999
    if ratio <= 0.8:
        return ("예산 여유", "up", 1)
    if ratio <= 1.0:
        return ("예산 안", "up", 0)
    if ratio <= 1.05:
        return ("상한 근접", "wait", 2)
    return ("제외", "mention", 3)


def _price_score(row, strategy):
    ratio = (row.get("midPriceEok") or 0) / (row.get("_budgetEok") or 1)
    target = {"buffer": 0.82, "stretch": 0.99}.get(strategy, 0.92)
    # 저렴한 단지를 무조건 상위에 두지 않고, 사용자가 고른 예산 사용 방식에 가까운지를 본다.
    return max(0, round(35 - abs(ratio - target) * 110, 1))


def _priority_score(row, entity, priority):
    # 단지명·지역명 키워드를 교통·학군·상품성의 근거로 쓰면 오추천이 된다.
    # 검증 가능한 데이터가 들어오기 전까지는 해당 우선순위에 가점을 주지 않는다.
    priorities = set(_multi_values(priority))
    if priorities.intersection({"price_buffer", "undervalued"}):
        ratio = (row.get("midPriceEok") or 0) / (row.get("_budgetEok") or 1)
        return 8 if ratio <= 0.85 else 4 if ratio <= 0.95 else 0
    return 0


def _single_commute_score(row, entity, commute):
    commute_key = real_estate_search.compact(commute)
    if not commute_key:
        return 0, ""
    region_values = [row.get("region", "")]
    if entity:
        region_values.extend([entity.get("district", ""), entity.get("city", "")])
    region_keys = {real_estate_search.compact(value) for value in region_values if value}
    if any(region_key and (region_key in commute_key or commute_key in region_key) for region_key in region_keys):
        return 12, f"{commute}와 같은 생활권으로 1차 분류"
    for group in COMMUTE_AFFINITY:
        if not any(real_estate_search.compact(alias) in commute_key for alias in group["aliases"]):
            continue
        score = max((group["regions"].get(value, 0) for value in region_keys), default=0)
        if score:
            return score, f"{commute} 접근성을 권역 기준으로 우선 반영"
        return 0, ""
    return 0, ""


def _commute_score(row, entity, commute):
    commutes = _multi_values(commute)
    if not commutes:
        return 0, ""
    scores = []
    matched = []
    for term in commutes:
        score, reason = _single_commute_score(row, entity, term)
        scores.append(score)
        if reason and score:
            matched.append(term)
    score = round(sum(scores) / len(scores), 1)
    if not matched:
        return score, ""
    return score, f"{'·'.join(matched)} 생활권을 권역 기준으로 함께 반영"


def _purpose_score(row, purpose):
    purposes = _multi_values(purpose)
    if not purposes:
        return 0
    households = row.get("households") or 0
    ratio = (row.get("midPriceEok") or 0) / (row.get("_budgetEok") or 1)
    scores = []
    for item in purposes:
        if item == "live":
            scores.append((4 if households >= 1000 else 1) + (3 if ratio <= 0.9 else 0))
        elif item == "move":
            scores.append((4 if households >= 1500 else 1) + (2 if ratio <= 0.95 else 0))
        elif item == "invest":
            scores.append((4 if row.get("priceSource") in VERIFIED_PRICE_SOURCES and row.get("transactionCount") else 0) + (2 if ratio <= 0.9 else 0))
    return round(sum(scores) / len(scores), 1) if scores else 0


def _candidate_score(row, entity, purpose, priority, commute, price_strategy):
    row["_budgetEok"] = row.get("_budgetEok") or 0
    commute_score, _ = _commute_score(row, entity, commute)
    return (
        _price_score(row, price_strategy)
        + _priority_score(row, entity, priority)
        + _purpose_score(row, purpose)
        + min(commute_score, 12)
        + min(row.get("households") or 0, 5000) / 500
        + min((row.get("transactionCount") or 0), 20) / 2
    )


def _priority_reason(row, priority):
    ratio = (row.get("midPriceEok") or 0) / (row.get("_budgetEok") or 1)
    if set(_multi_values(priority)).intersection({"price_buffer", "undervalued"}) and ratio <= 0.95:
        return "추정 구매력을 모두 쓰지 않는 가격 구간"
    return ""


def _decision_support(row, entity, purpose, priority, commute, move_timing, price_strategy, region):
    budget = row.get("_budgetEok") or 0
    mid_price = row.get("midPriceEok") or 0
    ratio = mid_price / budget if budget else 999
    reasons = []
    risks = []
    checks = []
    breakdown = []
    purposes = set(_multi_values(purpose))
    priorities = set(_multi_values(priority))
    commutes = _multi_values(commute)

    if mid_price:
        price_score = _price_score(row, price_strategy)
        reasons.append(f"기준 가격 {mid_price:.1f}억 · 추정 매수 가능 상한 {budget:.1f}억 대비 {round((1 - ratio) * 100)}% 여유")
        breakdown.append({"label": "예산", "score": price_score, "outOf": 35, "detail": f"{PRICE_STRATEGY_LABELS.get(price_strategy, '예산 균형')} 기준", "kind": "fit"})
        if ratio <= 0.75 and price_strategy != "buffer":
            risks.append("예산을 크게 남기는 후보예요. 입지·연식·면적의 교환 조건을 직접 비교해야 해요.")
    else:
        reasons.append("지역·면적·세대수·연식 필수 조건을 통과")
        risks.append("최근 동일 면적대 실거래가 없어 예산과 대출 가능 여부는 판정하지 않았어요.")
        breakdown.append({"label": "예산", "score": 0, "outOf": 35, "detail": "최근 거래 없음", "kind": "confidence"})

    commute_score, commute_reason = _commute_score(row, entity, commute)
    if commute_reason and commute_score:
        reasons.append(commute_reason)
        breakdown.append({"label": "생활권", "score": commute_score, "outOf": 12, "detail": "권역 기준 1차 일치", "kind": "fit"})
        risks.append(f"{'·'.join(commutes)}까지 실제 출근 시간은 지도 경로로 재확인 필요")
    elif commutes:
        risks.append(f"{'·'.join(commutes)}까지 실제 이동시간 데이터는 아직 연결되지 않았어요.")
        breakdown.append({"label": "생활권", "score": 0, "outOf": 12, "detail": "실제 경로 확인 필요", "kind": "fit"})
    elif region:
        reasons.append(f"선호 지역({', '.join(_region_terms(region))}) 안에서만 비교")
    priority_reason = _priority_reason(row, priority)
    if priority_reason:
        reasons.append(priority_reason)
    for unverified in ("school", "newer"):
        if unverified in priorities:
            missing_label = PRIORITY_LABELS.get(unverified, unverified)
            risks.append(f"{missing_label}의 검증 데이터가 아직 없어 후보 순위에는 반영하지 않았어요.")

    households = row.get("households") or 0
    if "live" in purposes and households >= 1000:
        reasons.append(f"{households:,}세대 규모로 실거주 비교 후보에 포함")
    if "move" in purposes and households >= 1500:
        reasons.append(f"{households:,}세대 규모로 갈아타기 비교 후보에 포함")
    if "invest" in purposes:
        risks.append("전세가율·보유세·거래비용은 아직 반영되지 않음")

    if households:
        breakdown.append({"label": "단지 규모", "score": round(min(households, 5000) / 500, 1), "outOf": 10, "detail": f"{households:,}세대", "kind": "fit"})
    else:
        risks.append("단지 세대수 데이터를 연결하지 못해 규모 비교에는 반영하지 않았어요.")

    building_age = row.get("buildingAge") or 0
    build_year = row.get("buildYear") or 0
    if build_year:
        breakdown.append({"label": "연식", "score": max(1, round(10 - min(building_age, 30) / 3, 1)), "outOf": 10, "detail": f"{build_year}년 사용승인 · {building_age}년차", "kind": "fit"})
    else:
        risks.append("사용승인일 데이터를 연결하지 못해 연식은 직접 확인해야 해요.")

    if row.get("priceSource") in VERIFIED_PRICE_SOURCES:
        count = row.get("transactionCount") or 0
        latest_deal_price = _float_value(row.get("latestDealPriceEok"))
        recent_median_price = _float_value(row.get("recentMedianPriceEok"))
        estimated_low = _float_value(row.get("estimatedMinPriceEok"))
        estimated_high = _float_value(row.get("estimatedMaxPriceEok"))
        if estimated_low and estimated_high:
            reasons.append(f"최근 동일 면적대 실거래 {count}건으로 현재 예상 거래가 {_price_text(estimated_low)}~{_price_text(estimated_high)} 산정")
            age_days = _int_value(row.get("estimatedPriceAgeDays"))
            if age_days > 30:
                age_label = f"약 {max(1, round(age_days / 30))}개월 전" if age_days < 180 else f"{max(1, round(age_days / 30))}개월 전"
                risks.insert(0, f"마지막 실거래가 {age_label}이라 지금 나온 매물가와 차이날 수 있어요.")
        elif latest_deal_price:
            reasons.append(f"가장 최근 동일 면적대 실거래 {_deal_price_text(latest_deal_price)}를 기준 가격으로 사용")
            if count < 3:
                risks.insert(0, f"최근 실거래 표본이 {count}건으로 적어 가격 차이 판단은 보수적으로 해야 해요.")
            elif recent_median_price:
                deal_gap_percent = round(abs(latest_deal_price - recent_median_price) / recent_median_price * 100)
                if deal_gap_percent >= 15:
                    risks.insert(0, f"가장 최근 실거래가 최근 6개월 동일 면적 중앙값과 {deal_gap_percent}% 차이 나요. 특별한 가격 근거가 없다면 신중 검토하세요.")
                elif deal_gap_percent >= 10:
                    risks.insert(0, f"가장 최근 실거래가 최근 6개월 동일 면적 중앙값과 {deal_gap_percent}% 차이 나요. 동·층·향·수리 상태와 현재 호가를 확인하세요.")
        elif count >= 3:
            reasons.append(f"최근 동일 면적대 실거래 {count}건을 가격에 반영")
        else:
            risks.append(f"최근 실거래 표본이 {count}건으로 적음")
        confidence = row.get("estimatedPriceConfidence") or ("높음" if count >= 3 else "보통")
        price_detail = (
            f"최근 6개월 동일 면적 실거래 {count}건으로 추정"
            if estimated_low and estimated_high
            else f"최근 실거래 1건 기준 · 최근 6개월 {count}건 확인"
            if row.get("latestDealPriceEok") else f"최근 동일 면적대 실거래 {count}건 반영"
        )
        breakdown.append({"label": "가격 신뢰도", "score": round(min(count, 20) / 2, 1), "outOf": 10, "detail": price_detail, "kind": "confidence"})
    else:
        if row.get("lastObservedDealDate"):
            last_price = _deal_price_text(row.get("lastObservedDealPriceEok")) if row.get("lastObservedDealPriceEok") else "가격"
            risks.append(f"6개월 내 동일 면적 실거래가 없어 마지막 실거래 {row.get('lastObservedDealDate')} · {last_price}와 현재 호가 차이 확인 필요")
        else:
            risks.append("현재 가격은 보강 가격대이며 최신 호가와 실거래 재확인 필요")
        confidence = "보통"
        breakdown.append({"label": "가격 신뢰도", "score": 0, "outOf": 10, "detail": "실거래 표본 보강 필요", "kind": "confidence"})

    if commutes:
        checks.append(f"평일 출근 시간대 {'·'.join(commutes)}까지 문 앞 이동시간")
    if "school" in priorities:
        checks.append("배정 학교·통학 동선·학원가 접근성")
    if "newer" in priorities:
        checks.append("정확한 준공연도·주차대수·커뮤니티 시설")
    if priorities.intersection({"price_buffer", "undervalued"}):
        checks.append("저가 거래의 층·동·수리 상태 차이")
    if priorities == {"transport"}:
        checks.append("역까지 도보 동선과 혼잡 시간대")
    if "move" in purposes:
        checks.append("기존 주택 매각일과 새집 잔금일 연결 가능성")
    else:
        checks.append("최신 매물 호가와 같은 면적의 최근 실거래")
    if move_timing and move_timing != "flexible":
        checks.append(f"{MOVE_TIMING_LABELS.get(move_timing, move_timing)} 입주 가능한 매물 여부")

    if commute_score >= 8:
        candidate_type = "생활권 우선형"
    elif building_age and building_age <= 10:
        candidate_type = "연식 균형형"
    elif price_strategy == "buffer":
        candidate_type = "예산 여유형"
    else:
        candidate_type = "예산 균형형"

    fit_breakdown = [item for item in breakdown if item.get("kind") == "fit"]
    fit_score = round(
        100 * sum(item["score"] for item in fit_breakdown) / max(1, sum(item["outOf"] for item in fit_breakdown))
    )
    if fit_score >= 80:
        match_label = "매우 잘 맞아요"
    elif fit_score >= 65:
        match_label = "대체로 잘 맞아요"
    elif fit_score >= 50:
        match_label = "보통이에요"
    else:
        match_label = "조건을 더 확인해보세요"

    if ratio <= 0.9:
        summary_start = "예산 범위에 여유가 있어요"
    elif ratio <= 1:
        summary_start = "예산 상한 안에서 검토할 수 있어요"
    else:
        summary_start = "예산 상한을 넘을 수 있어요"
    if building_age >= 15:
        match_summary = f"{summary_start}. 준공 {building_age}년차라 연식은 직접 확인해보세요."
    elif households and households < 500:
        match_summary = f"{summary_start}. {households:,}세대 단지라 관리와 거래 여건을 확인해보세요."
    else:
        match_summary = f"{summary_start}. 단지 규모와 연식도 함께 비교해보세요."

    return {
        "reasons": reasons[:3],
        "risks": risks[:3],
        "nextChecks": checks[:3],
        "dataConfidence": confidence,
        "commuteMatched": bool(commute_reason and commute_score),
        "candidateType": candidate_type,
        "matchScore": max(0, min(100, fit_score)),
        "matchLabel": match_label,
        "matchSummary": match_summary,
        "scoreBreakdown": breakdown,
    }


def _action(status):
    return {
        "예산 여유": "남는 예산을 입지·연식·수리비와 함께 비교해볼 만해요.",
        "예산 안": "최근 실거래와 현재 호가를 바로 비교해볼 만해요.",
        "상한 근접": "취득 부대비용과 대출 조건까지 함께 확인해야 해요.",
        "제외": "현재 예산에서는 후순위로 두는 편이 좋아요.",
    }.get(status, "가격 데이터를 더 보강해야 해요.")


def budget_candidates(
    budget,
    region="",
    purpose="",
    priority="",
    commute="",
    move_timing="",
    price_strategy="stretch",
    min_area=0,
    min_households=0,
    max_building_age=0,
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
    limit=6,
    all_matches=False,
    fast_mode=False,
):
    policy_profile = policy_evaluator.user_profile(
        home_ownership=home_ownership,
        first_time=first_time,
        cash_eok=cash_eok,
        annual_income=annual_income,
        monthly_debt_payment=monthly_debt_payment,
        co_borrower=co_borrower,
        spouse_annual_income=spouse_annual_income,
        spouse_monthly_debt_payment=spouse_monthly_debt_payment,
        mortgage_rate=mortgage_rate,
        loan_term_years=loan_term_years,
        purchase_cost_rate=purchase_cost_rate,
    )
    budget_eok = _budget_eok(budget)
    budget_source = "input"
    can_estimate_budget = bool(
        policy_profile["cashEok"]
        and policy_profile["annualIncomeManwon"]
        and policy_profile["mortgageRatePercent"]
    )
    estimate_regions = _region_terms(region) or ["서울시", "경기도"]
    if budget_eok > 0 and can_estimate_budget and region:
        regional_budget_eok = policy_evaluator.estimated_purchase_ceiling(policy_profile, estimate_regions)
        if regional_budget_eok > 0:
            budget_eok = regional_budget_eok
            budget_source = "region_adjusted"
    elif budget_eok <= 0:
        if not policy_profile["cashEok"] or not policy_profile["annualIncomeManwon"] or not policy_profile["mortgageRatePercent"]:
            return {"error": "자기자금, 주 대출 신청자 연소득, 예상 대출금리를 입력해 주세요.", "status": 400}
        budget_eok = policy_evaluator.estimated_purchase_ceiling(policy_profile, estimate_regions)
        budget_source = "calculated"
        if budget_eok <= 0:
            return {"error": "입력한 소득·부채·자기자금 기준으로 계산 가능한 매수 상한이 없어요.", "status": 400}
    price_strategy = price_strategy if price_strategy in PRICE_STRATEGY_LABELS else "stretch"
    min_area = _float_value(min_area)
    min_households = _int_value(min_households)
    max_building_age = _int_value(max_building_age)

    rows = []
    filtered = {
        "region": 0,
        "identity": 0,
        "price": 0,
        "area": 0,
        "households": 0,
        "buildingAge": 0,
        "rental": 0,
        "noLastDeal": 0,
    }
    for row in _load_price_bands():
        entity_matches = _find_entities(
            row["name"],
            row.get("region", ""),
            row.get("legalDong", ""),
            row.get("jibun", ""),
        )
        if len(entity_matches) > 1 and not (row.get("legalDong") and row.get("jibun")):
            filtered["identity"] += 1
            continue
        entity = entity_matches[0] if entity_matches else None
        if entity and entity.get("aggregate"):
            filtered["identity"] += 1
            continue
        if _is_rental_apartment(row, entity):
            filtered["rental"] += 1
            continue
        if not _matches_region(row, entity, region):
            filtered["region"] += 1
            continue
        households = real_estate_search._int_value(entity.get("households")) if entity else 0
        building = _building_profile(entity)
        area_min, area_max = _area_range(row.get("areaLabel"))
        if min_area and area_max and area_max < min_area:
            filtered["area"] += 1
            continue
        if min_households and households < min_households:
            filtered["households"] += 1
            continue
        if max_building_age and (not building["buildingAge"] or building["buildingAge"] > max_building_age):
            filtered["buildingAge"] += 1
            continue
        search_query = row["name"]
        if entity:
            scope = region or entity.get("district") or entity.get("city") or row.get("region")
            search_query = real_estate_search._region_apartment_search_query(entity, scope)
        candidate = {
            "name": row["name"],
            "region": row.get("region", ""),
            "legalDong": row.get("legalDong") or (entity or {}).get("legalDong", ""),
            "jibun": row.get("jibun") or _entity_jibun(entity),
            "areaLabel": row.get("areaLabel", ""),
            "minPriceEok": row.get("minPriceEok"),
            "midPriceEok": row.get("midPriceEok"),
            "maxPriceEok": row.get("maxPriceEok"),
            "households": households,
            "searchQuery": search_query,
            "updatedAt": row.get("updatedAt", ""),
            "sourceNote": row.get("sourceNote", ""),
            "priceSource": row.get("priceSource") or "manual",
            "transactionCount": row.get("transactionCount") or 0,
            "latestDealDate": row.get("latestDealDate") or "",
            "sourceUrl": row.get("sourceUrl") or "",
            "areaMin": area_min,
            "areaMax": area_max,
            **building,
            **_naver_property_link(row, entity),
            "_budgetEok": budget_eok,
        }
        _apply_fit(candidate, budget_eok)
        if (
            candidate["fitStatus"] == "제외"
            and candidate["priceSource"] in VERIFIED_PRICE_SOURCES
            and not (molit_transactions.enabled() and min_area)
        ):
            filtered["price"] += 1
            continue
        candidate["_score"] = _candidate_score(candidate, entity, purpose, priority, commute, price_strategy)
        rows.append(candidate)

    live_seed_count = 0
    if not fast_mode and region and (molit_transactions.enabled() or all_matches):
        seen_seed_keys = {
            (
                real_estate_search.compact(row.get("name")),
                real_estate_search.compact(row.get("region")),
            )
            for row in rows
        }
        for entity in real_estate_search.APARTMENT_MASTER:
            name_key = real_estate_search.compact(entity.get("name"))
            seed_region = entity.get("district") or entity.get("city") or ""
            seed_key = (name_key, real_estate_search.compact(seed_region))
            if not name_key or seed_key in seen_seed_keys:
                continue
            if _is_rental_apartment({"name": entity.get("name", "")}, entity):
                filtered["rental"] += 1
                continue
            households = real_estate_search._int_value(entity.get("households"))
            building = _building_profile(entity)
            if min_households and households < min_households:
                continue
            if max_building_age and (not building["buildingAge"] or building["buildingAge"] > max_building_age):
                continue
            candidate = _candidate_from_entity(
                entity,
                region,
                min_area,
                budget_eok,
                purpose,
                priority,
                commute,
                price_strategy,
            )
            if not candidate:
                continue
            seen_seed_keys.add(seed_key)
            rows.append(candidate)
            live_seed_count += 1

    if not rows:
        return {
            "budgetEok": budget_eok,
            "budgetText": _price_text(budget_eok),
            "budgetSource": budget_source,
            "region": region,
            "purpose": purpose,
            "priority": priority,
            "priceStrategy": price_strategy,
            "commute": commute,
            "moveTiming": move_timing,
            "purposeLabel": _multi_label(purpose, PURPOSE_LABELS, "매수 검토"),
            "priorityLabel": _multi_label(priority, PRIORITY_LABELS, ""),
            "moveTimingLabel": MOVE_TIMING_LABELS.get(move_timing, ""),
            "candidates": [],
            "excludedCount": filtered["price"],
            "filterSummary": filtered,
            "noLastDealCount": 0,
            "rentalExcludedCount": filtered["rental"],
            "priceBandCount": len(_load_price_bands()),
            "policySnapshot": {
                **policy_evaluator.summarize([], policy_profile),
                "estimatedPurchaseCeilingEok": budget_eok,
                "budgetSource": budget_source,
            },
            "message": "입력한 필수 조건을 모두 통과한 후보를 찾지 못했어요. 면적·세대수·연식 조건을 하나씩 완화해 보세요.",
        }

    if not fast_mode and molit_transactions.enabled():
        enrich_limit = max(1, (
            min(len(rows), config.MOLIT_TRANSACTION_ALL_MATCHES_ENRICH_LIMIT)
            if all_matches
            else max(config.MOLIT_TRANSACTION_ENRICH_LIMIT, max(limit, 1))
        ))
        priced_rows = [row for row in rows if not row.get("_liveLookup")]
        live_lookup_rows = [row for row in rows if row.get("_liveLookup")]
        ranked_priced = sorted(
            priced_rows,
            key=lambda row: (row["_fitRank"], -row["_score"], abs(row["budgetGapEok"])),
        )
        ranked_live = sorted(
            live_lookup_rows,
            key=lambda row: (-row["_score"], -(row.get("households") or 0), row.get("buildingAge") or 999, row["name"]),
        )
        # 정적 가격 후보와 신규 실거래 조회 후보를 합쳐 전체 보강 한도를 지킨다.
        # 신규 후보에는 최대 1/3을 먼저 배정하고, 남는 자리는 어느 쪽이든 채운다.
        live_target = min(len(ranked_live), max(1, enrich_limit // 3)) if ranked_live else 0
        priced_target = min(len(ranked_priced), enrich_limit - live_target)
        preselected = [*ranked_priced[:priced_target], *ranked_live[:live_target]]
        remaining = enrich_limit - len(preselected)
        if remaining > 0:
            preselected.extend(ranked_priced[priced_target:priced_target + remaining])
            remaining = enrich_limit - len(preselected)
        if remaining > 0:
            preselected.extend(ranked_live[live_target:live_target + remaining])
        # 후보 전체가 필요로 하는 (지역코드, 월)을 모아 한 번에 병렬 프리페치.
        # 이후 개별 조회는 전부 캐시 히트가 되어 직렬 HTTP 왕복이 사라진다.
        recent_months = molit_transactions._deal_months()
        prefetch_pairs = set()
        for row in preselected:
            try:
                for source_row in molit_transactions.source_rows(row["name"], row.get("region", "")):
                    lawd_cd = molit_transactions._row_lawd_cd(source_row)
                    if not lawd_cd:
                        continue
                    for deal_ymd in recent_months:
                        prefetch_pairs.add((lawd_cd, deal_ymd))
            except Exception:
                continue

        # 정적 국토부 가격대 파일은 거래 범위와 날짜만 보관하므로, 카드의
        # 대표 가격은 반드시 같은 면적대의 가장 최근 거래 1건으로 다시 채운다.
        # 앞선 우선순위 조회에서 밀린 단지도 범위가 대표값으로 남지 않게 한다.
        for row in rows:
            if (
                row.get("priceSource") not in VERIFIED_PRICE_SOURCES
                or not row.get("latestDealDate")
                or _float_value(row.get("latestDealPriceEok"))
            ):
                continue
            try:
                _apply_live_price(row, preferred_min_area=min_area)
                _apply_fit(row, budget_eok)
                row["_score"] = _candidate_score(
                    row,
                    _find_entity(row["name"], row.get("region", "")),
                    purpose,
                    priority,
                    commute,
                    price_strategy,
                )
            except Exception:
                continue
        molit_transactions.prefetch_months(prefetch_pairs)
        for row in preselected:
            try:
                _apply_live_price(row, preferred_min_area=min_area)
                if row.get("priceSource") not in VERIFIED_PRICE_SOURCES and not row.get("latestDealDate"):
                    _apply_last_observed_deal(row, preferred_min_area=min_area)
                _apply_fit(row, budget_eok)
                row["_score"] = _candidate_score(row, _find_entity(row["name"], row.get("region", "")), purpose, priority, commute, price_strategy)
            except Exception:
                continue

    verified_rows = []
    unverified_price_count = 0
    last_deal_over_budget_count = 0
    no_last_deal_count = 0
    for row in rows:
        if _float_value(row.get("lastObservedDealPriceEok")) > budget_eok:
            filtered["price"] += 1
            last_deal_over_budget_count += 1
            continue
        if row.get("priceSource") not in VERIFIED_PRICE_SOURCES:
            if not _float_value(row.get("lastObservedDealPriceEok")):
                filtered["noLastDeal"] += 1
                no_last_deal_count += 1
                continue
            unverified_price_count += 1
            if all_matches:
                _apply_fit(row, budget_eok)
                verified_rows.append(row)
            continue
        _apply_fit(row, budget_eok)
        if row["fitStatus"] == "제외":
            filtered["price"] += 1
            continue
        verified_rows.append(row)
    rows = verified_rows

    picked = list(rows)
    picked.sort(key=lambda row: (-row["_score"], abs(row["budgetGapEok"]), row["midPriceEok"]))
    unique_rows = _dedupe_candidate_rows(picked)

    total_matched_count = len(unique_rows)
    result_limit = max(1, config.BUDGET_ALL_MATCHES_RESULT_LIMIT)
    if all_matches and len(unique_rows) > result_limit:
        unique_rows = unique_rows[:result_limit]

    for row in unique_rows:
        entity = _find_entity(row["name"], row.get("region", ""))
        row["policyImpact"] = (
            policy_evaluator.evaluate_candidate(row, entity=entity, profile=policy_profile)
            if row.get("midPriceEok")
            else None
        )

    policy_excluded_rows = []
    if all_matches:
        policy_allowed_rows = unique_rows
        policy_excluded_rows = [
            row for row in unique_rows
            if row.get("policyImpact") and row["policyImpact"].get("status") != "possible"
        ]
    elif policy_profile["cashEok"]:
        policy_allowed_rows = [row for row in unique_rows if row["policyImpact"].get("status") == "possible"]
        policy_excluded_rows = [row for row in unique_rows if row["policyImpact"].get("status") != "possible"]
        policy_excluded_rows.sort(key=lambda row: (abs(row["policyImpact"].get("cashGapEok") or 999), -row["_score"]))
    else:
        policy_allowed_rows = unique_rows

    candidates = policy_allowed_rows if all_matches else policy_allowed_rows[:limit]
    policy_excluded_candidates = [] if all_matches else policy_excluded_rows[:limit]
    for row in [*candidates, *policy_excluded_candidates]:
        entity = _find_entity(row["name"], row.get("region", ""))
        row["displayName"] = _candidate_display_name(row, entity)
        row["displayRegion"] = _display_region(row, entity)
        row["displayAreaLabel"] = _display_area_label(row.get("areaLabel"))
        row.update(_decision_support(row, entity, purpose, priority, commute, move_timing, price_strategy, region))
        row.pop("_fitRank", None)
        row.pop("_score", None)
        row.pop("_budgetEok", None)

    display_rows = [*candidates, *policy_excluded_candidates]
    if not fast_mode and display_rows and molit_transactions.configured():
        # 시그널 계산에 필요한 (지역코드, 월)을 후보 전체 기준으로 병렬 선적재
        signal_months = molit_transactions._deal_months(momentum_signals.LOOKBACK_MONTHS)
        signal_pairs = set()
        for row in display_rows:
            try:
                for source_row in molit_transactions.source_rows(row["name"], row.get("region", "")):
                    lawd_cd = molit_transactions._row_lawd_cd(source_row)
                    if lawd_cd:
                        signal_pairs.update((lawd_cd, deal_ymd) for deal_ymd in signal_months)
            except Exception:
                continue
        # 회로 차단 중이면 prefetch_months는 즉시 반환하고, attach_signals가
        # 기존 월별 캐시를 사용해 점수 계산을 계속한다.
        molit_transactions.prefetch_months(signal_pairs)
        try:
            momentum_signals.attach_signals(display_rows)
        except Exception:
            pass

    if display_rows:
        if not fast_mode:
            try:
                naver_complex.attach_links(display_rows)
            except Exception:
                pass
        try:
            verdicts.attach_verdicts(display_rows, budget_eok)
        except Exception:
            pass

    result_message = ""
    if policy_profile["cashEok"] and not candidates and policy_excluded_candidates:
        result_message = "현재 자금과 정책상 대출 기준을 모두 통과한 후보가 없어요. 추가 자금 필요 후보에서 단지별 필요 금액을 확인할 수 있어요."
    elif no_last_deal_count and not candidates:
        result_message = "마지막 국토부 실거래 이력이 확인되지 않은 단지는 결과에서 제외했어요."
    elif unverified_price_count and not candidates:
        result_message = "최신 실거래를 확인하지 못한 수동 가격 후보는 결과에서 제외했어요. 국토부 API 연결을 복구한 뒤 다시 확인해 주세요."

    return {
        "budgetEok": budget_eok,
        "budgetText": _price_text(budget_eok),
        "budgetSource": budget_source,
        "region": region,
        "purpose": purpose,
        "priority": priority,
        "priceStrategy": price_strategy,
        "commute": commute,
        "moveTiming": move_timing,
        "purposeLabel": _multi_label(purpose, PURPOSE_LABELS, "매수 검토"),
        "priorityLabel": _multi_label(priority, PRIORITY_LABELS, ""),
        "moveTimingLabel": MOVE_TIMING_LABELS.get(move_timing, ""),
        "candidates": candidates,
        "policyExcludedCandidates": policy_excluded_candidates,
        "policyExcludedCount": 0 if all_matches else len(policy_excluded_rows),
        "policyEligibleCount": len(policy_allowed_rows),
        "allMatches": bool(all_matches),
        "initialStage": bool(fast_mode),
        "totalMatchedCount": total_matched_count,
        "resultLimited": total_matched_count > len(unique_rows),
        "resultLimit": result_limit if all_matches else limit,
        "excludedCount": filtered["price"],
        "filterSummary": filtered,
        "eligibleCount": len(rows),
        "priceBandCount": len(rows),
        "unverifiedPriceCount": unverified_price_count,
        "lastDealOverBudgetCount": last_deal_over_budget_count,
        "noLastDealCount": no_last_deal_count,
        "rentalExcludedCount": filtered["rental"],
        "liveSeedCount": live_seed_count,
        "livePriceEnabled": molit_transactions.enabled(),
        "livePriceCount": sum(1 for row in candidates if row.get("priceSource") in VERIFIED_PRICE_SOURCES),
        "officialPriceBandCount": sum(1 for row in rows if row.get("priceSource") in VERIFIED_PRICE_SOURCES),
        "livePriceError": molit_transactions.last_error(),
        "policySnapshot": {
            **policy_evaluator.summarize(
                [row["policyImpact"] for row in unique_rows if row.get("policyImpact")],
                policy_profile,
            ),
            "estimatedPurchaseCeilingEok": budget_eok,
            "budgetSource": budget_source,
        },
        "rankingNote": (
            "지역·최소면적·세대수·연식 조건을 통과하고, 최근 또는 마지막 국토부 실거래가가 확인된 단지입니다. 마지막 확인 실거래가가 매수 가능 상한을 넘는 단지와 실거래 이력 미확인 단지는 제외했습니다."
            if all_matches
            else "최신 실거래 근거가 확인된 후보만 표시합니다. 수동 가격과 주차·학군·매물 상태는 후보 판정에 사용하지 않습니다."
        ),
        "signalNote": momentum_signals.SIGNAL_NOTE,
        "message": result_message,
    }
