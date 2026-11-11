"""Synthetic fixtures verify identities, missing facts, collection, and report copy."""
import copy
import datetime as dt
import json
from unittest.mock import Mock

import pytest

import apartment_reconstruction as r
import building_hub
import collect_building_register as collector
import import_reconstruction_planning as planning_import
import shared_data

DAY = dt.date(2026, 11, 11)
ENTITY = {"apartmentId": "example-3", "name": "예시아파트3단지", "province": "서울특별시",
          "district": "노원구", "legalDong": "월계동", "jibun": "320-11", "cortarNo": "1135010200",
          "households": 884, "approvedAt": "1995-06-12"}


def entry(**changes):
    record = {**r.parcel(ENTITY), "regstrKindCd": "1", "mgmBldrgstPk": "example-register",
              "bldNm": "예시아파트3단지", "mainPurpsCdNm": "공동주택", "hhldCnt": 884,
              "vlRat": 160, "bcRat": 18, "platArea": 40000, "vlRatEstmTotArea": 64000,
              "archArea": 7200, **changes}
    return {"status": "ok", "checkedAt": DAY.isoformat(), "snapshot": {"parcel": r.parcel(ENTITY),
            "source": "국토교통부 건축HUB 총괄표제부", "sourceUrl": building_hub.SOURCE_URL,
            "recordType": "recap", "fetchedAt": DAY.isoformat(), "totalCount": 1, "records": [record]}}


def context(**changes):
    return {"identity": {k: ENTITY[k] for k in ("apartmentId", "district", "legalDong", "jibun")},
            "basis": {"kind": "current_limit", "floorAreaRatio": 250, "landAreaSqm": 40000,
                      "siteScopeVerified": True, "sourceUrl": "https://www.nowon.go.kr/official-plan",
                      "checkedAt": DAY.isoformat(), **changes}}


def ordinance_context(**changes):
    return {"identity": {k: ENTITY[k] for k in ("apartmentId", "district", "legalDong", "jibun")},
            "ordinanceReference": {"kind": "ordinance_reference", "pnu": r.parcel_pnu(ENTITY),
                "zoneName": "제3종일반주거지역", "floorAreaRatio": 250, "buildingCoverageRatio": 50,
                "parcelAreaSqm": 40100, "zoneAreaSqm": 40100, "checkedAt": DAY.isoformat(),
                "sourceUrl": "https://www.eum.go.kr/web/ar/lu/luLandDet.jsp",
                "districtPlanName": "예시지구", "districtPlanUrl": "https://www.nowon.kr/plan", **changes}}


def analyze(e=None, c=None, entity=None):
    return r.analyze(entity or ENTITY, e or entry(), c if c is not None else context(), day=DAY)


def test_verified_headroom_is_explained_without_a_score_or_project_stage():
    result = analyze()
    assert result["grade"] == "potential"
    assert result["differencePp"] == 90
    assert result["profile"]["buildingCoverageRatio"] == 18
    assert not {"score", "stars", "probability", "stage"}.intersection(result)
    assert "재건축 검토" in result["summary"]


@pytest.mark.parametrize("change", [
    {"floorAreaRatio": 0}, {"kind": "proposed_plan"}, {"landAreaSqm": 50000},
    {"siteScopeVerified": False}, {"sourceUrl": "https://example.com/plan"},
    {"sourceUrl": "https://nowon.go.kr.example.com/plan"}, {"checkedAt": "2020-01-01"},
    {"checkedAt": "2027-01-01"},
])
def test_an_unverified_or_different_site_limit_never_creates_headroom(change):
    result = analyze(c=context(**change))
    assert result["status"] == "basis_missing"
    assert result["summary"] == ""
    assert "differencePp" not in result


def test_no_default_300_percent_ceiling_and_wrong_phase_context_is_rejected():
    assert analyze(c={})["status"] == "basis_missing"
    wrong = context(); wrong["identity"]["jibun"] = "320-9"
    assert analyze(c=wrong)["basis"] is None


