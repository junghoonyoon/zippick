"""아파트 관련 기사에서 매수 판단에 영향을 주는 변화만 선별한다.

추천 문장에는 단지명이 직접 언급되고 착공·개통·인가처럼 진행 단계가
확인된 변화만 반영한다. 카드 하단에는 단지 직접 소식과 해당 법정동의
광역 교통·대규모 개발 소식만 제공한다.
"""
import datetime
import hashlib
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

import config


API_HUB_ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/news"
DEVELOPERS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
CACHE_DIR = config.CACHE_DIR / "news_catalysts"
CACHE_VERSION = "v10"
CACHE_LOCK = threading.Lock()
KEY_LOCKS = {}
KEY_LOCKS_LOCK = threading.Lock()

CONFIRMED_STAGE_RULES = (
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"관리처분(?:계획\s*)?인가"),
        "label": "정비사업 관리처분인가",
        "score": 120,
    },
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"사업시행(?:계획\s*)?인가"),
        "label": "정비사업 사업시행인가",
        "score": 116,
    },
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"조합설립인가"),
        "label": "정비사업 조합설립인가",
        "score": 112,
    },
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"정비구역\s*(?:지정|고시)"),
        "label": "정비구역 지정",
        "score": 108,
    },
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"정비계획\s*(?:확정|결정|고시|통과)"),
        "label": "정비계획 확정",
        "score": 104,
    },
    {
        "category": "reconstruction",
        "subject": re.compile(r"(재건축|재개발|정비사업)"),
        "stage": re.compile(r"(?:안전진단|재건축진단)\s*(?:통과|면제)"),
        "label": "재건축진단 통과",
        "score": 100,
    },
    {
        "category": "transport",
        "subject": re.compile(
            r"(GTX(?:[-·\s]?[A-F])?|신안산선|신분당선|월곶판교선|동북선|"
            r"서부선|위례신사선|대장홍대선|도시철도|경전철|지하철|철도|"
            r"\d+호선)"
        ),
        "stage": re.compile(
            r"(개통|착공|실시계획\s*승인|사업계획\s*승인|"
            r"예비타당성(?:조사)?\s*통과|노선\s*확정|기본계획\s*확정)"
        ),
        "label": "",
        "score": 90,
    },
    {
        "category": "development",
        "subject": re.compile(
            r"(복합개발|도시개발|개발사업|업무지구|산업단지|테크노밸리|"
            r"복합환승센터|대형병원|종합병원)"
        ),
        "stage": re.compile(
            r"(착공|준공|개장|개원|개교|실시계획\s*승인|사업계획\s*승인|"
            r"개발계획\s*(?:승인|확정)|사업시행자\s*지정)"
        ),
        "label": "",
        "score": 78,
    },
)

