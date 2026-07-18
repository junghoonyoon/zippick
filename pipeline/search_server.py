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
import naver_complex
import policy_evaluator
import real_estate_search
import rone_estimates

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
BUDGET_CACHE_SCHEMA_VERSION = 12
BUDGET_JOBS = {}
BUDGET_JOBS_LOCK = threading.Lock()
BUDGET_MAX_JOBS = 20
BUDGET_JOB_TIMEOUT_SECONDS = float(os.environ.get("BUDGET_JOB_TIMEOUT_SECONDS", "150"))
BUDGET_PREWARM_STATE = {"running": False, "done": False, "pairCount": 0, "finishedAt": None}


def _budget_cache_key(arguments):
    tracked_files = [
        budget_candidates.__file__,
        config.ROOT / "pipeline" / "region_adjacency.py",
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
    if signals.get("scoreFormulaVersion") != momentum_signals.SCORE_FORMULA_VERSION:
        return True
    status = signals.get("status")
    if status in {"insufficient", "stale"}:
        return False
    if status != "ok" or signals.get("score") is None:
        return True

    # 버전 표기만 최신이고 항목별 점수는 구버전인 불완전 캐시도 거른다.
    # 원시 지표로 현재 산식을 다시 계산해 점수·중립 처리 여부가 모두
    # 일치하는지 확인한다.
    try:
        expected = momentum_signals._score_details(signals)
    except (KeyError, TypeError, ValueError):
        return True
    if signals.get("score") != expected["score"]:
        return True
    actual_breakdown = signals.get("scoreBreakdown")
    if not isinstance(actual_breakdown, dict):
        return True
    for key, expected_component in expected["breakdown"].items():
        actual_component = actual_breakdown.get(key)
        if not isinstance(actual_component, dict):
            return True
        for field in ("points", "maxPoints", "available", "neutral"):
            if actual_component.get(field) != expected_component[field]:
                return True
    return False


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


def _apartment_report(name, region):
    """예산 흐름 없이 단지 하나의 상승 흐름 리포트를 만든다.

    후보 카드와 같은 데이터 구조(row + signals)를 반환해 프론트의
    바텀싯 리포트 렌더러를 그대로 재사용한다.
    """
    entity = None
    try:
        entity = budget_candidates._find_entity(name, region)
    except Exception:
        entity = None
    region_label = region or (entity or {}).get("district") or ""
    effective_region = region_label
    try:
        # 지역 표기(예: '성남분당구')가 실거래 소스 색인과 달라 매칭이 0건이 되면
        # 이름만으로 조회한다. 결과 없음보다 지역 미지정 조회가 낫다.
        if effective_region and not molit_transactions.source_rows(name, effective_region):
            effective_region = ""
    except Exception:
        pass
    row = {
        "name": name,
        "displayName": (entity or {}).get("name") or name,
        "region": effective_region,
        "regionLabel": region_label,
        "households": int((entity or {}).get("households") or 0),
        "buildYear": (entity or {}).get("buildYear") or 0,
        "peers": [],
    }
    if molit_transactions.configured():
        try:
            months = molit_transactions._deal_months(momentum_signals.LOOKBACK_MONTHS)
            pairs = set()
            for source_row in molit_transactions.source_rows(row["name"], row["region"]):
                lawd_cd = molit_transactions._row_lawd_cd(source_row)
                if lawd_cd:
                    pairs.update((lawd_cd, deal_ymd) for deal_ymd in months)
            molit_transactions.prefetch_months(pairs)
        except Exception:
            pass
        try:
            momentum_signals.attach_signals([row])
        except Exception:
            pass
        try:
            row["peers"] = momentum_signals.district_peer_reports(
                row["name"], row.get("regionLabel") or row.get("region") or "",
            )
        except Exception:
            row["peers"] = []
        try:
            last_deal = molit_transactions.latest_transaction_for_apartment(
                row["name"], region=row["region"], skip_months=0,
            )
            if last_deal:
                row["latestDealPriceEok"] = last_deal.get("latestDealPriceEok")
                row["latestDealDate"] = last_deal.get("latestDealDate")
                area = last_deal.get("latestDealExclusiveArea")
                if area:
                    row["displayAreaLabel"] = f"{area}㎡"
        except Exception:
            pass
    return {"report": row, "signalNote": momentum_signals.SIGNAL_NOTE}


def _molit_affordability_estimate(name, region, area, months):
    """Build a price estimate from MOLIT trades when R-ONE has no complex match.

    Without an area selection, the estimate intentionally summarizes all unit
    types in the complex. Once the user selects an exclusive area, only that
    matching unit type is used.
    """
    try:
        lookback_months = max(1, min(int(months or 24), 60))
    except (TypeError, ValueError):
        lookback_months = 24
    requested_area = str(area or "").strip()
    transaction_kind = molit_transactions.transaction_kind_for_apartment(name, region)
    lookup_regions = [region]
    if region and transaction_kind != molit_transactions.TRANSACTION_KIND_PRESALE:
        lookup_regions.append("")

    selected_band = None
    selected_region = region
    selected_area = requested_area
    for lookup_region in lookup_regions:
        try:
            band = molit_transactions.price_band_for_apartment(
                name,
                region=lookup_region,
                area_label=requested_area,
                lookback_months=lookback_months,
            )
        except Exception:
            band = None
        if not band:
            continue
        selected_band = band
        selected_region = lookup_region
        break

    if not selected_band:
        return None

    min_price = float(
        selected_band.get("currentEstimateMinPriceEok")
        or selected_band.get("minPriceEok")
        or 0
    )
    mid_price = float(
        selected_band.get("currentEstimateMidPriceEok")
        or selected_band.get("midPriceEok")
        or 0
    )
    max_price = float(
        selected_band.get("currentEstimateMaxPriceEok")
        or selected_band.get("maxPriceEok")
        or 0
    )
    if not (min_price and mid_price and max_price):
        return None

    try:
        transactions = molit_transactions.transactions_for_apartment(
            name,
            region=selected_region,
            area_label=selected_area,
            lookback_months=lookback_months,
        )
    except Exception:
        transactions = []
    latest_date = str(selected_band.get("latestDealDate") or "")
    try:
        latest_age_days = max(
            0,
            (datetime.date.today() - datetime.date.fromisoformat(latest_date)).days,
        )
    except ValueError:
        latest_age_days = 0
    sample_count = int(
        selected_band.get("currentEstimateSampleCount")
        or selected_band.get("transactionCount")
        or len(transactions)
        or 0
    )
    confidence = "보통" if sample_count >= 10 else "낮음"
    adjusted_transactions = [
        {
            "dealDate": row.get("dealDate"),
            "originalPriceEok": row.get("dealAmountEok"),
            "adjustedPriceEok": row.get("dealAmountEok"),
            "exclusiveArea": row.get("exclusiveArea"),
            "basePeriod": str(row.get("dealDate") or "")[:7].replace("-", ""),
            "baseIndex": None,
            "factor": 1.0,
            "adjustment": (
                "국토부 분양권·입주권 실거래 원가격"
                if transaction_kind == molit_transactions.TRANSACTION_KIND_PRESALE
                else "국토부 실거래 원가격"
            ),
        }
        for row in transactions
        if row.get("dealDate") and float(row.get("dealAmountEok") or 0) > 0
    ]
    area_basis = (
        f"전용 {selected_area}㎡ 최근 거래 기준"
        if selected_area
        else "단지 전체 평형 거래 기준"
    )
    return {
        "estimate": {
            "minPriceEok": round(min(min_price, max_price), 2),
            "midPriceEok": round(mid_price, 2),
            "maxPriceEok": round(max(min_price, max_price), 2),
            "confidence": confidence,
            "sampleCount": sample_count,
            "trimmedCount": int(selected_band.get("currentEstimateTrimmedCount") or 0),
            "latestTradeDate": latest_date,
            "latestTradeAgeDays": latest_age_days,
            "method": selected_band.get("currentEstimateMethod")
            or "최근 국토부 실거래 가격대",
            "source": "molit",
            "transactionKind": transaction_kind,
        },
        "latestTrade": {
            "dealDate": latest_date,
            "dealAmountEok": selected_band.get("latestDealPriceEok"),
            "exclusiveArea": selected_band.get("latestDealExclusiveArea"),
            "floor": selected_band.get("latestDealFloor"),
        },
        "adjustedTransactions": adjusted_transactions,
        "index": {},
        "areaBasis": area_basis,
        "transactionKind": transaction_kind,
    }


def _apartment_affordability(arguments):
    name = str(arguments.get("name") or "").strip()
    region = str(arguments.get("region") or "").strip()
    area = str(arguments.get("area") or "").strip()
    months = arguments.get("months") or 24
    if len(name) < 2 or len(region) < 2:
        return {"error": "단지명과 지역을 확인해 주세요."}, 400

    transaction_kind = molit_transactions.transaction_kind_for_apartment(name, region)
    if transaction_kind == molit_transactions.TRANSACTION_KIND_PRESALE:
        estimate_payload, estimate_status = {"error": "분양권·입주권 전용 실거래 조회"}, 404
    else:
        estimate_payload, estimate_status = rone_estimates.estimate(
            name,
            region,
            area=area,
            months=months,
            include_details=True,
        )
    estimate = estimate_payload.get("estimate") if isinstance(estimate_payload, dict) else None
    if estimate_status != 200 or not isinstance(estimate, dict):
        fallback_payload = _molit_affordability_estimate(
            name,
            region,
            area,
            months,
        )
        if fallback_payload:
            estimate_payload = fallback_payload
            estimate = fallback_payload["estimate"]
        else:
            message = (
                estimate_payload.get("error")
                if isinstance(estimate_payload, dict)
                else None
            )
            return {
                "state": "unavailable",
                "error": message or "현재 가격을 추정할 거래 자료가 부족해요.",
                "profileComplete": False,
            }, 200

    latest_trade = estimate_payload.get("latestTrade")
    if not isinstance(latest_trade, dict):
        latest_trade = {}
    response = {
        "state": "ready",
        "estimate": {
            "minPriceEok": estimate.get("minPriceEok"),
            "midPriceEok": estimate.get("midPriceEok"),
            "maxPriceEok": estimate.get("maxPriceEok"),
            "confidence": estimate.get("confidence"),
            "sampleCount": estimate.get("sampleCount"),
            "latestTradeDate": estimate.get("latestTradeDate"),
            "latestTradeAgeDays": estimate.get("latestTradeAgeDays"),
            "method": estimate.get("method"),
            "source": estimate.get("source") or "rone",
            "transactionKind": (
                estimate.get("transactionKind")
                or estimate_payload.get("transactionKind")
                or transaction_kind
            ),
        },
        "latestTrade": {
            key: latest_trade.get(key)
            for key in ("dealDate", "dealAmountEok", "exclusiveArea", "floor")
        },
        "market": {
            "adjustedTransactions": (
                estimate_payload.get("adjustedTransactions")
                if isinstance(estimate_payload.get("adjustedTransactions"), list)
                else []
            ),
            "index": (
                estimate_payload.get("index")
                if isinstance(estimate_payload.get("index"), dict)
                else {}
            ),
        },
        "areaBasis": (
            (
                estimate_payload.get("areaBasis")
                or f"전용 {area}㎡ 거래 기준"
            )
            if area
            else "단지 전체 평형 거래 기준"
        ),
        "selectedArea": area,
        "transactionKind": (
            estimate_payload.get("transactionKind")
            or estimate.get("transactionKind")
            or transaction_kind
        ),
        "profileComplete": False,
    }

    raw_profile = arguments.get("profile")
    if not isinstance(raw_profile, dict):
        return response, 200

    home_ownership = str(raw_profile.get("home_ownership") or "").strip()
    first_time = str(raw_profile.get("first_time", "")).strip().lower()
    cash_eok = raw_profile.get("cash_eok")
    annual_income = raw_profile.get("annual_income")
    mortgage_rate = raw_profile.get("mortgage_rate")
    co_borrower = str(raw_profile.get("co_borrower") or "false").strip().lower()
    spouse_income = raw_profile.get("spouse_annual_income")
    profile_complete = (
        home_ownership in policy_evaluator.HOME_OWNERSHIP_LABELS
        and home_ownership != "unknown"
        and first_time in {"true", "false"}
        and policy_evaluator._float(cash_eok) > 0
        and policy_evaluator._float(annual_income) > 0
        and policy_evaluator._float(mortgage_rate) > 0
        and (
            co_borrower not in {"1", "true", "yes", "on"}
            or policy_evaluator._float(spouse_income) > 0
        )
    )
    if not profile_complete:
        return response, 200

    profile = policy_evaluator.user_profile(
        home_ownership=home_ownership,
        first_time=first_time,
        cash_eok=cash_eok,
        annual_income=annual_income,
        monthly_debt_payment=raw_profile.get("monthly_debt_payment"),
        co_borrower=co_borrower,
        spouse_annual_income=spouse_income,
        spouse_monthly_debt_payment=raw_profile.get("spouse_monthly_debt_payment"),
        mortgage_rate=mortgage_rate,
        loan_term_years=raw_profile.get("loan_term_years") or 30,
        purchase_cost_rate=raw_profile.get("purchase_cost_rate") or 0,
    )
    policy_transactions = [
        {
            "dealDate": row.get("dealDate"),
            "dealAmountEok": (
                row.get("originalPriceEok")
                or row.get("dealAmountEok")
                or row.get("priceEok")
            ),
        }
        for row in response["market"]["adjustedTransactions"]
        if isinstance(row, dict)
    ]
    recent_trade_stats = molit_transactions.quarter_trade_stats(policy_transactions)
    candidate = {
        "name": name,
        "region": region,
        "minPriceEok": estimate.get("minPriceEok"),
        "midPriceEok": estimate.get("midPriceEok"),
        "maxPriceEok": estimate.get("maxPriceEok"),
        "latestDealPriceEok": latest_trade.get("dealAmountEok"),
        **recent_trade_stats,
    }
    try:
        entity = budget_candidates._find_entity(name, region)
    except Exception:
        entity = None
    response["profileComplete"] = True
    response["profile"] = {
        "cashEok": profile["cashEok"],
        "homeOwnershipLabel": profile["homeOwnershipLabel"],
        "combinedIncomeManwon": profile["combinedIncomeManwon"],
    }
    response["policyImpact"] = policy_evaluator.evaluate_candidate(
        candidate,
        entity=entity,
        profile=profile,
    )
    return response, 200


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
            elapsed = time.time() - float(job.get("startedAt") or 0)
            if elapsed >= BUDGET_JOB_TIMEOUT_SECONDS:
                payload = json.loads(json.dumps(job.get("initial") or {}, ensure_ascii=False))
                payload.update({
                    "done": True,
                    "enrichmentPending": False,
                    "enrichmentStage": "timeout",
                    "error": "최신 실거래 확인이 오래 걸려 현재 확보한 결과만 표시합니다.",
                })
                job["done"] = True
                job["result"] = payload
                job["finishedAt"] = time.time()
                return payload
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
    if not molit_transactions.configured():
        initial = json.loads(json.dumps(initial, ensure_ascii=False))
        momentum_signals.attach_signals(_budget_payload_rows(initial))
        initial.update({
            "enrichmentPending": False,
            "enrichmentStage": "complete",
        })
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

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/apartment-affordability":
            self._json({"error": "지원하지 않는 요청이에요."}, 404)
            return
        try:
            content_length = min(int(self.headers.get("Content-Length") or 0), 65536)
            arguments = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            self._json({"error": "요청 내용을 확인해 주세요."}, 400)
            return
        if not isinstance(arguments, dict):
            self._json({"error": "요청 내용을 확인해 주세요."}, 400)
            return
        payload, status = _apartment_affordability(arguments)
        self._json(payload, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/map-config":
            self._json({
                "provider": "kakao",
                "configured": bool(config.KAKAO_MAP_JAVASCRIPT_KEY),
                "appKey": config.KAKAO_MAP_JAVASCRIPT_KEY,
            })
            return
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
            ceiling_impacts = [
                policy_evaluator.evaluate_candidate(
                    {"region": region, "midPriceEok": ceiling},
                    profile=profile,
                )
                for region in ("서울시", "경기도")
            ]
            best_impact = max(
                ceiling_impacts,
                key=lambda impact: float(impact.get("estimatedLoanLimitEok") or 0),
            )
            snapshot["estimatedLoanLimitEok"] = best_impact.get("estimatedLoanLimitEok")
            snapshot["priceCapEok"] = best_impact.get("priceCapEok")
            self._json({"budgetEok": ceiling, "snapshot": snapshot})
            return
        if parsed.path == "/api/apartment-suggest":
            query = params.get("q", [""])[0].strip()
            suggestions = real_estate_search.suggest_apartments(query)
            resolve_naver = params.get("resolve_naver", ["false"])[0].strip().lower()
            if suggestions and resolve_naver in {"1", "true", "yes", "on"}:
                try:
                    naver_complex.attach_links(suggestions)
                except Exception:
                    pass
            self._json({"suggestions": suggestions})
            return
        if parsed.path == "/api/apartment-areas":
            name = params.get("name", [""])[0].strip()
            region = params.get("region", [""])[0].strip()
            months = params.get("months", ["24"])[0].strip()
            if len(name) < 2:
                self._json({"error": "단지명을 확인해 주세요."}, 400)
                return
            try:
                months = max(1, min(int(months), 60))
            except ValueError:
                months = 24
            try:
                areas = molit_transactions.area_options_for_apartment(
                    name,
                    region=region,
                    lookback_months=months,
                )
                if not areas and region:
                    areas = molit_transactions.area_options_for_apartment(
                        name,
                        region="",
                        lookback_months=months,
                    )
            except Exception:
                # 조회 장애를 정상적인 '거래 없음'으로 응답하면 프런트 캐시에 빈
                # 목록이 남아 재검색해도 복구되지 않는다. 오류 응답으로 재시도를 허용한다.
                self._json({"error": "전용면적을 불러오지 못했어요. 잠시 후 다시 시도해 주세요."}, 502)
                return
            self._json({
                "areas": areas,
                "lookbackMonths": months,
                "source": "국토부 실거래",
            })
            return
        if parsed.path == "/api/apartment-report":
            name = params.get("name", [""])[0].strip()
            region = params.get("region", [""])[0].strip()
            if len(name) < 2:
                self._json({"error": "단지명을 확인해 주세요."}, 400)
                return
            self._json(_apartment_report(name, region))
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
        if parsed.path == "/api/rone-estimate":
            name = params.get("name", [""])[0].strip()
            region = params.get("region", [""])[0].strip()
            area = params.get("area", [""])[0].strip()
            months = params.get("months", ["12"])[0].strip()
            include_details = params.get("details", [""])[0].strip().lower() in {"1", "true", "yes"}
            transaction_kind = molit_transactions.transaction_kind_for_apartment(name, region)
            if transaction_kind == molit_transactions.TRANSACTION_KIND_PRESALE:
                payload, status = {"error": "분양권·입주권 전용 실거래 조회"}, 404
            else:
                payload, status = rone_estimates.estimate(
                    name,
                    region,
                    area=area,
                    months=months,
                    include_details=include_details,
                )
            # R-ONE에 없는 단지(신축·분양권 등)는 국토부 실거래로 대체해
            # 거래 흐름·추정가가 항상 뜨도록 한다.
            if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("estimate"), dict):
                fallback_payload = _molit_affordability_estimate(name, region, area, months)
                if fallback_payload:
                    payload, status = fallback_payload, 200
            self._json(payload, status)
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