def test_parcel_ordinance_is_a_reference_not_an_approved_site_plan():
    result = analyze(c=ordinance_context())
    assert result["status"] == "reference"
    assert result["differencePp"] == 90
    assert result["basis"] is None
    assert result["planningReference"]["districtPlanName"] == "예시지구"
    assert "대표 지번" in result["heading"]
    assert "실제 건축 기준" in result["limitation"]
    assert not {"score", "stars", "stage", "householdIncrease"}.intersection(result)


@pytest.mark.parametrize("change", [
    {"pnu": "1135010200103200009"}, {"zoneAreaSqm": 39900},
    {"floorAreaRatio": 0}, {"buildingCoverageRatio": 101},
    {"sourceUrl": "https://eum.go.kr.evil.example/"}, {"checkedAt": "2027-01-01"},
])
def test_invalid_or_partial_parcel_reference_cannot_claim_a_difference(change):
    result = analyze(c=ordinance_context(**change))
    assert result["status"] == "basis_missing"
    assert result["planningReference"] is None
    assert "differencePp" not in result


def test_ordinance_wrong_identity_and_unofficial_district_plan_are_not_used():
    wrong = ordinance_context(); wrong["identity"]["jibun"] = "320-9"
    assert analyze(c=wrong)["status"] == "basis_missing"
    result = analyze(c=ordinance_context(districtPlanUrl="https://example.com/"))
    assert result["status"] == "reference"
    assert "districtPlanName" not in result["planningReference"]


def test_expired_reference_keeps_last_good_facts_without_a_positive_summary():
    result = analyze(c=ordinance_context(checkedAt="2020-01-01"))
    assert result["status"] == "stale"
    assert result["planningReference"]["floorAreaRatio"] == 250
    assert result["summary"] == ""
    assert "마지막" in result["heading"]


def test_verified_site_plan_takes_priority_over_ordinance_reference():
    both = {**ordinance_context(), "basis": context(kind="approved_plan")["basis"]}
    result = analyze(c=both)
    assert result["grade"] == "planned"
    assert result["planningReference"] is None


def test_building_key_and_pnu_use_different_normal_and_mountain_codes():
    assert r.parcel_key(ENTITY) == "1135010200003200011"
    assert r.parcel_pnu(ENTITY) == "1135010200103200011"
    mountain = {**ENTITY, "jibun": "산320-11"}
    assert r.parcel_key(mountain) == "1135010200103200011"
    assert r.parcel_pnu(mountain) == "1135010200203200011"


def test_shared_reference_and_source_revision_follow_the_primary_record(store):
    path = store / r.PLANNING_FILE
    path.write_text(json.dumps({"records": {ENTITY["apartmentId"]: ordinance_context()}}, ensure_ascii=False))
    before = r.revision()
    result = r.analyze(ENTITY, entry(), day=DAY)
    assert result["status"] == "reference"
    new = ordinance_context(floorAreaRatio=200)
    path.write_text(json.dumps({"records": {ENTITY["apartmentId"]: new}}, ensure_ascii=False))
    assert r.revision() != before
    assert r.analyze(ENTITY, entry(), day=DAY)["differencePp"] == 40


def test_broken_planning_source_is_not_reported_as_a_missing_plan(store):
    (store / r.PLANNING_FILE).write_text("{broken")
    result = r.analyze(ENTITY, entry(), day=DAY)
    assert result["status"] == "connection_error"
    assert "원본 연결" in result["reason"]
    assert result["profile"]["floorAreaRatio"] == 160


def test_failed_refresh_keeps_planning_facts_but_does_not_make_a_fresh_judgment(store):
    record = ordinance_context(); record["lastError"] = {"status": "connection_error"}
    (store / r.PLANNING_FILE).write_text(json.dumps({"records": {ENTITY["apartmentId"]: record}}, ensure_ascii=False))
    result = r.analyze(ENTITY, entry(), day=DAY)
    assert result["status"] == "stale"
    assert result["planningReference"]["floorAreaRatio"] == 250
    assert not result["summary"]


