import copy
import datetime as dt

import future_transformation as future
import living_area_map as maps
import living_area_metro as metro


def pilot():
    entity = future.registry_entity('4ba5297e34906625')
    return entity, future.public_facts(future.analyze(entity, entity))


def test_actual_boundaries_and_reference_distances_never_change_scores():
    entity, analysis = pilot()
    before = copy.deepcopy(analysis)
    result = maps.map_context(entity, analysis)
    by_name = {p['name']: p for p in result['zones']}
    assert len(result['zones']) > 3
    assert '장안1구역 재개발' in by_name
    assert result['featuredDevelopment'] == {'projectId':'seoul-plan-renewal:7073',
        'scaleBasis':'plannedHouseholds','scaleValue':1754,'selectionRadiusMeters':2000}
    assert len(result['featuredDevelopments']) == 3
    assert by_name['장안1구역 재개발']['distanceMeters'] == 27
    assert by_name['장안1구역 재개발']['stageLabel'] == '정비구역 지정'
    assert all(p['commercialAllowed'] is False and p['previewOnly'] is False and p['useContext'] == 'noncommercial' for p in result['zones'])
    assert all(p['geometry']['type'] in ('Polygon','MultiPolygon') for p in result['zones'])
    stations = {s['id']:s for s in result['stations']}
    assert stations['myeonmok-jangan-reference']['distanceMeters'] == 378
    assert stations['cheongnyangni-reference']['distanceMeters'] == 2330
    assert all(s['walkingMinutes'] is None and not s['stationEntranceVerified'] for s in stations.values())
    assert analysis == before and analysis['score'] is None
    assert result['connections'][0]['geometryBasis'] == 'landmark_connection_only'


def test_noncommercial_boundaries_keep_identity_checks_and_unknown_location_empty():
    entity, analysis = pilot()
    assert len(maps.map_context(entity,analysis)['zones']) > 1
    assert maps.map_context(entity,analysis)['useContext'] == 'noncommercial'


def test_map_keeps_all_boundaries_and_labels_three_large_projects_with_rail():
    entity=future.registry_entity('7752a5eab231bc4c')
    project=next(p for p in metro.catalog()['projects'] if p['name']=='하안주공12단지')
    analysis={
        'modelVersion':'living-area-v2-beta','apartmentId':future.apartment_key(entity),
        'asOfDate':'2026-10-17','center':{'latitude':37.4600847128236,'longitude':126.886483831561},
        'metroCoverage':{'status':'partial'},
        'metroIdentity':{key:entity.get(key) for key in ('province','district','legalDong','jibun')},
        'displayProjects':[{key:value for key,value in project.items() if key!='point'}],
    }
    result=maps.map_context(entity,analysis)
    assert len(result['zones']) > 3
    zone=next(zone for zone in result['zones'] if zone['name']=='하안주공10·11단지')
    assert zone['name']=='하안주공10·11단지'
    assert zone['plannedHouseholds']==4004
    assert result['featuredDevelopment']['scaleValue']==4119
    assert result['featuredDevelopments'][1]['projectId']==zone['projectId']
    assert len(result['featuredDevelopments']) == 3
    assert any(route['name']=='신안산선' and route['geometry']['type']=='LineString'
               for route in result['routes'])
    assert maps.map_context(entity,{})['stations'] == []
    assert maps.map_context({**entity, 'district':'강남구'},analysis)['stations'] == []
    changed = {**entity, 'jibun':'different lot'}
    assert maps.map_context(changed,analysis)['zones'] == []
    assert maps.map_context(entity,analysis)['useContext'] == 'noncommercial'


def test_map_labels_three_largest_known_projects_and_uses_area_only_as_fallback():
    zones=[
        {'projectId':'own','containsSubject':True,'businessNameConfirmed':True,
         'projectTypeLabel':'재건축','distanceMeters':0,'siteAreaM2':200000},
        {'projectId':'large-area','businessNameConfirmed':True,
         'projectTypeLabel':'재개발','distanceMeters':200,'siteAreaM2':120000},
        {'projectId':'known-homes','businessNameConfirmed':True,
         'projectTypeLabel':'재개발','distanceMeters':350,'siteAreaM2':40000,'plannedHouseholds':1800},
        {'projectId':'more-homes','businessNameConfirmed':True,
         'projectTypeLabel':'재건축','distanceMeters':1500,'plannedHouseholds':2500},
        {'projectId':'reported-homes','businessNameConfirmed':True,
         'projectTypeLabel':'재개발','distanceMeters':1700,'reportedHouseholds':2200},
        {'projectId':'outside','businessNameConfirmed':True,
         'projectTypeLabel':'재개발','distanceMeters':2100,'plannedHouseholds':9000},
        {'projectId':'broad','businessNameConfirmed':True,
         'projectTypeLabel':'도시재생활성화지역','distanceMeters':100,'siteAreaM2':900000},
    ]
    featured=maps._featured_developments(zones,[])
    assert [row['projectId'] for row in featured]==['more-homes','reported-homes','known-homes']
    assert all(row['selectionRadiusMeters']==2000 for row in featured)
    zones[2].pop('plannedHouseholds')
    assert [row['projectId'] for row in maps._featured_developments(zones,[])]==[
        'more-homes','reported-homes','large-area']
    for zone in zones:
        zone.pop('siteAreaM2',None)
        zone.pop('plannedHouseholds',None)
        zone.pop('reportedHouseholds',None)
    assert maps._featured_developments(zones,[]) == []


