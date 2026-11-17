"""Official city spelling and verified source identities must survive all consumers."""
import datetime as dt
import json
from pathlib import Path
import pytest
import collect_reconstruction_planning as parcels
import real_estate_search as search
from test_reconstruction_collection import public_html

@pytest.mark.parametrize('city,district,official',[
    ('성남시','성남분당구','성남시 분당구'),
    ('수원시','수원영통구','수원시 영통구'),
    ('고양시','고양일산동구','고양시 일산동구'),
])
def test_canonical_city_district_still_requires_exact_dong_and_parcel(city,district,official):
    e={'province':'경기도','city':city,'district':district,'legalDong':'백현동','jibun':'542','cortarNo':'4113511000'}
    raw=public_html(address=f'경기도 {official} 백현동 542')
    value=parcels.parse_public_page(raw,e,day=dt.date(2026,11,18))
    assert value['pnu']=='4113511000105420000'
    assert value['address']==f'경기도 {official} 백현동 542'
    assert value['scope']=='representative_parcel' and value['zoneCoverageVerified'] is False
    for bad in (f'경기도 {official} 백현동 543',f'경기도 {official} 정자동 542','경기도 용인시 수지구 백현동 542'):
        with pytest.raises(parcels.PlanningError) as exc:parcels.parse_public_page(public_html(address=bad),e)
        assert exc.value.status=='identity_unverified'


def test_city_spelling_is_not_guessed_without_catalogue_evidence():
    e={'province':'경기도','district':'성남분당구','legalDong':'백현동','jibun':'542','cortarNo':'4113511000'}
    with pytest.raises(parcels.PlanningError):parcels.parse_public_page(public_html(address='경기도 성남시 분당구 백현동 542'),e)


def test_recovered_complexes_use_the_exact_2026_official_identity():
    data=json.loads((Path(__file__).parent/'fixtures/identity_recovery_20261118.json').read_text())
    assert len(data['records'])==12
    for source in data['records']:
        matches=[e for e in search.APARTMENT_MASTER if e.get('apartmentId')==source['단지고유번호']]
        assert len(matches)==1
        e=matches[0];pnu=source['필지고유번호']
        assert e['cortarNo']==pnu[:10]
        assert e['households']==int(source['세대수'])
        assert e['approvedAt']==source['사용승인일']
        assert e['address']==source['주소']
        assert e['status']=='사용승인' and not e['plannedMoveInMonth']


def test_rural_address_uses_the_catalogue_eup_but_keeps_ri_and_actual_lot_exact():
    e={'apartmentId':'rural','province':'경기도','city':'가평군','district':'가평군',
       'legalDong':'읍내리','jibun':'읍내리 299-3','cortarNo':'4182025021',
       'address':'경기도 가평군 가평읍 읍내리 299-3'}
    ref=parcels.parse_public_page(public_html(address=e['address']),e)
    assert ref['address']==e['address'] and ref['pnu']=='4182025021102990003'
    for bad in ('경기도 가평군 설악면 읍내리 299-3','경기도 가평군 가평읍 읍내리 299-4','경기도 가평군 가평읍 대곡리 299-3'):
        with pytest.raises(parcels.PlanningError):parcels.parse_public_page(public_html(address=bad),e)
    for bad_metadata in ('경기도 가평군 가평읍 읍내리 299-4','경기도 양평군 가평읍 읍내리 299-3'):
        with pytest.raises(parcels.PlanningError):
            parcels.parse_public_page(public_html(address=bad_metadata),{**e,'address':bad_metadata})


def test_regenerating_the_supplement_keeps_verified_identity_and_completed_status():
    import copy
    import build_presale_supplement as builder
    fixture=json.loads((Path(__file__).parent/'fixtures/identity_recovery_20261118.json').read_text())
    expected={x['단지고유번호'] for x in fixture['records']}
    rows=[x for x in builder.existing_candidates(builder.SUPPLEMENT_PATH) if x.get('단지고유번호') in expected]
    assert len(rows)==12
    original=copy.deepcopy(rows[0])
    fresh=copy.deepcopy(original)
    fresh.update({'단지고유번호':'','필지고유번호':'','사용승인일':'','출처':'국토교통부 분양권/입주권 실거래',
                  '상태':'분양권','입주예정월':'2027-01','최근분양권거래일':'2026-11-18',
                  '_priority':1,'_source_keys':{'국토교통부 분양권/입주권 실거래'}})
    rebuilt=builder.finalize(builder.merge_candidates([copy.deepcopy(original),fresh]))
    assert len(rebuilt)==1
    row=rebuilt[0]
    for key in ('단지고유번호','필지고유번호','사용승인일'):
        assert row[key]==original[key]
    assert row['상태']=='사용승인' and row['입주예정월']==''
    other=copy.deepcopy(fresh);other['지번']='9999'
    assert len(builder.merge_candidates([copy.deepcopy(original),other]))==2
    other=copy.deepcopy(fresh);other['세대수']='9999'
    assert len(builder.merge_candidates([copy.deepcopy(original),other]))==2
