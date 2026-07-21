"""부동산 유튜브 요약 앱 설정."""
import os
import re
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
ROOT = PIPELINE_DIR.parent


def _resolve_parent_root():
    configured = os.environ.get("BEAVER_V2_ROOT", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        ROOT.parent / "beaver-v2",
        ROOT.parent / "지금사도될까요?" / "beaver-v2",
        ROOT.parent,
    ]
    for candidate in candidates:
        if candidate and (candidate / "pipeline" / "youtube.py").exists():
            return candidate
    return ROOT.parent


PARENT_ROOT = _resolve_parent_root()
PARENT_PIPELINE_DIR = PARENT_ROOT / "pipeline"


def _load_settings_file(path):
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    fields = [
        ("제미나이키", "GEMINI_API_KEY"),
        ("유튜브키", "YOUTUBE_API_KEY"),
        ("자막키", "SUPADATA_API_KEY"),
        ("국토교통부_아파트 매매 실거래가 자료키", "MOLIT_APARTMENT_TRADE_API_KEY"),
        ("국토교통부_아파트 분양권전매 실거래가 자료키", "MOLIT_PRESALE_TRADE_API_KEY"),
        ("공공데이터키", "PUBLIC_DATA_API_KEY"),
        ("국토부키", "PUBLIC_DATA_API_KEY"),
        ("실거래가키", "PUBLIC_DATA_API_KEY"),
        ("카카오REST키", "KAKAO_REST_API_KEY"),
        ("카카오지도키", "KAKAO_MAP_JAVASCRIPT_KEY"),
        ("네이버API허브아이디", "NAVER_API_HUB_CLIENT_ID"),
        ("네이버API허브시크릿", "NAVER_API_HUB_CLIENT_SECRET"),
        ("네이버검색아이디", "NAVER_SEARCH_CLIENT_ID"),
        ("네이버검색시크릿", "NAVER_SEARCH_CLIENT_SECRET"),
        ("분석방식", "ANALYSIS_PROVIDER"),
        ("로컬모델", "OLLAMA_MODEL"),
        ("오픈라우터키", "OPENROUTER_API_KEY"),
        ("오픈라우터모델", "OPENROUTER_MODEL"),
        ("오픈라우터URL", "OPENROUTER_BASE_URL"),
        ("오픈라우터리퍼러", "OPENROUTER_REFERER"),
        ("슈파베이스URL", "SUPABASE_URL"),
        ("슈파베이스서비스키", "SUPABASE_SERVICE_ROLE_KEY"),
        ("슈파베이스버킷", "SUPABASE_STORAGE_BUCKET"),
        ("검색분석수", "SEARCH_MAX_ANALYZED_VIDEOS"),
        ("검색후보수", "SEARCH_MAX_YOUTUBERS"),
        ("검색문맥길이", "SEARCH_CONTEXT_MAX_CHARS"),
        ("검색개월수", "REAL_ESTATE_LOOKBACK_MONTHS"),
    ]
    for label, env in fields:
        match = re.search(rf"^{label}\s*=\s*(.*?)\s*$", text, re.MULTILINE)
        if not match:
            continue
        value = match.group(1).strip()
        if value and not value.startswith(("여기에_", "새_키_", "YOUR_")):
            os.environ[env] = value


configured_settings = os.environ.get("BEAVER_V2_SETTINGS", "").strip()
if configured_settings:
    _load_settings_file(Path(configured_settings).expanduser())
_load_settings_file(PARENT_ROOT / "설정.txt")
_load_settings_file(ROOT / "설정.txt")

