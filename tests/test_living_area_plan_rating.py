import copy
import datetime as dt
import pytest
import living_area_plan_rating as policy

DAY = dt.date(2026,10,15)


def inputs():
    projects = [dict(id='housing',name='시험 정비사업',projectType='redevelopment',stage='designated',plannedHouseholds=1500,distanceMeters=400),
                dict(id='metro-rail:gtx-b',name='GTX-B',projectType='transport',stage='construction',stageLabel='착공')]
    spatial = {'stations':[dict(projectId='metro-rail:gtx-b',lineId='gtx-b',name='시험 경유지',
                                distanceMeters=400,positionLabel='시설 대표점',stage='construction',stageLabel='착공')], 'zones':[]}
    return projects, spatial


def test_weighted_rating_and_missing_values():
    assert policy.WEIGHTS == {'housing': .6, 'transport': .4}
    assert policy.aggregate({'housing':3.8,'transport':2.6}) == 3.3
    assert policy.aggregate({'housing':3.8,'transport':2.6,'competitiveness':0}) == 3.3
    assert policy.aggregate(dict.fromkeys(policy.WEIGHTS,0)) == 0
    for v in [None,True,float('nan'),-1,6]:
        assert policy.aggregate({'housing':v,'transport':3}) is None


def test_distance_and_stage_move_in_expected_directions():
    p,s = inputs()
    original = policy.calculate(p,s,DAY)
    p[0]['distanceMeters'] = 1200
    farther = policy.calculate(p,s,DAY)
    assert farther['subScores']['housing'] < original['subScores']['housing']
    p[0]['distanceMeters'] = 400
    p[0]['stage'] = 'construction'
    later = policy.calculate(p,s,DAY)
    assert later['subScores']['housing'] > original['subScores']['housing']
    s['stations'][0]['distanceMeters'] = 1500
    assert policy.calculate(p,s,DAY)['subScores']['transport'] < later['subScores']['transport']


def test_nearby_housing_projects_add_planned_units_with_stage_and_distance_weights():
    projects = [dict(id=f'zone-{i}', name=f'정비구역 {i}', projectType='redevelopment',
                     stage='construction', plannedHouseholds=households, distanceMeters=1000)
                for i, households in enumerate((3000, 2000, 1000), 1)]
    result = policy.calculate(projects, {'zones': [], 'stations': []}, DAY)
    housing = result['components']['housing']

    assert result['subScores']['housing'] == 3.9
    assert housing['projectCount'] == 3
    assert housing['plannedHouseholdsTotal'] == 6000
    assert housing['areaOnlyProjectCount'] == 0
    assert housing['selectedProjectId'] == 'zone-1'
    assert sum(row['rawScore'] for row in housing['inputs']) == pytest.approx(3.9166666667)
    assert sum(row['contributionScore'] for row in housing['inputs']) == pytest.approx(3.9166666667)
    assert '6,000세대' in housing['summary']

    earlier = copy.deepcopy(projects)
    for project in earlier:
        project['stage'] = 'planning'
    assert policy.calculate(earlier, {'zones': []}, DAY)['subScores']['housing'] == 2.7
    farther = copy.deepcopy(projects)
    for project in farther:
        project['distanceMeters'] = 2000
    assert policy.calculate(farther, {'zones': []}, DAY)['subScores']['housing'] == 3.3

    assert policy.calculate(projects + [copy.deepcopy(projects[0])], {'zones': []}, DAY)['subScores']['housing'] == 3.9
    assert policy.calculate(projects + [dict(id='zone-4', name='추가 구역', projectType='redevelopment',
                                            stage='construction', plannedHouseholds=1000, distanceMeters=1000)],
                            {'zones': []}, DAY)['subScores']['housing'] > 3.9


def test_stage_still_matters_after_many_projects_reach_the_scale_ceiling():
    projects = [dict(id=f'zone-{i}', name=f'정비구역 {i}', projectType='redevelopment',
                     stage='planning', plannedHouseholds=3000, distanceMeters=1000)
                for i in range(6)]
    early = policy.calculate(projects, {'zones': []}, DAY)
    later = copy.deepcopy(projects)
    later[0]['stage'] = 'construction'
    advanced = policy.calculate(later, {'zones': []}, DAY)

    assert early['subScores']['housing'] < advanced['subScores']['housing'] < 5
    assert early['components']['housing']['plannedHouseholdsTotal'] == 18000
    assert sum(p['contributionScore'] for p in advanced['components']['housing']['inputs']) == pytest.approx(
        advanced['subScores']['housing'], abs=.05)


