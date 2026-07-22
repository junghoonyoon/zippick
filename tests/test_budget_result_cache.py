import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import search_server  # noqa: E402


class BudgetResultCacheTest(unittest.TestCase):
    def test_heavy_rate_limit_blocks_repeated_public_requests(self):
        with mock.patch.object(search_server.config, "PUBLIC_RATE_LIMIT_WINDOW_SECONDS", 60), \
             mock.patch.object(search_server.config, "PUBLIC_HEAVY_RATE_LIMIT", 2):
            search_server.RATE_LIMIT_BUCKETS.clear()
            first = search_server._rate_limit_check(
                "203.0.113.10",
                "/api/budget-candidates",
                now=1000,
            )
            second = search_server._rate_limit_check(
                "203.0.113.10",
                "/api/budget-candidates",
                now=1001,
            )
            third = search_server._rate_limit_check(
                "203.0.113.10",
                "/api/budget-candidates",
                now=1002,
            )

        self.assertEqual(first, (True, None))
        self.assertEqual(second, (True, None))
        self.assertEqual(third[0], False)
        self.assertGreaterEqual(third[1], 1)

    def test_rate_limit_does_not_apply_to_light_status_request(self):
        with mock.patch.object(search_server.config, "PUBLIC_HEAVY_RATE_LIMIT", 1):
            search_server.RATE_LIMIT_BUCKETS.clear()
            self.assertEqual(
                search_server._rate_limit_check("203.0.113.20", "/api/status", now=1000),
                (True, None),
            )
            self.assertEqual(
                search_server._rate_limit_check("203.0.113.20", "/api/status", now=1001),
                (True, None),
            )

    def test_admin_token_accepts_current_and_legacy_setting(self):
        with mock.patch.object(search_server.config, "ADMIN_API_TOKEN", "secret-token"):
            self.assertTrue(search_server._admin_token_configured())
            self.assertTrue(search_server._admin_token_authorized("secret-token"))
            self.assertFalse(search_server._admin_token_authorized("wrong-token"))

    def test_staged_result_returns_fast_payload_then_completed_enrichment(self):
        def calculate(**arguments):
            if arguments.get("fast_mode"):
                return {"candidates": [{"name": "1차 후보"}], "initialStage": True}
            return {
                "candidates": [{"name": "보강 후보", "signals": {"status": "ok", "score": 60}}],
                "initialStage": False,
            }

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "BUDGET_JOBS", {}), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.budget_candidates, "budget_candidates", side_effect=calculate):
            initial = search_server._start_staged_budget_payload("staged", {"budget": "7.9"})
            self.assertTrue(initial["enrichmentPending"])
            self.assertEqual(initial["candidates"][0]["name"], "1차 후보")

            deadline = time.time() + 2
            completed = None
            while time.time() < deadline:
                completed = search_server._budget_job_snapshot(initial["enrichmentJobId"])
                if completed and completed.get("done"):
                    break
                time.sleep(0.01)

        self.assertTrue(completed["done"])
        self.assertFalse(completed["enrichmentPending"])
        self.assertEqual(completed["candidates"][0]["name"], "보강 후보")

    def test_critical_result_completes_before_optional_naver_links(self):
        link_started = threading.Event()
        release_links = threading.Event()

        def calculate(**arguments):
            if arguments.get("fast_mode"):
                return {"candidates": [{"name": "1차 후보"}]}
            return {
                "candidates": [{
                    "name": "확정 후보",
                    "naverPropertyQuery": "확정 후보",
                    "signals": {"status": "ok", "score": 70},
                }],
            }

        def attach_links(rows, update_display_name=True):
            self.assertFalse(update_display_name)
            link_started.set()
            release_links.wait(2)
            rows[0].update({
                "naverComplexNo": "12345",
                "naverPropertyUrl": "https://fin.land.naver.com/complexes/12345?tab=article",
                "naverLinkKind": "complex",
            })

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "BUDGET_JOBS", {}), \
             mock.patch.object(search_server, "BUDGET_OPTIONAL_LINK_KEYS", set()), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.budget_candidates, "budget_candidates", side_effect=calculate), \
             mock.patch.object(search_server.naver_complex, "attach_links", side_effect=attach_links):
            initial = search_server._start_staged_budget_payload(
                "optional-links",
                {"budget": "7.9"},
            )
            deadline = time.time() + 2
            completed = None
            while time.time() < deadline:
                completed = search_server._budget_job_snapshot(
                    initial["enrichmentJobId"],
                )
                if completed and completed.get("done"):
                    break
                time.sleep(0.01)

            self.assertTrue(completed["done"])
            self.assertFalse(completed["enrichmentPending"])
            self.assertTrue(completed["optionalEnrichmentPending"])
            self.assertTrue(link_started.wait(0.5))
            self.assertNotIn("naverComplexNo", completed["candidates"][0])

            release_links.set()
            optional = None
            deadline = time.time() + 2
            while time.time() < deadline:
                cached = search_server._read_budget_cache("optional-links")
                optional = cached[0] if cached else None
                if optional and not optional.get("optionalEnrichmentPending"):
                    break
                time.sleep(0.01)

        self.assertEqual(optional["optionalEnrichmentStage"], "complete")
        self.assertEqual(optional["candidates"][0]["naverComplexNo"], "12345")
        snapshot = search_server._budget_optional_link_snapshot("optional-links")
        self.assertIsNone(snapshot)  # 공개 조회 키는 64자리 캐시 키만 허용한다.

    def test_optional_link_snapshot_returns_only_non_ranking_fields(self):
        cache_key = "a" * 64
        payload = {
            "optionalEnrichmentPending": False,
            "optionalEnrichmentStage": "complete",
            "candidates": [{
                "name": "확정 후보",
                "region": "성동구",
                "areaLabel": "전용 84㎡",
                "score": 91,
                "naverComplexNo": "12345",
                "naverComplexName": "확정 후보 아파트",
                "naverPropertyUrl": "https://fin.land.naver.com/complexes/12345?tab=article",
                "naverLinkKind": "complex",
            }],
        }
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)):
            search_server._write_budget_cache(cache_key, payload)
            snapshot = search_server._budget_optional_link_snapshot(cache_key)

        self.assertTrue(snapshot["done"])
        self.assertEqual(snapshot["links"][0]["naverComplexNo"], "12345")
        self.assertNotIn("score", snapshot["links"][0])

    def test_optional_link_failure_finishes_without_blocking_result(self):
        cache_key = "b" * 64
        optional_keys = {cache_key}
        payload = {
            "optionalEnrichmentPending": True,
            "optionalEnrichmentStage": "naver_links",
            "candidates": [{
                "name": "확정 후보",
                "naverPropertyQuery": "확정 후보",
                "signals": {"status": "ok", "score": 70},
            }],
        }
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "BUDGET_OPTIONAL_LINK_KEYS", optional_keys), \
             mock.patch.object(search_server.naver_complex, "attach_links", side_effect=RuntimeError("down")):
            search_server._run_budget_optional_links(cache_key, payload)
            cached = search_server._read_budget_cache(cache_key)[0]

        self.assertFalse(cached["optionalEnrichmentPending"])
        self.assertEqual(cached["optionalEnrichmentStage"], "error")
        self.assertEqual(cached["candidates"][0]["signals"]["score"], 70)
        self.assertNotIn(cache_key, optional_keys)

    def test_staged_result_skips_enrichment_without_molit_configuration(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "BUDGET_JOBS", {}), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=False), \
             mock.patch.object(
                 search_server.budget_candidates,
                 "budget_candidates",
                 return_value={"candidates": [{"name": "1차 후보"}], "initialStage": True},
             ) as calculate:
            payload = search_server._start_staged_budget_payload("staged", {"budget": "7.9"})

        self.assertFalse(payload["enrichmentPending"])
        self.assertEqual(payload["enrichmentStage"], "complete")
        self.assertNotIn("enrichmentJobId", payload)
        self.assertEqual(payload["candidates"][0]["name"], "1차 후보")
        self.assertEqual(payload["candidates"][0]["signals"]["status"], "unavailable")
        calculate.assert_called_once_with(budget="7.9", fast_mode=True)

    def test_staged_job_soft_timeout_keeps_enrichment_running(self):
        job_id = "stuck-job"
        initial = {"candidates": [{"name": "1차 후보"}], "initialStage": True}
        with mock.patch.object(search_server, "BUDGET_JOBS", {
            job_id: {
                "cacheKey": "stuck",
                "startedAt": time.time() - 10,
                "done": False,
                "initial": initial,
                "result": None,
            },
        }), mock.patch.object(search_server, "BUDGET_JOB_TIMEOUT_SECONDS", 1), \
             mock.patch.object(search_server, "BUDGET_JOB_HARD_TIMEOUT_SECONDS", 30):
            payload = search_server._budget_job_snapshot(job_id)

        self.assertFalse(payload["done"])
        self.assertTrue(payload["enrichmentPending"])
        self.assertEqual(payload["enrichmentStage"], "live_data_slow")

    def test_staged_job_hard_timeout_returns_initial_payload(self):
        job_id = "stuck-job"
        initial = {"candidates": [{"name": "1차 후보"}], "initialStage": True}
        with mock.patch.object(search_server, "BUDGET_JOBS", {
            job_id: {
                "cacheKey": "stuck",
                "startedAt": time.time() - 10,
                "done": False,
                "initial": initial,
                "result": None,
            },
        }), mock.patch.object(search_server, "BUDGET_JOB_TIMEOUT_SECONDS", 1), \
             mock.patch.object(search_server, "BUDGET_JOB_HARD_TIMEOUT_SECONDS", 5):
            payload = search_server._budget_job_snapshot(job_id)

        self.assertTrue(payload["done"])
        self.assertFalse(payload["enrichmentPending"])
        self.assertEqual(payload["enrichmentStage"], "timeout")
        self.assertEqual(payload["candidates"][0]["name"], "1차 후보")

    def test_budget_prewarm_only_schedules_configured_regions(self):
        rows = [
            {"시도": "서울특별시", "필지고유번호": "1111010100100010000"},
            {"시도": "경기도", "필지고유번호": "4113510100100010000"},
        ]
        with mock.patch.object(search_server.config, "BUDGET_PREWARM_ENABLED", True), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_DELAY_SECONDS", 0), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_MONTHS", 2), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_MAX_WORKERS", 2), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_REGIONS", ("서울특별시",)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.molit_transactions, "_source_row_index", return_value=(rows, {})), \
             mock.patch.object(search_server.molit_transactions, "prefetch_months", return_value=2) as prefetch:
            search_server._prewarm_budget_transaction_cache()

        pairs = set(prefetch.call_args.args[0])
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(code == "11110" for code, _month in pairs))

    def test_budget_prewarm_city_setting_matches_district_index_names(self):
        rows = [
            {
                "시도": "경기도",
                "자치구": "성남분당구",
                "필지고유번호": "4113510100100010000",
            },
            {
                "시도": "경기도",
                "자치구": "수원영통구",
                "필지고유번호": "4111710100100010000",
            },
        ]
        with mock.patch.object(search_server.config, "BUDGET_PREWARM_ENABLED", True), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_DELAY_SECONDS", 0), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_MONTHS", 2), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_MAX_WORKERS", 2), \
             mock.patch.object(search_server.config, "BUDGET_PREWARM_REGIONS", ("성남시",)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.molit_transactions, "_source_row_index", return_value=(rows, {})), \
             mock.patch.object(search_server.molit_transactions, "prefetch_months", return_value=2) as prefetch:
            search_server._prewarm_budget_transaction_cache()

        pairs = set(prefetch.call_args.args[0])
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(code == "41135" for code, _month in pairs))

    def test_key_is_stable_and_changes_with_search_conditions(self):
        first = search_server._budget_cache_key({"region": "성남시", "min_area": "59"})
        reordered = search_server._budget_cache_key({"min_area": "59", "region": "성남시"})
        changed = search_server._budget_cache_key({"region": "성남시", "min_area": "84"})

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_market_snapshot_fills_first_stage_without_live_lookup(self):
        saved_at = time.time()
        cached = {
            "savedAt": saved_at,
            "payload": {
                "candidates": [{
                    "name": "즉시단지",
                    "region": "강동구",
                    "legalDong": "천호동",
                    "jibun": "1",
                    "areaLabel": "전용 59㎡",
                    "resultSchemaVersion": search_server.budget_candidates.CANDIDATE_RESULT_SCHEMA_VERSION,
                    "priceIdentityVerified": True,
                    "latestDealPriceEok": 8.1,
                    "latestDealDate": "2026-07-01",
                    "transactionCount": 12,
                    "signals": {
                        "status": "ok",
                        "score": 72,
                        "scoreFormulaVersion": (
                            search_server.momentum_signals.SCORE_FORMULA_VERSION
                        ),
                    },
                }],
            },
        }
        initial = {
            "candidates": [{
                "name": "즉시단지",
                "region": "강동구",
                "legalDong": "천호동",
                "jibun": "1",
                "areaLabel": "전용 60~60㎡",
                "latestDealPriceEok": None,
                "signals": None,
            }],
        }

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(
                 search_server.momentum_signals,
                 "attach_cached_signals",
             ) as attach_cached:
            (Path(directory) / "completed.json").write_text(
                json.dumps(cached, ensure_ascii=False),
                encoding="utf-8",
            )
            search_server._attach_market_snapshots(initial)

        row = initial["candidates"][0]
        self.assertTrue(initial["marketSnapshotReady"])
        self.assertEqual(initial["marketSnapshotHitCount"], 1)
        self.assertEqual(row["latestDealPriceEok"], 8.1)
        self.assertEqual(row["latestDealDate"], "2026-07-01")
        self.assertEqual(row["signals"]["score"], 72)
        self.assertTrue(row["marketSnapshotHit"])
        attach_cached.assert_called_once_with(initial["candidates"], only_missing=True)

    def test_condition_change_recalculates_cash_scenarios_after_market_snapshot(self):
        cached = {
            "savedAt": time.time(),
            "payload": {
                "candidates": [{
                    "name": "백련산힐스테이트2차",
                    "region": "은평구",
                    "legalDong": "불광동",
                    "jibun": "1",
                    "areaLabel": "전용 59㎡",
                    "resultSchemaVersion": search_server.budget_candidates.CANDIDATE_RESULT_SCHEMA_VERSION,
                    "priceIdentityVerified": True,
                    "latestDealPriceEok": 8.4,
                    "latestDealDate": "2026-06-30",
                    "recent3AveragePriceEok": 8.3,
                    "recent3AdjustedAveragePriceEok": 8.3,
                    "recent3TradeCount": 10,
                    "recent3AdjustedTradeCount": 10,
                    "transactionCount": 10,
                }],
            },
        }
        profile = search_server.policy_evaluator.user_profile(cash_eok=5)
        stale_impact = search_server.policy_evaluator.evaluate_candidate(
            {
                "name": "백련산힐스테이트2차",
                "region": "은평구",
                "midPriceEok": 8.3,
            },
            profile=profile,
        )
        initial = {
            "candidates": [{
                "name": "백련산힐스테이트2차",
                "region": "은평구",
                "legalDong": "불광동",
                "jibun": "1",
                "areaLabel": "전용 59㎡",
                "midPriceEok": 8.3,
                "policyImpact": stale_impact,
            }],
            "policyExcludedCandidates": [],
            "allMatches": True,
            "initialStage": True,
            "policySnapshot": {
                **search_server.policy_evaluator.summarize([stale_impact], profile),
                "estimatedPurchaseCeilingEok": 9.4,
                "budgetSource": "region_adjusted",
            },
        }
        self.assertEqual(stale_impact["cashScenarios"], [])

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "BUDGET_JOBS", {}), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=False), \
             mock.patch.object(search_server, "_attach_cached_market_bands"), \
             mock.patch.object(
                 search_server.momentum_signals,
                 "attach_cached_signals",
             ), mock.patch.object(
                 search_server.budget_candidates,
                 "budget_candidates",
                 return_value=initial,
             ):
            (Path(directory) / "previous-condition.json").write_text(
                json.dumps(cached, ensure_ascii=False),
                encoding="utf-8",
            )
            payload = search_server._start_staged_budget_payload(
                "changed-condition",
                {
                    "budget": "9.4",
                    "cash_eok": "5",
                    "all_matches": True,
                },
            )

        row = payload["candidates"][0]
        scenarios = {
            scenario["type"]: scenario
            for scenario in row["policyImpact"]["cashScenarios"]
        }
        self.assertEqual(set(scenarios), {"latest_deal", "recent3_average"})
        self.assertEqual(scenarios["latest_deal"]["requiredCashEok"], 5.04)
        self.assertEqual(scenarios["recent3_average"]["requiredCashEok"], 4.98)
        self.assertEqual(row["policyImpact"]["status"], "short")
        self.assertEqual(payload["policySnapshot"]["counts"]["short"], 1)
        self.assertEqual(payload["policySnapshot"]["estimatedPurchaseCeilingEok"], 9.4)
        self.assertEqual(payload["policySnapshot"]["budgetSource"], "region_adjusted")

    def test_market_snapshot_does_not_reuse_signal_from_another_area(self):
        cached = {
            "savedAt": time.time(),
            "payload": {
                "candidates": [{
                    "name": "평형분리단지",
                    "region": "강동구",
                    "legalDong": "길동",
                    "jibun": "1",
                    "areaLabel": "전용 59㎡",
                    "signals": {
                        "status": "ok",
                        "score": 72,
                        "scoreFormulaVersion": (
                            search_server.momentum_signals.SCORE_FORMULA_VERSION
                        ),
                    },
                }],
            },
        }
        initial = {
            "candidates": [{
                "name": "평형분리단지",
                "region": "강동구",
                "legalDong": "길동",
                "jibun": "1",
                "areaLabel": "전용 84~85㎡",
                "signals": None,
            }],
        }

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server, "_attach_cached_market_bands"), \
             mock.patch.object(
                 search_server.momentum_signals,
                 "attach_cached_signals",
             ) as attach_cached:
            (Path(directory) / "completed.json").write_text(
                json.dumps(cached, ensure_ascii=False),
                encoding="utf-8",
            )
            search_server._attach_market_snapshots(initial)

        self.assertIsNone(initial["candidates"][0]["signals"])
        attach_cached.assert_called_once_with(initial["candidates"], only_missing=True)

    def test_incomplete_price_row_is_not_indexed_as_ready_market_snapshot(self):
        payload = {
            "candidates": [{
                "name": "미완성단지",
                "region": "강동구",
                "areaLabel": "전용 84~85㎡",
                "midPriceEok": 0,
            }],
        }

        search_server.MARKET_ROW_SNAPSHOTS.clear()
        search_server.MARKET_ROW_SNAPSHOT_KEYS.clear()
        search_server._index_market_snapshot_payload(payload, time.time())

        self.assertEqual(search_server.MARKET_ROW_SNAPSHOTS, {})
        self.assertEqual(search_server.MARKET_ROW_SNAPSHOT_KEYS, {})

    def test_complete_no_trade_state_is_indexed_without_becoming_pending(self):
        payload = {
            "candidates": [{
                "name": "무거래단지",
                "region": "강동구",
                "legalDong": "상일동",
                "jibun": "1",
                "areaLabel": "전용 84~85㎡",
                "midPriceEok": 0,
                "marketDataStatus": "no_recent_trade",
                "resultSchemaVersion": search_server.budget_candidates.CANDIDATE_RESULT_SCHEMA_VERSION,
                "priceIdentityVerified": True,
            }],
        }

        search_server.MARKET_ROW_SNAPSHOTS.clear()
        search_server.MARKET_ROW_SNAPSHOT_KEYS.clear()
        search_server._index_market_snapshot_payload(payload, time.time())

        snapshot = next(iter(search_server.MARKET_ROW_SNAPSHOTS.values()))[1]
        self.assertEqual(snapshot["marketDataStatus"], "no_recent_trade")

    def test_local_month_cache_fills_filtered_search_price_before_reveal(self):
        row = {
            "name": "재검색단지",
            "region": "강동구",
            "legalDong": "성내동",
            "jibun": "1",
            "areaLabel": "전용 84~85㎡",
            "areaMin": 84,
            "midPriceEok": 0,
        }
        live = {
            "areaLabel": "전용 84㎡",
            "minPriceEok": 7.8,
            "midPriceEok": 8.0,
            "averagePriceEok": 8.1,
            "maxPriceEok": 8.4,
            "latestDealPriceEok": 8.2,
            "latestDealDate": "2026-07-01",
            "transactionCount": 5,
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value={},
        ), mock.patch.object(
            search_server.molit_transactions,
            "cached_market_bundle_for_apartment",
            return_value={
                "band": live,
                "comparison": live,
                "coverage": {"complete": True},
                "transactions": [],
            },
        ):
            search_server._attach_cached_market_bands([row])

        self.assertEqual(row["latestDealPriceEok"], 8.2)
        self.assertEqual(row["midPriceEok"], 8.0)
        self.assertEqual(row["marketDataStatus"], "ready")
        self.assertTrue(row["marketLocalCacheHit"])

    def test_local_month_cache_fills_last_observed_selected_area_trade(self):
        row = {
            "name": "과거거래단지",
            "region": "강동구",
            "legalDong": "둥촌동",
            "jibun": "1",
            "areaLabel": "전용 84~85㎡",
            "areaMin": 84,
            "midPriceEok": 0,
        }
        last_observed = {
            "lastObservedDealPriceEok": 15.0,
            "lastObservedDealExclusiveArea": 84.8,
            "lastObservedDealFloor": "17",
            "lastObservedDealDate": "2025-09-25",
            "lastObservedDealNote": "국토부 실거래가 최근 36개월 확장 조회",
        }

        with mock.patch.object(
            search_server.budget_candidates,
            "_find_entity",
            return_value={},
        ), mock.patch.object(
            search_server.molit_transactions,
            "cached_market_bundle_for_apartment",
            return_value={
                "band": None,
                "comparison": None,
                "coverage": {"complete": True},
                "transactions": [],
                "lastObserved": last_observed,
            },
        ):
            search_server._attach_cached_market_bands([row])

        self.assertEqual(row["lastObservedDealPriceEok"], 15.0)
        self.assertEqual(row["lastObservedDealDate"], "2025-09-25")
        self.assertEqual(row["marketDataStatus"], "no_recent_trade")

    def test_result_is_persisted_and_expired_by_ttl(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.config, "BUDGET_RESULT_CACHE_TTL_SECONDS", 10):
            saved_at = search_server._write_budget_cache(
                "same-search",
                {"candidates": [{"name": "테스트", "signals": {"status": "ok", "score": 50}}]},
            )
            cached = search_server._read_budget_cache("same-search")
            self.assertEqual(cached[0]["candidates"][0]["name"], "테스트")
            self.assertEqual(cached[1], saved_at)

            path = Path(directory) / "same-search.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["savedAt"] = time.time() - 11
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(search_server._read_budget_cache("same-search"))
            self.assertFalse(path.exists())

    def test_error_result_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)):
            saved_at = search_server._write_budget_cache("failed", {"livePriceError": "API 오류"})
            self.assertEqual(saved_at, 0)
            self.assertIsNone(search_server._read_budget_cache("failed"))

    def test_complete_fallback_result_is_cached_despite_transient_warning(self):
        payload = {
            "livePriceError": "일시 지연으로 저장 데이터 사용",
            "candidates": [{"name": "테스트", "signals": {"status": "ok", "score": 50}}],
        }
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True):
            saved_at = search_server._write_budget_cache("fallback", payload)
            self.assertGreater(saved_at, 0)
            self.assertIsNotNone(search_server._read_budget_cache("fallback"))

    def test_missing_signal_result_is_cached_and_repaired_on_hit(self):
        # API 지연으로 시그널이 비어도 결과는 캐시한다. 재검색 때 전체를
        # 다시 계산하지 않고 캐시 히트 경로에서 시그널만 보강한다.
        payload = {"candidates": [{"name": "테스트", "signals": None}]}

        def repair(rows, **_kwargs):
            for row in rows:
                signals = {
                    "status": "ok",
                    "momentumPct": 0.0,
                    "turnoverRatio": 1.0,
                    "districtRelativePct": 0.0,
                    "recent3Pct": 1.0,
                }
                details = search_server.momentum_signals._score_details(signals)
                signals.update({
                    "score": details["score"],
                    "scoreFormulaVersion": details["formulaVersion"],
                    "scoreBreakdown": details["breakdown"],
                    "scoreCaps": details["caps"],
                })
                row["signals"] = signals

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.momentum_signals, "attach_signals", side_effect=repair) as attach, \
             mock.patch.object(search_server.budget_candidates, "budget_candidates") as compute:
            saved_at = search_server._write_budget_cache("missing-signal", payload)
            self.assertGreater(saved_at, 0)
            self.assertIsNotNone(search_server._read_budget_cache("missing-signal"))

            result = search_server._load_budget_payload("missing-signal", {})
            self.assertTrue(result["cacheHit"])
            self.assertEqual(result["candidates"][0]["signals"]["status"], "ok")
            attach.assert_called_once()
            compute.assert_not_called()

            # 보강된 시그널이 캐시에도 반영되어 다음 히트에서는 보강이 필요 없다.
            repaired = search_server._read_budget_cache("missing-signal")
            self.assertEqual(repaired[0]["candidates"][0]["signals"]["status"], "ok")

    def test_outdated_signal_formula_is_repaired_on_cache_hit(self):
        payload = {
            "candidates": [{
                "name": "테스트",
                "signals": {"status": "ok", "score": 75, "scoreFormulaVersion": 1},
            }],
        }

        def repair(rows, **_kwargs):
            for row in rows:
                row["signals"] = {
                    "status": "ok",
                    "score": 44,
                    "scoreFormulaVersion": search_server.momentum_signals.SCORE_FORMULA_VERSION,
                    "scoreBreakdown": {"priceMomentum": {"points": 20, "maxPoints": 40}},
                }

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.momentum_signals, "attach_signals", side_effect=repair) as attach:
            search_server._write_budget_cache("old-formula", payload)
            result = search_server._load_budget_payload("old-formula", {})

        attach.assert_called_once()
        signals = result["candidates"][0]["signals"]
        self.assertEqual(signals["score"], 44)
        self.assertEqual(
            signals["scoreFormulaVersion"],
            search_server.momentum_signals.SCORE_FORMULA_VERSION,
        )
        self.assertIn("priceMomentum", signals["scoreBreakdown"])

    def test_error_signal_result_is_cached_without_recompute(self):
        payload = {"allCandidates": [{"name": "테스트", "signals": {"status": "error", "score": None}}]}
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True):
            saved_at = search_server._write_budget_cache("error-signal", payload)
            self.assertGreater(saved_at, 0)
            self.assertIsNotNone(search_server._read_budget_cache("error-signal"))

    def test_same_search_is_computed_once_for_concurrent_requests(self):
        started = threading.Barrier(2)

        def load():
            started.wait()
            return search_server._load_budget_payload("same", {"budget": "7.9"})

        def calculate(**_arguments):
            time.sleep(0.05)
            return {"candidates": [{"name": "테스트", "signals": {"status": "ok", "score": 50}}]}

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(search_server, "BUDGET_CACHE_DIR", Path(directory)), \
             mock.patch.object(search_server.molit_transactions, "configured", return_value=True), \
             mock.patch.object(search_server.budget_candidates, "budget_candidates", side_effect=calculate) as compute:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _index: load(), range(2)))

        self.assertEqual(compute.call_count, 1)
        self.assertEqual(sorted(result["cacheHit"] for result in results), [False, True])


if __name__ == "__main__":
    unittest.main()
