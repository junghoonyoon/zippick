import datetime as dt
import json
from unittest.mock import patch

import living_area_metro as metro
import redevelopment_completion as completion
import redevelopment_occupancy as occupancy
import search_server
from shapely.geometry import Point,box
from pyproj import Transformer
from shapely import transform


def test_existing_supply_does_not_hide_a_new_reconstruction_or_neighbouring_phase():
    forward=Transformer.from_crs(4326,5179,always_xy=True).transform
    geom=transform(box(127,37.5,127.002,37.502),forward,interleaved=False)
    row={'id':'supply','name':'테스트1단지(6차공급)','sourceName':'테스트1단지(6차공급)',
         'projectTypeLabel':'미리내집','stage':'construction','stageLabel':'입주자 모집공고 완료'}
    apt={'apt_cd':'A1','apt_nm':'테스트1단지아파트','emd_addr':'테스트동','apt_rdn_addr':'공식 주소'}
    rebuild={**row,'id':'new','name':'테스트1단지 재건축','projectTypeLabel':'재건축(공동)','stageLabel':'조합설립인가'}
    next_phase={**row,'id':'phase2','name':'테스트2단지','projectTypeLabel':'재개발(주택정비형)'}
    with patch.object(completion,'approved_apartments',return_value=[(apt,Point(127.001,37.501),'2000-01-01')]):
        kept,_,audit=completion.filter_boundaries([row,rebuild,next_phase],[geom,geom,geom.buffer(300)],[],lambda *a:(None,None))
    assert {x['id'] for x in kept}=={'new','phase2'}
    assert audit['excludedBoundaries'][0]['evidence']['kaptCode']=='A1'


def test_same_name_far_away_is_not_retired():
    row={'id':'supply','name':'테스트1단지','sourceName':'테스트1단지','projectTypeLabel':'장기전세주택'}
    apt={'apt_cd':'A1','apt_nm':'테스트1단지','emd_addr':'다른동','apt_rdn_addr':'다른 주소'}
    with patch.object(completion,'approved_apartments',return_value=[(apt,Point(128,37),'2000-01-01')]):
        kept,_,_=completion.filter_boundaries([row],[box(0,0,1,1)],[],lambda *a:(None,None))
    assert kept==[row]


def test_all_completed_variants_are_absent_from_maps_and_lists():
    payload=search_server._redevelopment_zones_payload({'limit':['3000']})
    visible={z['id'] for z in payload['zones']}
    expected={'11000UQ120PS202407010642', # 중화1
              '11000UQ120PS202407010571','11000UQ120PS202407010612', # 이문 3-1/3-2
              '11000UQ120PS202602240068','11000UQ120PS202505311100', # 길음센터피스 공급차수
              'gg-zone:13:5505','gg-zone:13:5508', # 포레스티아 경계 두 조각
              'gg-zone:13:5537','gg-zone:13:5646','gg-zone:13:5678',
              'gg-zone:13:5733','gg-zone:13:5772', # completed projects missed by earlier boundary matching
              'gg-zone:13:5502','gg-zone:13:5529','gg-zone:13:5535','gg-zone:13:5539',
              'gg-zone:13:5540','gg-zone:13:5547','gg-zone:13:5556','gg-zone:13:5558',
              'gg-zone:13:5568','gg-zone:13:5569',
              'gg-zone:13:5573','gg-zone:13:5575','gg-zone:13:5624',
              'gg-zone:13:5622','gg-zone:13:5625','gg-zone:13:5656','gg-zone:13:5759',
              'gg-zone:13:5472','gg-zone:13:5632',
              'gg-zone:15:1601','gg-zone:15:1602'}
    assert not visible.intersection(expected)
    assert all(not any(k in z['name'].replace(' ','') for k in ('리버센','이문아이파크자이','래미안길음센터피스')) for z in payload['zones'])
    assert '11230UQ120PS202603170001' in visible # 이문4는 진행 중
    assert 'gg-zone:13:5504' in visible # 산성 헤리스톤 공사 구역은 유지
    assert 'gg-zone:13:5670' in visible # 능곡6 is a separate active project
    assert 'gg-zone:13:5675' in visible # 능곡2 is active; nearby occupied ability is not the same site
    assert 'gg-zone:13:5570' in visible # 미륭아파트 재건축 is active, not the nearby completed 석수주공3 project
    assert 'gg-zone:13:5469' in visible # 113-12's other similar-area boundary is over 6km away
    assert 'gg-zone:13:5608' in visible # generic boundary stays when a named completed-project boundary is distinct


