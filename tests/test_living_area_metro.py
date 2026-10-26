import copy
import datetime as dt
import json
import pytest
import future_transformation as future
import living_area as living
import living_area_metro as metro
import living_area_plan_rating as rating
import import_living_area_metro as importer

DAY=dt.date(2026,10,16)


def test_containing_zone_facts_are_kept_for_report_without_neighbor_benefit():
    from shapely.geometry import shape
    feature = next(f for f in json.loads((future.config.ROOT / 'data/redevelopment_zones.geojson').read_text())['features']
                   if f['id'] == '11000UQ120PS202407010944')
    point = shape(feature['geometry']).representative_point()
    identity = {'apartmentId':'11380100000585', 'name':'미성아파트', 'province':'서울특별시',
                'district':'은평구', 'legalDong':'불광동', 'jibun':'248'}
    result = metro.attach({'projects':[], 'referenceProjects':[], 'snapshotId':'test',
                           'center':{'latitude':point.y, 'longitude':point.x}}, identity, DAY)
    own = next(z for z in result['subjectZoneReferences'] if z['id'] == feature['id'])
    assert own['name'] == '불광미성'
    assert own['districtCode'] == '11380'
    assert own['containsSubject'] is True
    assert own['projectTypeLabel'] == '신속통합기획'
    assert own['sourceUrl'].startswith('https://data.seoul.go.kr/')
    assert 'geometry' not in own
    assert own['projectId'] not in {p['id'] for p in result['referenceProjects']}


@pytest.mark.parametrize('relative', ['data/living_area_metro_catalog.json', 'data/planned_rail_metro.json', 'data/redevelopment_zones.geojson',
                                    'data/redevelopment_project_scales.json',
                                    'data/redevelopment_occupancy_overrides.json',
                                    'pipeline/redevelopment_occupancy.py',
                                    'pipeline/living_area_plan_rating.py'])
def test_data_and_rating_refresh_invalidates_candidate_cache(tmp_path, monkeypatch, relative):
    import os
    import living_area_sources as sources
    monkeypatch.setattr(sources.config, 'ROOT', tmp_path)
    before = sources.revision()
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}')
    added = sources.revision()
    assert added != before
    modified = path.stat().st_mtime_ns + 1_000_000
    os.utime(path, ns=(modified, modified))
    assert sources.revision() != added


def test_catalog_complete_sources_but_never_claim_universal_coverage():
    data=metro.catalog()
    assert len(data['nationalRows'])==1566
    assert sum(p['sourceId']=='gg-quarter' for p in data['projects'])==542
    assert sum(p['sourceId']=='seoul-plan-renewal' for p in data['projects'])==830
    assert len(data['ggBoundaries'])==407
    assert len(data['railStations'])==51
    assert data['coverage']['scopeComplete'] is False
    assert all(p['stage']=='announced' and p['plannedHouseholds'] is None
               for p in data['projects'] if p['projectType']=='new_supply')
    assert all(s['walkingMinutes'] is None and not s['stationEntranceVerified'] for s in data['railStations'])


def test_wondang_scale_is_an_attributed_reference_not_a_score_input():
    from shapely.geometry import shape
    feature = next(f for f in json.loads((future.config.ROOT / 'data/redevelopment_zones.geojson').read_text())['features']
                   if f['properties']['id'] == '11000UQ120PS202505310524')
    point = shape(feature['geometry']).representative_point()
    zones = metro.spatial({'latitude':point.y + .002, 'longitude':point.x}, [], DAY)['zones']
    zone = next(z for z in zones if z['id'] == feature['properties']['id'])
    assert zone['reportedHouseholds'] == 108
    assert zone['reportedHouseholdsBasis'] == '2024년 공람안 기준'
    assert zone['plannedHouseholds'] is None
    assert zone['stageLabel'] == '조합설립인가'


def test_haan_official_boundary_remark_links_the_same_business_without_confusing_12_with_1_and_2():
    center={'latitude':37.4600847128236,'longitude':126.886483831561}
    zones=metro.spatial(center,metro.catalog()['projects'],DAY)['zones']
    by_id={z['id']:z for z in zones}
    expected={
        'gg-zone:13:5628':('하안주공12단지','gg-quarter:3a8e30c08a377883a4ec'),
        'gg-zone:13:5612':('하안주공6·7단지','gg-quarter:5d5916c15644b037acf5'),
        'gg-zone:13:5617':('하안주공10·11단지','gg-quarter:f369a61b1c96f7d431c7'),
        'gg-zone:13:5621':('하안주공3·4단지','gg-quarter:7b92ec33001394db99d4'),
    }
    for boundary_id,(name,project_id) in expected.items():
        zone=by_id[boundary_id]
        assert zone['name']==name
        assert zone['projectId']==project_id
        assert zone['businessNameConfirmed'] is True
        assert zone['sourceNameField']=='REMARK'
        assert zone['plannedHouseholds']>0
    generic=by_id['gg-zone:13:5630']
    assert generic['businessNameConfirmed'] is False
    assert generic['matchMethod']=='boundary_only'
    assert generic['projectId'].startswith('boundary:')