CACHE_DIR = PIPELINE_DIR / "cache"
TRANSCRIPT_CACHE_DIR = CACHE_DIR / "transcripts"
ANALYSIS_CACHE_DIR = CACHE_DIR / "analysis"
REAL_ESTATE_ANALYSIS_CACHE_DIR = CACHE_DIR / "real_estate_analysis"
MANUAL_TRANSCRIPT_DIR = CACHE_DIR / "manual_transcripts"
SEARCH_INDEX_JSON = CACHE_DIR / "search_index.json"

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
PUBLIC_DATA_API_KEY = os.environ.get("PUBLIC_DATA_API_KEY", os.environ.get("MOLIT_API_KEY", ""))
MOLIT_APARTMENT_TRADE_API_KEY = os.environ.get("MOLIT_APARTMENT_TRADE_API_KEY", PUBLIC_DATA_API_KEY)
MOLIT_PRESALE_TRADE_API_KEY = os.environ.get("MOLIT_PRESALE_TRADE_API_KEY", PUBLIC_DATA_API_KEY)
KAKAO_MAP_JAVASCRIPT_KEY = os.environ.get("KAKAO_MAP_JAVASCRIPT_KEY", "")
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
KAKAO_LOCAL_TIMEOUT_SECONDS = float(os.environ.get("KAKAO_LOCAL_TIMEOUT_SECONDS", "8"))
KAKAO_STATION_RADIUS_METERS = max(
    1000,
    min(int(os.environ.get("KAKAO_STATION_RADIUS_METERS", "20000")), 20000),
)
KAKAO_STATION_MAX_WORKERS = max(
    1,
    min(int(os.environ.get("KAKAO_STATION_MAX_WORKERS", "6")), 16),
)
NAVER_API_HUB_CLIENT_ID = os.environ.get("NAVER_API_HUB_CLIENT_ID", "")
NAVER_API_HUB_CLIENT_SECRET = os.environ.get("NAVER_API_HUB_CLIENT_SECRET", "")
NAVER_SEARCH_CLIENT_ID = os.environ.get("NAVER_SEARCH_CLIENT_ID", "")
NAVER_SEARCH_CLIENT_SECRET = os.environ.get("NAVER_SEARCH_CLIENT_SECRET", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPADATA_API_KEY = os.environ.get("SUPADATA_API_KEY", "")
ANALYSIS_PROVIDER = os.environ.get("ANALYSIS_PROVIDER", "openrouter")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_REFERER = os.environ.get("OPENROUTER_REFERER", "")
OPENROUTER_TITLE = os.environ.get("OPENROUTER_TITLE", "beaver-real-estate-youtube")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "beaver-cache")
SUPABASE_CACHE_ENABLED = os.environ.get("SUPABASE_CACHE_ENABLED", "1") == "1"

