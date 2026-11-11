"""HTTP regression test with isolated provider fixtures, never production writes."""
import json
import threading
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest
import apartment_reconstruction as reconstruction
import collect_building_register as buildings
import reconstruction_refresh as refresh
import search_server
import shared_data
from test_apartment_reconstruction import ENTITY, entry


def test_report_http_collects_once_then_returns_matching_facts_and_rejects_other_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("ZIPPICK_DATA_MODE", "isolated")
    monkeypatch.setattr(shared_data, "cache_path", lambda name: tmp_path / name)
    monkeypatch.setattr(search_server.budget_candidates, "_find_entities", lambda *args: [ENTITY])
    monkeypatch.setattr(refresh.parcels, "request", lambda entity: False)
    monkeypatch.setattr(refresh.projects, "request", lambda: False)
    monkeypatch.setattr(refresh.ordinances, "request", lambda: False)
    monkeypatch.setattr(buildings, "_JOBS", {})
    monkeypatch.setattr(buildings, "_BLOCKED_UNTIL", 0)
    original = buildings.collect
    calls = []
    def fetcher(*args, **kwargs):
        calls.append(args)
        return entry()["snapshot"]
    monkeypatch.setattr(buildings, "collect", lambda rows: original(rows, fetcher=fetcher))
    server = search_server.SearchServer(("127.0.0.1", 0), search_server.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        params = {"apartment_id": ENTITY["apartmentId"], "name": ENTITY["name"], "region": "서울특별시 노원구",
                  "legal_dong": ENTITY["legalDong"], "jibun": ENTITY["jibun"]}
        base = f"http://127.0.0.1:{server.server_address[1]}/api/apartment-reconstruction?"
        def get(parameters):
            with urlopen(base + urlencode(parameters), timeout=5) as response:
                return json.load(response)
        assert get(params)["reconstructionConditions"]["status"] == "loading"
        buildings._JOBS[reconstruction.parcel_key(ENTITY)][0].result(timeout=5)
        result = get(params)["reconstructionConditions"]
        assert result["apartmentId"] == ENTITY["apartmentId"]
        assert result["profile"]["floorAreaRatio"] == 160
        assert result["profile"]["buildingCoverageRatio"] == 18
        assert result["status"] != "loading"
        assert len(calls) == 1
        with pytest.raises(HTTPError) as error:
            get({**params, "apartment_id": "another-complex"})
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_regional_plan_is_connected_to_the_same_refresh_api_and_reused_across_areas(tmp_path, monkeypatch):
    import collect_regional_reconstruction_plans as regional
    from test_regional_reconstruction_plans import ENTITY as REGIONAL_ENTITY, GG_URL, workbook
    entity = {**REGIONAL_ENTITY, 'households':884, 'cortarNo':'4111710200'}
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated')
    monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    monkeypatch.setattr(search_server.budget_candidates,'_find_entities',lambda *args:[entity])
    for module in (refresh.parcels,refresh.projects,refresh.ordinances,refresh.regional_projects,buildings):
        monkeypatch.setattr(module,'request',lambda *a,**k:False)
    regional._save('gg-renewal',regional.parse_gyeonggi(workbook(),GG_URL))
    raw = entry()
    raw['snapshot']['parcel'] = reconstruction.parcel(entity)
    raw['snapshot']['records'][0].update(reconstruction.parcel(entity),bldNm=entity['name'])
    (tmp_path/reconstruction.FACT_FILE).write_text(json.dumps({'records':{reconstruction.parcel_key(entity):raw}}))
    server=search_server.SearchServer(('127.0.0.1',0),search_server.Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        params={'apartment_id':entity['apartmentId'],'name':entity['name'],'region':entity['district'],
                'legal_dong':entity['legalDong'],'jibun':entity['jibun']}
        results=[]
        for area in ('59','84'):
            url=f'http://127.0.0.1:{server.server_address[1]}/api/apartment-reconstruction?'+urlencode({**params,'area_label':area})
            with urlopen(url,timeout=5) as response:
                results.append(json.load(response)['reconstructionConditions'])
        assert results[0] == results[1]
        assert results[0]['projectPlan']['plannedFloorAreaRatio'] == 250
        assert results[0]['projectPlan']['stageLabel'] == '추진위원회'
        assert results[0]['feasibility']['direction'] == 'favorable'
        assert results[0]['feasibility']['comparison']['siteScopeVerified'] is False
    finally:
        server.shutdown();server.server_close()