def test_reviewed_completion_cannot_return_through_curated_points_or_regional_list():
    data=json.loads(occupancy.OVERRIDES_PATH.read_text())
    row=next(r for r in data['entries'] if r['zoneName']=='반포주공1단지(3주구)')
    identity=row['projectIdentities'][0]
    project=next(p for p in metro.catalog()['projects'] if p['id']==identity['id'])
    assert project['stage']=='construction' # stale source must not revive the project
    center={'latitude':row['latitude']+.003,'longitude':row['longitude']}
    subject={'apartmentId':'test','province':'서울특별시','district':'서초구','legalDong':'반포동','jibun':'99999'}
    result=metro.attach({'snapshotId':'test','center':center,'projects':[project]},subject,dt.date.today())
    for field in ('projects','referenceProjects','regionalProjects'):
        assert identity['id'] not in {p['id'] for p in result.get(field,[])}


def test_split_boundaries_need_full_name_district_and_total_area():
    rows=[{'id':str(i),'sourceId':'gg-plan-boundary','businessNameConfirmed':True,
           'sourceName':'신흥 주택재건축 정비구역','districtCode':'41130','sourceLayer':13,
           'siteAreaM2':area} for i,area in enumerate((6000,175000))]
    p={'id':'finished','name':'신흥주택재건축','province':'경기도','region':'성남수정구',
       'siteAreaM2':181000,'stage':'completed'}
    geoms=[box(0,0,10,10),box(10,0,20,10)]
    assert set(completion.completed_boundary_groups(rows,geoms,[p],[]))=={0,1}
    for change in ({'name':'신흥2주택재건축'},{'siteAreaM2':190000},{'region':'광명시'},{'stage':'construction'}):
        assert not completion.completed_boundary_groups(rows,geoms,[{**p,**change}],[])


def test_unnamed_completed_boundary_needs_unique_area_district_and_nearby_site():
    row={'id':'anonymous','sourceId':'gg-plan-boundary','businessNameConfirmed':False,
         'sourceName':'정비구역','districtCode':'41280','sourceLayer':13,'siteAreaM2':33263}
    geometry=box(0,0,100,100)
    project={'id':'finished','name':'능곡연합','province':'경기도','region':'고양덕양구',
             'projectType':'reconstruction','stage':'completed','stageLabel':'준공','siteAreaM2':33263}
    points=[(project,Point(101,50))]
    assert completion.nearby_completed_boundary_groups([row],[geometry],[project],points)=={0:project}
    far=[(project,Point(351,50))]
    assert not completion.nearby_completed_boundary_groups([row],[geometry],[project],far)
    wrong_district={**project,'region':'광명시'}
    assert not completion.nearby_completed_boundary_groups([row],[geometry],[wrong_district],[(wrong_district,Point(101,50))])
    active={**project,'stage':'construction'}
    assert not completion.nearby_completed_boundary_groups([row],[geometry],[active],[(active,Point(101,50))])
    ambiguous={'id':'other','name':'두산아파트','province':'경기도','region':'고양덕양구',
               'projectType':'reconstruction','stage':'completed','stageLabel':'준공','siteAreaM2':33263}
    assert not completion.nearby_completed_boundary_groups([row],[geometry],[project,ambiguous],
        [(project,Point(101,50)),(ambiguous,Point(102,50))])


def test_unnamed_completed_boundary_without_project_coordinates_needs_a_strict_one_to_one_area_match():
    row={'id':'anonymous','sourceId':'gg-plan-boundary','businessNameConfirmed':False,
         'sourceName':' ','name':'정비구역','districtCode':'41170','sourceLayer':13,
         'siteAreaM2':52222.94}
    project={'id':'finished','name':'비산2동주민자치센터주변','province':'경기도','region':'안양만안구',
             'projectType':'reconstruction','stage':'completed','stageLabel':'준공',
             'siteAreaM2':52223.0,'plannedHouseholds':1199}
    assert completion.unique_completed_area_boundary_groups([row],[project],[])=={0:project}
    same_area={'id':'ambiguous','name':'다른 완료 사업','province':'경기도','region':'안양만안구',
               'projectType':'reconstruction','stage':'completed','stageLabel':'준공',
               'siteAreaM2':52223.0,'plannedHouseholds':500}
    assert not completion.unique_completed_area_boundary_groups([row],[project,same_area],[])
    assert not completion.unique_completed_area_boundary_groups([row,row],[project],[])
    far_project={**project,'siteAreaM2':52320.0}
    assert not completion.unique_completed_area_boundary_groups([row],[far_project],[])
    assert not completion.unique_completed_area_boundary_groups([row],[project],[(project,Point(0,0))])