def test_manual_import_validates_identity_merges_and_never_overwrites_corrupt_source(store, monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "isolated")
    record = ordinance_context(); record["identity"]["cortarNo"] = ENTITY["cortarNo"]
    result = planning_import.import_verified({ENTITY["apartmentId"]: record}, day=DAY)
    assert (result["total"], result["success"], result["failed"]) == (1, 1, 0)
    path = store / r.PLANNING_FILE
    saved = path.read_text()
    bad = copy.deepcopy(record); bad["identity"]["jibun"] = "320-9"
    with pytest.raises(ValueError): planning_import.import_verified({ENTITY["apartmentId"]: bad}, day=DAY)
    assert path.read_text() == saved
    path.write_text("{broken")
    with pytest.raises(ValueError): planning_import.import_verified({ENTITY["apartmentId"]: record}, day=DAY)
    assert path.read_text() == "{broken"


def test_manual_import_keeps_newer_facts_and_existing_plan_fields(store, monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "isolated")
    current = ordinance_context(); current["identity"]["cortarNo"] = ENTITY["cortarNo"]
    current["basis"] = context()["basis"]
    planning_import.import_verified({ENTITY["apartmentId"]: current}, day=DAY)
    path = store / r.PLANNING_FILE
    before = path.read_text()
    older = copy.deepcopy(current)
    older["ordinanceReference"].update(checkedAt="2026-11-10", floorAreaRatio=200)
    older.pop("basis")
    counts = planning_import.import_verified({ENTITY["apartmentId"]: older}, day=DAY)
    assert (counts["success"], counts["reused"]) == (0, 1)
    assert path.read_text() == before
    current_update = copy.deepcopy(older)
    current_update["ordinanceReference"]["checkedAt"] = DAY.isoformat()
    planning_import.import_verified({ENTITY["apartmentId"]: current_update}, day=DAY)
    saved = json.loads(path.read_text())["records"][ENTITY["apartmentId"]]
    assert saved["basis"] == current["basis"]
    assert saved["ordinanceReference"]["floorAreaRatio"] == 200


