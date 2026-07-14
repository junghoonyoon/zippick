#!/usr/bin/env python3
"""부동산 유튜브 요약 화면과 로컬 API를 제공한다."""
import datetime
import hashlib
import json
import mimetypes
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import config
import budget_candidates
import molit_transactions
import momentum_signals
import policy_evaluator
import real_estate_search

ROOT = config.ROOT
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"
ASSETS_DIR = ROOT / "앱화면" / "assets"
HOST = os.environ.get("REAL_ESTATE_HOST", "127.0.0.1")
PORT = int(os.environ.get("REAL_ESTATE_PORT", "8766"))
JOBS = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 20
BUDGET_CACHE_DIR = config.CACHE_DIR / "budget_candidates"
BUDGET_CACHE_LOCK = threading.Lock()
BUDGET_KEY_LOCKS = {}
BUDGET_KEY_LOCKS_LOCK = threading.Lock()
BUDGET_CACHE_SCHEMA_VERSION = 6
BUDGET_JOBS = {}
BUDGET_JOBS_LOCK = threading.Lock()
BUDGET_MAX_JOBS = 20
BUDGET_PREWARM_STATE = {"running": False, "done": False, "pairCount": 0, "finishedAt": None}


def _budget_cache_key(arguments):
    tracked_files = [
        budget_candidates.__file__,
        config.ROOT / "pipeline" / "molit_transactions.py",
        config.ROOT / "pipeline" / "momentum_signals.py",
        config.ROOT / "pipeline" / "naver_complex.py",
        config.ROOT / "pipeline" / "verdicts.py",
        policy_evaluator.__file__,
        policy_evaluator.POLICY_SNAPSHOT_PATH,
        config.ROOT / "data" / "apartment_price_bands.csv",
        config.ROOT / "data" / "seoul_small_apartment_price_bands.csv",
    ]
    revisions = {}
    for path_value in tracked_files:
        path = os.fspath(path_value)
        try:
            revisions[path] = os.path.getmtime(path)
        except OSError:
            revisions[path] = 0
    material = {
        "schema": BUDGET_CACHE_SCHEMA_VERSION,
        "date": datetime.date.today().isoformat(),
        "arguments": arguments,
        "revisions": revisions,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_budget_cache(cache_key):
    path = BUDGET_CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    saved_at = float(cached.get("savedAt") or 0)
    if time.time() - saved_at > config.BUDGET_RESULT_CACHE_TTL_SECONDS:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    payload = cached.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload, saved_at


def _write_budget_cache(cache_key, payload):
    if payload.get("error") or int(payload.get("status") or 200) >= 400:
        return 0
    display_rows = _budget_payload_rows(payload)
    if payload.get("livePriceError") and not display_rows:
        return 0
    saved_at = time.time()
    BUDGET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = BUDGET_CACHE_DIR / f"{cache_key}.json"
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({
        "savedAt": saved_at,
        "payload": payload,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return saved_at


def _budget_payload_rows(payload):
    rows = []
    seen = set()
    for key in ("allCandidates", "policyDefaultCandidates", "candidates", "policyExcludedCandidates"):
        for row in payload.get(key) or []:
            marker = id(row)
            if marker in seen:
                continue
            seen.add(marker)
            rows.append(row)
    return rows


def _signal_unavailable(row):
    signals = row.get("signals")
    if not isinstance(signals, dict):
        return True
    status = signals.get("status")
    if status == "insufficient":
        return False
    return status != "ok" or signals.get("score") is None


def _repair_budget_signals(payload):
    """응답 직전 누락·오류 시그널을 캐시 기반으로 한 번 더 계산한다."""
    rows = _budget_payload_rows(payload)
    if not rows or not molit_transactions.configured():
        return
    if any(_signal_unavailable(row) for row in rows):
        momentum_signals.attach_signals(rows)


def _budget_key_lock(cache_key):
    with BUDGET_KEY_LOCKS_LOCK:
        return BUDGET_KEY_LOCKS.setdefault(cache_key, threading.Lock())


def _load_budget_payload(cache_key, candidate_arguments):
    """동일 조건의 동시 요청은 한 번만 계산하고 결과를 공유한다."""
    with _budget_key_lock(cache_key):
        # 잠금을 기다린 요청은 앞선 계산이 저장한 캐시를 다시 확인한다.
        with BUDGET_CACHE_LOCK:
            cached_result = _read_budget_cache(cache_key)
        if cached_result:
            payload, saved_at = cached_result
            payload = json.loads(json.dumps(payload, ensure_ascii=False))
            # API 지연으로 시그널이 비어 있던 결과는 전체 재계산 대신
            # 시그널만 다시 계산한다. 복구되면 캐시도 갱신한다.
            rows = _budget_payload_rows(payload)
            if molit_transactions.configured() and any(_signal_unavailable(row) for row in rows):
                _repair_budget_signals(payload)
                if not any(_signal_unavailable(row) for row in _budget_payload_rows(payload)):
                    payload.pop("livePriceError", None)
                    with BUDGET_CACHE_LOCK:
                        saved_at = _write_budget_cache(cache_key, payload) or saved_at
            payload["cacheHit"] = True
            payload["cacheSavedAt"] = datetime.datetime.fromtimestamp(
                saved_at, real_estate_search.KST,
            ).isoformat()
            return payload

        payload = budget_candidates.budget_candidates(**candidate_arguments)
        _repair_budget_signals(payload)
        with BUDGET_CACHE_LOCK:
            saved_at = _write_budget_cache(cache_key, payload)
        payload["cacheHit"] = False
        if saved_at:
            payload["cacheSavedAt"] = datetime.datetime.fromtimestamp(
                saved_at, real_estate_search.KST,
            ).isoformat()
        return payload


def _cached_budget_payload(cache_key):
    """완성된 결과가 있으면 추가 계산 없이 즉시 반환한다."""
    with BUDGET_CACHE_LOCK:
        cached_result = _read_budget_cache(cache_key)
    if not cached_result:
        return None
    payload, saved_at = cached_result
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    payload.update({
        "cacheHit": True,
        "cacheSavedAt": datetime.datetime.fromtimestamp(saved_at, real_estate_search.KST).isoformat(),
        "enrichmentPending": False,
        "enrichmentStage": "complete",
    })
    return payload


def _trim_budget_jobs_locked():
    if len(BUDGET_JOBS) <= BUDGET_MAX_JOBS:
        return
    ordered = sorted(BUDGET_JOBS.items(), key=lambda item: item[1].get("startedAt", 0))
    for job_id, _job in ordered[:len(BUDGET_JOBS) - BUDGET_MAX_JOBS]:
        BUDGET_JOBS.pop(job_id, None)


def _run_budget_enrichment(job_id, cache_key, candidate_arguments):
    try:
        payload = _load_budget_payload(cache_key, candidate_arguments)
        payload.update({"enrichmentPending": False, "enrichmentStage": "complete"})
    except Exception as exc:
        payload = {
            "done": True,
            "enrichmentPending": False,
            "enrichmentStage": "error",
            "error": str(exc),
        }
    with BUDGET_JOBS_LOCK:
        job = BUDGET_JOBS.get(job_id)
        if not job:
            return
        job["done"] = True
        job["result"] = payload
        job["finishedAt"] = time.time()


def _budget_job_snapshot(job_id):
    with BUDGET_JOBS_LOCK:
        job = BUDGET_JOBS.get(job_id)
        if not job:
            return None
        if not job.get("done"):
            return {
                "done": False,
                "enrichmentPending": True,
                "enrichmentStage": "live_data",
            }
        payload = json.loads(json.dumps(job.get("result") or {}, ensure_ascii=False))
        payload["done"] = True
        return payload


def _start_staged_budget_payload(cache_key, candidate_arguments):
    cached = _cached_budget_payload(cache_key)
    if cached:
        return cached

    with BUDGET_JOBS_LOCK:
        for job_id, job in BUDGET_JOBS.items():
            if job.get("cacheKey") != cache_key:
                continue
            if job.get("done") and job.get("result"):
                payload = json.loads(json.dumps(job["result"], ensure_ascii=False))
                payload.update({"done": True, "enrichmentPending": False})
                return payload
            initial = json.loads(json.dumps(job.get("initial") or {}, ensure_ascii=False))
            initial.update({
                "enrichmentJobId": job_id,
                "enrichmentPending": True,
                "enrichmentStage": "live_data",
            })
            return initial

    initial_arguments = {**candidate_arguments, "fast_mode": True}
    initial = budget_candidates.budget_candidates(**initial_arguments)
    if initial.get("error") or int(initial.get("status") or 200) >= 400:
        initial.update({"enrichmentPending": False, "enrichmentStage": "error"})
        return initial

    job_id = uuid.uuid4().hex[:12]
    with BUDGET_JOBS_LOCK:
        BUDGET_JOBS[job_id] = {
            "cacheKey": cache_key,
            "startedAt": time.time(),
            "done": False,
            "initial": initial,
            "result": None,
        }
        _trim_budget_jobs_locked()
    thread = threading.Thread(
        target=_run_budget_enrichment,
        args=(job_id, cache_key, candidate_arguments),
        daemon=True,
    )
    thread.start()
    initial = json.loads(json.dumps(initial, ensure_ascii=False))
    initial.update({
        "enrichmentJobId": job_id,
        "enrichmentPending": True,
        "enrichmentStage": "live_data",
    })
    return initial


def _prewarm_budget_transaction_cache():
    if not config.BUDGET_PREWARM_ENABLED or not molit_transactions.configured():
        return
    if config.BUDGET_PREWARM_DELAY_SECONDS > 0:
        time.sleep(config.BUDGET_PREWARM_DELAY_SECONDS)
    BUDGET_PREWARM_STATE.update({"running": True, "done": False})
    try:
        source_rows, _exact = molit_transactions._source_row_index()
        region_keys = {
            real_estate_search.compact(value)
            for value in config.BUDGET_PREWARM_REGIONS
            if real_estate_search.compact(value)
        }
        lawd_codes = {
            molit_transactions._row_lawd_cd(row)
            for row in source_rows
            if any(
                real_estate_search.compact(value) in region_keys
                for value in (
                    row.get("시도", ""),
                    row.get("자치구", ""),
                    row.get("시군구", ""),
                    row.get("일반구", ""),
                )
            )
        }
        months = molit_transactions._deal_months(max(1, config.BUDGET_PREWARM_MONTHS))
        pairs = {(code, month) for code in lawd_codes if code for month in months}
        BUDGET_PREWARM_STATE["pairCount"] = len(pairs)
        molit_transactions.prefetch_months(
            pairs,
            max_workers=max(1, config.BUDGET_PREWARM_MAX_WORKERS),
        )
    finally:
        BUDGET_PREWARM_STATE.update({
            "running": False,
            "done": True,
            "finishedAt": time.time(),
        })


class SearchServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _index_age_seconds(index):
    updated_at = index.get("updatedAt")
    if not updated_at:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(updated_at)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=real_estate_search.KST)
    return max(0, (datetime.datetime.now(real_estate_search.KST) - parsed).total_seconds())


def _snapshot(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        payload = json.loads(json.dumps(job["result"], ensure_ascii=False))
    payload["opinions"].sort(key=real_estate_search.opinion_sort_key)
    for opinion in payload["opinions"]:
        opinion.pop("_order", None)
    return payload


def _trim_jobs():
    if len(JOBS) <= MAX_JOBS:
        return
    old_ids = sorted(JOBS, key=lambda key: JOBS[key].get("startedAt", 0))[:len(JOBS) - MAX_JOBS]
    for old_id in old_ids:
        JOBS.pop(old_id, None)


def _run_search_job(job_id, query, videos):
    with JOBS_LOCK:
        result = JOBS[job_id]["result"]
        result["currentStatus"] = "관련 영상을 고르는 중이에요."

    if not videos:
        with JOBS_LOCK:
            result = JOBS[job_id]["result"]
            result["done"] = True
            result["running"] = False
            result["currentStatus"] = "최근 영상에서 관련 언급을 찾지 못했어요."
        return

    for video in videos:
        with JOBS_LOCK:
            result = JOBS[job_id]["result"]
            generate = result["analyzedVideos"] < config.SEARCH_MAX_ANALYZED_VIDEOS
            result["currentChannel"] = video.get("channel", "")
            result["currentStatus"] = (
                f"{video.get('channel', '')} 의견을 분석 중이에요."
                if generate else f"{video.get('channel', '')} 캐시를 확인 중이에요."
            )
        try:
            if generate:
                opinion_result, cached = real_estate_search.analyze_match(video, query)
            else:
                opinion_result, cached = real_estate_search.cached_match(video, query)
                if not cached:
                    with JOBS_LOCK:
                        JOBS[job_id]["result"]["processedVideos"] += 1
                    continue
            opinion = real_estate_search.opinion_from_result(video, opinion_result, cached)
            with JOBS_LOCK:
                result = JOBS[job_id]["result"]
                if generate:
                    result["analyzedVideos"] += 1
                real_estate_search.add_opinion(result, opinion)
                result["processedVideos"] += 1
        except Exception as exc:
            with JOBS_LOCK:
                result = JOBS[job_id]["result"]
                result["errors"].append(f"{video.get('channel', '')}: {str(exc)[:120]}")
                result["processedVideos"] += 1

    with JOBS_LOCK:
        result = JOBS[job_id]["result"]
        result["done"] = True
        result["running"] = False
        result["currentChannel"] = ""
        result["currentStatus"] = "분석이 끝났어요."


def _wait_for_first_update(job_id, timeout_seconds=1.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with JOBS_LOCK:
            result = JOBS.get(job_id, {}).get("result")
            if not result:
                return
            if result.get("opinions") or result.get("processedVideos") or result.get("done"):
                return
        time.sleep(0.05)


def _lookback_months(params):
    try:
        months = int(params.get("months", [""])[0])
    except (TypeError, ValueError):
        months = config.SEARCH_LOOKBACK_MONTHS
    return months if months in {3, 6, 12} else config.SEARCH_LOOKBACK_MONTHS


def start_search_job(query, lookback_months=None):
    lookback_months = lookback_months or config.SEARCH_LOOKBACK_MONTHS
    videos, stats = real_estate_search.find_videos_with_stats(query, lookback_months=lookback_months)
    job_id = uuid.uuid4().hex[:12]
    result = real_estate_search.base_search_result(query, videos, stats, lookback_months=lookback_months)
    result.update({
        "jobId": job_id,
        "done": False,
        "running": True,
        "currentChannel": "",
        "currentStatus": "검색을 시작했어요.",
    })
    with JOBS_LOCK:
        JOBS[job_id] = {"startedAt": time.time(), "result": result}
        _trim_jobs()
    thread = threading.Thread(target=_run_search_job, args=(job_id, query, videos), daemon=True)
    thread.start()
    _wait_for_first_update(job_id)
    return _snapshot(job_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[부동산 서버] {fmt % args}")

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/status":
            index = real_estate_search.load_index()
            self._json({
                "ready": bool(index.get("videos")),
                "indexVersion": index.get("version"),
                "videoCount": len(index.get("videos", [])),
                "updatedAt": index.get("updatedAt"),
                "ageSeconds": _index_age_seconds(index),
                "lookbackDays": index.get("lookbackDays", config.SEARCH_LOOKBACK_DAYS),
                "readyChannels": len(config.ready_channels()),
                "fallbackEnabled": config.SEARCH_FALLBACK_ENABLED,
                "analysisProvider": config.ANALYSIS_PROVIDER.lower(),
                "molitConfigured": molit_transactions.configured(),
                "molitAvailable": molit_transactions.enabled(),
                "molitLastError": molit_transactions.last_error(),
                "budgetPrewarm": dict(BUDGET_PREWARM_STATE),
            })
            return
        if parsed.path == "/api/chips":
            all_label = "요즘 많이 언급되는 지역·이슈"
            apartment_label = "지역 안에서 자주 언급된 단지"
            self._json({
                "label": all_label,
                "chips": real_estate_search.popular_chips(),
                "tabs": [
                    {
                        "id": "all",
                        "label": all_label,
                        "caption": f"최근 {config.POPULAR_CHIPS_LOOKBACK_DAYS}일 기준",
                        "chips": real_estate_search.popular_chips(),
                    },
                    {
                        "id": "apartments",
                        "label": apartment_label,
                        "caption": f"최근 {config.POPULAR_CHIPS_LOOKBACK_DAYS}일 기준",
                        "chips": real_estate_search.popular_chips(kind="apartments"),
                    },
                ],
            })
            return
        if parsed.path == "/api/suggest":
            query = params.get("q", [""])[0].strip()
            self._json({"suggestions": real_estate_search.suggest_entities(query)})
            return
        if parsed.path == "/api/region-apartments":
            region = params.get("region", [""])[0].strip()
            if len(region) < 2:
                self._json({"error": "지역을 두 글자 이상 입력해 주세요."}, 400)
                return
            region_scope = real_estate_search.region_query_scope(region)
            self._json({
                "region": region_scope,
                "parentRegion": real_estate_search._region_parent_city(region_scope) or region_scope,
                "label": f"{real_estate_search.region_display_name(region_scope)}에서 먼저 볼 아파트",
                "caption": "세대수 기준으로 후보를 좁혔어요. 아파트를 선택하면 의견과 근거 영상을 확인합니다.",
                "subdistricts": real_estate_search.region_subdistricts(region_scope),
                "apartments": real_estate_search.region_apartments(region),
            })
            return
        if parsed.path == "/api/purchase-power":
            first_time = params.get("first_time", [""])[0].strip()
            profile = policy_evaluator.user_profile(
                home_ownership=params.get("home_ownership", ["unknown"])[0].strip(),
                first_time=first_time,
                cash_eok=params.get("cash_eok", [""])[0].strip(),
                annual_income=params.get("annual_income", [""])[0].strip(),
                monthly_debt_payment=params.get("monthly_debt_payment", [""])[0].strip(),
                co_borrower=params.get("co_borrower", ["false"])[0].strip(),
                spouse_annual_income=params.get("spouse_annual_income", [""])[0].strip(),
                spouse_monthly_debt_payment=params.get("spouse_monthly_debt_payment", [""])[0].strip(),
                mortgage_rate=params.get("mortgage_rate", [""])[0].strip(),
                loan_term_years=params.get("loan_term_years", ["30"])[0].strip(),
                purchase_cost_rate=params.get("purchase_cost_rate", ["0"])[0].strip(),
            )
            if profile["homeOwnership"] == "unknown" or first_time not in {"true", "false"} or not profile["cashEok"] or not profile["annualIncomeManwon"] or not profile["mortgageRatePercent"]:
                self._json({"error": "보유 주택, 생애최초 여부, 자기자금, 연소득과 예상 금리를 입력해 주세요."}, 400)
                return
            ceiling = policy_evaluator.estimated_purchase_ceiling(profile, ["서울시", "경기도"])
            if ceiling <= 0:
                self._json({"error": "입력한 소득·부채·자기자금 기준으로 계산 가능한 매수 상한이 없어요."}, 400)
                return
            snapshot = policy_evaluator.summarize([], profile)
            snapshot["estimatedPurchaseCeilingEok"] = ceiling
            self._json({"budgetEok": ceiling, "snapshot": snapshot})
            return
        if parsed.path == "/api/apartment-last-deal":
            name = params.get("name", [""])[0].strip()
            region = params.get("region", [""])[0].strip()
            area_label = params.get("area_label", [""])[0].strip()
            if len(name) < 2:
                self._json({"error": "단지명을 확인해 주세요."}, 400)
                return
            if not molit_transactions.enabled():
                self._json({"lastDeal": None, "error": molit_transactions.last_error() or "공공데이터키가 설정되어 있지 않아요."})
                return
            last_deal = molit_transactions.latest_transaction_for_apartment(
                name,
                region=region,
                area_label=area_label,
                skip_months=config.MOLIT_TRANSACTION_LOOKBACK_MONTHS,
            )
            self._json({"lastDeal": last_deal})
            return
        if parsed.path == "/api/budget-candidates/progress":
            job_id = params.get("id", [""])[0].strip()
            payload = _budget_job_snapshot(job_id)
            if not payload:
                self._json({"error": "후보 보강 작업을 찾지 못했어요."}, 404)
                return
            status = payload.pop("status", 200)
            self._json(payload, status)
            return
        if parsed.path == "/api/budget-candidates":
            budget = params.get("budget", [""])[0].strip()
            region = params.get("region", [""])[0].strip()
            purpose = params.get("purpose", [""])[0].strip()
            priority = params.get("priority", [""])[0].strip()
            commute = params.get("commute", [""])[0].strip()
            move_timing = params.get("move_timing", [""])[0].strip()
            price_strategy = params.get("price_strategy", ["stretch"])[0].strip()
            min_area = params.get("min_area", [""])[0].strip()
            min_households = params.get("min_households", [""])[0].strip()
            max_building_age = params.get("max_building_age", [""])[0].strip()
            home_ownership = params.get("home_ownership", ["unknown"])[0].strip()
            first_time = params.get("first_time", ["false"])[0].strip()
            cash_eok = params.get("cash_eok", [""])[0].strip()
            annual_income = params.get("annual_income", [""])[0].strip()
            monthly_debt_payment = params.get("monthly_debt_payment", [""])[0].strip()
            co_borrower = params.get("co_borrower", ["false"])[0].strip()
            spouse_annual_income = params.get("spouse_annual_income", [""])[0].strip()
            spouse_monthly_debt_payment = params.get("spouse_monthly_debt_payment", [""])[0].strip()
            mortgage_rate = params.get("mortgage_rate", [""])[0].strip()
            loan_term_years = params.get("loan_term_years", ["30"])[0].strip()
            purchase_cost_rate = params.get("purchase_cost_rate", ["0"])[0].strip()
            all_matches = params.get("all_matches", ["false"])[0].strip()
            limit = params.get("limit", ["6"])[0].strip()
            try:
                limit = int(limit)
            except ValueError:
                limit = 3
            candidate_arguments = {
                "budget": budget,
                "region": region,
                "purpose": purpose,
                "priority": priority,
                "commute": commute,
                "move_timing": move_timing,
                "price_strategy": price_strategy,
                "min_area": min_area,
                "min_households": min_households,
                "max_building_age": max_building_age,
                "home_ownership": home_ownership,
                "first_time": first_time,
                "cash_eok": cash_eok,
                "annual_income": annual_income,
                "monthly_debt_payment": monthly_debt_payment,
                "co_borrower": co_borrower,
                "spouse_annual_income": spouse_annual_income,
                "spouse_monthly_debt_payment": spouse_monthly_debt_payment,
                "mortgage_rate": mortgage_rate,
                "loan_term_years": loan_term_years,
                "purchase_cost_rate": purchase_cost_rate,
                "limit": max(1, min(limit, 12)),
                "all_matches": all_matches.lower() in {"1", "true", "yes", "on"},
            }
            cache_key = _budget_cache_key(candidate_arguments)
            staged = params.get("staged", ["false"])[0].strip().lower() in {"1", "true", "yes", "on"}
            payload = (
                _start_staged_budget_payload(cache_key, candidate_arguments)
                if staged
                else _load_budget_payload(cache_key, candidate_arguments)
            )
            status = payload.pop("status", 200)
            self._json(payload, status)
            return
        if parsed.path == "/api/search":
            query = params.get("q", [""])[0].strip()
            months = _lookback_months(params)
            if len(query) < 2:
                self._json({"error": "지역·단지·정책 키워드를 두 글자 이상 입력해 주세요."}, 400)
                return
            try:
                self._json(real_estate_search.search_real_estate(query, lookback_months=months))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/search/start":
            query = params.get("q", [""])[0].strip()
            months = _lookback_months(params)
            if len(query) < 2:
                self._json({"error": "지역·단지·정책 키워드를 두 글자 이상 입력해 주세요."}, 400)
                return
            try:
                self._json(start_search_job(query, lookback_months=months))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/search/progress":
            job_id = params.get("id", [""])[0].strip()
            payload = _snapshot(job_id)
            if not payload:
                self._json({"error": "검색 작업을 찾지 못했어요."}, 404)
                return
            self._json(payload)
            return
        if parsed.path.startswith("/assets/"):
            asset_name = unquote(parsed.path[len("/assets/"):])
            asset_path = (ASSETS_DIR / asset_name).resolve()
            try:
                asset_path.relative_to(ASSETS_DIR.resolve())
            except ValueError:
                self.send_error(404)
                return
            self._file(asset_path)
            return
        if parsed.path in ("/", "/real-estate-search.html"):
            self._file(APP_HTML)
            return
        self.send_error(404)


def main():
    print(f"부동산 유튜브 요약 서버: http://{HOST}:{PORT}")
    if not config.ready_channels():
        print("채널 ID가 아직 없어 검색어 기반 YouTube 보강으로 동작합니다.")
    if config.BUDGET_PREWARM_ENABLED:
        threading.Thread(target=_prewarm_budget_transaction_cache, daemon=True).start()
    SearchServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