def test_official_rail_route_has_a_nearest_point_for_a_line_label():
    center={'latitude':37.4600847128236,'longitude':126.886483831561}
    routes=metro.spatial(center,[],DAY)['routes']
    rail=next(route for route in routes if route['name']=='신안산선')
    assert rail['geometry']['type']=='LineString'
    assert 600<rail['distanceMeters']<750
    assert 37<rail['latitude']<38 and 126<rail['longitude']<127
    assert rail['geometryBasis']=='official_reference_alignment'
    assert rail['scoringEligible'] is False


def test_stage_does_not_confuse_finished_planning_with_finished_construction():
    assert importer.stage('기획완료')=='planning'
    assert importer.stage('조합설립인가 추진중(연번부여)')=='planning'
    assert importer.stage('준공')=='completed'
    assert importer.stage('5)사업시행인가')=='approved'


def test_exact_address_does_not_relax_an_explicit_district(monkeypatch):
    import kakao_station_distances as kakao
    raw={'region_1depth_name':'경기','region_2depth_name':'수원시 팔달구','region_3depth_name':'원천동',
         'main_address_no':'71','sub_address_no':'1','mountain_yn':'N','x':'127.0','y':'37.3'}
    monkeypatch.setattr(kakao,'_request_json',lambda *args:{'documents':[{'address':raw}]})
    target={'province':'경기도','region':'수원영통구','city':'수원시','legalDong':'원천동','jibun':'71-1'}
    assert importer.exact_point(target) is None
    raw['region_2depth_name']='수원시 영통구'
    assert importer.exact_point(target)['latitude']==37.3
    raw['sub_address_no']='2'
    assert importer.exact_point(target) is None


@pytest.mark.parametrize('apartment_id,point',[
    ('9f52fd4776b153b6',{'latitude':37.5845,'longitude':126.9445}),
    ('dffce49905593ace',{'latitude':37.281,'longitude':127.061}),
    ('676a2d82a3acdf6b',{'latitude':37.561,'longitude':127.193}),
])
def test_nonpilot_regions_share_reports_and_never_claim_walking_benefit(monkeypatch,apartment_id,point):
    # Synthetic test positions exercise spatial plumbing; they are never shipped as data.
    entity={**future.registry_entity(apartment_id),'apartmentId':apartment_id}
    monkeypatch.setattr(metro,'center_for',lambda *args:point)
    result=living.analyze(entity,day=DAY)
    assert 'metroCoverage' in result and result['status']!='error'
    assert result['metroIdentity']['district']==entity['district']
    assert result['planRating']['version']==rating.VERSION
    assert result['score'] is None
    for p in result['referenceProjects']:
        assert p.get('walkingMinutes') is None
        assert p.get('benefitClass')!='direct'
        assert p.get('sourceUrl')
    assert isinstance(result['regionalProjects'],list)


def test_missing_position_still_returns_regional_catalogue_without_fake_distance(monkeypatch):
    entity={**future.registry_entity('676a2d82a3acdf6b'),'apartmentId':'676a2d82a3acdf6b'}
    monkeypatch.setattr(metro,'center_for',lambda *args:None)
    result=living.analyze(entity,day=DAY)
    assert result['metroCoverage']['locationStatus']=='unresolved'
    assert result['regionalProjects']
    assert result['planRating']['subScores']['housing'] is None
    assert result['planRating']['subScores']['transport'] is None
    assert result['planRating']['score'] is None
    assert not result['metroCoverage']['scopeComplete']


def test_future_catalogue_does_not_change_historical_report():
    entity={**future.registry_entity('4ba5297e34906625'),'apartmentId':'4ba5297e34906625'}
    result=living.analyze(entity,day=DAY-dt.timedelta(days=1))
    assert 'metroCoverage' not in result
    assert len(result['displayProjects'])==3


