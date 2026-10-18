import copy
import datetime as dt
import pytest
import living_area_plan_rating as policy
import future_transformation as future

DAY = dt.date(2026,10,15)


def inputs():
    projects = [dict(id='housing',name='시험 정비사업',projectType='redevelopment',stage='designated',plannedHouseholds=1500,distanceMeters=400),
                dict(id='rail',name='시험 철도',projectType='transport',stage='planning')]
    spatial = {'stations':[dict(projectId='rail',name='시험 경유지',distanceMeters=400,positionLabel='시설 대표점')], 'zones':[]}
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


def test_real_apartment_plan_rating_is_separate_and_traceable():
    x = future.registry_entity('4ba5297e34906625')
    r = future.public_facts(future.analyze(x,x,as_of=DAY))
    rating = r['planRating']
    assert rating['score'] == 3.3
    assert rating['subScores'] == {'housing':3.8,'transport':2.6}
    assert rating['components']['housing']['inputs'][0]['distanceMeters'] == 27
    assert 'competitiveness' not in rating['components']
    assert rating['version'] == policy.VERSION and rating['basis'] == '계획 기준 · 베타'
    assert r['score'] is None and r['status'] == 'insufficient_data'
