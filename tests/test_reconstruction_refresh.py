"""Exercise production collection and replica forwarding as one real data flow."""
import json
import threading
from unittest.mock import Mock

import pytest

import apartment_reconstruction as reconstruction
import collect_building_register as buildings
import reconstruction_refresh as refresh
import shared_data
from test_apartment_reconstruction import DAY, ENTITY, entry


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
