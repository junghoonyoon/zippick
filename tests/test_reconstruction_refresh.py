"""Exercise production collection and replica forwarding as one real data flow."""
import json
import ssl
import subprocess
import threading
from concurrent.futures import Future
from urllib.error import HTTPError, URLError
from unittest.mock import Mock

import pytest

import apartment_reconstruction as reconstruction
import collect_building_register as buildings
import reconstruction_refresh as refresh
import process_runtime
import shared_data
from test_apartment_reconstruction import DAY, ENTITY, entry, ordinance_context


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "isolated")
    monkeypatch.setattr(shared_data, "cache_path", lambda name: tmp_path / name)
    monkeypatch.setattr(refresh.parcels, "request", lambda entity: False)
    monkeypatch.setattr(refresh.projects, "request", lambda: False)
    monkeypatch.setattr(refresh.ordinances, "request", lambda: False)
    monkeypatch.setattr(buildings, "_JOBS", {})
    monkeypatch.setattr(buildings, "_BLOCKED_UNTIL", 0)
    monkeypatch.setattr(refresh, "_SYNC_JOB", None)
    monkeypatch.setattr(reconstruction, "_SOURCE_CONFIRMATIONS", {})
    reconstruction._read.cache_clear()
    return tmp_path


def test_first_report_collects_persists_and_reuses_the_same_parcel_for_both_areas(store, monkeypatch):
    fetcher = Mock(return_value=entry()["snapshot"])
    original = buildings.collect
    monkeypatch.setattr(buildings, "collect", lambda rows: original(rows, fetcher=fetcher))
    first = refresh.refresh(ENTITY)
    assert first["status"] == "loading"
    buildings._JOBS[reconstruction.parcel_key(ENTITY)][0].result(timeout=5)
    for area in (59, 84, 59):
        result = refresh.refresh({**ENTITY, "areaLabel": str(area)})
        assert result["profile"]["floorAreaRatio"] == 160
        assert result["profile"]["buildingCoverageRatio"] == 18
        assert result["status"] != "loading"
    fetcher.assert_called_once()
    data = json.loads((store / reconstruction.FACT_FILE).read_text())
    assert data["records"][reconstruction.parcel_key(ENTITY)]["status"] == "ok"


