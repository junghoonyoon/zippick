"""공식 지적도 응답을 흉내 낸 가상 필지. 실제 점수 자료에는 쓰지 않는다."""

import io
import json
import sqlite3
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

import vworld_cadastral as cadastral
import import_vworld_cadastral as importer


LAT, LON = 37.5984958012818, 127.063534965389
APARTMENT_ID = "fixture-only"


@pytest.mark.parametrize("approval_args", [[], ["--commercial-approval", "C-1"],
                                              ["--storage-approval", "S-1"]])
def test_import_requires_both_vworld_permissions_before_fetch(monkeypatch, capsys, approval_args):
    monkeypatch.setattr(sys, "argv", ["import_vworld_cadastral.py", "seongnam", *approval_args])
    monkeypatch.setattr(importer, "fetch_radius", lambda *args, **kwargs: pytest.fail("API called"))
    with pytest.raises(SystemExit) as error:
        importer.main()
    assert error.value.code == 2
    assert "상업적 이용 허락과 데이터 저장 승낙" in capsys.readouterr().err


def feature(number, *, east=None):
    west, south = LON - .00001, LAT - .00001
    east = east if east is not None else LON + .00001
    north = LAT + .00001
    return {"type": "Feature", "properties": {"pnu": f"112301100010000{number:04d}"},
            "geometry": {"type": "Polygon", "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]]}}


def page(total, current, features, page_size):
    return {"response": {"status": "OK",
                         "page": {"total": max(1, (total + page_size - 1) // page_size), "current": current},
                         "record": {"total": total},
                         "result": {"featureCollection": {"type": "FeatureCollection", "features": features}}}}


def test_tiles_cover_pilot_circle_under_api_limit():
    for latitude, longitude in [(37.454462641495, 127.151543173773), (LAT, LON)]:
        tiles = cadastral.tile_boxes(latitude, longitude)
        assert len(tiles) == 9
        assert all(w < e and s < n for w, s, e, n in tiles)


def test_all_pages_deduplicate_store_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(cadastral, "PAGE_SIZE", 2)
    calls = []

    def opener(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        calls.append(query)
        number = int(query["page"][0])
        rows = [feature(1), feature(2)] if number == 1 else [feature(3)]
        return io.BytesIO(json.dumps(page(3, number, rows, 2)).encode())

    snapshot = cadastral.fetch_radius(APARTMENT_ID, LAT, LON, api_key="secret-fixture",
                                      opener=opener, pause_seconds=0)
    assert len(calls) == 18
    assert len(snapshot["tileCounts"]) == 9
    assert len(snapshot["features"]) == 3
    assert snapshot["queryComplete"] is True
    assert "secret-fixture" not in json.dumps(snapshot)
    path = tmp_path / "cadastral.sqlite3"
    digest = cadastral.store_snapshot(snapshot, path=path)
    assert digest == cadastral.store_snapshot(snapshot, path=path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT parcel_count FROM cadastral_snapshots").fetchall() == [(3,)]
        assert "secret-fixture" not in db.execute("SELECT payload_json FROM cadastral_snapshots").fetchone()[0]


@pytest.mark.parametrize("problem", ["missing_key", "short_page", "wrong_page", "conflicting_geometry", "invalid_pnu", "http_error"])
def test_incomplete_or_untrusted_responses_never_persist(tmp_path, monkeypatch, problem):
    monkeypatch.setattr(cadastral, "PAGE_SIZE", 2)
    if problem == "missing_key":
        monkeypatch.setattr(cadastral.config, "VWORLD_API_KEY", "")
    path = tmp_path / "cadastral.sqlite3"

    def opener(request, timeout):
        if problem == "http_error":
            raise OSError(request.full_url)  # Real HTTP errors may include the key.
        number = int(parse_qs(urlsplit(request.full_url).query)["page"][0])
        rows = [feature(1), feature(2)] if number == 1 else [feature(3)]
        if problem == "short_page":
            rows = rows[:1]
        if problem == "conflicting_geometry" and number == 2:
            rows = [feature(1, east=LON + .00002)]
        if problem == "invalid_pnu":
            rows[0]["properties"]["pnu"] = "bad"
        payload = page(3, number, rows, 2)
        if problem == "wrong_page":
            payload["response"]["page"]["current"] = 9
        return io.BytesIO(json.dumps(payload).encode())

    with pytest.raises(cadastral.CadastralError) as error:
        cadastral.fetch_radius(APARTMENT_ID, LAT, LON,
                               api_key=None if problem == "missing_key" else "secret-fixture",
                               opener=opener, pause_seconds=0, retry_wait_seconds=0)
    assert "secret-fixture" not in str(error.value)
    assert not path.exists()


def test_temporary_network_failure_is_retried_without_leaking_key():
    attempts = 0

    def opener(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(request.full_url)
        return io.BytesIO(json.dumps(page(0, 1, [], 1000)).encode())

    snapshot = cadastral.fetch_radius(APARTMENT_ID, LAT, LON, api_key="secret-fixture",
                                      opener=opener, pause_seconds=0, retry_wait_seconds=0)
    assert attempts == 10  # one retry, then the remaining eight tiles
    assert snapshot["queryComplete"] is True


def test_storage_rejects_incomplete_snapshot(tmp_path):
    snapshot = {"dataset": cadastral.DATASET, "sourceUrl": cadastral.SOURCE_URL,
                "center": {"latitude": LAT, "longitude": LON}, "radiusMeters": 1500,
                "apartmentId": APARTMENT_ID, "fetchedAt": "2026-10-12T00:00:00Z",
                "tileCounts": [0] * 9, "features": []}
    with pytest.raises(ValueError):
        cadastral.store_snapshot(snapshot, path=tmp_path / "no.sqlite3")
    assert not (tmp_path / "no.sqlite3").exists()


def test_building_join_reports_missing_dongs_without_scoring(tmp_path):
    other = feature(2)
    other["properties"]["pnu"] = "4113110500100000002"
    snapshot = {"radiusMeters": 1500, "features": [feature(1), other]}
    db_path = tmp_path / "building.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE dong_snapshots "
                   "(dong_id TEXT, fetched_at TEXT, source_url TEXT, total_count INTEGER, payload TEXT)")
        record = {"sigunguCd": "11230", "bjdongCd": "11000", "platGbCd": "1",
                  "bun": "0000", "ji": "0001"}
        payload = json.dumps({"totalCount": 1, "records": [record]})
        db.execute("INSERT INTO dong_snapshots VALUES (?, ?, ?, ?, ?)",
                   ("1123011000", "2026-10-12", cadastral.BUILDING_SOURCE_URL, 1, payload))
    audit = cadastral.audit_building_join(snapshot, building_db_path=db_path)
    assert audit["requiredDongCodes"] == ["1123011000", "4113110500"]
    assert audit["missingDongCodes"] == ["4113110500"]
    assert audit["matchedParcelCount"] == 1
    assert audit["buildingRecordCountOnMatchedParcels"] == 1
    assert audit["fullBuildingDongCoverage"] is False
    assert audit["scoreReady"] is False