SEARCH_LOOKBACK_MONTHS = int(os.environ.get("REAL_ESTATE_LOOKBACK_MONTHS", "12"))
LOOKBACK_DAYS = int(os.environ.get("REAL_ESTATE_LOOKBACK_DAYS", os.environ.get("SEARCH_LOOKBACK_DAYS", str(SEARCH_LOOKBACK_MONTHS * 31))))
SEARCH_LOOKBACK_DAYS = LOOKBACK_DAYS
POPULAR_CHIPS_LOOKBACK_DAYS = int(os.environ.get("REAL_ESTATE_POPULAR_CHIPS_LOOKBACK_DAYS", "30"))
SEARCH_INDEX_REFRESH_HOURS = float(os.environ.get("REAL_ESTATE_INDEX_REFRESH_HOURS", "6"))
SEARCH_MAX_VIDEOS_PER_CHANNEL = int(os.environ.get("REAL_ESTATE_MAX_VIDEOS_PER_CHANNEL", "12"))
SEARCH_MAX_YOUTUBERS = int(os.environ.get("SEARCH_MAX_YOUTUBERS", "20"))
SEARCH_MAX_ANALYZED_VIDEOS = int(os.environ.get("SEARCH_MAX_ANALYZED_VIDEOS", "8"))
SEARCH_FALLBACK_ENABLED = os.environ.get("REAL_ESTATE_SEARCH_FALLBACK_ENABLED", "1") == "1"
SEARCH_FALLBACK_MAX_RESULTS = int(os.environ.get("REAL_ESTATE_SEARCH_FALLBACK_MAX_RESULTS", "30"))
SEARCH_FALLBACK_ORDER = os.environ.get("REAL_ESTATE_SEARCH_FALLBACK_ORDER", "relevance")
SEARCH_FALLBACK_MIN_VIEWS = int(os.environ.get("REAL_ESTATE_SEARCH_FALLBACK_MIN_VIEWS", "100"))
SEARCH_CONTEXT_WINDOW = int(os.environ.get("SEARCH_CONTEXT_WINDOW", "520"))
SEARCH_CONTEXT_MAX_CHARS = int(os.environ.get("SEARCH_CONTEXT_MAX_CHARS", "4200"))
SEARCH_CONTEXT_MAX_SPANS = int(os.environ.get("SEARCH_CONTEXT_MAX_SPANS", "5"))
MOLIT_TRANSACTION_LOOKBACK_MONTHS = int(os.environ.get("MOLIT_TRANSACTION_LOOKBACK_MONTHS", "6"))
MOLIT_STALE_TRANSACTION_LOOKBACK_MONTHS = int(os.environ.get("MOLIT_STALE_TRANSACTION_LOOKBACK_MONTHS", "36"))
MOLIT_TRANSACTION_ENRICH_LIMIT = int(os.environ.get("MOLIT_TRANSACTION_ENRICH_LIMIT", "12"))
MOLIT_TRANSACTION_ALL_MATCHES_ENRICH_LIMIT = int(os.environ.get("MOLIT_TRANSACTION_ALL_MATCHES_ENRICH_LIMIT", "80"))
BUDGET_BROAD_REGION_LIVE_SEED_LIMIT = int(os.environ.get("BUDGET_BROAD_REGION_LIVE_SEED_LIMIT", "80"))
MOLIT_TRANSACTION_TIMEOUT_SECONDS = float(os.environ.get("MOLIT_TRANSACTION_TIMEOUT_SECONDS", "5"))
MOLIT_PREFETCH_MAX_WORKERS = int(os.environ.get("MOLIT_PREFETCH_MAX_WORKERS", "8"))
MOMENTUM_SIGNAL_MAX_WORKERS = max(
    1,
    min(int(os.environ.get("MOMENTUM_SIGNAL_MAX_WORKERS", "4")), 8),
)
MOMENTUM_SCOPE_MAX_WORKERS = max(
    1,
    min(int(os.environ.get("MOMENTUM_SCOPE_MAX_WORKERS", "4")), 8),
)
NAVER_COMPLEX_TIMEOUT_SECONDS = max(
    0.5,
    min(float(os.environ.get("NAVER_COMPLEX_TIMEOUT_SECONDS", "2")), 5),
)
NAVER_COMPLEX_MAX_WORKERS = max(
    1,
    min(int(os.environ.get("NAVER_COMPLEX_MAX_WORKERS", "2")), 4),
)
MOLIT_STALE_PREFETCH_BATCH_MONTHS = int(os.environ.get("MOLIT_STALE_PREFETCH_BATCH_MONTHS", "6"))
MOLIT_SIGNAL_LOOKBACK_MONTHS = int(os.environ.get("MOLIT_SIGNAL_LOOKBACK_MONTHS", "24"))
BUDGET_ALL_MATCHES_RESULT_LIMIT = int(os.environ.get("BUDGET_ALL_MATCHES_RESULT_LIMIT", "80"))
BUDGET_PREWARM_ENABLED = os.environ.get("BUDGET_PREWARM_ENABLED", "1") == "1"
BUDGET_PREWARM_DELAY_SECONDS = float(os.environ.get("BUDGET_PREWARM_DELAY_SECONDS", "30"))
BUDGET_PREWARM_MONTHS = int(os.environ.get("BUDGET_PREWARM_MONTHS", str(MOLIT_SIGNAL_LOOKBACK_MONTHS)))
BUDGET_PREWARM_MAX_WORKERS = int(os.environ.get("BUDGET_PREWARM_MAX_WORKERS", "4"))
# 서버 시작 시 미리 실거래 캐시를 데워 둘 지역. 조건 검색이 지원하는
# 서울·경기 전체를 기본으로 준비해 첫 검색도 저장 데이터만으로 계산한다.
# 환경변수로 더 좁게 재정의할 수 있다.
BUDGET_PREWARM_REGIONS = tuple(
    value.strip()
    for value in os.environ.get("BUDGET_PREWARM_REGIONS", "서울특별시,경기도").split(",")
    if value.strip()
)
# 신고 기한(계약 후 30일)이 지난 과거 월 실거래는 거의 바뀌지 않으므로 긴 주기로만 갱신한다.
MOLIT_SETTLED_MONTH_CACHE_TTL_SECONDS = int(os.environ.get("MOLIT_SETTLED_MONTH_CACHE_TTL_SECONDS", str(60 * 60 * 24 * 30)))
MOLIT_MONTH_CACHE_RECENT_WINDOW_MONTHS = int(os.environ.get("MOLIT_MONTH_CACHE_RECENT_WINDOW_MONTHS", "3"))
SIGNAL_MIN_WINDOW_DEALS = int(os.environ.get("SIGNAL_MIN_WINDOW_DEALS", "3"))
SIGNAL_MIN_TOTAL_DEALS = int(os.environ.get("SIGNAL_MIN_TOTAL_DEALS", "5"))
BUDGET_RESULT_CACHE_TTL_SECONDS = int(os.environ.get("BUDGET_RESULT_CACHE_TTL_SECONDS", str(60 * 60 * 12)))
NEWS_CATALYST_CACHE_TTL_SECONDS = int(os.environ.get("NEWS_CATALYST_CACHE_TTL_SECONDS", str(60 * 60 * 3)))
NEWS_CATALYST_LOOKBACK_DAYS = int(os.environ.get("NEWS_CATALYST_LOOKBACK_DAYS", "548"))
NEWS_RELATED_LOOKBACK_DAYS = int(os.environ.get("NEWS_RELATED_LOOKBACK_DAYS", "730"))
NEWS_RELATED_LIMIT = max(1, min(int(os.environ.get("NEWS_RELATED_LIMIT", "2")), 4))
NEWS_CATALYST_TIMEOUT_SECONDS = float(os.environ.get("NEWS_CATALYST_TIMEOUT_SECONDS", "4"))
NEWS_CATALYST_SEARCH_RESULTS = max(1, min(int(os.environ.get("NEWS_CATALYST_SEARCH_RESULTS", "100")), 100))
NEWS_CATALYST_BATCH_LIMIT = max(1, min(int(os.environ.get("NEWS_CATALYST_BATCH_LIMIT", "12")), 24))
NEWS_CATALYST_MAX_WORKERS = max(1, min(int(os.environ.get("NEWS_CATALYST_MAX_WORKERS", "4")), 8))