def test_replica_forwards_and_publishes_the_verified_primary_snapshot_without_local_collection(store, monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    monkeypatch.setattr(shared_data, "status", lambda: {"status": "ready"})
    local_collector = Mock(side_effect=AssertionError("replica called a provider"))
    monkeypatch.setattr(buildings, "request", local_collector)
    remote = reconstruction.analyze(ENTITY, entry(), day=DAY)
    forward = Mock(side_effect=[{**remote, "status": "loading"}, remote, remote])
    monkeypatch.setattr(refresh, "_request_primary", forward)
    def publish():
        (store / reconstruction.FACT_FILE).write_text(json.dumps({"records": {reconstruction.parcel_key(ENTITY): entry()}}))
        return {"status": "ready"}
    sync = Mock(side_effect=publish)
    monkeypatch.setattr(shared_data, "sync_once", sync)
    assert refresh.refresh(ENTITY)["status"] == "loading"
    sync.assert_not_called()
    assert refresh.refresh(ENTITY)["status"] == "loading"
    refresh._SYNC_JOB.result(timeout=5)
    result = refresh.refresh(ENTITY)
    assert result["profile"]["floorAreaRatio"] == 160
    assert result["status"] != "loading"
    sync.assert_called_once()
    assert forward.call_count == 3
    local_collector.assert_not_called()


def test_replica_failure_is_retryable_and_preserves_facts_without_a_positive_verdict(store, monkeypatch):
    (store / reconstruction.FACT_FILE).write_text(json.dumps({"records": {reconstruction.parcel_key(ENTITY): entry()}}))
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    monkeypatch.setattr(shared_data, "status", lambda: {"status": "ready"})
    monkeypatch.setattr(refresh, "_request_primary", Mock(side_effect=OSError("offline")))
    result = refresh.refresh(ENTITY)
    assert result["status"] == "stale"
    assert result["profile"]["floorAreaRatio"] == 160
    assert result["feasibility"]["status"] == "unavailable"
    assert "다시 불러오기" in result["reason"]
    assert not result["summary"]


def test_forwarding_sends_only_public_identity_and_rejects_a_different_parcel():
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return json.dumps({"reconstructionConditions": result}).encode()
    requests = []
    def opener(request, timeout):
        requests.append(request.full_url)
        return Response()
    entity = {**ENTITY, "budget": 11, "income": 10000, "secret": "private"}
    assert refresh._request_primary(entity, opener=opener)["apartmentId"] == ENTITY["apartmentId"]
    assert not any(word in requests[0] for word in ("private", "budget", "income", "secret"))
    result["identity"]["jibun"] = "320-9"
    with pytest.raises(ValueError, match="identity mismatch"):
        refresh._request_primary(entity, opener=opener)


def test_no_records_and_auth_failure_finish_without_becoming_zero_or_staying_loading(store, monkeypatch):
    for code in (None, "403"):
        original = buildings.collect
        fetcher = Mock(return_value={**entry()["snapshot"], "records": [], "totalCount": 0})
        if code:
            fetcher.side_effect = buildings.building_hub.BuildingHubError("denied", code)
        entity = {**ENTITY, "jibun": "322" if code else "321"}
        fetcher.return_value["parcel"] = reconstruction.parcel(entity)
        monkeypatch.setattr(buildings, "collect", lambda rows, _original=original: _original(rows, fetcher=fetcher))
        assert refresh.refresh(entity)["status"] == "loading"
        buildings._JOBS[reconstruction.parcel_key(entity)][0].result(timeout=5)
        model = refresh.refresh(entity)
        assert model["status"] == ("access_denied" if code else "no_records")
        assert not model["profile"].get("floorAreaRatio")
        monkeypatch.setattr(buildings, "collect", original)


def test_replica_does_not_block_or_start_duplicate_syncs_while_publishing(store, monkeypatch):
    remote = reconstruction.analyze(ENTITY, entry(), day=DAY)
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    monkeypatch.setattr(shared_data, "status", lambda: {"status": "ready"})
    monkeypatch.setattr(refresh, "_request_primary", Mock(return_value=remote))
    release = threading.Event()
    def publish():
        assert release.wait(timeout=5)
        (store / reconstruction.FACT_FILE).write_text(json.dumps({"records": {reconstruction.parcel_key(ENTITY): entry()}}))
        return {"status": "ready"}
    sync = Mock(side_effect=publish)
    monkeypatch.setattr(shared_data, "sync_once", sync)
    try:
        for _ in range(5):
            assert refresh.refresh(ENTITY)["status"] == "loading"
        assert not refresh._SYNC_JOB.done()
    finally:
        release.set()
        refresh._SYNC_JOB.result(timeout=5)
    assert refresh.refresh(ENTITY)["profile"]["floorAreaRatio"] == 160
    sync.assert_called_once()


def test_replica_reuses_identical_facts_without_an_unnecessary_source_download(store, monkeypatch):
    (store / reconstruction.FACT_FILE).write_text(json.dumps({"records": {reconstruction.parcel_key(ENTITY): entry()}}))
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    monkeypatch.setattr(shared_data, "status", lambda: {"status": "ready"})
    remote = reconstruction.analyze(ENTITY)
    remote["sourceRevision"] = ["different filesystem stamps"]
    monkeypatch.setattr(refresh, "_request_primary", Mock(return_value=remote))
    sync = Mock(side_effect=AssertionError("unchanged source downloaded again"))
    monkeypatch.setattr(shared_data, "sync_once", sync)
    assert refresh.refresh(ENTITY)["profile"]["floorAreaRatio"] == 160
    sync.assert_not_called()


def test_python_certificate_failure_uses_verified_system_https_and_validates_identity(monkeypatch):
    model = reconstruction.analyze(ENTITY, entry(), day=DAY)
    fetch = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({
        'reconstructionConditions': model}).encode()))
    monkeypatch.setattr(process_runtime, 'run', fetch)
    opener = Mock(side_effect=URLError(ssl.SSLCertVerificationError('Missing Authority Key Identifier')))
    assert refresh._request_primary(ENTITY, opener=opener) == json.loads(json.dumps(model))
    args, kwargs = fetch.call_args
    command = args[0]
    assert '--insecure' not in command and '-k' not in command
    assert command[command.index('--proto') + 1] == '=https'
    assert '--max-filesize' in command
    assert command[-1].startswith('https://')
    assert kwargs['check'] is True and kwargs['timeout'] == 10
    model['identity']['jibun'] = 'wrong-parcel'
    fetch.return_value.stdout = json.dumps({'reconstructionConditions': model}).encode()
    with pytest.raises(ValueError, match='identity mismatch'):
        refresh._request_primary(ENTITY, opener=opener)