def test_miseong_map_keeps_subject_boundary_but_labels_three_external_projects():
    import real_estate_search

    entity=next(row for row in real_estate_search._search_entities()
                if row.get('name')=='미성아파트' and row.get('district')=='은평구'
                and row.get('jibun')=='248')
    analysis=future.public_facts(future.analyze(entity,entity))
    result=maps.map_context(entity,analysis)
    assert len(result['zones']) > 3
    assert any(zone['name']=='불광미성' and zone['containsSubject'] for zone in result['zones'])
    assert [row['scaleValue'] for row in result['featuredDevelopments']]==[2451,1481,1302]
    assert not any(row['projectId'] in {zone['projectId'] for zone in result['zones'] if zone['containsSubject']}
                   for row in result['featuredDevelopments'])
    assert result['featuredDevelopment']['scaleValue']==2451
    assert result['featuredDevelopment']['selectionRadiusMeters']==2000


def test_miseong_map_connects_operating_yeonsinnae_gtx_a_without_future_bonus():
    import real_estate_search
    import living_area_plan_rating

    entity=next(row for row in real_estate_search._search_entities()
                if row.get('name')=='미성아파트' and row.get('district')=='은평구'
                and row.get('legalDong')=='불광동' and row.get('jibun')=='248')
    analysis={'modelVersion':'living-area-v2-beta','apartmentId':future.apartment_key(entity),
              'asOfDate':'2026-10-19','center':{'latitude':37.6148205101596,'longitude':126.928054602465},
              'metroCoverage':{'status':'partial'},
              'metroIdentity':{key:entity.get(key) for key in ('province','district','legalDong','jibun')},
              'displayProjects':[]}
    result=maps.map_context(entity,analysis)
    station=next(station for station in result['stations'] if station['id']=='gtx-a:004')
    assert station['name']=='연신내역 · GTX-A'
    assert station['distanceMeters']==798
    assert station['serviceStatus']=='operating'
    assert station['stageLabel']=='운행 중'
    assert station['routeId']=='gg-rail:650'
    assert station['scoringEligible'] is False
    assert station['walkingMinutes'] is None and not station['stationEntranceVerified']
    rating=living_area_plan_rating.calculate([],result,dt.date(2026,10,19))
    assert rating['subScores']['transport'] is None
    assert maps.map_context({**entity,'jibun':'different lot'},analysis)['stations']==[]


def test_operating_station_visibility_is_separate_from_planned_bonus():
    station={'serviceStatus':'operating','stage':'completed',
             'checkedAt':'2026-10-19','sourceDate':'2026-06-30'}
    day=dt.date(2026,10,19)
    assert metro.station_visible(station,day)
    assert not metro.station_active(station,day)
    assert not metro.station_visible({**station,'checkedAt':'2026-01-01'},day)


def test_nearby_planned_stations_link_to_their_named_route_without_claiming_entrances():
    entity=future.registry_entity('7752a5eab231bc4c')
    analysis={
        'modelVersion':'living-area-v2-beta','apartmentId':future.apartment_key(entity),
        'asOfDate':'2026-10-18','center':{'latitude':37.4600847128236,'longitude':126.886483831561},
        'metroCoverage':{'status':'partial'},
        'metroIdentity':{key:entity.get(key) for key in ('province','district','legalDong','jibun')},
        'displayProjects':[],
    }
    result=maps.map_context(entity,analysis)
    route=next(route for route in result['routes'] if route['name']=='신안산선')
    stations=[station for station in result['stations'] if station.get('routeId')==route['id']]
    assert {station['id'] for station in stations}=={
        'shinansan-sindoksan-reference','shinansan-siheung-crossroads-reference'}
    assert all(0 < station['routeLinkMeters'] <= 500 for station in stations)
    assert all(station['coordinateSourceUrl'].startswith('https://place.map.kakao.com/') for station in stations)
    assert all(not station['stationEntranceVerified'] and station['walkingMinutes'] is None for station in stations)
    assert all(station['routeLinkBasis']=='reference_point_to_official_alignment' for station in stations)
    assert maps.map_context(entity,{**analysis,'asOfDate':'2026-10-17'})['stations']==[]
