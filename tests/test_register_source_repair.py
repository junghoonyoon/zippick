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


def test_planning_page_import_parses_the_raw_official_evidence_and_validates_identity(primary):
    import hashlib
    from test_reconstruction_collection import public_html
    raw=public_html();page=primary/'source.html';page.write_bytes(raw)
    pnu=r.parcel_pnu(ENTITY)
    identity={k:ENTITY.get(k,'') for k in ('apartmentId','province','district','legalDong','jibun','cortarNo')}
    item={'file':page.name,'sha256':hashlib.sha256(raw).hexdigest(),'observedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'identity':identity,'sourceUrl':'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp?pnu='+pnu}
    manifest=primary/'manifest.json';manifest.write_text(json.dumps({'pages':{ENTITY['apartmentId']:item}}))
    (primary/r.PLANNING_FILE).write_text(json.dumps({'records':{}}))
    before=(primary/r.PLANNING_FILE).read_bytes()
    assert repair.import_planning_pages(manifest,[ENTITY])['verified']==1
    assert (primary/r.PLANNING_FILE).read_bytes()==before
    result=repair.import_planning_pages(manifest,[ENTITY],apply=True)
    assert result['written']==1
    data=json.loads((primary/r.PLANNING_FILE).read_text())['records'][ENTITY['apartmentId']]
    assert data['parcelReference']['pnu']==pnu and data['parcelReference']['zoneCoverageVerified'] is False
    page.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):repair.import_planning_pages(manifest,[ENTITY])


def test_unpublished_official_parcel_is_not_a_licence_failure_and_never_supplies_facts():
    from pathlib import Path
    import collect_reconstruction_planning as c
    f=json.loads((Path(__file__).parent/'fixtures/unpublished_parcel_20261118.json').read_text())
    with pytest.raises(c.PlanningError) as error:c.parse_public_page(f['htmlExcerpt'],ENTITY)
    assert error.value.status=='no_records' and error.value.code=='parcel_not_published'
    with pytest.raises(c.PlanningError) as missing_title:c.parse_public_page(f['htmlExcerpt'].replace('토지이음','unverified'),ENTITY)
    assert missing_title.value.status=='license_unverified'


def test_unpublished_page_import_preserves_a_prior_success_and_marks_it_stale(primary):
    import hashlib
    from pathlib import Path
    from test_reconstruction_collection import public_html
    import collect_reconstruction_planning as c
    ref=c.parse_public_page(public_html(),ENTITY)
    (primary/r.PLANNING_FILE).write_text(json.dumps({'records':{ENTITY['apartmentId']:{'identity':dict(ENTITY),'parcelReference':ref}}}))
    f=json.loads((Path(__file__).parent/'fixtures/unpublished_parcel_20261118.json').read_text())
    raw=f['htmlExcerpt'].encode('cp949');(primary/'empty.html').write_bytes(raw)
    item={'file':'empty.html','sha256':hashlib.sha256(raw).hexdigest(),'observedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'identity':dict(ENTITY),'sourceUrl':ref['sourceUrl'],'error':{'status':'license_unverified'}}
    manifest=primary/'manifest.json';manifest.write_text(json.dumps({'pages':{ENTITY['apartmentId']:item}}))
    result=repair.import_planning_pages(manifest,[ENTITY],apply=True)
    assert result['classification_no_records']==1 and result.get('verified',0)==0
    record=json.loads((primary/r.PLANNING_FILE).read_text())['records'][ENTITY['apartmentId']]
    assert record['parcelReference']==ref and record['lastError']['status']=='no_records'


def test_explicit_official_no_parcel_result_keeps_missing_data_distinct_from_licence():
    from pathlib import Path
    import collect_reconstruction_planning as c
    f=json.loads((Path(__file__).parent/'fixtures/missing_parcel_20261118.json').read_text())
    with pytest.raises(c.PlanningError) as error:c.parse_public_page(f['htmlExcerpt'],ENTITY)
    assert error.value.status=='no_records' and error.value.code=='parcel_not_found'


@pytest.mark.parametrize('stale',[False,True])
def test_manual_ordinance_does_not_hide_independent_public_parcel_land(primary,monkeypatch,stale):
    day=dt.date(2026,11,18)
    title=source();title['snapshot']['records'][0]['platArea']=0
    (primary/repair.single.FILE).write_text(json.dumps({'records':{ENTITY['apartmentId']:title}}))
    pnu=r.parcel_pnu(ENTITY)
    ref={'kind':'parcel_zoning','pnu':pnu,'scope':'representative_parcel',
         'zoneCoverageVerified':False,'license':'공공누리 출처표시',
         'sourceUrl':'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp?pnu='+pnu,
         'checkedAt':'2026-11-18' if not stale else '2020-01-01',
         'parcelAreaSqm':10000,'zoneNames':['제3종일반주거지역'],'districtPlans':[]}
    context={'identity':dict(ENTITY),'parcelReference':ref}
    manual={'kind':'ordinance_reference','parcelAreaSqm':9000,'floorAreaRatio':250,
            'buildingCoverageRatio':50,'zoneName':'제3종일반주거지역'}
    monkeypatch.setattr(r,'_planning_reference',lambda *a,**kw:manual)
    monkeypatch.setattr(r.reconstruction_project_plans,'for_apartment',lambda *a,**kw:{'status':'out_of_coverage'})
    result=r._conditions(ENTITY,context=context,day=day)
    assert result['planningReference']==manual
    if stale:
        assert not result['profile']
    else:
        assert result['profile']['floorAreaRatio']==200
        assert result['profile']['landAreaSqm']==10000
        assert result['profile']['fieldSources']['landAreaSqm']['method']=='independent_official_parcel_area'
