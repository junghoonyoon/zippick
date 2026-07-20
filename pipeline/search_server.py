#!/usr/bin/env python3
"""부동산 유튜브 요약 화면과 로컬 API를 제공한다."""
import datetime
import hashlib
import hmac
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import config
import apartment_leaders
import budget_candidates
import listing_review
import molit_transactions
import momentum_signals
import naver_complex
import news_catalysts
import paid_access
import policy_evaluator
import real_estate_search
import report_store
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
BUDGET_CACHE_SCHEMA_VERSION = 15
BUDGET_SOURCE_REVISIONS = None
BUDGET_JOBS = {}
BUDGET_JOBS_LOCK = threading.Lock()
BUDGET_MAX_JOBS = 20
BUDGET_JOB_TIMEOUT_SECONDS = float(os.environ.get("BUDGET_JOB_TIMEOUT_SECONDS", "150"))
BUDGET_JOB_HARD_TIMEOUT_SECONDS = float(os.environ.get("BUDGET_JOB_HARD_TIMEOUT_SECONDS", "600"))
BUDGET_PREWARM_STATE = {"running": False, "done": False, "pairCount": 0, "finishedAt": None}
MARKET_SNAPSHOT_LOCK = threading.Lock()
MARKET_SIGNAL_SNAPSHOTS = {}
MARKET_SIGNAL_SNAPSHOT_KEYS = {}
MARKET_ROW_SNAPSHOTS = {}
MARKET_ROW_SNAPSHOT_KEYS = {}
MARKET_SNAPSHOT_SOURCE_DIR = None
MARKET_SNAPSHOTS_LOADED = False
REGIONAL_INDEX_CACHE = {}
REGIONAL_INDEX_CACHE_LOCK = threading.Lock()
MARKET_SNAPSHOT_MAX_AGE_SECONDS = int(os.environ.get(
    "MARKET_SNAPSHOT_MAX_AGE_SECONDS",
    # 검색 즉시 표시용 스냅샷은 최대 48시간까지 먼저 보여주고, 같은 요청에서
    # 백그라운드 최신화를 시작한다. 실거래 신고 단위보다 짧은 범위다.
    str(60 * 60 * 48),
))
MARKET_SNAPSHOT_FIELDS = (
    "areaLabel",
    "recentMinPriceEok",
    "recentMedianPriceEok",
    "recentAveragePriceEok",
    "recentMaxPriceEok",
    "currentEstimateMinPriceEok",
    "currentEstimateMidPriceEok",
    "currentEstimateMaxPriceEok",
    "currentEstimateSampleCount",
    "currentEstimateTrimmedCount",
    "currentEstimateMethod",
    "latestDealPriceEok",
    "latestDealExclusiveArea",
    "latestDealFloor",
    "latestDealDate",
    "lastObservedDealPriceEok",
    "lastObservedDealExclusiveArea",
    "lastObservedDealFloor",
    "lastObservedDealDate",
    "lastObservedDealNote",
    "previousDealPriceEok",
    "previousDealDate",
    "transactionCount",
    "tradeLookbackMonths",
    "statsThrough",
    "recent3AveragePriceEok",
    "recent3TradeCount",
    "recent3AdjustedAveragePriceEok",
    "recent3AdjustedTradeCount",
    "recent3ExcludedTradeCount",
    "previous3AveragePriceEok",
    "previous3TradeCount",
    "recent6AveragePriceEok",
    "recent6TradeCount",
    "previous6AveragePriceEok",
    "previous6TradeCount",
    "sourceNote",
    "priceSource",
)


