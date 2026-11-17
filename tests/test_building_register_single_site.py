"""A sole complete official title can identify a site; mixed/missing scopes cannot."""
import copy
import datetime as dt
import json
import pytest
import apartment_reconstruction as r
import building_register_single_site as single
import shared_data

DAY=dt.date(2026,11,18)
ENTITY={'apartmentId':'unit-sole','name':'검증3차','province':'서울특별시','district':'노원구',
        'legalDong':'월계동','jibun':'320-11','cortarNo':'1135010200','households':100,'approvedAt':'1992-04-27'}


def source():
    parcel=r.parcel(ENTITY)
    row={**parcel,'mgmBldrgstPk':'title-1','regstrKindCd':'3','mainAtchGbCd':'0',
         'mainPurpsCdNm':'공동주택','bldNm':'검증3차 아파트','hhldCnt':100,
         'platArea':10000,'archArea':2000,'vlRatEstmTotArea':20000,'vlRat':200,'bcRat':20,
         'bylotCnt':0,'atchBldCnt':0,'atchBldArea':0,'grndFlrCnt':10,'useAprDay':'19920427'}
    return {'status':'ok','identity':dict(ENTITY),'snapshot':{'parcel':parcel,'recordType':'title',
        'sourceUrl':'https://www.data.go.kr/data/15134735/openapi.do','fetchedAt':'2026-11-18',
        'source':'국토교통부 건축HUB 건축물대장 표제부','totalCount':1,'records':[row]}}


def profile(entry=None):return single.profile(ENTITY,r.parcel(ENTITY),entry or source(),day=DAY)


def test_complete_single_title_supplies_only_the_reported_whole_site_ratios():
    p=profile()
    assert p['floorAreaRatio']==200 and p['buildingCoverageRatio']==20
    assert p['mainBuildingCount']==1 and p['households']==100
    assert p['scope']=='whole_registered_site' and p['recordType']=='title'
    assert p['fieldSources']['floorAreaRatio']['scope']=='sole_main_building_whole_site'
    assert p['floorAreaForRatioSqm']==20000 and p['landAreaSqm']==10000


@pytest.mark.parametrize('change',[
    'second_building','annex','missing_page','wrong_identity','wrong_parcel','wrong_name','wrong_phase',
    'wrong_households','unknown_households','wrong_kind','not_main','not_residential','no_land',
    'zero_far','zero_coverage','bad_far','bad_coverage','unofficial','stale','old_reference_month',
    'attached_parcel','unregistered_annex','unknown_parcel_extent','failed','wrong_record_type','malformed_snapshot','malformed_identity',
])
def test_no_other_scope_or_unverified_ratio_can_enter_the_report(change):
    e=source();s=e['snapshot'];x=s['records'][0]
    if change in ('second_building','annex'):
        other={**x,'mgmBldrgstPk':'second'}
        if change=='annex':other.update(mainAtchGbCd='1',hhldCnt=0)
        s['records'].append(other);s['totalCount']=2
    elif change=='missing_page':s['totalCount']=2
    elif change=='wrong_identity':e['identity']['apartmentId']='another'
    elif change=='wrong_parcel':x['ji']='0012'
    elif change=='wrong_name':x['bldNm']='다른3차'
    elif change=='wrong_phase':x['bldNm']='검증4차'
    elif change=='wrong_households':x['hhldCnt']=99
    elif change=='unknown_households':x['hhldCnt']=0
    elif change=='wrong_kind':x['regstrKindCd']='1'
    elif change=='not_main':x['mainAtchGbCd']='1'
    elif change=='not_residential':x['mainPurpsCdNm']='업무시설'
    elif change=='no_land':x['platArea']=0
    elif change=='zero_far':x['vlRat']=0
    elif change=='zero_coverage':x['bcRat']=0
    elif change=='bad_far':x['vlRat']=220
    elif change=='bad_coverage':x['bcRat']=120
    elif change=='unofficial':s['sourceUrl']='https://example.com'
    elif change=='stale':s['fetchedAt']='2025-11-18'
    elif change=='old_reference_month':s['referenceMonth']='2025-09'
    elif change=='attached_parcel':x['bylotCnt']=1
    elif change=='unregistered_annex':x['atchBldCnt']=1
    elif change=='unknown_parcel_extent':x.pop('bylotCnt')
    elif change=='failed':e['lastError']={'status':'connection_error'}
    elif change=='wrong_record_type':s['recordType']='recap'
    elif change=='malformed_snapshot':e['snapshot']=['bad']
    elif change=='malformed_identity':e['identity']=['bad']
    assert profile(e) is None


@pytest.mark.parametrize('recap_state',[None,'no_records','connection_error','identity_unverified'])
def test_shared_source_fallback_never_masks_a_live_connection_or_identity_failure(tmp_path,monkeypatch,recap_state):
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated')
    monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    monkeypatch.setattr(r.reconstruction_project_plans,'for_apartment',lambda *a,**kw:{'status':'out_of_coverage'})
    p=tmp_path/single.FILE;p.write_text(json.dumps({'records':{ENTITY['apartmentId']:source()}}))
    facts={} if recap_state is None else {'records':{r.parcel_key(ENTITY):{'status':recap_state}}}
    (tmp_path/r.FACT_FILE).write_text(json.dumps({'records':{}} if recap_state is None else facts))
    model=r._conditions(ENTITY,context={},day=DAY)
    if recap_state in (None,'no_records'):
        assert model['profile']['floorAreaRatio']==200
        assert model['profile']['recordType']=='title'
    else:
        assert not model['profile']
        assert model['status']==recap_state
