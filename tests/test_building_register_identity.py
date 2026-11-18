import copy
import datetime as dt
import json
from pathlib import Path
import pytest
import apartment_identity
import apartment_reconstruction as r
import building_register_identity as bridge
import building_register_single_site as single
from test_building_register_single_site import source,ENTITY,DAY

HW={'apartmentId':'41590120324058','name':'동탄역 시범 더샵 센트럴시티','province':'경기도','district':'화성시','city':'화성시','legalDong':'청계동','jibun':'519','cortarNo':'4159013000','households':874,'address':'경기도 화성시 청계동 519'}

def test_explicit_official_dong_change_keeps_lot_and_site_identity():
    p=r.parcel(HW);variants=bridge.variants(HW,p,day=DAY)
    assert variants[-1]=={**p,'sigunguCd':'41597','bjdongCd':'10500'}
    assert HW['district']=='화성시' and HW['cortarNo']=='4159013000'
    assert bridge.query_entity(HW,day=DAY)['district']=='화성시 동탄구'
    assert bridge.pnu_variants(HW,p,day=DAY)==['4159013000105190000','4159710500105190000']

@pytest.mark.parametrize('change',['wrong_dong','wrong_province','future','split'])
def test_unverified_or_split_dong_is_never_guessed(change):
    e=copy.deepcopy(HW);day=DAY
    if change=='wrong_dong':e['legalDong']='다른동'
    elif change=='wrong_province':e['province']='서울특별시'
    elif change=='future':day=dt.date(2026,1,1)
    else:e.update(cortarNo='4159011800',legalDong='능동')
    assert bridge.variants(e,r.parcel(e),day=day)==[r.parcel(e)]


def test_chained_official_name_change_and_mountain_subparcel_are_lossless():
    e={**HW,'cortarNo':'4159012900','legalDong':'오산동','jibun':'산10-2','address':'경기도 화성시 오산동 산10-2'}
    p=bridge.variants(e,r.parcel(e),day=DAY)[-1]
    assert (p['sigunguCd'],p['bjdongCd'],p['platGbCd'],p['bun'],p['ji'])==('41597','11500','1','0010','0002')
    q=bridge.query_entity(e,day=DAY)
    assert q['legalDong']=='여울동' and q['address']=='경기도 화성시 동탄구 여울동 산10-2'


def test_new_code_recap_is_not_a_different_parcel_and_old_success_is_preserved():
    new=copy.deepcopy(source());p=bridge.variants(HW,r.parcel(HW),day=DAY)[-1]
    row=new['snapshot']['records'][0];row.update(p,regstrKindCd='1',bldNm=HW['name'],hhldCnt=874)
    new['snapshot'].update(recordType='recap',parcel=p)
    assert r.profile(HW,new)['floorAreaRatio']==200
    assert r.register_entry(HW,{bridge.parcel_key(p):new}) is new
    old=copy.deepcopy(new);old['snapshot']['parcel']=r.parcel(HW);old['snapshot']['records'][0].update(r.parcel(HW))
    assert r.register_entry(HW,{bridge.parcel_key(r.parcel(HW)):old,bridge.parcel_key(p):new}) is old
    new['snapshot']['records'][0]['ji']='0001'
    assert r.profile(HW,new)['status']=='identity_unverified'


def basic(entry):
    entry=copy.deepcopy(entry);entry['snapshot']['records'][0]['bldNm']=''
    entry['officialBasic']={'sourceUrl':'https://www.data.go.kr/data/15106861/fileData.do','sourceDate':'2026-08-31','sourceSha256':'a'*64,'record':{'단지고유번호':ENTITY['apartmentId'],'필지고유번호':r.parcel_pnu(ENTITY),'세대수':'100','단지명_공시가격':ENTITY['name']}}
    return entry


def test_blank_title_name_requires_independent_exact_official_identity():
    e=basic(source());assert single.profile(ENTITY,r.parcel(ENTITY),e,day=DAY)['floorAreaRatio']==200
    del e['officialBasic'];assert single.profile(ENTITY,r.parcel(ENTITY),e,day=DAY) is None

@pytest.mark.parametrize('field,value',[('단지고유번호','wrong'),('필지고유번호','1135010200103200012'),('세대수','99'),('단지명_공시가격','검증4차')])
def test_blank_name_corroboration_rejects_every_identity_conflict(field,value):
    e=basic(source());e['officialBasic']['record'][field]=value
    assert single.profile(ENTITY,r.parcel(ENTITY),e,day=DAY) is None