def test_area_only_projects_are_scored_separately_and_missing_scale_is_not_zero():
    projects = [dict(id='units', name='세대수 확인', projectType='reconstruction',
                     stage='construction', plannedHouseholds=3000, siteAreaM2=200000, distanceMeters=1000),
                dict(id='area', name='면적만 확인', projectType='redevelopment',
                     stage='construction', siteAreaM2=200000, distanceMeters=1000),
                dict(id='unknown', name='규모 미확인', projectType='redevelopment',
                     stage='construction', distanceMeters=1000)]
    result = policy.calculate(projects, {'zones': []}, DAY)
    housing = result['components']['housing']

    assert result['subScores']['housing'] == 3.9
    assert housing['plannedHouseholdsTotal'] == 3000
    assert housing['areaOnlyProjectCount'] == 1
    assert housing['areaOnlyTotalM2'] == 200000
    assert housing['unscoredProjectCount'] == 1
    assert {row['projectId']:row['scaleBasis'] for row in housing['inputs']} == {
        'units':'planned_households', 'area':'official_area'}
    assert '세대수 없는 1곳' in housing['summary']
    assert '규모를 확인하지 못한 1곳' in housing['policy']


def test_own_or_conflicting_boundary_is_not_counted_and_nearest_boundary_wins():
    project = dict(id='zone', name='시험 구역', projectType='redevelopment',
                   stage='designated', plannedHouseholds=3000, distanceMeters=1800)
    zones = [{'projectId':'zone', 'distanceMeters':1000},
             {'projectId':'zone', 'distanceMeters':400}]
    result = policy.calculate([project], {'zones': zones}, DAY)
    assert result['components']['housing']['inputs'][0]['distanceMeters'] == 400
    assert result['components']['housing']['projectCount'] == 1

    assert policy.calculate([project], {'zones':[{'projectId':'zone'}]}, DAY)[
        'components']['housing']['inputs'][0]['distanceMeters'] == 1800

    zones.append({'projectId':'zone', 'distanceMeters':100, 'containsSubject':True})
    assert policy.calculate([project], {'zones': zones}, DAY)['subScores']['housing'] is None
    zones[-1].pop('containsSubject')
    zones[-1]['stageMismatch'] = True
    assert policy.calculate([project], {'zones': zones}, DAY)['subScores']['housing'] is None


def test_deduplication_and_unknowns_are_not_zero_or_walking_gains():
    p,s = inputs()
    r = policy.calculate(p,s,DAY)
    assert policy.calculate(p+[copy.deepcopy(p[0])],s,DAY) == r
    missing = policy.calculate(p,{},DAY)
    assert missing['subScores']['housing'] is not None
    assert missing['subScores']['transport'] is None
    assert missing['score'] is None and missing['status'] == 'insufficient_data'
    assert policy.calculate([],s,DAY)['score'] is None
    assert '이동시간 단축 점수가 아니에요' in r['components']['transport']['policy']
    assert 'walkingMinutes' not in r['components']['transport']['inputs'][0]


def test_map_only_station_point_cannot_enter_transport_score():
    projects, spatial = inputs()
    spatial['stations'][0]['scoringEligible'] = False
    result = policy.calculate(projects, spatial, DAY)
    assert result['subScores']['transport'] is None
    assert result['score'] is None


def test_rail_policy_covers_every_catalogue_line_and_withholds_unknowns():
    import json
    from pathlib import Path
    from living_area_rail_policy import line_policy
    root = Path(__file__).resolve().parents[1] / 'data'
    plans = json.loads((root/'planned_rail_metro.json').read_text())['lines']
    policy = json.loads((root/'rail_impact_policy.json').read_text())['lines']
    assert {line['id'] for line in plans} == set(policy)
    for line in plans:
        row = policy[line['id']]
        assert row['stageCode'] == line['stageCode']
        assert row['stageLabel'] == line['stage']
        assert row['sourceUrl'] == line['sourceUrl']
        assert bool(line_policy(line['id'], line['stageCode'], line['stage'])) == (
            row['maturity'] not in ('unknown', 'completed')
            and row.get('reviewStatus') != 'reconsidering'
            and row['impactClass'] not in ('intercity', 'freight'))


