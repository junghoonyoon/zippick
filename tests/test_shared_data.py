import json
import datetime
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import shared_data
import kakao_station_distances
import education_environment
import molit_transactions


class SharedDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [mock.patch.dict(os.environ, {"ZIPPICK_DATA_MODE": "replica"}),
                        mock.patch.object(shared_data, "MIRROR_ROOT", self.root / "mirror"),
                        mock.patch.object(shared_data, "CONTROL_ROOT", self.root / "ssh"),
                        mock.patch.object(shared_data, "_LISTENERS", [])]
        for patch in self.patches:
            patch.start()
        self.facts = {
            "apartment_station_distances.json": {"version": 1, "records": {"station": {"status": "ok"}}},
            "education_environment_records.json": {"records": {"school": {"score": 90}}},
            "molit_transactions/11440_202610.json": {"items": [{"dealAmountEok": 17}], "fetchedAt": 1, "lawdCd": "11440", "dealYmd": "202610"},
        }

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def manifest(self, marker=1):
        return {name: [len(json.dumps(value).encode()), marker] for name, value in self.facts.items()}

    def copy(self, command, **kwargs):
        destination = Path(command[-1])
        for name in kwargs["input"].splitlines():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.facts[name]))
        return subprocess.CompletedProcess(command, 0)

    def sync(self, manifest=None):
        manifest = manifest or self.manifest()
        with mock.patch.object(shared_data, "_source_manifest", return_value=manifest), \
             mock.patch.object(shared_data.subprocess, "run", side_effect=self.copy):
            return shared_data.sync_once()

    def test_replica_publishes_one_complete_version_and_keeps_local_files_separate(self):
        local = self.root / "original-local.json"
        local.write_text('{"old": true}')
        listener = mock.Mock()
        shared_data.subscribe(listener)
        result = self.sync()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["fileCount"], 3)
        self.assertEqual(result["rawTransactionFiles"], 1)
        self.assertTrue(result["readOnly"])
        self.assertEqual(shared_data.revision(), shared_data._manifest_revision(self.manifest()))
        self.assertEqual(json.loads(shared_data.cache_path("molit_transactions/11440_202610.json").read_text())["items"][0]["dealAmountEok"], 17)
        self.assertEqual(local.read_text(), '{"old": true}')
        listener.assert_called_once()

    def test_unchanged_source_does_not_download_again(self):
        self.sync()
        with mock.patch.object(shared_data, "_source_manifest", return_value=self.manifest()), \
             mock.patch.object(shared_data.subprocess, "run") as transfer:
            result = shared_data.sync_once()
        self.assertEqual(result["status"], "ready")
        transfer.assert_not_called()

    def test_failed_connection_keeps_last_good_version_and_reports_stale(self):
        self.sync()
        original = shared_data.revision()
        with mock.patch.object(shared_data, "_source_manifest", side_effect=OSError("offline")):
            result = shared_data.sync_once()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(shared_data.revision(), original)
        self.assertTrue(result["error"])

    def test_ssh_timeout_has_a_public_reason_code_and_preserves_the_last_good_version(self):
        self.sync()
        original = shared_data.revision()
        error = subprocess.CalledProcessError(255, ['ssh', 'private-command'],
            stderr='Connection timed out during banner exchange\nprivate-diagnostic')
        with mock.patch.object(shared_data, '_source_manifest', side_effect=error):
            result = shared_data.sync_once()
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['errorReason'], 'ssh_timeout')
        self.assertEqual(result['errorStage'], 'source_manifest')
        self.assertEqual(shared_data.revision(), original)
        self.assertNotIn('private-diagnostic', json.dumps(result))
        recovered = self.sync()
        self.assertEqual(recovered['status'], 'ready')
        self.assertNotIn('errorReason', recovered)


    def test_first_connection_failure_is_not_reported_as_missing_apartment_data(self):
        with mock.patch.object(shared_data, "_source_manifest", side_effect=OSError("offline")):
            self.assertEqual(shared_data.sync_once()["status"], "unavailable")
        with mock.patch.object(shared_data, "sync_once", return_value={"status": "unavailable"}):
            with self.assertRaisesRegex(shared_data.SharedDataError, "공용 원본에 연결하지 못해"):
                shared_data.start()

    def test_source_changing_mid_copy_does_not_replace_last_good_version(self):
        self.sync()
        original = shared_data.revision()
        with mock.patch.object(shared_data, "_source_manifest", side_effect=[self.manifest(2), self.manifest(3)]), \
             mock.patch.object(shared_data.subprocess, "run", side_effect=self.copy):
            result = shared_data.sync_once()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(shared_data.revision(), original)

    def test_corrupt_or_partial_copy_is_never_published(self):
        self.sync()
        original = shared_data.revision()
        def bad_copy(command, **kwargs):
            self.copy(command, **kwargs)
            (Path(command[-1]) / "education_environment_records.json").write_text("{")
        with mock.patch.object(shared_data, "_source_manifest", return_value=self.manifest(2)), \
             mock.patch.object(shared_data.subprocess, "run", side_effect=bad_copy):
            result = shared_data.sync_once()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(shared_data.revision(), original)

    def test_invalid_planning_snapshot_keeps_the_last_good_version(self):
        self.facts["reconstruction_planning_records.json"] = {"version": 1, "records": {"unit": {"status": "ok"}}}
        self.assertEqual(self.sync()["status"], "ready")
        original = shared_data.revision()
        self.facts["reconstruction_planning_records.json"] = {"version": 1, "records": {"unit": "bad"}}
        self.assertEqual(self.sync(self.manifest(2))["status"], "stale")
        self.assertEqual(shared_data.revision(), original)

    def test_incomplete_seoul_plan_snapshot_does_not_replace_good_data(self):
        self.facts["seoul_reconstruction_plans.json"] = {
            "totalCount": 1, "sourceUrl": "https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do",
            "records": {"one": {"basic_info_seq": 1, "bsns_name": "사업", "site_code_nm": "노원구"}}}
        self.assertEqual(self.sync()["status"], "ready")
        original = shared_data.revision()
        self.facts["seoul_reconstruction_plans.json"]["totalCount"] = 2
        self.assertEqual(self.sync(self.manifest(2))["status"], "stale")
        self.assertEqual(shared_data.revision(), original)

    def test_empty_station_or_school_snapshot_keeps_the_last_good_records(self):
        self.sync()
        original = shared_data.revision()
        self.facts["education_environment_records.json"] = {"records": {}}
        self.assertEqual(self.sync(self.manifest(2))["status"], "stale")
        self.assertEqual(shared_data.revision(), original)

    def test_status_detects_a_refresh_worker_that_stopped_checking_the_source(self):
        self.sync()
        state = shared_data._read_state()
        state["lastCheckedAt"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat()
        shared_data.persistent_json_store.write_json_atomically(shared_data.MIRROR_ROOT / "status.json", state)
        self.assertEqual(shared_data.status()["status"], "stale")

    def test_replica_cannot_write_or_call_separate_collectors(self):
        for operation in (
            lambda: kakao_station_distances._request_json("search/address.json", {}),
            lambda: kakao_station_distances._merge_records({"new": {"status": "ok"}}),
            lambda: education_environment._save_precomputed_record("new", {"score": 90}),
            lambda: molit_transactions._write_cached_month("11440", "202610", []),
        ):
            with self.assertRaises(shared_data.SharedDataError):
                operation()

    def test_raw_transactions_always_come_from_the_shared_source(self):
        self.sync()
        with mock.patch.object(molit_transactions, "TRANSACTION_CACHE_DIR", shared_data.cache_path("molit_transactions")), \
             mock.patch.object(molit_transactions, "_official_api_xml") as external:
            self.assertEqual(molit_transactions.fetch_month("11440", "202610")[0]["dealAmountEok"], 17)
            with self.assertRaisesRegex(shared_data.SharedDataError, "공용 원본에"):
                molit_transactions.fetch_month("11680", "202610")
        external.assert_not_called()

    def test_source_revision_invalidates_memory_and_calculated_price_band(self):
        self.sync()
        with mock.patch.object(molit_transactions, "TRANSACTION_CACHE_DIR", shared_data.cache_path("molit_transactions")):
            first_key = molit_transactions._price_band_cache_key("테스트", "마포구", "59㎡", 6)
            self.assertEqual(molit_transactions.fetch_month("11440", "202610")[0]["dealAmountEok"], 17)
            self.facts["molit_transactions/11440_202610.json"]["items"][0]["dealAmountEok"] = 20
            self.sync(self.manifest(2))
            self.assertEqual(molit_transactions.fetch_month("11440", "202610")[0]["dealAmountEok"], 20)
            self.assertNotEqual(first_key, molit_transactions._price_band_cache_key("테스트", "마포구", "59㎡", 6))

    def test_manifest_never_accepts_personal_reports_or_path_traversal(self):
        for name in ("listing_reports/private.json", "../설정.txt"):
            payload = {**self.manifest(), name: [1, 1]}
            result = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload))
            with mock.patch.object(shared_data.subprocess, "run", return_value=result):
                with self.assertRaises(shared_data.SharedDataError):
                    shared_data._source_manifest()

    def test_manifest_retries_one_transient_connection_failure(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps(self.manifest()))
        with mock.patch.object(shared_data.subprocess, "run", side_effect=[OSError("offline"), response]) as transfer:
            self.assertEqual(shared_data._source_manifest(), self.manifest())
        self.assertEqual(transfer.call_count, 2)

    def test_handshake_timeout_reconnects_without_reusing_the_failed_master(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps(self.manifest()))
        error = subprocess.CalledProcessError(255, ['ssh'], stderr='Connection timed out during banner exchange')
        with mock.patch.object(shared_data.process_runtime, 'run', side_effect=[error, response]) as transfer:
            self.assertEqual(shared_data._source_manifest(), self.manifest())
        first, second = (call.args[0] for call in transfer.call_args_list)
        self.assertIn('-oControlMaster=auto', first)
        self.assertIn('-oControlMaster=no', second)
        self.assertIn('-oControlPath=none', second)
        self.assertNotIn('-oStrictHostKeyChecking=no', second)

    def test_download_reconnects_once_and_publishes_only_a_complete_snapshot(self):
        self.sync()
        original = shared_data.revision()
        error = subprocess.CalledProcessError(255, ['rsync'], stderr='Connection reset by peer')
        count = 0
        def flaky(command, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                raise error
            self.assertIn('-oControlPath=none', command[command.index('-e') + 1])
            return self.copy(command, **kwargs)
        with mock.patch.object(shared_data, '_source_manifest', return_value=self.manifest(2)), \
             mock.patch.object(shared_data.process_runtime, 'run', side_effect=flaky):
            recovered = shared_data.sync_once()
        self.assertEqual(count, 2)
        self.assertEqual(recovered['status'], 'ready')
        self.assertNotEqual(shared_data.revision(), original)

    def test_authentication_and_host_key_errors_do_not_retry(self):
        for diagnostic in ('Permission denied (publickey)', 'Host key verification failed'):
            error = subprocess.CalledProcessError(255, ['ssh'], stderr=diagnostic)
            with mock.patch.object(shared_data.process_runtime, 'run', side_effect=error) as transfer:
                with self.assertRaises(subprocess.CalledProcessError):
                    shared_data._source_manifest()
            self.assertEqual(transfer.call_count, 1)

    def test_refresh_reuses_an_authenticated_connection_with_private_socket_permissions(self):
        options = shared_data._ssh_options()
        self.assertIn("-oControlMaster=auto", options)
        self.assertIn("-oControlPersist=120", options)
        socket = Path(next(value.split("=", 1)[1] for value in options if value.startswith("-oControlPath=")))
        self.assertEqual(socket.parent.stat().st_mode & 0o777, 0o700)

    def test_auto_mode_reuses_path_resolution_but_tracks_configuration_changes(self):
        shared_data._auto_mode.cache_clear()
        source = self.root / "source"
        source.mkdir()
        local = self.root / "local"
        local.mkdir()
        original_resolve = Path.resolve
        with mock.patch.dict(os.environ, {"ZIPPICK_DATA_MODE": "auto"}), \
             mock.patch.object(shared_data, "SOURCE_ROOT", str(source.resolve())), \
             mock.patch.object(shared_data.config, "CACHE_DIR", source), \
             mock.patch.object(Path, "resolve", autospec=True, side_effect=original_resolve) as resolve:
            for _ in range(100):
                self.assertEqual(shared_data.mode(), "primary")
            self.assertEqual(resolve.call_count, 1)
            with mock.patch.object(shared_data.config, "CACHE_DIR", local):
                self.assertEqual(shared_data.mode(), "replica")
                self.assertTrue(shared_data.read_only())
            self.assertEqual(resolve.call_count, 2)
            with mock.patch.dict(os.environ, {"ZIPPICK_DATA_MODE": "replica"}):
                with self.assertRaises(shared_data.SharedDataError):
                    shared_data.require_writer()
            with mock.patch.dict(os.environ, {"ZIPPICK_DATA_MODE": "bad-mode"}):
                with self.assertRaises(shared_data.SharedDataError):
                    shared_data.mode()
        shared_data._auto_mode.cache_clear()

    def test_revision_detects_external_atomic_switch_without_resolving_ancestors(self):
        mirror = shared_data.MIRROR_ROOT
        first = mirror / "generations" / ("a" * 64)
        second = mirror / "generations" / ("b" * 64)
        first.mkdir(parents=True)
        second.mkdir()
        current = mirror / "current"
        current.symlink_to(first)
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("must not resolve ancestors")):
            self.assertEqual(shared_data.revision(), "a" * 64)
            next_link = mirror / "next"
            next_link.symlink_to(Path("generations") / second.name)
            os.replace(next_link, current)
            self.assertEqual(shared_data.revision(), "b" * 64)
            second.rmdir()
            self.assertEqual(shared_data.revision(), "", "broken snapshot is not usable")

    def test_revision_preserves_missing_and_legacy_directory_behavior(self):
        self.assertEqual(shared_data.revision(), "")
        (shared_data.MIRROR_ROOT / "current").mkdir(parents=True)
        self.assertEqual(shared_data.revision(), "current")

    def test_primary_and_test_modes_do_not_contact_the_production_host(self):
        for selected in ("primary", "isolated"):
            with mock.patch.dict(os.environ, {"ZIPPICK_DATA_MODE": selected}), \
                 mock.patch.object(shared_data.subprocess, "run") as transfer:
                self.assertEqual(shared_data.start()["mode"], selected)
                shared_data.require_writer()
            transfer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