@pytest.mark.parametrize('error', [URLError('offline'), HTTPError('https://example.invalid', 403, 'denied', {}, None)])
def test_non_certificate_failure_does_not_retry_through_another_http_client(monkeypatch, error):
    fallback = Mock(side_effect=AssertionError('unexpected fallback'))
    monkeypatch.setattr(process_runtime, 'run', fallback)
    with pytest.raises(URLError):
        refresh._request_primary(ENTITY, opener=Mock(side_effect=error))
    fallback.assert_not_called()


def test_system_https_failure_remains_retryable_and_does_not_disclose_raw_diagnostics(store, monkeypatch):
    (store / reconstruction.FACT_FILE).write_text(json.dumps({'records': {reconstruction.parcel_key(ENTITY): entry()}}))
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'replica')
    monkeypatch.setattr(shared_data, 'status', lambda: {'status': 'ready'})
    monkeypatch.setattr(refresh, 'urlopen', Mock(side_effect=URLError(ssl.SSLCertVerificationError('chain'))))
    monkeypatch.setattr(process_runtime, 'run', Mock(side_effect=subprocess.CalledProcessError(
        60, ['curl', 'private-diagnostic'], stderr=b'private-diagnostic')))
    result = refresh.refresh(ENTITY)
    assert result['status'] == 'stale'
    assert result['profile']['floorAreaRatio'] == 160
    assert result['sourceConnection'] == {'status': 'error', 'stage': 'primary_api', 'code': 'tls_verification_failed'}
    assert result['feasibility']['status'] == 'unavailable'
    assert '인증서' in result['reason']
    assert 'private-diagnostic' not in json.dumps(result)
    # A successful retry recovers normally without keeping the earlier TLS error.
    normal = reconstruction.analyze(ENTITY)
    monkeypatch.setattr(refresh, '_request_primary', Mock(return_value=normal))
    recovered = refresh.refresh(ENTITY)
    assert recovered['profile']['floorAreaRatio'] == 160
    assert 'sourceConnection' not in recovered


def test_ssh_sync_failure_is_distinct_from_a_failed_primary_api(store, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'replica')
    monkeypatch.setattr(shared_data, 'status', lambda: {'status': 'ready'})
    remote = reconstruction.analyze(ENTITY, entry(), day=DAY)
    monkeypatch.setattr(refresh, '_request_primary', Mock(return_value=remote))
    job = Future()
    job.set_result({'status': 'stale', 'errorStage': 'source_manifest', 'errorReason': 'ssh_timeout'})
    monkeypatch.setattr(refresh, '_SYNC_JOB', job)
    result = refresh.refresh(ENTITY)
    assert result['sourceConnection'] == {'status': 'error', 'stage': 'source_manifest', 'code': 'ssh_timeout'}
    assert '동기화' in result['heading']
    assert '운영 API는 응답했지만' in result['reason']
    assert result['status'] != 'loading'