def _budget_cache_key(arguments):
    global BUDGET_SOURCE_REVISIONS
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
    if BUDGET_SOURCE_REVISIONS is None:
        revisions = []
        for path_value in tracked_files:
            path = os.fspath(path_value)
            try:
                revisions.append(hashlib.sha256(Path(path).read_bytes()).hexdigest())
            except OSError:
                revisions.append("")
        BUDGET_SOURCE_REVISIONS = revisions
    material = {
        "schema": BUDGET_CACHE_SCHEMA_VERSION,
        "date": datetime.date.today().isoformat(),
        "arguments": arguments,
        # 파일 수정시간은 새 릴리스마다 달라져 내용이 같은 캐시까지 매번
        # 무효화한다. 내용 해시는 실제 로직·데이터가 바뀔 때만 키를 바꾼다.
        "revisions": BUDGET_SOURCE_REVISIONS,
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
    _index_market_snapshot_payload(payload, saved_at)
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


def _market_snapshot_key(row):
    return (
        real_estate_search.compact(row.get("name", "")),
        real_estate_search.compact(row.get("region", "")),
    )


def _market_snapshot_area_key(row):
    value = str(row.get("areaLabel") or row.get("displayAreaLabel") or "")
    numbers = re.findall(r"\d+(?:\.\d+)?", value)
    return "|".join(numbers) if numbers else real_estate_search.compact(value)


def _market_snapshot_area_range(area_key):
    values = [
        float(value)
        for value in str(area_key or "").split("|")
        if value
    ]
    if not values:
        return None
    return min(values), max(values)


def _market_snapshot_area_compatible(left_key, right_key):
    left = _market_snapshot_area_range(left_key)
    right = _market_snapshot_area_range(right_key)
    if not left or not right:
        return left_key == right_key
    # 공공 원본과 실거래의 59.x㎡가 반올림 과정에서 59㎡/60㎡로 달라지는
    # 경우를 같은 평형대로 취급한다.
    return max(left[0], right[0]) <= min(left[1], right[1]) + 2


def _compatible_snapshot(snapshot_index, snapshot_keys, key, area_key):
    exact = snapshot_index.get((*key, area_key))
    if exact:
        return exact
    compatible = [
        snapshot_index[row_key]
        for row_key in snapshot_keys.get(key, ())
        if _market_snapshot_area_compatible(area_key, row_key[2])
    ]
    return max(compatible, key=lambda item: item[0]) if compatible else None


def _index_market_snapshot_payload_locked(payload, saved_at):
    for row in _budget_payload_rows(payload):
        key = _market_snapshot_key(row)
        if not all(key):
            continue
        signals = row.get("signals")
        if (
            isinstance(signals, dict)
            and signals.get("scoreFormulaVersion") == momentum_signals.SCORE_FORMULA_VERSION
        ):
            signal_key = (*key, _market_snapshot_area_key(row))
            MARKET_SIGNAL_SNAPSHOT_KEYS.setdefault(key, set()).add(signal_key)
            previous = MARKET_SIGNAL_SNAPSHOTS.get(signal_key)
            if not previous or saved_at >= previous[0]:
                MARKET_SIGNAL_SNAPSHOTS[signal_key] = (
                    saved_at,
                    json.loads(json.dumps(signals, ensure_ascii=False)),
                )
        area_key = _market_snapshot_area_key(row)
        market = {
            field: row.get(field)
            for field in MARKET_SNAPSHOT_FIELDS
            if row.get(field) is not None
        }
        market_status = str(row.get("marketDataStatus") or "")
        if market_status in {"ready", "no_recent_trade", "no_selected_area_trade"}:
            market["marketDataStatus"] = market_status
        has_price = any(
            _positive_number(row.get(field))
            for field in (
                "latestDealPriceEok",
                "lastObservedDealPriceEok",
                "recentMedianPriceEok",
                "midPriceEok",
            )
        )
        # areaLabel만 있는 미완성 행은 완성 스냅샷으로 저장하지 않는다.
        # 그렇지 않으면 조건 변경 검색에서 빈 가격을 "ready"로 오인한다.
        if not has_price and market_status not in {
            "no_recent_trade",
            "no_selected_area_trade",
        }:
            continue
        row_key = (*key, area_key)
        MARKET_ROW_SNAPSHOT_KEYS.setdefault(key, set()).add(row_key)
        previous = MARKET_ROW_SNAPSHOTS.get(row_key)
        if not previous or saved_at >= previous[0]:
            MARKET_ROW_SNAPSHOTS[row_key] = (
                saved_at,
                json.loads(json.dumps(market, ensure_ascii=False)),
            )


def _index_market_snapshot_payload(payload, saved_at):
    with MARKET_SNAPSHOT_LOCK:
        _index_market_snapshot_payload_locked(payload, saved_at)


def _load_market_snapshots():
    """완료 검색 캐시를 단지별 인메모리 스냅샷으로 합친다."""
    global MARKET_SNAPSHOT_SOURCE_DIR, MARKET_SNAPSHOTS_LOADED
    try:
        source_dir = str(BUDGET_CACHE_DIR.resolve())
    except OSError:
        source_dir = os.fspath(BUDGET_CACHE_DIR)
    with MARKET_SNAPSHOT_LOCK:
        if MARKET_SNAPSHOTS_LOADED and MARKET_SNAPSHOT_SOURCE_DIR == source_dir:
            return
        MARKET_SIGNAL_SNAPSHOTS.clear()
        MARKET_SIGNAL_SNAPSHOT_KEYS.clear()
        MARKET_ROW_SNAPSHOTS.clear()
        MARKET_ROW_SNAPSHOT_KEYS.clear()
        MARKET_SNAPSHOT_SOURCE_DIR = source_dir
        MARKET_SNAPSHOTS_LOADED = True
        now = time.time()
        for path in BUDGET_CACHE_DIR.glob("*.json"):
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            saved_at = float(cached.get("savedAt") or 0)
            if not saved_at or now - saved_at > MARKET_SNAPSHOT_MAX_AGE_SECONDS:
                continue
            payload = cached.get("payload")
            if not isinstance(payload, dict):
                continue
            _index_market_snapshot_payload_locked(payload, saved_at)


def _positive_number(value):
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _market_price_ready(row):
    return any(
        _positive_number(row.get(field))
        for field in (
            "latestDealPriceEok",
            "lastObservedDealPriceEok",
            "recentMedianPriceEok",
            "midPriceEok",
        )
    )


def _cached_market_band(row):
    if _market_price_ready(row):
        return row, None, None, None, None, None
    try:
        entity = budget_candidates._find_entity(
            row.get("name", ""),
            row.get("region", ""),
        )
    except Exception:
        entity = None
    area_range = _market_snapshot_area_range(_market_snapshot_area_key(row))
    minimum = float(row.get("areaMin") or (area_range or (0, 0))[0] or 0)
    try:
        bundle = molit_transactions.cached_market_bundle_for_apartment(
            row.get("name", ""),
            region=row.get("region", ""),
            area_label=row.get("areaLabel") or row.get("displayAreaLabel") or "",
            min_area=minimum,
            lookback_months=config.MOLIT_STALE_TRANSACTION_LOOKBACK_MONTHS,
            entity=entity,
        )
    except Exception:
        bundle = {}
    return (
        row,
        bundle.get("band"),
        bundle.get("comparison"),
        bundle.get("coverage"),
        bundle.get("transactions"),
        bundle.get("lastObserved"),
    )


def _attach_cached_market_bands(rows):
    """Fill selected-area prices from local month caches without live requests."""
    missing = [row for row in rows if not _market_price_ready(row)]
    if not missing:
        return
    workers = min(24, len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        resolved = list(pool.map(_cached_market_band, missing))
    for row, live, comparison, coverage, transactions, last_observed in resolved:
        row["_cachedMarketTransactions"] = transactions
        if live:
            budget_candidates._apply_live_band(row, live, comparison)
            row["marketDataStatus"] = "ready"
            row["marketLocalCacheHit"] = True
        elif (coverage or {}).get("complete"):
            if last_observed:
                row.update(last_observed)
            row["marketDataStatus"] = (
                "no_recent_trade"
                if last_observed
                else "no_selected_area_trade"
            )
            row["marketCacheCoverage"] = coverage
        else:
            row["marketDataStatus"] = "pending"
            if coverage:
                row["marketCacheCoverage"] = coverage


def _attach_market_snapshots(payload):
    """1차 조건 검색에 저장된 실거래·점수를 외부 조회 없이 부착한다."""
    _load_market_snapshots()
    rows = _budget_payload_rows(payload)
    hit_count = 0
    newest_saved_at = 0
    with MARKET_SNAPSHOT_LOCK:
        for row in rows:
            key = _market_snapshot_key(row)
            if not all(key):
                continue
            area_key = _market_snapshot_area_key(row)
            signal_snapshot = _compatible_snapshot(
                MARKET_SIGNAL_SNAPSHOTS,
                MARKET_SIGNAL_SNAPSHOT_KEYS,
                key,
                area_key,
            )
            market_snapshot = _compatible_snapshot(
                MARKET_ROW_SNAPSHOTS,
                MARKET_ROW_SNAPSHOT_KEYS,
                key,
                area_key,
            )
            hit = False
            if signal_snapshot:
                saved_at, signals = signal_snapshot
                row["signals"] = json.loads(json.dumps(signals, ensure_ascii=False))
                newest_saved_at = max(newest_saved_at, saved_at)
                hit = True
            if market_snapshot:
                saved_at, market = market_snapshot
                row.update(json.loads(json.dumps(market, ensure_ascii=False)))
                row["marketDataStatus"] = market.get("marketDataStatus") or "ready"
                newest_saved_at = max(newest_saved_at, saved_at)
                hit = True
            if hit:
                row["marketSnapshotHit"] = True
                hit_count += 1

    # 조건 변경으로 선택 평형이 달라진 후보는 단지명 점수만 재사용하지 않는다.
    # 선택 평형의 월별 로컬 캐시에서 가격을 먼저 조립한 뒤 같은 평형으로
    # 점수를 계산한다. 외부 API는 이 응답 경로에서 호출하지 않는다.
    _attach_cached_market_bands(rows)
    momentum_signals.attach_cached_signals(rows, only_missing=True)
    pending_count = sum(
        1
        for row in rows
        if not _market_price_ready(row)
        and row.get("marketDataStatus") not in {
            "no_recent_trade",
            "no_selected_area_trade",
        }
    )
    payload.update({
        "marketSnapshotReady": True,
        "marketPresentationReady": pending_count == 0,
        "marketSnapshotHitCount": hit_count,
        "marketSnapshotMissCount": max(0, len(rows) - hit_count),
        "marketPendingCount": pending_count,
        "marketReadyCount": max(0, len(rows) - pending_count),
    })
    if newest_saved_at:
        payload["marketSnapshotAsOf"] = datetime.datetime.fromtimestamp(
            newest_saved_at,
            real_estate_search.KST,
        ).isoformat()
    return payload


def _refresh_snapshot_policy_impacts(payload, candidate_arguments):
    """Recalculate financing after cached market prices replace first-stage data.

    The staged search evaluates policy before ``_attach_market_snapshots`` runs.
    When a changed condition reuses market data from the previous search, the
    card prices are refreshed but the earlier policy result can otherwise keep
    an empty ``cashScenarios`` list.
    """
    profile = policy_evaluator.user_profile(
        home_ownership=candidate_arguments.get("home_ownership", "unknown"),
        first_time=candidate_arguments.get("first_time", False),
        cash_eok=candidate_arguments.get("cash_eok", 0),
        annual_income=candidate_arguments.get("annual_income", 0),
        monthly_debt_payment=candidate_arguments.get("monthly_debt_payment", 0),
        co_borrower=candidate_arguments.get("co_borrower", False),
        spouse_annual_income=candidate_arguments.get("spouse_annual_income", 0),
        spouse_monthly_debt_payment=candidate_arguments.get(
            "spouse_monthly_debt_payment",
            0,
        ),
        mortgage_rate=candidate_arguments.get("mortgage_rate", 0),
        loan_term_years=candidate_arguments.get("loan_term_years", 30),
        purchase_cost_rate=candidate_arguments.get("purchase_cost_rate", 0),
    )
    impacts = []
    price_fields = (
        "latestDealPriceEok",
        "recent3AdjustedAveragePriceEok",
        "recent3AveragePriceEok",
        "midPriceEok",
        "maxPriceEok",
        "minPriceEok",
    )
    for row in _budget_payload_rows(payload):
        has_price = False
        for field in price_fields:
            try:
                if float(row.get(field) or 0) > 0:
                    has_price = True
                    break
            except (TypeError, ValueError):
                continue
        if not has_price:
            row["policyImpact"] = None
            continue
        try:
            entity = budget_candidates._find_entity(
                row.get("name", ""),
                row.get("region", ""),
            )
        except Exception:
            entity = None
        impact = policy_evaluator.evaluate_candidate(
            row,
            entity=entity,
            profile=profile,
        )
        row["policyImpact"] = impact
        impacts.append(impact)

    previous_snapshot = payload.get("policySnapshot") or {}
    policy_snapshot = policy_evaluator.summarize(impacts, profile)
    for field in ("estimatedPurchaseCeilingEok", "budgetSource"):
        if field in previous_snapshot:
            policy_snapshot[field] = previous_snapshot[field]
    payload["policySnapshot"] = policy_snapshot
    return payload


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
    entity = entity or {}
    entity_name = str(entity.get("name") or name).strip()
    aliases = []
    for value in (entity_name, name, *(entity.get("aliases") or [])):
        value = str(value or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    region_label = region or (entity or {}).get("district") or ""
    effective_region = region_label
    try:
        # 지역 표기(예: '성남분당구')가 실거래 소스 색인과 달라 매칭이 0건이 되면
        # 이름만으로 조회한다. 결과 없음보다 지역 미지정 조회가 낫다.
        source_rows = (
            molit_transactions.source_rows_for_entity(entity, effective_region)
            if entity
            else molit_transactions.source_rows(name, effective_region)
        )
        if effective_region and not source_rows:
            effective_region = ""
    except Exception:
        pass
    row = {
        "name": name,
        "displayName": entity_name,
        "region": effective_region,
        "regionLabel": region_label,
        "province": str(entity.get("province") or "").strip(),
        "city": str(entity.get("city") or "").strip(),
        "district": str(entity.get("district") or "").strip(),
        "legalDong": str(entity.get("legalDong") or "").strip(),
        "jibun": str(entity.get("jibun") or "").strip(),
        "address": str(entity.get("address") or "").strip(),
        "aliases": aliases,
        "households": int(entity.get("households") or 0),
        "buildYear": entity.get("buildYear") or 0,
        "peers": [],
    }
    if molit_transactions.configured():
        try:
            months = molit_transactions._deal_months(momentum_signals.LOOKBACK_MONTHS)
            pairs = set()
            source_rows = (
                molit_transactions.source_rows_for_entity(row, row["region"])
                if entity
                else molit_transactions.source_rows(row["name"], row["region"])
            )
            for source_row in source_rows:
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
                row["name"], region=row["region"], skip_months=0, entity=row,
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


def _regional_index_from_rone_payload(payload, source_apartment=""):
    if not isinstance(payload, dict):
        return None
    index = payload.get("index")
    if not isinstance(index, dict):
        return None
    values = {}
    for row in payload.get("adjustedTransactions") or []:
        if not isinstance(row, dict):
            continue
        period = str(row.get("basePeriod") or "")[:6]
        try:
            value = float(row.get("baseIndex") or 0)
        except (TypeError, ValueError):
            value = 0
        if re.fullmatch(r"\d{6}", period) and value > 0:
            values[period] = value
    latest_period = str(index.get("latestPeriod") or "")[:6]
    try:
        latest_value = float(index.get("latestValue") or 0)
    except (TypeError, ValueError):
        latest_value = 0
    if re.fullmatch(r"\d{6}", latest_period) and latest_value > 0:
        values[latest_period] = latest_value
    if len(values) < 2:
        return None
    history = [
        {"period": period, "value": values[period]}
        for period in sorted(values)
    ]
    return {
        "source": index.get("source") or "한국부동산원 R-ONE 월간 아파트 매매가격지수",
        "region": index.get("region") or "",
        "latestPeriod": history[-1]["period"],
        "latestValue": history[-1]["value"],
        "history": history,
        "sourceApartment": source_apartment,
        "method": "official_rone",
    }


def _regional_transaction_index(region, source_candidates, months):
    """R-ONE 연결 실패 시 지역 대표 단지 실거래로 월별 평균지수를 만든다."""
    monthly_complex_values = {}
    for candidate in source_candidates:
        try:
            rows = molit_transactions.transactions_for_apartment(
                candidate.get("name", ""),
                region=candidate.get("region") or region,
                lookback_months=months,
            )
        except Exception:
            rows = []
        by_month = {}
        for row in rows:
            period = str(row.get("dealDate") or "")[:7].replace("-", "")
            try:
                price = float(row.get("dealAmountEok") or 0)
                area = float(row.get("exclusiveArea") or 0)
            except (TypeError, ValueError):
                continue
            if not re.fullmatch(r"\d{6}", period) or price <= 0 or area <= 0:
                continue
            by_month.setdefault(period, []).append(price / area)
        for period, values in by_month.items():
            ordered = sorted(values)
            middle = len(ordered) // 2
            median = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / 2
            )
            monthly_complex_values.setdefault(period, []).append(median)
    raw_history = []
    for period, values in sorted(monthly_complex_values.items()):
        if not values:
            continue
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )
        raw_history.append((period, median))
    if len(raw_history) < 2 or raw_history[0][1] <= 0:
        return None
    anchor = raw_history[0][1]
    history = [
        {"period": period, "value": round(value / anchor * 100, 6)}
        for period, value in raw_history
    ]
    return {
        "source": "국토부 실거래 기반 지역 대표 단지 평균지수",
        "region": region,
        "latestPeriod": history[-1]["period"],
        "latestValue": history[-1]["value"],
        "history": history,
        "method": "district_transaction_median",
        "comparisonComplexCount": len(source_candidates),
    }


def _regional_index_for_apartment(name, region, months):
    try:
        lookback_months = max(6, min(int(months or 24), 60))
    except (TypeError, ValueError):
        lookback_months = 24
    candidates = momentum_signals.district_index_source_candidates(
        region,
        exclude_name=name,
        limit=8,
    )
    normalized_region = candidates[0].get("region") if candidates else region
    cache_key = (real_estate_search.compact(normalized_region), lookback_months)
    with REGIONAL_INDEX_CACHE_LOCK:
        cached = REGIONAL_INDEX_CACHE.get(cache_key)
    if cached:
        return cached

    probes = [{"name": name, "region": normalized_region}, *candidates[:6]]
    unique_probes = []
    seen = set()
    for probe in probes:
        key = (
            real_estate_search.compact(probe.get("name")),
            real_estate_search.compact(probe.get("region")),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique_probes.append(probe)

    executor = ThreadPoolExecutor(max_workers=min(4, len(unique_probes) or 1))
    futures = {
        executor.submit(
            rone_estimates.estimate,
            probe["name"],
            probe.get("region") or normalized_region,
            months=lookback_months,
            include_details=True,
        ): probe
        for probe in unique_probes
    }
    official = None
    try:
        for future in as_completed(futures):
            probe = futures[future]
            try:
                payload, status = future.result()
            except Exception:
                continue
            if status != 200:
                continue
            official = _regional_index_from_rone_payload(
                payload,
                source_apartment=probe["name"],
            )
            if official:
                break
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    regional_index = official or _regional_transaction_index(
        normalized_region,
        candidates,
        lookback_months,
    )
    if regional_index:
        with REGIONAL_INDEX_CACHE_LOCK:
            REGIONAL_INDEX_CACHE[cache_key] = regional_index
    return regional_index


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
    regional_index = _regional_index_for_apartment(
        name,
        selected_region or region,
        lookback_months,
    )
    if regional_index:
        index_by_period = {
            str(row.get("period") or ""): row.get("value")
            for row in regional_index.get("history") or []
            if isinstance(row, dict)
        }
        for row in adjusted_transactions:
            row["baseIndex"] = index_by_period.get(row["basePeriod"])
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
        "index": regional_index or {},
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

    raw_profile = arguments.get("profile")
    profile_arguments = raw_profile if isinstance(raw_profile, dict) else {}
    common_candidate_arguments = {
        "name": name,
        "region": region,
        "search_region": arguments.get("search_region") or region,
        "area": area,
        "budget": arguments.get("budget") or 0,
        "purpose": arguments.get("purpose") or "",
        "priority": arguments.get("priority") or "",
        "commute": arguments.get("commute") or "",
        "move_timing": arguments.get("move_timing") or "",
        "price_strategy": arguments.get("price_strategy") or "stretch",
        "min_area": arguments.get("min_area") or 0,
        "min_households": arguments.get("min_households") or 0,
        "max_building_age": arguments.get("max_building_age") or 0,
        "home_ownership": profile_arguments.get("home_ownership") or "unknown",
        "first_time": profile_arguments.get("first_time") or False,
        "cash_eok": profile_arguments.get("cash_eok") or 0,
        "annual_income": profile_arguments.get("annual_income") or 0,
        "monthly_debt_payment": profile_arguments.get("monthly_debt_payment") or 0,
        "co_borrower": profile_arguments.get("co_borrower") or False,
        "spouse_annual_income": profile_arguments.get("spouse_annual_income") or 0,
        "spouse_monthly_debt_payment": profile_arguments.get("spouse_monthly_debt_payment") or 0,
        "mortgage_rate": profile_arguments.get("mortgage_rate") or 0,
        "loan_term_years": profile_arguments.get("loan_term_years") or 30,
        "purchase_cost_rate": profile_arguments.get("purchase_cost_rate") or 0,
    }
    try:
        common_candidate = budget_candidates.apartment_candidate_result(
            **common_candidate_arguments
        )
    except Exception:
        common_candidate = None

    effective_area = area
    area_fallback = False
    minimum_area = policy_evaluator._float(arguments.get("min_area")) if not area else 0
    if minimum_area:
        try:
            area_options = molit_transactions.area_options_for_apartment(
                name,
                region=region,
                lookback_months=months,
            )
            if not area_options and region:
                area_options = molit_transactions.area_options_for_apartment(
                    name,
                    region="",
                    lookback_months=months,
                )
        except Exception:
            area_options = None
        if area_options is None:
            return {
                "state": "unavailable",
                "error": "선택한 전용면적의 실거래를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.",
                "candidate": common_candidate,
                "profileComplete": False,
            }, 200
        available_areas = sorted(
            policy_evaluator._float(option.get("value"))
            for option in area_options
            if isinstance(option, dict)
            and policy_evaluator._float(option.get("value")) > 0
        )
        if not available_areas:
            return {
                "state": "unavailable",
                "error": "이 단지에서 자동 선택할 수 있는 전용면적 실거래가 없어요.",
                "candidate": common_candidate,
                "candidateResultSchemaVersion": (
                    (common_candidate or {}).get("resultSchemaVersion")
                    or budget_candidates.CANDIDATE_RESULT_SCHEMA_VERSION
                ),
                "selectedArea": "",
                "profileComplete": False,
            }, 200
        resolved_area = min(
            available_areas,
            key=lambda value: (abs(value - minimum_area), value),
        )
        area_fallback = abs(resolved_area - minimum_area) > 0.01
        effective_area = f"{resolved_area:g}"
        try:
            resolved_candidate = budget_candidates.apartment_candidate_result(
                **{
                    **common_candidate_arguments,
                    "area": effective_area,
                    "min_area": 0,
                }
            )
            if resolved_candidate:
                common_candidate = resolved_candidate
        except Exception:
            pass

    transaction_kind = molit_transactions.transaction_kind_for_apartment(name, region)
    if transaction_kind == molit_transactions.TRANSACTION_KIND_PRESALE:
        estimate_payload, estimate_status = {"error": "분양권·입주권 전용 실거래 조회"}, 404
    else:
        estimate_payload, estimate_status = rone_estimates.estimate(
            name,
            region,
            area=effective_area,
            months=months,
            include_details=True,
        )
    estimate = estimate_payload.get("estimate") if isinstance(estimate_payload, dict) else None
    if estimate_status != 200 or not isinstance(estimate, dict):
        fallback_payload = _molit_affordability_estimate(
            name,
            region,
            effective_area,
            months,
        )
        if fallback_payload:
            estimate_payload = fallback_payload
            estimate = fallback_payload["estimate"]
        elif common_candidate and (
            common_candidate.get("estimatedMinPriceEok")
            or common_candidate.get("currentEstimateMinPriceEok")
            or common_candidate.get("minPriceEok")
        ):
            estimate_payload = {
                "estimate": {},
                "latestTrade": {},
                "adjustedTransactions": [],
                "index": {},
            }
            estimate = estimate_payload["estimate"]
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
                or f"전용 {effective_area}㎡ 거래 기준"
            )
            if effective_area
            else "단지 전체 평형 거래 기준"
        ),
        "selectedArea": effective_area,
        "resolvedArea": effective_area,
        "areaFallback": area_fallback,
        "requestedMinArea": minimum_area or None,
        "transactionKind": (
            estimate_payload.get("transactionKind")
            or estimate.get("transactionKind")
            or transaction_kind
        ),
        "profileComplete": False,
    }

    if common_candidate:
        canonical_min = (
            common_candidate.get("estimatedMinPriceEok")
            or common_candidate.get("currentEstimateMinPriceEok")
            or common_candidate.get("recentMinPriceEok")
            or common_candidate.get("minPriceEok")
        )
        canonical_mid = (
            common_candidate.get("estimatedMidPriceEok")
            or common_candidate.get("currentEstimateMidPriceEok")
            or common_candidate.get("recentMedianPriceEok")
            or common_candidate.get("midPriceEok")
        )
        canonical_max = (
            common_candidate.get("estimatedMaxPriceEok")
            or common_candidate.get("currentEstimateMaxPriceEok")
            or common_candidate.get("recentMaxPriceEok")
            or common_candidate.get("maxPriceEok")
        )
        if canonical_min and canonical_mid and canonical_max:
            response["estimate"].update({
                "minPriceEok": canonical_min,
                "midPriceEok": canonical_mid,
                "maxPriceEok": canonical_max,
                "confidence": (
                    common_candidate.get("estimatedPriceConfidence")
                    or common_candidate.get("dataConfidence")
                    or response["estimate"].get("confidence")
                ),
                "sampleCount": (
                    common_candidate.get("currentEstimateSampleCount")
                    or common_candidate.get("transactionCount")
                    or 0
                ),
                "latestTradeDate": common_candidate.get("latestDealDate") or "",
                "latestTradeAgeDays": budget_candidates._deal_age_days(
                    common_candidate.get("latestDealDate")
                ),
                "method": (
                    common_candidate.get("currentEstimateMethod")
                    or "공통 후보 파이프라인 최근 실거래 가격대"
                ),
                "source": common_candidate.get("priceSource") or "molit",
            })
        if common_candidate.get("latestDealPriceEok"):
            response["latestTrade"] = {
                "dealDate": common_candidate.get("latestDealDate") or "",
                "dealAmountEok": common_candidate.get("latestDealPriceEok"),
                "exclusiveArea": common_candidate.get("latestDealExclusiveArea"),
                "floor": common_candidate.get("latestDealFloor") or "",
            }
        response["candidate"] = common_candidate
        response["candidateResultSchemaVersion"] = (
            common_candidate.get("resultSchemaVersion")
            or budget_candidates.CANDIDATE_RESULT_SCHEMA_VERSION
        )
        response["areaBasis"] = (
            f"{common_candidate.get('displayAreaLabel')} 최근 거래 기준"
            if common_candidate.get("displayAreaLabel")
            else response["areaBasis"]
        )

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

    if common_candidate:
        profile = budget_candidates._candidate_policy_context(
            arguments.get("budget") or 0.01,
            arguments.get("search_region") or region,
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
        )["profile"]
        response["profileComplete"] = True
        response["profile"] = {
            "cashEok": profile["cashEok"],
            "homeOwnershipLabel": profile["homeOwnershipLabel"],
            "combinedIncomeManwon": profile["combinedIncomeManwon"],
        }
        response["policyImpact"] = common_candidate.get("policyImpact")
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