def test_corroborated_title_does_not_erase_attached_parcel_ambiguity():
    e=basic(source());e['snapshot']['records'][0]['bylotCnt']=1
    assert single.profile(ENTITY,r.parcel(ENTITY),e,day=DAY) is None


def test_all_official_block_parcel_corrections_require_the_original_identity():
    path=Path(__file__).resolve().parents[1]/'data/apartment_identity_corrections.json'
    for row in json.loads(path.read_text())['corrections'].values():
        raw=row['record'];e={**row['expected'],'name':raw['단지명_공시가격'] or raw['단지명_도로명주소'],'aliases':[]}
        fixed=apartment_identity.corrected_entity(e)
        assert fixed['jibun']==row['jibun'] and fixed['cortarNo']==row['cortarNo']
        assert r.parcel(fixed)
        wrong={**e,'households':e['households']+1}
        assert apartment_identity.corrected_entity(wrong)==wrong


def test_changed_code_is_used_by_the_real_report_http_collector(tmp_path,monkeypatch):
    import threading
    from urllib.request import urlopen
    from urllib.parse import urlencode
    import shared_data,search_server,collect_building_register as collector,reconstruction_refresh as refresh
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated')
    monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    monkeypatch.setattr(search_server.budget_candidates,'_find_entities',lambda *a:[HW])
    for module in (refresh.parcels,refresh.projects,refresh.ordinances):monkeypatch.setattr(module,'request',lambda *a,**k:False)
    monkeypatch.setattr(collector,'_JOBS',{});monkeypatch.setattr(collector,'_BLOCKED_UNTIL',0)
    p=bridge.variants(HW,r.parcel(HW),day=DAY)[-1];entry=copy.deepcopy(source());entry['snapshot'].update(parcel=p,recordType='recap')
    entry['snapshot']['records'][0].update(p,regstrKindCd='1',bldNm=HW['name'],hhldCnt=874)
    original=collector.collect;calls=[]
    def provider(*args,**kw):calls.append(args);return entry['snapshot']
    monkeypatch.setattr(collector,'collect',lambda entities:original(entities,fetcher=provider))
    server=search_server.SearchServer(('127.0.0.1',0),search_server.Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    params=urlencode({'apartment_id':HW['apartmentId'],'name':HW['name'],'region':'화성시','legal_dong':HW['legalDong'],'jibun':HW['jibun']})
    url=f'http://127.0.0.1:{server.server_address[1]}/api/apartment-reconstruction?'+params
    try:
        with urlopen(url,timeout=5) as response:json.load(response)
        collector._JOBS[bridge.parcel_key(p)][0].result(timeout=5)
        with urlopen(url,timeout=5) as response:model=json.load(response)['reconstructionConditions']
        assert model['profile']['floorAreaRatio']==200
        assert calls[0][:2]==('41597','10500')
        assert model['apartmentId']==HW['apartmentId']
    finally:server.shutdown();server.server_close()


def test_bulk_month_archive_preserves_reference_month_and_imports_exact_new_code(tmp_path,monkeypatch):
    import zipfile,shared_data,import_building_register_bulk as bulk
    monkeypatch.setenv('ZIPPICK_DATA_MODE','isolated');monkeypatch.setattr(shared_data,'cache_path',lambda name:tmp_path/name)
    p=bridge.variants(HW,r.parcel(HW),day=DAY)[-1]
    values=['']*64
    row={**p,'mgmBldrgstPk':'actual','regstrKindCd':'1','bldNm':HW['name'],'mainPurpsCdNm':'공동주택','hhldCnt':'874','platArea':'10000','archArea':'2000','vlRatEstmTotArea':'20000','vlRat':'200','bcRat':'20','mainBldCnt':'5'}
    for index,key in bulk.FIELDS.items():values[index]=str(row.get(key,''))
    path=tmp_path/'public.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('mart_djy_02.txt','|'.join(values)+'\n')
    result=bulk.import_archive(path,[HW],'2026-09')
    assert result['inserted']==1
    entry=json.loads((tmp_path/r.FACT_FILE).read_text())['records'][bridge.parcel_key(p)]
    assert entry['snapshot']['referenceMonth']=='2026-09'
    assert entry['snapshot']['referenceDatePrecision']=='month'
    assert entry['snapshot']['fetchedAt'][:10]!= '2026-09-30'
    assert r.profile(HW,entry)['mainBuildingCount']==5
    assert bulk.import_archive(path,[HW],'2026-09')['preserved']==1
