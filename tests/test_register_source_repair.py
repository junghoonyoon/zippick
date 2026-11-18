import copy,datetime as dt,json
import pytest
import repair_register_sources as repair
import shared_data,building_hub,apartment_reconstruction as r
from test_building_register_single_site import ENTITY,source

@pytest.fixture
def primary(tmp_path,monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated')
    monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    (tmp_path/r.FACT_FILE).write_text(json.dumps({'records':{}}))
    (tmp_path/repair.single.FILE).write_text(json.dumps({'records':{}}))
    return tmp_path


def test_gap_collection_preserves_concurrent_official_corroboration(primary,monkeypatch):
    original=source();path=primary/repair.single.FILE
    def fetch(*a,**k):
        path.write_text(json.dumps({'records':{ENTITY['apartmentId']:{'officialBasic':{'verified':'new'}}}}))
        return original['snapshot']
    monkeypatch.setattr(building_hub,'fetch_title_records',fetch)
    result=repair.collect_title_gaps([ENTITY],apply=True)
    record=json.loads(path.read_text())['records'][ENTITY['apartmentId']]
    assert result['success']==1 and record['officialBasic']=={'verified':'new'}
    assert record['snapshot']==original['snapshot']


def test_gap_auth_failure_stops_and_keeps_durable_diagnostic(primary,monkeypatch):
    def denied(*a,**k):raise building_hub.BuildingHubError('permission denied',code='403')
    monkeypatch.setattr(building_hub,'fetch_title_records',denied)
    result=repair.collect_title_gaps([ENTITY,{**ENTITY,'apartmentId':'next'}],apply=True)
    assert result['processed']==1 and result['unprocessed']==1 and result['stoppedCode']=='403'
    pending=json.loads((primary/'building_register_gap_pending.json').read_text())
    assert pending['records'][ENTITY['apartmentId']]['lastError']['status']=='access_denied'


def test_gap_dry_run_does_not_fetch_or_write(primary,monkeypatch):
    before={p.name:p.read_bytes() for p in primary.iterdir()}
    monkeypatch.setattr(building_hub,'fetch_title_records',lambda *a,**k:pytest.fail('network call in dry run'))
    assert repair.collect_title_gaps([ENTITY])['targets']==1
    assert before=={p.name:p.read_bytes() for p in primary.iterdir()}