def test_named_alias_can_link_to_a_completed_project_by_unique_area():
    row={'id':'alias','sourceId':'gg-plan-boundary','businessNameConfirmed':True,
         'sourceName':'중앙생활권 3구역','name':'중앙생활권 3구역',
         'districtCode':'41150','sourceLayer':13,'siteAreaM2':36190.72}
    project={'id':'finished','name':'중앙3구역','province':'경기도','region':'의정부시',
             'projectType':'redevelopment','stage':'completed','stageLabel':'준공',
             'siteAreaM2':36192.5,'plannedHouseholds':926}
    assert completion._same_area_project_name(row['sourceName'],project)
    assert completion.unique_completed_area_boundary_groups([row],[project],[])=={0:project}


def test_named_completed_boundary_wins_over_anonymous_area_collision():
    project={'id':'finished','name':'광육재건축단지','province':'경기도','region':'광명시',
             'projectType':'reconstruction','stage':'completed','stageLabel':'준공',
             'siteAreaM2':73577.0,'plannedHouseholds':1267}
    named={'id':'named','sourceId':'gg-plan-boundary','sourceLayer':13,'sourceName':'광육 주택재건축 정비구역',
           'districtCode':'41210','siteAreaM2':73663.64}
    anonymous={'id':'anonymous','sourceId':'gg-plan-boundary','sourceLayer':13,'sourceName':'재정비촉진지구',
               'districtCode':'41210','siteAreaM2':73553.36}
    assert completion.unique_completed_area_boundary_groups([named,anonymous],[project],[])=={0:project}


def test_named_boundary_matches_parenthetical_project_alias():
    row={'id':'named','sourceId':'gg-plan-boundary','businessNameConfirmed':True,
         'sourceName':'대야3 주택재건축정비구역','districtCode':'41390','sourceLayer':13,'siteAreaM2':34901}
    project={'id':'finished','name':'대야3(시흥영남2차아파트)','province':'경기도','region':'시흥시',
             'projectType':'reconstruction','stage':'completed','stageLabel':'준공','siteAreaM2':34901}
    assert completion._same_area_project_name(row['sourceName'],project)


def test_goyang_occupied_project_is_removed_by_exact_official_identity():
    override=next(e for e in occupancy.reviewed_entries() if e['zoneId']=='gg-zone:13:5678')
    assert override['kaptCode']=='41281120452747'
    assert override['projectIdentities'][0]['id']=='gg-quarter:6d1643de7f68622871ec'
    rows,_,_,audit=metro.spatial_index()
    assert 'gg-zone:13:5678' not in {r['id'] for r in rows}
    assert any(r['id']=='gg-zone:13:5678' and r['reason']=='reviewed_completion'
               for r in audit['excludedBoundaries'])


def test_jev_review_tls_fallback_keeps_verification_and_credentials_off_argv(monkeypatch):
    import typesafe_jev as jev
    from types import SimpleNamespace
    monkeypatch.setattr(jev.config,'TYPESAFE_API_KEY','test-secret')
    def failing_post(*args,**kwargs):
        instructions=kwargs['json']['questions']['record_0']['instructions']
        assert 'actual move-in has started' in instructions
        raise jev.requests.exceptions.SSLError('test certificate bundle failure')
    monkeypatch.setattr(jev.requests,'post',failing_post)
    def verified_curl(args,**kwargs):
        assert 'test-secret' not in ' '.join(args)
        assert '--insecure' not in args and '-k' not in args
        assert 'test-secret' in kwargs['input']
        return SimpleNamespace(stdout=json.dumps({'answers':{'record_0':{'choice':'supported','confidence':.9}}}))
    monkeypatch.setattr(jev.subprocess,'run',verified_curl)
    result=jev.review_occupancy_evidence([{'evidence':'입주가 실제 시작됨'}],'2026-10-19')
    assert result['status']=='ok'
    assert result['automaticRemovalAllowed'] is False