RELATED_PROGRESS_STAGE = re.compile(
    r"(추진|검토|협의|논의|발표|공모|입찰|발주|협약\s*체결|"
    r"시공사\s*(?:선정|확정)|사업자\s*선정|우선협상대상자\s*선정|"
    r"도시계획위원회\s*(?:심의|통과)|주민공람|계획안\s*(?:공개|통과)|"
    r"기본계획\s*(?:수립|고시)|착공\s*예정|개통\s*예정|준공\s*예정)"
)
NEARBY_RECONSTRUCTION_PROGRESS = re.compile(
    r"(시공사\s*(?:선정|확정)|도시계획위원회\s*통과)"
)
UNCONFIRMED_STAGE_TITLE = re.compile(
    r"(조합설립인가\s*(?:신청|예정)|"
    r"(?:정비구역\s*지정|정비계획\s*(?:확정|결정|통과))\s*(?:신청|예정)|"
    r"시공사\s*선정\s*(?:준비|예정|절차|입찰|착수)|"
    r"(?:인가|지정|선정|확정|통과)\s*(?:가시화|유력|임박)|"
    r"성사되나)"
)
RELATED_SUBJECT = re.compile(
    r"(재건축|재개발|정비사업|리모델링|GTX(?:[-·\s]?[A-F])?|"
    r"신안산선|신분당선|월곶판교선|동북선|서부선|위례신사선|"
    r"대장홍대선|도시철도|경전철|지하철|철도|\d+호선|"
    r"복합개발|도시개발|개발사업|업무지구|산업단지|테크노밸리|"
    r"복합환승센터|대형병원|종합병원|역세권)"
)
NEARBY_MAJOR_DEVELOPMENT = re.compile(
    r"(복합개발|도시개발|업무지구|산업단지|테크노밸리|"
    r"복합환승센터|대형병원|종합병원)"
)
PROMOTIONAL_NEWS = re.compile(
    r"(청약\s*(?:예정|접수|일정|시작)|분양\s*(?:예정|중|개시|돌입)|"
    r"견본주택|모델하우스|홍보관|특별공급|일반공급|입주자\s*모집|"
    r"선착순|계약금\s*\d|프리미엄\s*(?:기대|주목)|"
    r"(?:수요자|투자자).{0,12}(?:눈길|주목))"
)
LIFESTYLE_NEWS = re.compile(
    r"(물놀이장|문화재단|도서관|인문학|지혜학교|장학금|후원|"
    r"축제|캠페인|공모사업|강연|탐방|체험|공연|전시|"
    r"복지\s*(?:사업|프로그램)|봉사|기부|나눔|건강검진|"
    r"체육대회|걷기대회|주민\s*(?:교육|프로그램)|구민\s*(?:대상|행사))"
)
POLITICAL_GENERAL_NEWS = re.compile(
    r"(\[?기획특집\]?|당선자|당선인|"
    r"(?:시장|구청장|군수|도지사|국회의원|시의원|구의원)\s*후보자?|"
    r"선거|공약|취임|"
    r"민선\s*\d+기|(?:구청장|시장)\s*(?:인터뷰|대담)|대전환\s*시대)"
)
MARKET_ONLY_NEWS = re.compile(
    r"(신고가|최고가|집값|시세|급매|매매가|전셋값|거래량|"
    r"청약경쟁률|분양가|경매|호가|관망세|세제개편|"
    r"부동산\s*시장|주택\s*시장|수요\s*(?:증가|감소|쏠림)|"
    r"\d+(?:만|억)원|가격\s*(?:상승|하락)|급등|급락|"
    r"오르(?:다|고|는|며)|올랐|내렸|떨어졌|빠졌|상승\s*왜|하락\s*왜)"
)


def configured():
    return bool(
        (
            config.NAVER_API_HUB_CLIENT_ID
            and config.NAVER_API_HUB_CLIENT_SECRET
        )
        or (
            config.NAVER_SEARCH_CLIENT_ID
            and config.NAVER_SEARCH_CLIENT_SECRET
        )
    )


def _provider():
    if config.NAVER_API_HUB_CLIENT_ID and config.NAVER_API_HUB_CLIENT_SECRET:
        return {
            "name": "naver_api_hub",
            "endpoint": API_HUB_ENDPOINT,
            "headers": {
                "X-NCP-APIGW-API-KEY-ID": config.NAVER_API_HUB_CLIENT_ID,
                "X-NCP-APIGW-API-KEY": config.NAVER_API_HUB_CLIENT_SECRET,
            },
        }
    if config.NAVER_SEARCH_CLIENT_ID and config.NAVER_SEARCH_CLIENT_SECRET:
        return {
            "name": "naver_developers",
            "endpoint": DEVELOPERS_ENDPOINT,
            "headers": {
                "X-Naver-Client-Id": config.NAVER_SEARCH_CLIENT_ID,
                "X-Naver-Client-Secret": config.NAVER_SEARCH_CLIENT_SECRET,
            },
        }
    return None


def _clean_text(value):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _compact(value):
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", _clean_text(value)).lower()