def test_manual_planning_import_cannot_write_in_replica(monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    with pytest.raises(shared_data.SharedDataError): planning_import.import_verified({"record": {}}, day=DAY)


@pytest.mark.parametrize("change", [
    {"ji": "0009"}, {"bldNm": "예시아파트2단지"}, {"hhldCnt": 3031},
    {"regstrKindCd": "2"}, {"mainPurpsCdNm": "근린생활시설"}, {"mgmBldrgstPk": ""},
])
def test_same_name_different_parcel_phase_households_or_dong_title_is_not_used(change):
    result = analyze(entry(**change))
    assert result["status"] == "identity_unverified"
    assert result["summary"] == ""
    assert "floorAreaRatio" not in result["profile"]


def test_dong_records_aggregates_and_duplicate_whole_site_titles_are_rejected():
    e = entry(); e["snapshot"]["recordType"] = "title"
    assert analyze(e)["status"] == "identity_unverified"
    e = entry(); e["snapshot"]["records"] *= 2; e["snapshot"]["totalCount"] = 2
    assert analyze(e)["status"] == "identity_unverified"
    assert analyze(entity={**ENTITY, "aggregate": True})["status"] == "identity_unverified"


@pytest.mark.parametrize("value", [None, 0, -1, "", "NaN", "Infinity"])
def test_unknown_far_is_not_interpreted_as_low_density(value):
    result = analyze(entry(vlRat=value))
    assert result["profile"]["floorAreaRatio"] is None
    assert result["status"] == "partial"
    assert result["grade"] == "unknown"
    assert "현재 용적률" in result["heading"]


def test_inconsistent_area_totals_and_invalid_coverage_are_rejected():
    result = analyze(entry(vlRat=200, bcRat=101))
    assert result["profile"]["floorAreaRatio"] is None
    assert result["profile"]["buildingCoverageRatio"] is None


def test_coverage_is_secondary_and_never_produces_headroom_itself():
    low = analyze(entry(bcRat=5, archArea=2000))
    high = analyze(entry(bcRat=50, archArea=20000))
    assert (low["grade"], low["summary"]) == (high["grade"], high["summary"])


def test_small_or_negative_difference_does_not_claim_reconstruction_is_impossible():
    for ceiling in (170, 160, 150):
        result = analyze(c=context(floorAreaRatio=ceiling))
        assert result["grade"] == "limited"
        assert "불가능" not in result["heading"]
    assert analyze(c=context(kind="approved_plan"))["grade"] == "planned"


def test_old_or_failed_refresh_preserves_facts_but_removes_positive_judgment():
    e = entry(); e["lastError"] = {"status": "connection_error"}
    result = analyze(e)
    assert result["status"] == "stale"
    assert result["profile"]["floorAreaRatio"] == 160
    assert not result["summary"]
    e = entry(); e["snapshot"]["fetchedAt"] = "2020-01-01"
    assert analyze(e)["status"] == "stale"


def test_young_building_is_not_presented_as_a_reconstruction_candidate():
    result = analyze(entity={**ENTITY, "approvedAt": "2020-06-12"})
    assert result["grade"] == "not_assessed"
    assert not result["summary"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(shared_data, "cache_path", lambda name: tmp_path / name)
    r._read.cache_clear()
    return tmp_path


def test_collection_merges_preserves_last_good_data_and_reuses_recent_records(store):
    snapshot = entry()["snapshot"]
    fetcher = Mock(return_value=snapshot)
    stats = collector.collect([ENTITY], fetcher=fetcher)
    assert (stats["success"], stats["usable"], stats["requests"]) == (1, 1, 1)
    stats = collector.collect([ENTITY], fetcher=fetcher)
    assert (stats["reused"], stats["usable"], stats["requests"]) == (1, 1, 0)
    fetcher.side_effect = building_hub.BuildingHubError("denied", "30")
    stats = collector.collect([ENTITY, {**ENTITY, "jibun": "321"}], fetcher=fetcher, refresh=True)
    assert (stats["failed"], stats["unprocessed"], stats["stoppedCode"]) == (1, 1, "30")
    saved = json.loads((store / r.FACT_FILE).read_text())["records"][r.parcel_key(ENTITY)]
    assert saved["snapshot"] == snapshot
    assert saved["lastError"]["errorCode"] == "30"


def test_empty_result_after_success_and_corrupt_store_never_erase_facts(store):
    key = r.parcel_key(ENTITY)
    collector.save_record(key, entry())
    empty = entry(); empty["status"] = "no_records"; empty["snapshot"].update(records=[], totalCount=0)
    collector.save_record(key, empty)
    saved = json.loads((store / r.FACT_FILE).read_text())["records"][key]
    assert saved["snapshot"]["records"]
    (store / r.FACT_FILE).write_text("{broken")
    with pytest.raises(ValueError): collector.save_record(key, entry())
    assert (store / r.FACT_FILE).read_text() == "{broken"


def test_replica_never_calls_external_building_api(monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "replica")
    fetcher = Mock()
    assert collector.request(ENTITY) is False
    with pytest.raises(shared_data.SharedDataError): collector.collect([ENTITY], fetcher=fetcher)
    fetcher.assert_not_called()


def test_recap_operation_and_http_auth_errors_are_explicit_and_secret_free():
    from test_building_hub import Response, page
    from urllib.error import HTTPError
    requests = []
    def opener(request, timeout):
        requests.append(request.full_url.split("?")[0])
        return Response(page(entry()["snapshot"]["records"], 1))
    result = building_hub.fetch_recap_records("11350", "10200", "0320", "0011", api_key="secret", opener=opener)
    assert requests == ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrRecapTitleInfo"]
    assert result["recordType"] == "recap"
    def denied(*args, **kwargs): raise HTTPError("https://api/?key=secret", 403, "secret", {}, None)
    with pytest.raises(building_hub.BuildingHubError) as error:
        building_hub.fetch_recap_records("11350", "10200", "0320", "0011", api_key="secret", opener=denied)
    assert error.value.code == "403"
    assert "secret" not in str(error.value)