def test_hongje_route_is_visible_without_claiming_new_station_benefit():
    entity={**future.registry_entity('9f52fd4776b153b6'),'apartmentId':'9f52fd4776b153b6'}
    result=living.analyze(entity,day=DAY)
    route=next(p for p in result['transportRoutes'] if p['id']=='gg-rail:650')
    assert route['name']=='광역급행철도 A노선'
    assert '우선개통' in route['stageLabel']
    assert 'geometry' not in route and route['scoringEligible'] is False
    assert any(i['kind']=='transport' and '강북횡단선' in i['fact'] for i in result['insights'])
    plan=result['planRating']
    assert plan['subScores']=={'housing':3.2,'transport':2.5}
    assert plan['score']==rating.aggregate(plan['subScores'])
    assert plan['status']=='ready'
    rail=plan['components']['transport']
    assert rail['selectedProjectId']=='metro-rail:gangbuk-cross'
    assert all(r['projectId']=='metro-rail:gangbuk-cross' and r['stage']=='planning' for r in rail['inputs'])
    assert '재추진' in rail['summary']
    assert '바뀔 수 있어요' in rail['policy']
    assert result['score'] is None  # No fabricated measured travel-time score.
    project=next(p for p in result['displayProjects'] if p['id']=='metro-rail:gangbuk-cross')
    assert project['distanceMeters']>0 and project['benefitClass']=='unverified'


def test_route_facts_are_not_hidden_when_no_housing_projects_exist():
    import living_area_context as context
    result=living.empty_report('test',DAY)
    result['transportRoutes']=[{'name':'노선 참고','stageLabel':'부분 개통'}]
    context.describe(result,{})
    assert result['insights'][0]['kind']=='transport'
    assert '부분 개통' in result['intro']


def test_supply_publication_is_not_a_construction_fact_and_old_notice_can_still_be_upcoming():
    notice={'projectType':'new_supply','stage':'announced','sourceDate':'2023-01-01',
            'checkedAt':'2026-10-16','plannedMoveInMonth':'2027-03'}
    assert metro.active(notice,DAY)
    assert not metro.active({**notice,'plannedMoveInMonth':'2026-09'},DAY)
    assert not metro.active({**notice,'sourceDate':'2027-01-01'},DAY)


def test_area_only_scale_and_supply_does_not_enter_living_change_score():
    p={'id':'area','name':'구역','projectType':'redevelopment','stage':'designated','distanceMeters':500,'siteAreaM2':50000}
    r=rating.calculate([p],{},DAY)
    assert r['subScores']['housing'] is not None
    assert r['components']['housing']['inputs'][0]['plannedHouseholds'] is None
    assert 'competitiveness' not in r['components']
    assert r['score'] is None
    supply={'id':'notice','name':'입주예정','projectType':'new_supply','stage':'announced',
            'distanceMeters':200,'offeredHouseholds':1000}
    with_supply=rating.calculate([p,supply],{},DAY)
    assert with_supply['subScores'] == r['subScores']
    assert with_supply['score'] == r['score']
    assert rating.calculate([p],{'zones':[{'projectId':'area','distanceMeters':0,'containsSubject':True}]},DAY)['subScores']['housing'] is None


def test_supply_only_report_has_no_invented_rail_headline():
    import living_area_context as context
    report=living.empty_report('test',DAY)
    report['referenceProjects']=[{'id':'s','name':'공고 단지','projectType':'new_supply','stage':'announced','stageLabel':'입주 예정',
                                  'factSummary':'2027-03 입주 계획','sourceDate':'2026-01-01'}]
    result=context.describe(report,{'district':'하남시'})
    assert '새 아파트' in result['headline'] and '철도' not in result['headline']


def test_rural_ri_address_keeps_lot_and_ambiguity_checks(monkeypatch):
    import kakao_station_distances as kakao
    raw={'region_1depth_name':'경기','region_2depth_name':'가평군','region_3depth_name':'가평읍 읍내리',
         'main_address_no':'457','sub_address_no':'5','mountain_yn':'N','x':'127.5','y':'37.8'}
    docs=[{'address':raw}]
    monkeypatch.setattr(kakao,'_request_json',lambda *args:{'documents':docs})
    target={'province':'경기도','region':'가평군','legalDong':'읍내리','jibun':'읍내리 457-5'}
    assert importer.exact_point(target)
    docs.append({'address':{**raw,'region_3depth_name':'다른면 읍내리'}})
    assert importer.exact_point(target) is None
    docs.pop()
    assert importer.exact_point({**target,'jibun':'다른리 457-5'}) is None