def _name_variants(apartment):
    values = [
        apartment.get("name"),
        apartment.get("displayName"),
        apartment.get("naverComplexName"),
    ]
    variants = set()
    for value in values:
        clean = _clean_text(value)
        if not clean:
            continue
        candidates = {
            clean,
            re.sub(r"\([^)]*\)", "", clean),
            re.sub(r"(?:아파트|주상복합)$", "", clean),
            clean.replace("아파트", ""),
        }
        reordered = re.match(
            r"^(?P<prefix>[가-힣A-Za-z]{2,})(?P<order>\d+차)(?P<brand>[가-힣A-Za-z]{2,})$",
            re.sub(r"(?:아파트|주상복합)$", "", clean),
        )
        if reordered:
            candidates.add(
                f"{reordered.group('prefix')}{reordered.group('brand')}{reordered.group('order')}"
            )
        if "신시가지" in clean:
            candidates.add(re.sub(r"신시가지(?:아파트)?", "", clean))
        for candidate in candidates:
            compact = _compact(candidate)
            if len(compact) >= 4:
                variants.add(compact)
    return variants


def _article_location_variants(apartment):
    """Return specific location hints that can disambiguate short complex names."""
    values = [
        apartment.get("legalDong"),
        apartment.get("displayRegion"),
    ]
    if not _clean_text(apartment.get("displayRegion")):
        values.append(apartment.get("region"))
    variants = set()
    for value in values:
        for token in re.split(r"[\s>·,/]+", _clean_text(value)):
            compact = _compact(token)
            if len(compact) < 2 or compact.endswith("도"):
                continue
            variants.add(compact)
            base = re.sub(r"(?:시|군|구|동|읍|면)$", "", compact)
            if len(base) >= 2:
                variants.add(base)
            # 화면 표시용 지역명이 '성남중원구', '수원영통구'처럼 시·구를
            # 붙여 보내는 경우 기사에는 보통 앞의 도시명만 적힌다.
            if compact.endswith("구") and len(base) >= 4:
                variants.add(base[:2])
    return variants


def _article_mentions_apartment(article_text, apartment):
    compact_text = _compact(article_text)
    variants = _name_variants(apartment)
    if not variants or not any(variant in compact_text for variant in variants):
        return False
    # 짧고 흔한 단지명은 같은 동이나 지역까지 기사에 나와야 오탐을 줄인다.
    if max(map(len, variants)) >= 6:
        return True
    locations = _article_location_variants(apartment)
    return any(location and location in compact_text for location in locations)


def _article_mentions_location(article_text, apartment):
    compact_text = _compact(article_text)
    legal_dong = _compact(apartment.get("legalDong"))
    if len(legal_dong) < 2:
        return False
    locations = {legal_dong}
    if len(legal_dong) >= 3 and legal_dong.endswith("동"):
        locations.add(legal_dong[:-1])
    return any(len(location) >= 2 and location in compact_text for location in locations)


def _article_mentions_complex_family(article_text, apartment):
    compact_text = _compact(article_text)
    for field in ("name", "displayName", "naverComplexName"):
        compact_name = _compact(apartment.get(field))
        if not compact_name:
            continue
        family = re.sub(r"(?:아파트)?\d+단지.*$", "", compact_name)
        if len(family) >= 4 and family in compact_text:
            return True
        if "신시가지" in compact_name:
            area_name = compact_name.split("신시가지", 1)[0]
            if len(area_name) >= 2 and area_name in compact_text:
                return True
    return False


def _article_is_irrelevant(title):
    return any(pattern.search(title) for pattern in (
        PROMOTIONAL_NEWS,
        LIFESTYLE_NEWS,
        POLITICAL_GENERAL_NEWS,
    ))


def _normalized_stage(match):
    return re.sub(r"\s+", "", match.group(0))


def _event_label(rule, subject_match, stage_match):
    if rule["label"]:
        return rule["label"]
    subject = re.sub(r"\s+", "", subject_match.group(0)).upper()
    stage = _normalized_stage(stage_match)
    if rule["category"] == "transport":
        if subject in {"도시철도", "경전철", "지하철", "철도"}:
            subject = "인근 교통사업"
        return f"{subject} {stage}"
    if subject in {"개발사업", "도시개발"}:
        subject = "인근 개발사업"
    return f"{subject} {stage}"


