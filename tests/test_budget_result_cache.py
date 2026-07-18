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

        def repair(rows):
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

        def repair(rows):
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