def local_snapshot_with_primary_reply(store, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'replica')
    monkeypatch.setattr(reconstruction, 'CONTEXT_PATH', store / 'manual.json')
    (store / reconstruction.FACT_FILE).write_text(json.dumps({'records': {reconstruction.parcel_key(ENTITY): entry()}}))
    (store / reconstruction.PLANNING_FILE).write_text(json.dumps({'records': {ENTITY['apartmentId']: ordinance_context()}}))
    state = {'status': 'ready'}
    monkeypatch.setattr(shared_data, 'status', lambda: dict(state))
    remote = json.loads(json.dumps(reconstruction.analyze(ENTITY)))
    assert remote['status'] == 'reference'
    state['status'] = 'stale'
    assert reconstruction.analyze(ENTITY)['status'] == 'stale'
    monkeypatch.setattr(refresh, '_request_primary', Mock(return_value=remote))
    return state, remote


def test_identical_primary_facts_recover_building_status_without_hiding_global_ssh_failure(store, monkeypatch):
    state, remote = local_snapshot_with_primary_reply(store, monkeypatch)
    files_before = {p.name: p.read_bytes() for p in store.iterdir() if p.is_file()}
    sync = Mock(side_effect=AssertionError('identical records should not download 7,000 files'))
    monkeypatch.setattr(shared_data, 'sync_once', sync)
    result = refresh.refresh(ENTITY)
    assert result['status'] == remote['status']
    assert result['feasibility'] == remote['feasibility']
    assert result['sourceVerification']['method'] == 'primary_api_same_snapshot'
    assert shared_data.status()['status'] == 'stale'
    sync.assert_not_called()
    assert {p.name: p.read_bytes() for p in store.iterdir() if p.is_file()} == files_before
    # Every API consumer reads the same locally calculated result, across areas.
    for area in [59, 84, 59.87]:
        row = reconstruction.attach({'areaLabel': str(area)}, ENTITY)
        assert row['reconstructionConditions'] == result
    assert 'sourceVerification' not in reconstruction.analyze({**ENTITY, 'jibun': '320-9'})


@pytest.mark.parametrize('change', ['expiry', 'file_revision', 'primary_error'])
def test_primary_confirmation_cannot_outlive_expiry_source_changes_or_a_failed_retry(store, monkeypatch, change):
    local_snapshot_with_primary_reply(store, monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(reconstruction.time, 'monotonic', lambda: clock[0])
    assert refresh.refresh(ENTITY)['status'] == 'reference'
    if change == 'expiry':
        clock[0] += shared_data.REFRESH_SECONDS + 1
    elif change == 'file_revision':
        path = store / reconstruction.FACT_FILE
        path.write_text(json.dumps({'records': {reconstruction.parcel_key(ENTITY): entry(vlRat=170, vlRatEstmTotArea=68000)}}))
    else:
        monkeypatch.setattr(refresh, '_request_primary', Mock(side_effect=URLError('offline')))
        assert refresh.refresh(ENTITY)['status'] == 'stale'
    result = reconstruction.analyze(ENTITY)
    assert result['status'] == 'stale'
    assert 'sourceVerification' not in result


def test_different_primary_facts_still_require_verified_snapshot_sync(store, monkeypatch):
    _, remote = local_snapshot_with_primary_reply(store, monkeypatch)
    remote['profile']['floorAreaRatio'] = 170
    assert reconstruction.confirm_primary_snapshot(ENTITY, remote) is False
    assert reconstruction.analyze(ENTITY)['status'] == 'stale'
    job = Future()
    job.set_result({'status': 'stale', 'errorStage': 'source_manifest', 'errorReason': 'ssh_timeout'})
    monkeypatch.setattr(refresh, '_SYNC_JOB', job)
    result = refresh.refresh(ENTITY)
    assert result['sourceConnection']['code'] == 'ssh_timeout'
    assert result['profile']['floorAreaRatio'] == 160
    assert 'sourceVerification' not in result