def _confirmed_event(text):
    matches = []
    for rule in CONFIRMED_STAGE_RULES:
        subject_match = rule["subject"].search(text)
        stage_match = rule["stage"].search(text)
        if not subject_match or not stage_match:
            continue
        matches.append({
            "category": rule["category"],
            "label": _event_label(rule, subject_match, stage_match),
            "score": rule["score"],
        })
    return max(matches, key=lambda row: row["score"]) if matches else None


def _progress_event(text):
    subject_match = RELATED_SUBJECT.search(text)
    stage_match = RELATED_PROGRESS_STAGE.search(text)
    if not subject_match or not stage_match:
        return None
    subject = re.sub(r"\s+", "", subject_match.group(0)).upper()
    if subject in {"도시철도", "경전철", "지하철", "철도"}:
        subject = "인근 교통사업"
    elif subject in {"개발사업", "도시개발"}:
        subject = "인근 개발사업"
    if re.search(r"(재건축|재개발|정비사업|리모델링)", subject_match.group(0)):
        category = "reconstruction"
    elif re.search(
        r"(GTX|신안산선|신분당선|월곶판교선|동북선|서부선|"
        r"위례신사선|대장홍대선|도시철도|경전철|지하철|철도|\d+호선)",
        subject_match.group(0),
    ):
        category = "transport"
    else:
        category = "development"
    return {
        "category": category,
        "label": f"{subject} {_normalized_stage(stage_match)}",
        "score": 45,
    }


def _nearby_event_allowed(confirmed, progress, title):
    event = confirmed or progress
    if not event:
        return False
    if UNCONFIRMED_STAGE_TITLE.search(title):
        return False
    if event.get("category") == "transport":
        return True
    if event.get("category") == "reconstruction":
        return bool(
            confirmed
            or NEARBY_RECONSTRUCTION_PROGRESS.search(title)
        )
    return (
        event.get("category") == "development"
        and bool(NEARBY_MAJOR_DEVELOPMENT.search(title))
    )


