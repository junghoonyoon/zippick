import datetime as dt
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest
import apartment_development as development

ROOT=Path(__file__).resolve().parents[1]
DAY=dt.date(2026,10,20)
SUBJECT={'apartmentId':'11350100002615','name':'삼호4','province':'서울특별시',
         'district':'노원구','legalDong':'월계동','jibun':'12','approvedAt':'1987-07-06'}


def project(**overrides):
    row={'id':'test:one','name':'월계삼호4차아파트 재건축사업',
         'province':'서울특별시','district':'노원구','address':'월계동 12',
         'legalDong':'월계동','jibun':'12','sourcePriority':100,
         'stageLabel':'추진위원회승인','projectTypeLabel':'재건축',
         'sourceUrl':'https://cleanup.seoul.go.kr/cafe/mainIndx.do?cafeUrl=test',
         'sourceDate':None,'checkedAt':'2026-10-20',**overrides}
    row['keys']=development.name_keys(row['name'],row['legalDong'])
    row['addressLots']=development.address_lots(row['address'])
    return row


def registry(*rows):
    by_district,by_address=defaultdict(list),defaultdict(list)
    for row in rows:
        by_district[(row['province'],row['district'])].append(row)
        for dong,lot in row['addressLots']:
            by_address[(row['province'],row['district'],dong,lot)].append(row)
    return {'byDistrict':by_district,'byAddress':by_address,'codes':{},'cached':{},
            'pointCheckedAt':DAY.isoformat(),'points':{},'rows':list(rows)}


@pytest.mark.parametrize('left,right,dong',[
    ('삼호4','월계삼호4차아파트 재건축사업','월계동'),
    ('미성아파트','불광미성아파트 주택재건축정비사업','불광동'),
    ('주공11','상계주공11단지아파트 재건축사업','상계동'),
    ('미륭','월계시영(미륭,미성,삼호3)','월계동'),
    ('하안주공7단지','하안주공6·7단지','하안동'),
    ('목동신시가지아파트7단지','목동7','목동'),
])
def test_name_variations_preserve_actual_complex_number(left,right,dong):
    assert development.name_keys(left,dong) & development.name_keys(right,dong)


def test_full_parcels_and_explicit_excluded_buildings_stay_distinct():
    assert development.address_lots('경동 40번지 및 율목동10-1 일원') == [('경동','40'),('율목동','10-1')]
    assert development.excluded_member('여의도광장(1~2동 제외)',{'name':'광장(1,2동)'})
    assert not development.excluded_member('여의도광장(1~2동 제외)',{'name':'광장(3동)'})
    assert '현대' not in development.name_keys('현대(5차)','가락동')


def test_phase_and_lot_conflicts_do_not_become_own_development():
    for change in ({'name':'월계삼호3차'}, {'district':'은평구'}, {'address':'월계동 13','jibun':'13'},
                   {'address':'상계동 12','legalDong':'상계동'}, {'name':'월계삼호40차'}):
        result=development.for_apartment(SUBJECT,day=DAY,registry=registry(project(**change)))
        assert result['status'] != 'confirmed'
        assert not result['projects']


def test_official_current_business_stage_outranks_old_inventory():
    old=project(id='old',sourcePriority=60,stageLabel='대상지선정',sourceDate='2026-10-13')
    fresh=project()
    result=development.for_apartment(SUBJECT,day=DAY,registry=registry(old,fresh))
    assert result['status']=='confirmed'
    assert result['rating']['points']==2.5
    assert result['projects'][0]['matchedSubjectApartmentId']==SUBJECT['apartmentId']
    assert result['rating']['sourceDate'] is None
    assert result['rating']['checkedAt']=='2026-10-20'
    assert len(result['evidence'])==2


@pytest.mark.parametrize('label',['조합해산','준공인가','조합청산','이전고시','해제','취소'])
def test_completed_or_cancelled_evidence_cannot_revive_old_project(label):
    result=development.for_apartment(SUBJECT,day=DAY,registry=registry(project(stageLabel=label),
        project(id='old',sourcePriority=40,stageLabel='조합설립인가')))
    assert result['status']=='completed_or_cancelled'
    assert not result['projects'] and 'rating' not in result


def test_unknown_or_young_building_and_unconfirmed_stages_are_not_positive():
    for entity in ({**SUBJECT,'approvedAt':''}, {**SUBJECT,'approvedAt':'2022-01-01'},
                   {**SUBJECT,'status':'분양권'}, {**SUBJECT,'apartmentId':''}):
        result=development.for_apartment(entity,day=DAY,registry=registry(project()))
        assert result['status']!='confirmed'
    result=development.for_apartment(SUBJECT,day=DAY,registry=registry(project(stageLabel='조합설립인가 신청')))
    assert result['status']=='confirmed'
    assert result['rating']['points'] is None


def test_joint_group_names_propagate_current_stage_without_merging_subject_ids():
    old=project(id='joint-old',name='월계시영(미륭,미성,삼호3)',address='월계동 13',jibun='13',sourcePriority=60)
    fresh=project(id='joint-live',name='월계시영고층아파트 재건축사업',address='월계동 13',jibun='13')
    for n,name in enumerate(['미륭','미성','삼호3']):
        entity={**SUBJECT,'apartmentId':f'member-{n}','name':name,'jibun':'13'}
        result=development.for_apartment(entity,day=DAY,registry=registry(old,fresh))
        assert result['projects'][0]['id']=='joint-live'
        assert result['projects'][0]['matchedSubjectApartmentId']==f'member-{n}'
        assert result['rating']['points']==2.5


