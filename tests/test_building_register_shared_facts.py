"""Production and local readers share verified attributes without inventing areas."""
import copy
import datetime as dt
import json
from pathlib import Path
import pytest
import apartment_reconstruction as r
import building_register_crosscheck as cross

ROOT=Path(__file__).parent/'fixtures'
CASES=json.loads((ROOT/'registered_ratio_crosschecks_20261117.json').read_text())['cases']
DAY=dt.date(2026,11,18)

@pytest.mark.parametrize('case',CASES,ids=[x['entity']['apartmentId'] for x in CASES])
def test_all_actual_registered_ratio_confirmations_keep_unknown_physical_areas_excluded(case):
    before=copy.deepcopy(case)
    p=cross.apply(case['entity'],case['profile'],case['crosscheck'],day=DAY)
    assert p['floorAreaRatio']>0
    issue=next(x for x in p['fieldIssues'] if x['field']=='floorAreaRatio')
    assert issue['resolvedValue']==issue['reportedValue'] and cross.resolved(issue)
    assert p['fieldSources']['floorAreaRatio']['scope']=='whole_registered_site'
    if p.get('areaIntegrity',{}).get('status')=='unresolved':
        assert p['landAreaSqm'] is p['floorAreaForRatioSqm'] is None
        assert p['originalLandAreaSqm']>0
    assert case==before

@pytest.mark.parametrize('change',['id','parcel','households','source','date','ratio','entry_identity'])
def test_wrong_municipal_record_never_overrides_unverified_values(change):
    c=copy.deepcopy(next(x for x in CASES if x['entity']['apartmentId']=='11170120286127'))
    s=c['crosscheck']['municipalRecap'];row=s['records'][0]
    if change=='id':row['건축물대장일련번호']='other'
    elif change=='parcel':row['주지번']='0410'
    elif change=='households':row['세대수']='560'
    elif change=='source':s['sourceUrl']='https://example.com'
    elif change=='date':s['fetchedAt']='2025-01-01'
    elif change=='ratio':row['용적률']='800'
    else:c['crosscheck']['identity']['jibun']='410'
    assert cross.apply(c['entity'],c['profile'],c['crosscheck'],day=DAY)['floorAreaRatio'] is None


def test_missing_area_never_makes_an_unverified_site_limit_look_matched(monkeypatch):
    h=json.loads((ROOT/'hansol4_register_20261117.json').read_text())
    c=next(x for x in CASES if x['entity']['apartmentId']==h['entity']['apartmentId'])
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated')
    monkeypatch.setattr(cross,'entry_for',lambda entity:c['crosscheck'])
    monkeypatch.setattr(r.reconstruction_project_plans,'for_apartment',lambda *a,**kw:{'status':'out_of_coverage'})
    context={'identity':dict(h['entity']),'basis':{'kind':'current_limit','siteScopeVerified':True,
       'landAreaSqm':None,'floorAreaRatio':300,'checkedAt':'2026-11-18','sourceUrl':'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp'}}
    model=r._conditions(h['entity'],h['entry'],context,day=DAY)
    assert model['profile']['floorAreaRatio']==148.11
    assert model['profile']['landAreaSqm'] is None
    assert model.get('basis') is None and model['status']!='ready'


def test_both_readers_share_one_versioned_raw_store(tmp_path,monkeypatch):
    import shared_data
    import building_register_single_site as single
    path=tmp_path/cross.FILE
    value={'identity':{'apartmentId':'shared'},'status':'ok'}
    path.write_text(json.dumps({'records':{'shared':value}}))
    monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    single._read.cache_clear()
    entity={'apartmentId':'shared'}
    assert cross.entry_for(entity) is single.entry_for(entity)
    assert single._read.cache_info().misses==1