@pytest.mark.parametrize('stage_code,expected', [('planning',1),('construction',1),('unknown',0),('completed',0),(None,0)])
def test_station_import_preserves_explicit_plan_stage(monkeypatch,stage_code,expected):
    import kakao_station_distances as kakao
    monkeypatch.setattr(kakao,'_request_json',lambda *args:{'documents':[{
        'id':'test','category_group_code':'SW8','place_name':'홍제역 3호선',
        'address_name':'서울 서대문구 홍제동','x':'126.944','y':'37.589','place_url':'https://place.map.kakao.com/test'}]})
    line={'id':'test','name':'시험 계획','stage':'원문 단계','stageCode':stage_code,
          'sourceDate':'2026-06-15','sourceUrl':'https://example.go.kr/plan','stationsSourceUrl':'https://example.go.kr/stations',
          'stations':[{'name':'홍제','sido':'서울특별시','sigungu':'서대문구'}]}
    rows=importer.fetch_station_references({'checkedAt':'2026-10-16','lines':[line]})
    assert len(rows)==expected
    if rows:
        assert rows[0]['stage']==stage_code
        assert rows[0]['walkingMinutes'] is None and not rows[0]['stationEntranceVerified']
    line['sourceDate']='2040-01-01'
    assert importer.fetch_station_references({'checkedAt':'2026-10-16','lines':[line]})==[]


def test_old_pilot_review_does_not_erase_new_metro_station_scores(monkeypatch):
    import living_area_map as maps
    original=maps.read
    stale=lambda path: {**original(path),'checkedAt':'2020-01-01'} if path.name=='living_area_map_references.json' else original(path)
    monkeypatch.setattr(maps,'read',stale)
    entity={**future.registry_entity('9f52fd4776b153b6'),'apartmentId':'9f52fd4776b153b6'}
    assert living.analyze(entity,day=DAY)['planRating']['subScores']['transport'] is not None


def test_city_only_identity_accepts_new_gu_but_not_another_city(monkeypatch):
    import kakao_station_distances as kakao
    raw={'region_1depth_name':'경기','region_2depth_name':'화성시 동탄구','region_3depth_name':'청계동',
         'main_address_no':'541','sub_address_no':'','mountain_yn':'N','x':'127.1','y':'37.2'}
    monkeypatch.setattr(kakao,'_request_json',lambda *args:{'documents':[{'address':raw}]})
    target={'province':'경기도','region':'화성시','legalDong':'청계동','jibun':'541'}
    assert importer.exact_point(target)
    raw['region_2depth_name']='다른시 동탄구'
    assert importer.exact_point(target) is None


def test_audited_center_requires_full_identity_and_date(tmp_path,monkeypatch):
    import living_area_sources as sources
    identity={'apartmentId':'one','province':'경기도','district':'화성시','legalDong':'청계동','jibun':'541'}
    point={'latitude':37.2,'longitude':127.1,'coordinateBasis':'address_geocode'}
    record={'identity':identity,'day':DAY.isoformat(),'point':point}
    path=tmp_path/'points.json'
    path.write_text(json.dumps({sources.digest(identity):record}))
    monkeypatch.setattr(metro,'AUDITED_CENTER_PATH',path)
    metro._audited_centers.cache_clear()
    assert metro.audited_center(identity,DAY)==point
    assert metro.audited_center({**identity,'jibun':'542'},DAY) is None
    assert metro.audited_center(identity,DAY-dt.timedelta(days=1)) is None
    assert metro.audited_center(identity,DAY+dt.timedelta(days=121)) is None


def test_transport_audit_does_not_turn_failed_or_missing_data_into_zero():
    from audit_living_area_transport import classify
    point={'latitude':37.5,'longitude':127.0}
    station={**point,'id':'station','name':'시험역','lineName':'시험선','projectId':'rail',
             'stage':'construction','checkedAt':DAY.isoformat(),'sourceDate':'2026-01-01','planSourceUrl':'https://example.go.kr'}
    assert classify(None,[station],DAY)['score'] is None
    assert classify(point,[],DAY)['score'] is None
    assert classify(point,[{**station,'stage':'completed'}],DAY)['score'] is None
    assert classify(point,[{**station,'sourceDate':'2040-01-01'}],DAY)['score'] is None
    assert classify(point,[{**station,'checkedAt':'2020-01-01'}],DAY)['score'] is None
    assert classify(point,[station],DAY)['score']==4.8