def test_latest_real_sources_link_samho4_and_bulgwang_misung():
    import real_estate_search as search
    for name,dong,lot in [('삼호4','월계동','12'),('미성아파트','불광동','248')]:
        entity=next(e for e in search.APARTMENT_MASTER if e['name']==name and e.get('legalDong')==dong and e.get('jibun')==lot)
        result=development.for_apartment(entity,day=DAY)
        assert result['status']=='confirmed'
        assert result['rating']['points']==2.5
        assert result['projects'][0]['sourceId']=='cleanup-business'


def test_own_evidence_survives_unrelated_living_area_failure(tmp_path,monkeypatch):
    import living_area
    import living_area_context
    def unavailable(*args,**kwargs):
        raise ValueError('test-only living-area failure')
    monkeypatch.setattr(living_area_context,'prepare',unavailable)
    result=living_area.analyze(SUBJECT,path=tmp_path/'absent.sqlite',day=DAY)
    assert result['status']=='error'
    assert result['ownDevelopment']['status']=='confirmed'
    assert result['ownDevelopment']['rating']['points']==2.5


def test_own_evidence_changes_snapshot_and_cannot_attach_to_another_subject(monkeypatch):
    monkeypatch.setattr(development,'for_apartment',lambda *args,**kwargs:{'status':'confirmed','stage':'one'})
    first=development.attach({'apartmentId':SUBJECT['apartmentId'],'snapshotId':'same'},SUBJECT,DAY)
    monkeypatch.setattr(development,'for_apartment',lambda *args,**kwargs:{'status':'confirmed','stage':'two'})
    second=development.attach({'apartmentId':SUBJECT['apartmentId'],'snapshotId':'same'},SUBJECT,DAY)
    assert first['snapshotId']!=second['snapshotId']
    other=development.attach({'apartmentId':'another'},SUBJECT,DAY)
    assert 'ownDevelopment' not in other


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_policy_matches_frontend_and_every_audited_confirmed_apartment_renders():
    html=(ROOT/'앱화면/real-estate-search.html').read_text()
    names=['zippickDevelopmentArticleSignalAllowed','zippickOwnDevelopmentNewsAllowed',
           'zippickValidatedNewsBundle','zippickDevelopmentEvidenceText','zippickDevelopmentExclusionText',
           'zippickDevelopmentRows','zippickConfirmedOwnDevelopmentRow','zippickOwnDevelopmentProgressRow',
           'zippickOwnDevelopmentRows','zippickOwnDevelopmentModel','zippickOwnDevelopmentZones',
           'zippickConfirmedOwnDevelopmentRows','zippickDevelopmentStageTier','zippickDevelopmentProjectWord',
           'zippickDevelopmentRatingView','zippickDevelopmentRatingBasisHtml','zippickDevelopmentHtml',
           'zippickSectionRatingData','zippickSectionRatingHtml','zippickNumberSteps']
    code='\n'.join(re.search(r'    function '+name+r'\(.*?\n    \}',html,re.S).group() for name in names)
    code+='\n'+re.search(r'    const ZIPPICK_DEVELOPMENT_STAGE_RATINGS = \[.*?\n    \];',html,re.S).group()
    code+='\n'+'\n'.join(re.findall(r'    const ZIPPICK_(?:DEVELOPMENT_PATTERN|DEVELOPMENT_EXCLUDED_PATTERN|MINIMUM_ARTICLE_RECONSTRUCTION_AGE) = .*?;',html))
    cases_path=Path('/tmp/zippick-development-render-cases.json')
    if not cases_path.exists():
        pytest.skip('Run scripts/audit-apartment-development.py for full-catalog render verification')
    cases=json.loads(cases_path.read_text())
    assert cases, 'audit must contain actual confirmed apartments'
    code+='\nconst cases='+json.dumps(cases,ensure_ascii=False)+';'
    code+='\nconst expected='+json.dumps(development.policy()['stages'],ensure_ascii=False)+';'
    code+=r'''
const assert=require('node:assert/strict');
const esc=value=>String(value??'').replaceAll('<','&lt;');
const compactText=value=>String(value||'').replace(/\s+/g,'');
const candidateDisplayName=item=>item.name;
const zpJosa=(word,a,b)=>word+a;
const zippickDevelopmentDistanceText=()=>'';
const zippickDevelopmentOfficialType=value=>value;
assert.deepEqual(ZIPPICK_DEVELOPMENT_STAGE_RATINGS,expected);
assert.equal(zippickDevelopmentProjectWord([{title:'인근 재개발 소식'}],[{projectType:'재건축'}]),'재건축');
for (const item of cases) {
  const body=zippickNumberSteps(zippickDevelopmentHtml(item),item);
  assert.match(body,/단지 변화/,item.apartmentId);
  const rating=item.futureTransformation.ownDevelopment.rating;
  if (rating.state==='ready') assert.ok(body.includes(rating.scoreText),item.apartmentId);
  const other={...item,apartmentId:'wrong-apartment'};
  assert.equal(zippickOwnDevelopmentModel(other),null);
  const terminal={...item,futureTransformation:{ownDevelopment:{...item.futureTransformation.ownDevelopment,status:'completed_or_cancelled'}}};
  assert.equal(zippickDevelopmentArticleSignalAllowed(terminal),false);
  assert.equal(zippickDevelopmentHtml(terminal),'');
}
console.log(JSON.stringify({rendered:cases.length}));
'''
    run=subprocess.run(['node'],input=code,text=True,capture_output=True)
    assert run.returncode==0,run.stderr[:3000]