def test_rail_gtx_weight_exceeds_tram_at_same_distance_and_stage():
    projects = [dict(id='gtx', name='GTX-B', projectType='transport', stage='construction', stageLabel='착공'),
                dict(id='tram', name='위례선 트램', projectType='transport', stage='construction', stageLabel='시운전 중 · 개통 전')]
    stations = [dict(projectId='gtx', lineId='gtx-b', name='GTX-B 역', stage='construction',stageLabel='착공',
                     distanceMeters=800, positionLabel='역 참고점'),
                dict(projectId='tram', lineId='wirye', name='트램 정거장', stage='construction',
                     stageLabel='시운전 중 · 개통 전', distanceMeters=800, positionLabel='정거장 참고점')]
    gtx = policy.calculate(projects, {'stations':stations[:1]}, DAY)['subScores']['transport']
    tram = policy.calculate(projects, {'stations':stations[1:]}, DAY)['subScores']['transport']
    both = policy.calculate(projects, {'stations':stations}, DAY)
    assert gtx > tram
    assert gtx < both['subScores']['transport'] <= gtx + .6
    assert both['components']['transport']['secondLineId'] == 'wirye'


def test_multiple_stations_on_one_line_count_only_once_and_unknown_stage_is_withheld():
    projects, spatial = inputs()
    baseline = policy.calculate(projects, spatial, DAY)['subScores']['transport']
    farther = copy.deepcopy(spatial['stations'][0])
    farther.update(name='다른 역', distanceMeters=1200)
    spatial['stations'].append(farther)
    result = policy.calculate(projects, spatial, DAY)
    assert result['subScores']['transport'] == baseline
    assert len(result['components']['transport']['inputs']) == 1
    spatial['stations'][0]['stage'] = 'unknown'
    spatial['stations'][1]['stage'] = 'unknown'
    assert policy.calculate(projects, spatial, DAY)['subScores']['transport'] is None


def test_rail_progress_and_third_line_do_not_overstate_transport_score():
    projects = [dict(id='design',name='용산 연장',projectType='transport',stage='planning',stageLabel='설계 단계'),
                dict(id='build',name='호매실 연장',projectType='transport',stage='construction',stageLabel='공사 중'),
                dict(id='gtx',name='GTX-B',projectType='transport',stage='construction',stageLabel='착공')]
    stations = [dict(projectId='design',lineId='shinbundang-yongsan',name='설계역',
                     stage='planning',stageLabel='설계 단계',distanceMeters=800),
                dict(projectId='build',lineId='shinbundang-homaesil',name='공사역',
                     stage='construction',stageLabel='공사 중',distanceMeters=800),
                dict(projectId='gtx',lineId='gtx-b',name='GTX역',
                     stage='construction',stageLabel='착공',distanceMeters=800)]
    design = policy.calculate(projects, {'stations':stations[:1]}, DAY)['subScores']['transport']
    build = policy.calculate(projects, {'stations':stations[1:2]}, DAY)['subScores']['transport']
    two = policy.calculate(projects, {'stations':stations[1:]}, DAY)
    three = policy.calculate(projects, {'stations':stations}, DAY)
    assert build > design
    assert three['subScores']['transport'] == two['subScores']['transport']
    assert sum('contributionScore' in row for row in three['components']['transport']['inputs']) == 2


def test_plan_rating_attaches_separately_and_traceably(monkeypatch):
    import living_area_map
    projects, spatial = inputs()
    monkeypatch.setattr(living_area_map, 'map_context', lambda identity, result: spatial)
    result = {'displayProjects':projects, 'snapshotId':'fixture', 'status':'insufficient_data',
              'score':None, 'metroCoverage':{'checkedAt':DAY.isoformat()}}
    r = policy.attach(result, {}, DAY)
    rating = r['planRating']
    assert rating['score'] == policy.aggregate(rating['subScores'])
    assert rating['components']['housing']['inputs'][0]['distanceMeters'] == 400
    assert 'competitiveness' not in rating['components']
    assert rating['version'] == policy.VERSION and rating['basis'] == '계획 기준 · 베타'
    assert r['score'] is None and r['status'] == 'insufficient_data'