def _listing_review(arguments):
    """같은 단지 가격 파이프라인으로 특정 매물 검토 리포트를 만든다."""
    affordability, status = _apartment_affordability({
        **arguments,
        "area": arguments.get("area") or "",
        "months": arguments.get("months") or 24,
    })
    if status >= 400:
        return affordability, status
    if affordability.get("state") != "ready":
        return {
            "error": affordability.get("error")
            or "현재 매물가격을 비교할 실거래 자료가 부족해요.",
        }, 422
    try:
        review = listing_review.build_review(arguments, affordability)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    payload = {"review": review}
    owner_token = str(arguments.get("owner_token") or "").strip()
    if owner_token:
        try:
            payload["saved"] = report_store.save(review, owner_token)
        except ValueError as exc:
            return {"error": str(exc)}, 400
    return payload, 200


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
            # 보강 스레드는 계속 돌고 있으므로 소프트 타임아웃에는 작업을
            # 끝내지 않고 '오래 걸리는 중' 신호만 보낸다. 콜드 캐시 지역에서
            # 가격 없는 1차 결과가 최종으로 굳는 문제를 막는다.
            if elapsed >= BUDGET_JOB_HARD_TIMEOUT_SECONDS:
                payload = json.loads(json.dumps(job.get("initial") or {}, ensure_ascii=False))
                payload.update({
                    "done": True,
                    "enrichmentPending": False,
                    "enrichmentStage": "timeout",
                    "error": "최신 실거래 확인이 오래 걸려 현재 확보한 결과만 표시합니다. 잠시 후 다시 검색하면 이어서 확인돼요.",
                })
                job["done"] = True
                job["result"] = payload
                job["finishedAt"] = time.time()
                return payload
            return {
                "done": False,
                "enrichmentPending": True,
                "enrichmentStage": (
                    "live_data_slow"
                    if elapsed >= BUDGET_JOB_TIMEOUT_SECONDS
                    else "live_data"
                ),
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
    _attach_market_snapshots(initial)
    _refresh_snapshot_policy_impacts(initial, candidate_arguments)
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
        # 색인은 '성남분당구'처럼 구 단위 표기라 '성남시' 같은 시 단위 설정은
        # 접두어('성남')로도 매칭한다.
        prefix_keys = {
            key[:-1]
            for key in region_keys
            if key.endswith("시") and len(key) >= 3
        }

        def _region_matches(value):
            key = real_estate_search.compact(value)
            if not key:
                return False
            if key in region_keys:
                return True
            return any(key.startswith(prefix) for prefix in prefix_keys)

        lawd_codes = {
            molit_transactions._row_lawd_cd(row)
            for row in source_rows
            if any(
                _region_matches(value)
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
        report_share_match = re.fullmatch(
            r"/api/reports/([a-f0-9-]{16,64})/share",
            parsed.path,
        )
        if parsed.path not in {
            "/api/apartment-affordability",
            "/api/apartment-catalysts",
            "/api/listing-review",
            "/api/admin/apartment-leaders/recalculate",
        } and not report_share_match:
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
        if report_share_match:
            try:
                saved = report_store.create_share(
                    report_share_match.group(1),
                    arguments.get("owner_token"),
                )
            except PermissionError as exc:
                self._json({"error": str(exc)}, 403)
                return
            if not saved:
                self._json({"error": "저장된 리포트를 찾지 못했어요."}, 404)
                return
            self._json({"saved": saved})
            return
        if parsed.path == "/api/admin/apartment-leaders/recalculate":
            configured_token = os.environ.get("APARTMENT_LEADER_ADMIN_TOKEN", "").strip()
            supplied_token = (
                self.headers.get("X-Admin-Token", "").strip()
                or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            )
            local_only = HOST in {"127.0.0.1", "localhost", "::1"}
            if not configured_token and not local_only:
                self._json({"error": "운영 환경의 재계산 인증 토큰이 설정되지 않았어요."}, 503)
                return
            if configured_token and not hmac.compare_digest(configured_token, supplied_token):
                self._json({"error": "재계산 권한을 확인해 주세요."}, 401)
                return
            sido = str(arguments.get("sido") or "").strip()
            sigungu = str(arguments.get("sigungu") or "").strip()
            if not sido or not sigungu:
                self._json({"error": "시·도와 시·군·구를 입력해 주세요."}, 400)
                return
            try:
                payload = apartment_leaders.get_leaders(
                    sido,
                    sigungu,
                    area_bucket_value=str(
                        arguments.get("areaBucket")
                        or apartment_leaders.DEFAULT_AREA_BUCKET
                    ),
                    reference_month=str(arguments.get("referenceMonth") or ""),
                    category=str(arguments.get("category") or "overall"),
                    limit=arguments.get("limit") or 5,
                    force=True,
                    cache_only=bool(arguments.get("dryRun")),
                )
            except (TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception:
                self._json({"error": "대장 순위를 다시 계산하지 못했어요."}, 502)
                return
            self._json(payload)
            return
        if parsed.path == "/api/apartment-catalysts":
            apartments = arguments.get("apartments")
            if not isinstance(apartments, list):
                self._json({"error": "단지 목록을 확인해 주세요."}, 400)
                return
            self._json(news_catalysts.catalysts_for_apartments(apartments))
            return
        if parsed.path == "/api/listing-review":
            allowed, access_payload = paid_access.authorize(
                self.headers.get("X-Report-Access-Token", ""),
            )
            if not allowed:
                self._json(access_payload, 402)
                return
            payload, status = _listing_review(arguments)
            self._json(payload, status)
            return
        payload, status = _apartment_affordability(arguments)
        self._json(payload, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        report_match = re.fullmatch(r"/api/reports/([a-f0-9-]{16,64})", parsed.path)
        if report_match:
            try:
                report = report_store.get(
                    report_match.group(1),
                    owner_token=(
                        self.headers.get("X-Report-Owner-Token", "").strip()
                        or params.get("owner_token", [""])[0].strip()
                    ),
                    share_token=params.get("token", [""])[0].strip(),
                )
            except PermissionError as exc:
                self._json({"error": str(exc)}, 403)
                return
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            if not report:
                self._json({"error": "저장된 리포트를 찾지 못했어요."}, 404)
                return
            self._json({"review": report})
            return
        if parsed.path == "/api/reports":
            owner_token = (
                self.headers.get("X-Report-Owner-Token", "").strip()
                or params.get("owner_token", [""])[0].strip()
            )
            self._json({"reports": report_store.list_owned(owner_token)})
            return
        if parsed.path == "/api/paid-access/status":
            self._json(paid_access.status())
            return
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
                "newsCatalystConfigured": news_catalysts.configured(),
                "budgetPrewarm": dict(BUDGET_PREWARM_STATE),
            })
            return
        if parsed.path == "/api/apartment-leader-regions":
            self._json({
                "regions": apartment_leaders.leader_regions(),
                "areaBuckets": [
                    {"id": key, "label": value["label"]}
                    for key, value in apartment_leaders.AREA_BUCKETS.items()
                ],
                "defaultAreaBucket": apartment_leaders.DEFAULT_AREA_BUCKET,
                "calculationVersion": apartment_leaders.CALCULATION_VERSION,
            })
            return
        if parsed.path == "/api/apartment-leaders":
            sido = params.get("sido", [""])[0].strip()
            sigungu = params.get("sigungu", [""])[0].strip()
            area_bucket = (
                params.get("areaBucket", params.get("area_bucket", [apartment_leaders.DEFAULT_AREA_BUCKET]))[0].strip()
            )
            reference_month = params.get("referenceMonth", params.get("reference_month", [""]))[0].strip()
            category = params.get("category", ["overall"])[0].strip()
            try:
                limit = int(params.get("limit", ["5"])[0])
            except ValueError:
                limit = 5
            if not sido or not sigungu:
                self._json({"error": "시·도와 시·군·구를 선택해 주세요."}, 400)
                return
            try:
                payload = apartment_leaders.get_leaders(
                    sido,
                    sigungu,
                    area_bucket_value=area_bucket,
                    reference_month=reference_month,
                    category=category,
                    limit=limit,
                )
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception:
                self._json({"error": "지역 대장 순위를 불러오지 못했어요."}, 502)
                return
            self._json(payload)
            return
        detail_match = re.fullmatch(r"/api/apartments/([^/]+)/leader-score", parsed.path)
        if detail_match:
            sido = params.get("sido", [""])[0].strip()
            sigungu = params.get("sigungu", [""])[0].strip()
            area_bucket = params.get("areaBucket", [apartment_leaders.DEFAULT_AREA_BUCKET])[0].strip()
            reference_month = params.get("referenceMonth", [""])[0].strip()
            if not sido or not sigungu:
                self._json({"error": "시·도와 시·군·구를 선택해 주세요."}, 400)
                return
            try:
                payload = apartment_leaders.apartment_detail(
                    unquote(detail_match.group(1)),
                    sido,
                    sigungu,
                    area_bucket,
                    reference_month=reference_month,
                )
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception:
                self._json({"error": "단지 대장지수 상세를 불러오지 못했어요."}, 502)
                return
            if not payload:
                self._json({"error": "해당 단지의 대장지수 결과가 없어요."}, 404)
                return
            self._json(payload)
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
    # 검색 요청이 들어온 뒤 수백 개 결과 캐시를 다시 읽지 않도록 서버가
    # 준비되는 동안 단지별 시장 스냅샷 인덱스를 먼저 만든다.
    _load_market_snapshots()
    print(f"부동산 유튜브 요약 서버: http://{HOST}:{PORT}")
    if not config.ready_channels():
        print("채널 ID가 아직 없어 검색어 기반 YouTube 보강으로 동작합니다.")
    if config.BUDGET_PREWARM_ENABLED:
        threading.Thread(target=_prewarm_budget_transaction_cache, daemon=True).start()
    SearchServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