TRANSCRIPT_FAILURE_TTL_HOURS = int(os.environ.get("TRANSCRIPT_FAILURE_TTL_HOURS", "12"))
TRANSCRIPT_TRANSIENT_FAILURE_TTL_HOURS = int(os.environ.get("TRANSCRIPT_TRANSIENT_FAILURE_TTL_HOURS", "2"))
TRANSCRIPT_REQUEST_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_REQUEST_DELAY_SECONDS", "1.0"))
FORCE_TRANSCRIPT_REFRESH = os.environ.get("FORCE_TRANSCRIPT_REFRESH", "") == "1"
FORCE_ANALYSIS_REFRESH = os.environ.get("FORCE_ANALYSIS_REFRESH", "") == "1"
TRANSCRIPT_LANGS = ["ko", "ko-KR"]

STANCES = ["상승기대", "관망", "주의", "단순언급"]


def _channel(name, kind, categories, channel_id=""):
    return {
        "name": name,
        "channelId": channel_id,
        "type": kind,
        "categories": categories,
    }


# YouTube Rank 주식/경제/부동산 카테고리의 View순을 우선하고,
# 부동산 전용성이 높은 대형 채널과 최근 검색에서 자주 빠지는 전문가 채널을 보강한 로스터다.
CHANNELS = [
    _channel("삼프로TV", "경제", ["부동산", "거시", "정책"], "UChlv4GSd7OQl3js-jkLOnFA"),
    _channel("김작가 TV", "경제", ["부동산", "거시", "투자"], "UCvil4OAt-zShzkKHsg9EQAw"),
    _channel("신사임당", "경제", ["부동산", "재테크", "시장"], "UCaJdckl6MBdDPDf75Ec_bJA"),
    _channel("부읽남TV", "부동산", ["아파트", "입지", "시장"], "UC2QeHNJFfuQWB4cy3M-745g"),
    _channel("월급쟁이부자들TV", "부동산", ["아파트", "투자", "지역분석"], "UCDSj40X9FFUAnx1nv7gQhcA"),
    _channel("815머니톡", "경제", ["부동산", "거시", "투자"], "UCCG6BEYjfQMGzypJw2EJCDQ"),
    _channel("전인구경제연구소", "경제", ["부동산", "거시", "재테크"], "UCznImSIaxZR7fdLCICLdgaQ"),
    _channel("발품부동산TV", "부동산", ["전원주택", "토지", "매물"], "UCkRYaZLpNLRDqBIqPbD9NZA"),
    _channel("단희TV", "부동산", ["부동산재테크", "노후", "상가"], "UCOMG2V-vUgYX0aHiBDbBTyg"),
    _channel("행크TV", "부동산", ["경매", "투자", "재테크"], "UCz4CFx4eeELZNReE_Wyit4g"),
    _channel("쇼킹부동산", "부동산", ["정책", "시장", "청약"], "UCcloDgiDqz8twby7zvG-USg"),
    _channel("라이트하우스", "부동산", ["시장", "정책", "경제"], "UCoROtLOzsB4pAMarab00ANQ"),
    _channel("얼음공장의 반백수 프로젝트", "부동산", ["아파트", "지역분석", "시장"], "UCuDVP_3ImJ9rIW184cUWObg"),
    _channel("싱글파이어", "경제", ["부동산", "내집마련", "재테크"], "UC5CyCSvCdoEP-VgQmFq3iww"),
    _channel("후랭이TV", "부동산", ["부동산", "투자", "재테크"], "UChnfOZtjny0KBSVkfS9nwsg"),
    _channel("놀라운부동산", "부동산", ["개발", "소액투자", "지역분석"], "UCysO8h0ZdipoFZd-2-EZ4uQ"),
    _channel("스마트튜브", "부동산", ["지역분석", "시장", "정책"], "UCKosTo5bqKm4v264z2zDnFQ"),
    _channel("박병찬의 부자병법", "부동산", ["갭투자", "시장", "강의"], "UCKcXypG00FkZfI_4FIcN1kA"),
    _channel("배종찬교수의 맛있는 돈이야기", "부동산", ["재개발", "재건축", "상가"], "UCqIxpbr47Ga4MLiu6fhIHrQ"),
    _channel("전은성의 현장이 답이다", "부동산", ["임장", "재개발", "투자"], "UCJmx95ElUDyDRH6nKQ7qyZg"),
    _channel("후스파파의 부동산 상식사전", "부동산", ["중개", "임대차", "상식"], "UCZCiOVgBEb7IHdSOjQrsmmw"),
    _channel("공부하는 붇옹산", "부동산", ["시장", "정책", "공부"], "UC9HYs-EG-tXxZbsgMi6TzEw"),
    _channel("부동산분석왕 TV", "부동산", ["분석", "경제", "시장"], "UCzVxelIsmKDrNQTUHpzokQg"),
    _channel("급매물과 반값매매", "부동산", ["급매", "매물", "시장"], "UC0WXpjw0Uayhz-z8be0ILeQ"),

    # 이름 검색/커뮤니티 추천에서 자주 언급되지만 기존 30개 풀에 빠져 있던 부동산 전문가 채널.
    _channel("작가 송희구", "부동산", ["아파트", "투자", "지역분석"], "UCrxr7eBgbKdz0e1t5ax9kCg"),
    _channel("새벽보기Live", "부동산", ["아파트", "지역분석", "투자"], "UCcp1GsUZnKPf8AbbxAzUGfw"),
    _channel("푸릉", "부동산", ["아파트", "투자", "강의"], "UC8tWxC9EPKUCrHmEhiYTbhQ"),
    _channel("AforU 아포유", "부동산", ["아파트", "시장", "투자"], "UCK6bIuN3aDIV4F53QQ4__Ng"),
    _channel("투미부동산[투미TV]", "부동산", ["재개발", "재건축", "정책"], "UC9meL6XNNckzlleWelmO9tQ"),
    _channel("[이현철] 아파트사이클연구소", "부동산", ["아파트", "시장", "사이클"], "UCr8tO6DbPIaZw6R5nSNq07A"),
    _channel("재테크 신선배, 부룡TV", "부동산", ["아파트", "시장", "투자"], "UC_oIz7_AHOXaRSaWQcpqNAA"),
    _channel("상가투자, 토지투자 김종율TV", "부동산", ["상가", "토지", "투자"], "UCa08Pwp6Rj7jGz6QElDHojw"),
    _channel("채부심 - 채상욱의 부동산 심부름센터", "부동산", ["시장", "정책", "데이터"], "UCD9vzSxZ69pjcnf8hgCQXVQ"),
    _channel("고부자", "부동산", ["아파트", "투자", "시장"], "UCF_eZbmXq2t-5HS4PqAAUwA"),
    _channel("집터뷰", "부동산", ["아파트", "임장", "지역분석"], "UC6RUdJ9pYwEcaDfVfobvi3g"),
    _channel("부자티비", "부동산", ["부동산", "재테크", "시장"], "UCFNvxbkVLERlXqoSRtZ8KVQ"),
    _channel("집코치", "부동산", ["아파트", "내집마련", "상담"], "UCVPlR2EcGAMxhY4dLYjPppA"),
    _channel("한문도TV_부동산채널", "부동산", ["시장", "정책", "전망"], "UCu9SkglGtbnwtht-fP75Nbw"),
    _channel("김인만의 부다방TV", "부동산", ["시장", "정책", "상담"], "UC02Dp0K7JKQ8w2Yifz3UGTg"),
    _channel("재테크읽어주는 파일럿", "부동산", ["아파트", "재테크", "투자"], "UCaWi2foADm_lKAKnmeQwLSA"),

    # 부동산 단독 채널은 아니지만 부동산 전문가 인터뷰와 거시/정책 맥락을 자주 다루는 대형 경제 채널.
    _channel("슈카월드", "경제", ["부동산", "거시", "정책"], "UCsJ6RuBiTVWRX156FVbeaGg"),
    _channel("언더스탠딩 : 세상의 모든 지식", "경제", ["부동산", "거시", "시장"], "UCIUni4ScRp4mqPXsxy62L5w"),
    _channel("머니인사이드", "경제", ["부동산", "투자", "시장"], "UCxfko2YOD6DODYRGzeOPhIQ"),
    _channel("경제 읽어주는 남자(김광석TV)", "경제", ["부동산", "거시", "정책"], "UC3pfEoxaRDT6hvZZjpHu7Tg"),
    _channel("부티플 - 부의 배수를 높여라", "경제", ["부동산", "투자", "시장"], "UCriq8I8GEESkQq0svX19oCw"),

    # 사람 중심의 부동산 전문 채널 위주로 보강한다.
    _channel("이상우 부동산 애널리스트", "부동산", ["아파트", "시장", "전망"], "UC6inuEkuN_Xq2sjfO8MLXeQ"),
    _channel("채널 제네시스박", "부동산", ["세금", "정책", "절세"], "UCHOPWa8g36QPHB00JmdZluw"),
    _channel("도나쓰의 내집마련TV", "부동산", ["내집마련", "아파트", "청약"], "UCWszmQybNJzkw3J7HRMZPYQ"),
    _channel("도시와경제", "부동산", ["도시", "개발", "시장"], "UCFRCYjZ-L2F7UklMlw4V_Eg"),
    _channel("집슐랭 ZIPCHELIN", "부동산", ["아파트", "입지", "지역분석"], "UCqxw2I-MDWXt1JRE_EZFQ_g"),
]


def ready_channels():
    return [channel for channel in CHANNELS if channel.get("channelId")]
