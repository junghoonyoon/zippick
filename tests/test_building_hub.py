import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from building_hub import (BuildingHubError, fetch_dong_records, fetch_title_records,
                          store_dong_snapshot, store_snapshot)
from building_hub import SOURCE_URL
from export_building_hub_summary import build_summary, residential_age_summary


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.value).encode()


def page(items, total, code="00"):
    return {"response": {"header": {"resultCode": code},
                         "body": {"totalCount": total, "items": {"item": items}}}}


def record(building_id, **changes):
    return {"mgmBldrgstPk": building_id, "sigunguCd": "11230", "bjdongCd": "11000",
            "platGbCd": "0", "bun": "0028", "ji": "0004", "useAprDay": "19800101",
            "mainPurpsCdNm": "공동주택", **changes}


def test_exact_parcel_pagination_and_storage(tmp_path):
    requests = []
    values = [page(record("a"), 2), page([record("b")], 2)]

    def opener(request, timeout):
        requests.append((parse_qs(urlparse(request.full_url).query), timeout))
        return Response(values.pop(0))

    snapshot = fetch_title_records("11230", "11000", "0028", "0004", api_key="key%2Bvalue",
                                   page_size=1, opener=opener)
    assert snapshot["totalCount"] == 2
    assert [r["mgmBldrgstPk"] for r in snapshot["records"]] == ["a", "b"]
    assert [x[0]["pageNo"] for x in requests] == [["1"], ["2"]]
    assert requests[0][0]["serviceKey"] == ["key+value"]
    assert requests[0][0]["bun"] == ["0028"]
    db_path = tmp_path / "building.sqlite3"
    store_snapshot(snapshot, db_path)
    with sqlite3.connect(db_path) as db:
        stored = json.loads(db.execute("SELECT payload FROM snapshots").fetchone()[0])
    assert stored["records"] == snapshot["records"]
    assert "serviceKey" not in json.dumps(stored)


def test_missing_key_mismatched_parcel_and_incomplete_page_do_not_save(tmp_path):
    with pytest.raises(BuildingHubError, match="인증키"):
        fetch_title_records("11230", "11000", "0028", "0004", api_key="")
    with pytest.raises(ValueError, match="5자리"):
        fetch_title_records("1123", "11000", "0028", "0004", api_key="key")

    def wrong_parcel(*_args, **_kwargs):
        return Response(page(record("a", ji="0005"), 1))

    with pytest.raises(BuildingHubError, match="지번"):
        fetch_title_records("11230", "11000", "0028", "0004", api_key="key", opener=wrong_parcel)

    def incomplete(*_args, **_kwargs):
        return Response(page(record("a"), 2))

    with pytest.raises(BuildingHubError, match="전체 자료"):
        fetch_title_records("11230", "11000", "0028", "0004", api_key="key",
                            max_pages=1, opener=incomplete)
    assert not (tmp_path / "building.sqlite3").exists()


def test_api_rejection_does_not_expose_key():
    def rejected(*_args, **_kwargs):
        return Response(page([], 0, code="30"))

    with pytest.raises(BuildingHubError, match="활용신청") as error:
        fetch_title_records("11230", "11000", "0028", "0004", api_key="private-key", opener=rejected)
    assert "private-key" not in str(error.value)


def test_dong_pages_are_complete_and_saved_separately(tmp_path):
    queries = []
    values = [page(record("a"), 2), page(record("b", bun="0149", ji="0008"), 2)]

    def opener(request, timeout):
        queries.append(parse_qs(urlparse(request.full_url).query))
        return Response(values.pop(0))

    snapshot = fetch_dong_records("11230", "11000", api_key="key", page_size=1,
                                  opener=opener)
    assert snapshot["totalCount"] == 2
    assert "bun" not in queries[0] and "ji" not in queries[0]
    path = tmp_path / "building.sqlite3"
    assert store_dong_snapshot(snapshot, path) == "1123011000"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT total_count FROM dong_snapshots").fetchone()[0] == 2


def test_report_export_uses_only_complete_dong_counts_and_no_raw_records(tmp_path):
    path = tmp_path / "building.sqlite3"
    for code, count in (("4113110500", 1), ("1123011000", 2), ("1123010900", 3)):
        snapshot = {"dong": {"sigunguCd": code[:5], "bjdongCd": code[5:]},
                    "fetchedAt": "2026-10-12T14:00:00+00:00", "sourceUrl": SOURCE_URL,
                    "totalCount": count,
                    "records": [{"mgmBldrgstPk": f"private-{code}-{index}"} for index in range(count)]}
        store_dong_snapshot(snapshot, path)
    result = build_summary(db_path=path)
    assert [area["recordCount"] for entry in result for area in entry["areas"]] == [1, 2, 3]
    assert all(area['age30SharePct'] is None for entry in result for area in entry['areas'])
    assert "private-" not in json.dumps(result)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE dong_snapshots SET total_count=99 WHERE dong_id='1123011000'")
    with pytest.raises(ValueError, match="검증"):
        build_summary(db_path=path)


def test_residential_age_counts_only_verified_approval_dates():
    records = [
        record('old', useAprDay='19961012'),
        record('new', useAprDay='19961013'),
        record('missing', useAprDay=''),
        record('invalid', useAprDay='19960230'),
        record('future', useAprDay='20271012'),
        record('nonresidential', mainPurpsCdNm='근린생활시설', useAprDay='19800101'),
    ]
    assert residential_age_summary(records, '2026-10-12') == {
        'residentialRecordCount': 5,
        'approvalDateCount': 2,
        'age30RecordCount': 1,
        'age30SharePct': 50.0,
    }
    assert residential_age_summary([record('missing', useAprDay='')], '2026-10-12')['age30SharePct'] is None