def test_map_station_reference_is_explained_without_inventing_a_transport_score(monkeypatch):
    import living_area_map
    projects, _ = inputs()
    spatial = {'zones': [], 'routes':[{'name':'신안산선'}], 'stations':[
        {'name':'신독산역(예정) · 신안산선','distanceMeters':1447,'scoringEligible':False},
        {'name':'시흥사거리역(예정) · 신안산선','distanceMeters':1745,'scoringEligible':False},
    ]}
    monkeypatch.setattr(living_area_map, 'map_context', lambda identity, result: spatial)
    result = {'displayProjects':projects[:1], 'center':{'latitude':37.46,'longitude':126.88},
              'metroCoverage':{'checkedAt':'2026-10-18'}, 'snapshotId':'test'}
    plan = policy.attach(result, {}, dt.date(2026,10,18))['planRating']
    assert plan['subScores']['transport'] is None
    assert plan['transportCoverage']['status'] == 'map_reference_only'
    assert '신독산역(예정)' in plan['missingReasons']['transport']
    assert '시흥사거리역(예정)' in plan['missingReasons']['transport']
    assert '참고 위치' in plan['missingReasons']['transport']


@pytest.mark.parametrize('nearest', [None, {'name':'먼 예정역', 'distanceMeters':2001}])
def test_confirmed_absence_of_nearby_planned_station_is_zero(monkeypatch, nearest):
    import living_area_map
    import rail_station_mapping
    projects, _ = inputs()
    spatial = {'zones':[], 'stations':[], 'routes':[{'name':'확인한 노선', 'stationCoverage':{
        'mappingComplete':True, 'stationListComplete':True, 'nearestPlannedStation':nearest}}]}
    monkeypatch.setattr(living_area_map, 'map_context', lambda identity, result: spatial)
    monkeypatch.setattr(rail_station_mapping, 'complex_coverage', lambda *args: {
        'scopeComplete':True, 'nearbyPlannedStations':[], 'nearbyReferenceStations':[]})
    result = {'displayProjects':projects[:1], 'center':{'latitude':37.46,'longitude':126.88},
              'metroCoverage':{'checkedAt':DAY.isoformat()}, 'snapshotId':'test'}
    plan = policy.attach(result, {}, DAY)['planRating']
    assert plan['subScores']['transport'] == 0
    assert plan['subScores']['housing'] > 0
    assert plan['score'] == policy.aggregate(plan['subScores'])
    assert plan['status'] == 'ready'
    assert 'transport' not in plan['missingReasons']
    assert '가점은 0점' in plan['components']['transport']['summary']
    assert plan['components']['transport']['inputs'] == []


@pytest.mark.parametrize('change', ['incomplete_list', 'incomplete_mapping', 'no_center',
                                    'no_catalogue', 'unknown_distance', 'within_radius',
                                    'map_reference', 'unknown_stage', 'other_lines_incomplete'])
def test_unknown_station_evidence_does_not_become_zero(monkeypatch, change):
    import living_area_map
    import rail_station_mapping
    projects, _ = inputs()
    coverage = {'mappingComplete':True, 'stationListComplete':True,
                'nearestPlannedStation':{'name':'예정역', 'distanceMeters':2001}}
    spatial = {'zones':[], 'stations':[], 'routes':[{'name':'확인한 노선', 'stationCoverage':coverage}]}
    result = {'displayProjects':projects[:1], 'center':{'latitude':37.46,'longitude':126.88},
              'metroCoverage':{'checkedAt':DAY.isoformat()}, 'snapshotId':'test'}
    if change == 'incomplete_list': coverage['stationListComplete'] = False
    if change == 'incomplete_mapping': coverage['mappingComplete'] = False
    if change == 'no_center': result.pop('center')
    if change == 'no_catalogue': result.pop('metroCoverage')
    if change == 'unknown_distance': coverage['nearestPlannedStation']['distanceMeters'] = None
    if change == 'within_radius': coverage['nearestPlannedStation']['distanceMeters'] = 2000
    if change == 'map_reference':
        spatial['stations'] = [{'name':'참고역', 'scoringEligible':False, 'distanceMeters':800}]
    if change == 'unknown_stage':
        spatial['stations'] = [{'name':'예정역', 'lineId':'gtx-b', 'stage':'unknown', 'distanceMeters':800}]
    monkeypatch.setattr(living_area_map, 'map_context', lambda identity, result: spatial)
    monkeypatch.setattr(rail_station_mapping, 'complex_coverage', lambda *args: {
        'status':'partial',
        'scopeComplete':change in ('map_reference','unknown_stage','within_radius'),
        'nearbyPlannedStations':([{'id':'test'}] if change == 'within_radius' else []),
        'nearbyReferenceStations':[]})
    plan = policy.attach(result, {}, DAY)['planRating']
    assert plan['subScores']['transport'] is None
    assert 'transport' in plan['missingReasons']
    assert plan['score'] is None
    if change == 'other_lines_incomplete':
        assert plan['transportCoverage']['status'] == 'station_mapping_incomplete'