def _published_at(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_article_url(article):
    for field in ("originallink", "link"):
        value = str(article.get(field) or "").strip()
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return ""


def _article_basics(article, now=None, lookback_days=None):
    title = _clean_text(article.get("title"))
    description = _clean_text(article.get("description"))
    text = f"{title} {description}".strip()
    if not title:
        return None
    published = _published_at(article.get("pubDate"))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not published:
        return None
    age_days = max(0, (now - published).total_seconds() / 86400)
    if age_days > (lookback_days or config.NEWS_CATALYST_LOOKBACK_DAYS):
        return None
    url = _safe_article_url(article)
    if not url:
        return None
    return {
        "title": title,
        "description": description,
        "text": text,
        "url": url,
        "publishedAt": published.date().isoformat(),
        "ageDays": age_days,
    }



def _article_candidate(article, apartment, now=None):
    basics = _article_basics(article, now=now)
    if (
        not basics
        or _article_is_irrelevant(basics["title"])
        or UNCONFIRMED_STAGE_TITLE.search(basics["title"])
        or not _article_mentions_apartment(basics["title"], apartment)
    ):
        return None
    event = _confirmed_event(basics["text"])
    if not event:
        return None
    score = event["score"]
    if _article_mentions_apartment(basics["title"], apartment):
        score += 8
    score += max(0, 6 - basics["ageDays"] / 60)
    return {
        **event,
        "score": score,
        "title": basics["title"],
        "url": basics["url"],
        "publishedAt": basics["publishedAt"],
    }


def _related_news_candidate(article, apartment, now=None):
    basics = _article_basics(
        article,
        now=now,
        lookback_days=config.NEWS_RELATED_LOOKBACK_DAYS,
    )
    if not basics:
        return None
    if _article_is_irrelevant(basics["title"]):
        return None
    direct = _article_mentions_apartment(basics["title"], apartment)
    nearby = (
        _article_mentions_location(basics["title"], apartment)
        or _article_mentions_complex_family(basics["title"], apartment)
    )
    if not direct and not nearby:
        return None

    direct_confirmed = _confirmed_event(basics["text"])
    direct_progress = _progress_event(basics["text"])
    if direct and UNCONFIRMED_STAGE_TITLE.search(basics["title"]):
        direct_confirmed = None
    if nearby and not direct:
        confirmed = _confirmed_event(basics["title"])
        progress = _progress_event(basics["title"])
    else:
        confirmed = direct_confirmed
        progress = direct_progress
    subject = RELATED_SUBJECT.search(basics["text"])
    fresh_confirmed = (
        confirmed
        and basics["ageDays"] <= config.NEWS_CATALYST_LOOKBACK_DAYS
    )
    event = confirmed or progress
    if nearby and not direct and not _nearby_event_allowed(
        confirmed,
        progress,
        basics["title"],
    ):
        return None
    if direct and not (confirmed or progress or subject):
        return None
    if direct and not fresh_confirmed and MARKET_ONLY_NEWS.search(basics["title"]):
        return None

    if direct and fresh_confirmed:
        badge = "확인된 호재"
        status = "confirmed"
    elif direct:
        badge = "단지 소식"
        status = "related"
    else:
        badge = (
            "인근 정비사업"
            if event.get("category") == "reconstruction"
            else "인근 교통·개발"
        )
        status = "nearby"
    event_label = event["label"] if event else _clean_text(subject.group(0))
    score = (90 if direct else 35) + (45 if fresh_confirmed else 20 if progress else 0)
    score += max(0, 10 - basics["ageDays"] / 90)
    return {
        "scope": "complex" if direct else "area",
        "status": status,
        "badge": badge,
        "eventLabel": event_label,
        "title": basics["title"],
        "url": basics["url"],
        "publishedAt": basics["publishedAt"],
        "score": score,
    }


def _select_catalyst(articles, apartment):
    candidates = [
        candidate
        for article in articles
        if (candidate := _article_candidate(article, apartment))
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (row["score"], row["publishedAt"]),
        reverse=True,
    )
    selected = candidates[0]
    matching_urls = {
        row["url"]
        for row in candidates
        if row["category"] == selected["category"] and row["label"] == selected["label"]
    }
    return {
        "category": selected["category"],
        "label": selected["label"],
        "title": selected["title"],
        "url": selected["url"],
        "publishedAt": selected["publishedAt"],
        "articleCount": len(matching_urls),
    }


def _select_related_news(articles, apartment):
    candidates = [
        candidate
        for article in articles
        if (candidate := _related_news_candidate(article, apartment))
    ]
    candidates.sort(
        key=lambda row: (row["score"], row["publishedAt"]),
        reverse=True,
    )
    selected = []
    seen_urls = set()
    seen_events = set()

    def append_candidate(candidate):
        event_key = (
            candidate["scope"],
            _compact(candidate.get("eventLabel") or candidate["title"]),
        )
        if candidate["url"] in seen_urls or event_key in seen_events:
            return
        seen_urls.add(candidate["url"])
        seen_events.add(event_key)
        selected.append({
            key: value
            for key, value in candidate.items()
            if key != "score"
        })

    # 자기 단지 기사와 주변 정비·교통 변화를 함께 볼 수 있도록 두 범주가
    # 모두 있으면 각각 한 자리를 먼저 확보한다.
    if config.NEWS_RELATED_LIMIT >= 2:
        direct = next((row for row in candidates if row["scope"] == "complex"), None)
        nearby = next((row for row in candidates if row["scope"] == "area"), None)
        if direct:
            append_candidate(direct)
        if nearby:
            append_candidate(nearby)

    for candidate in candidates:
        append_candidate(candidate)
        if len(selected) >= config.NEWS_RELATED_LIMIT:
            break
    return selected


def _cache_key(apartment):
    material = "|".join(
        _compact(apartment.get(field))
        for field in (
            "name",
            "displayName",
            "naverComplexName",
            "region",
            "displayRegion",
            "legalDong",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{CACHE_VERSION}_{digest}"


def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


def _read_cache(key):
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(cached.get("savedAt") or 0) > config.NEWS_CATALYST_CACHE_TTL_SECONDS:
        return None
    return cached


def _write_cache(key, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    body = {**payload, "savedAt": time.time()}
    path = _cache_path(key)
    temporary = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _key_lock(key):
    with KEY_LOCKS_LOCK:
        return KEY_LOCKS.setdefault(key, threading.Lock())


def _specific_location(apartment):
    legal_dong = _clean_text(apartment.get("legalDong"))
    if legal_dong:
        return legal_dong
    for field in ("displayRegion", "region"):
        value = _clean_text(apartment.get(field))
        matches = re.findall(r"([가-힣0-9]{2,}(?:동|읍|면))(?=\s|$)", value)
        if matches:
            return matches[-1]
    return ""


def _query(apartment):
    name = _clean_text(
        apartment.get("displayName")
        or apartment.get("naverComplexName")
        or apartment.get("name")
    )
    location = _specific_location(apartment) or _clean_text(apartment.get("region"))
    return " ".join(value for value in (name, location) if value)


def _search_query(query):
    provider = _provider()
    if not provider or not query:
        return None
    params = {
        "query": query,
        "display": config.NEWS_CATALYST_SEARCH_RESULTS,
        "start": 1,
        "sort": "date",
    }
    if provider["name"] == "naver_api_hub":
        params["format"] = "json"
    response = requests.get(
        provider["endpoint"],
        params=params,
        headers=provider["headers"],
        timeout=config.NEWS_CATALYST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _search_articles(apartment):
    return _search_query(_query(apartment))


def _search_area_articles(apartment):
    location = (
        _specific_location(apartment)
        or _clean_text(apartment.get("displayRegion") or apartment.get("region"))
    )
    return _search_query(location) if location else []


def news_bundle_for_apartment(apartment):
    if not configured() or not isinstance(apartment, dict):
        return {"catalyst": None, "news": []}
    key = _cache_key(apartment)
    with _key_lock(key):
        with CACHE_LOCK:
            cached = _read_cache(key)
        if cached is not None:
            return {
                "catalyst": cached.get("catalyst"),
                "news": cached.get("news") or [],
            }
        direct_articles = _search_articles(apartment)
        if direct_articles is None:
            return {"catalyst": None, "news": []}
        area_articles = _search_area_articles(apartment)
        articles_by_url = {}
        for article in [*direct_articles, *(area_articles or [])]:
            url = _safe_article_url(article)
            if url:
                articles_by_url.setdefault(url, article)
        articles = list(articles_by_url.values())
        catalyst = _select_catalyst(articles, apartment)
        related_news = _select_related_news(articles, apartment)
        if catalyst:
            for row in related_news:
                if row["url"] == catalyst["url"]:
                    row["articleCount"] = catalyst["articleCount"]
                    break
        with CACHE_LOCK:
            _write_cache(key, {"catalyst": catalyst, "news": related_news})
        return {"catalyst": catalyst, "news": related_news}


def catalyst_for_apartment(apartment):
    return news_bundle_for_apartment(apartment)["catalyst"]


def catalysts_for_apartments(apartments):
    rows = [row for row in (apartments or []) if isinstance(row, dict)][
        : config.NEWS_CATALYST_BATCH_LIMIT
    ]
    if not configured():
        return {
            "configured": False,
            "results": [
                {"id": str(row.get("id") or ""), "catalyst": None, "news": []}
                for row in rows
            ],
        }

    def resolve(row):
        try:
            bundle = news_bundle_for_apartment(row)
        except Exception:
            bundle = {"catalyst": None, "news": []}
        return {
            "id": str(row.get("id") or ""),
            "catalyst": bundle["catalyst"],
            "news": bundle["news"],
        }

    with ThreadPoolExecutor(max_workers=min(config.NEWS_CATALYST_MAX_WORKERS, len(rows) or 1)) as pool:
        results = list(pool.map(resolve, rows))
    return {
        "configured": True,
        "provider": _provider()["name"],
        "results": results,
    }
