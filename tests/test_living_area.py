"""Fictional measurements are test-only; real pilots must remain unscored."""
import copy
import datetime as dt
import io
import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import living_area as living
import living_area_sources as sources
import living_area_scoring_policy as policy
from import_living_area import save_observation

DAY = dt.date(2026, 10, 15)
IDENTITY = {'apartmentId': 'fixture-only', 'district': '동대문구', 'legalDong': '가상동', 'jibun': '1'}


@pytest.fixture
def facts(monkeypatch):
    source = 'fixture-only-official'
    monkeypatch.setitem(sources.REGISTRY, source, {
        'name': '가상 시험 기관', 'url': 'https://www.seoul.go.kr/test-only',
        'licenseUrl': 'https://www.seoul.go.kr/test-only', 'verifiedAt': DAY.isoformat(),
        'licenseStatus': 'commercial_allowed', 'allowedUses': ['collect','derive','web','pdf'], 'pointAllowed': True})
    def evidence(raw):
        return {'sourceId': source, 'sourceRecordId': 'fixture', 'snapshotId': 'fixture-snapshot',
                'raw': raw, 'verificationStatus': 'verified', 'asOfDate': DAY.isoformat(), 'collectedAt': DAY.isoformat()}
    center = {'latitude': 37.58, 'longitude': 127.06, 'geometryType': 'point',
              'coordinateBasis': 'official_point', 'verificationStatus': 'verified', 'evidenceIds': ['center']}
    point = {**center, 'latitude': 37.584, 'evidenceIds': ['point']}
    project = {'id': 'p1', 'sourceId': source, 'sourceRecordId': 'p1', 'snapshotId': 'fixture-snapshot',
               'name': '가상 시험 사업', 'region': '동대문구', 'legalDong': '가상동', 'jibun': '2',
               'stage': 'construction', 'projectType': 'redevelopment', 'plannedHouseholds': 500,
               'sourceDate': DAY.isoformat(), 'collectedAt': DAY.isoformat()}
    inputs = {
        'housing_conversion': {'convertedLandM2': 500, 'oldResidentialLandM2': 1000, 'overlapRemoved': True, 'scopeSurveyComplete': True},
        'new_build_belt': {'connectedLengthM': 100, 'assessedLengthM': 100, 'scopeSurveyComplete': True},
        'transport_improvement': {'beforeMinutes': 50, 'afterMinutes': 30, 'routeVerified': True, 'stationEntranceVerified': True},
        'amenity_improvement': {'beforeAccessibleFacilities': 0, 'afterAccessibleFacilities': 2, 'assessedFacilities': 2, 'openingScheduleVerified': True},
        'supply_demand_stability': {'plannedHouseholds': 100, 'existingHouseholds': 1000, 'annualAbsorptionHouseholds': 100, 'scopeSurveyComplete': True},
        'exposure': {'improvedDailyRoutes': 2, 'assessedDailyRoutes': 2, 'scopeSurveyComplete': True},
        'relative_competitiveness': {'competitiveAttributes': 3, 'assessedAttributes': 3, 'sameAreaCompared': True},
        'negative_impact': {'noiseExposure': 0, 'routeDisruption': 0, 'supplyCompetition': 0, 'scopeSurveyComplete': True},
    }
    obs = {'apartmentId': IDENTITY['apartmentId'], 'identity': IDENTITY, 'modelVersion': policy.VERSION,
           'center': center, 'projectLocations': {'p1': point},
           'evidence': {'center': evidence({'latitude': center['latitude'], 'longitude': center['longitude']}),
                        'point': evidence({'latitude': point['latitude'], 'longitude': point['longitude']}), 'm': evidence(inputs)},
           'projectRoutes': {'p1': {'evidenceIds': ['m'], 'barriersReviewed': True, 'connected': True,
                                   'walkingMeters': 500, 'walkingMinutes': 8, 'expectedBenefitVerified': True}},
           'measurements': {k: {'method': 'observed_inputs_v2', 'inputs': v, 'verificationStatus': 'verified',
                               'effectiveDate': '2028-01-01', 'evidenceIds': ['m'],
                               'scope': {'apartmentId': IDENTITY['apartmentId'], 'radiusMeters': 2000}} for k, v in inputs.items()}}
    return project, obs


def test_required_weights_and_60_40_formula():
    assert list(policy.REGIONAL.values()) == [30,15,15,15,15,10]
    assert list(policy.DIRECT.values()) == [30,25,20,15,10]
    for r, d, expected in [(100,100,5), (0,0,0), (85,40,3.4), (70,90,3.9)]:
        values = {**{k:r for k in policy.REGIONAL}, **{k:d for k in policy.DIRECT}}
        assert policy.aggregate(values)['score'] == expected
        values['exposure'] = None
        assert policy.aggregate(values)['score'] is None


@pytest.mark.parametrize('distance,expected', [(0,1),(800,.6),(2000,.2),(5000,0),(6000,0)])
def test_distance_policy(distance, expected):
    assert policy.distance_decay(distance) == pytest.approx(expected)


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf'), -1])
def test_invalid_distance_is_missing(value):
    assert policy.distance_decay(value) is None


def test_ready_score_and_traceable_distance(facts):
    p, obs = facts
    r = living.evaluate(IDENTITY, [p], obs, day=DAY)
    assert r['status'] == 'ready' and r['score'] == 4.8
    assert r['projects'][0]['benefitClass'] == 'direct'
    assert r['projects'][0]['distanceMeters'] == 445
    assert r['projects'][0]['distanceLabel'] == '대표점 직선거리'
    assert r['projects'][0]['walkingMinutes'] == 8
    assert r['evidence']['center']['snapshotId'] == 'fixture-snapshot'
    assert all(row['audit'] for row in r['metrics'])
    assert living.evaluate(IDENTITY, [p], obs, day=DAY) == r


def test_same_district_different_position_changes_result(facts):
    p, obs = facts
    near = living.evaluate(IDENTITY, [p], obs, day=DAY)
    other = copy.deepcopy(obs)
    other['apartmentId'] = 'other'
    other['identity'] = {**IDENTITY, 'apartmentId': 'other', 'jibun': '9'}
    other['center']['latitude'] = 37.61
    other['evidence']['center']['raw']['latitude'] = 37.61
    far = living.evaluate(other['identity'], [p], other, day=DAY)
    assert near['score'] is not None and far['score'] is None
    assert not far['projects']  # >2km without verified regional connection


@pytest.mark.parametrize('change', ['barrier', 'entrance', 'stale', 'identity', 'license', 'missing_metric', 'future_date', 'spoofed_point'])
def test_unknown_cannot_become_direct_or_zero(facts, monkeypatch, change):
    p, obs = facts
    if change == 'barrier': obs['projectRoutes']['p1']['connected'] = False
    if change == 'entrance': p['projectType'] = 'transport'
    if change == 'stale': obs['evidence']['m']['asOfDate'] = '2025-01-01'
    if change == 'identity': obs['identity'] = {**IDENTITY, 'jibun':'99'}
    if change == 'license': monkeypatch.setitem(sources.REGISTRY[p['sourceId']], 'allowedUses', ['web'])
    if change == 'missing_metric': obs['measurements'].pop('relative_competitiveness')
    if change == 'future_date': obs['measurements']['transport_improvement']['effectiveDate'] = '2040-01-01'
    if change == 'spoofed_point': obs['center']['latitude'] = 37.59
    r = living.evaluate(IDENTITY, [p], obs, day=DAY)
    assert r['score'] is None and r['status'] == 'insufficient_data'
    if change == 'entrance':
        assert r['referenceProjects'][0]['distanceMeters'] is None
        assert 'latitude' not in r['referenceProjects'][0]


def test_no_district_or_project_count_bonus_and_no_duplicate(facts):
    p, obs = facts
    single = living.evaluate(IDENTITY, [p], obs, day=DAY)
    duplicate = living.evaluate(IDENTITY, [p] * 20, obs, day=DAY)
    assert duplicate['score'] == single['score']
    assert len(duplicate['projects']) == 1
    conflict = living.evaluate(IDENTITY, [p, {**p,'stage':'approved'}], obs, day=DAY)
    assert conflict['score'] is None and not conflict['projects']
    without = living.evaluate(IDENTITY, [p], day=DAY)
    assert without['score'] is None and not without['projects']


def test_matching_address_preserves_all_original_records(facts):
    p, _ = facts
    merged = living.deduplicate([p, {**p, 'id':'other-id','sourceRecordId':'other-record'}])
    assert len(merged) == 1 and len(merged[0]['sourceRecords']) == 2
    separate = living.deduplicate([p, {**p, 'id':'other-id','sourceRecordId':'other-record','jibun':'3'}])
    assert len(separate) == 2


def test_numeric_inputs_and_missing_are_different():
    assert policy.normalize('negative_impact', {'noiseExposure':1,'routeDisruption':1,'supplyCompetition':1,'scopeSurveyComplete':True}) == 0
    assert policy.normalize('negative_impact', {'noiseExposure':1,'routeDisruption':1}) is None
    assert policy.normalize('housing_conversion', {'convertedLandM2':1,'oldResidentialLandM2':0,'scopeSurveyComplete':True,'overlapRemoved':True}) is None


def test_official_export_dates_use_korea_time_not_collection_date():
    assert sources.stage_date(1781708400000) == '2026-06-18'
    assert sources.stage_date('2026-06-18 00:00:00.0') == '2026-06-18'
    assert sources.stage_date(None) is None
    assert sources.stage_date(float('nan')) is None


def raw_row():
    return {'BASIC_INFO_SEQ': 1, 'BSNS_NAME':'가상 시험 사업', 'SITE_CODE_NM':'동대문구',
            'BSNS_ADDR':'장안동 1-1 일대', 'CLASSIFY_L_NM':'재개발', 'PROPEL_CD_NM':'사업시행인가', 'SUPLY_HSHLD':None}


def test_snapshot_idempotency_partial_and_atomic_failure(tmp_path):
    path = tmp_path / 'sources.sqlite3'
    first = sources.save_snapshot('seoul-plan-renewal', [raw_row()], as_of=DAY.isoformat(), complete=True, path=path)
    assert sources.save_snapshot('seoul-plan-renewal', [raw_row()], as_of=DAY.isoformat(), complete=True, path=path) == first
    row = sources.load_projects(path)[0]
    assert row['plannedHouseholds'] is None and row['stage'] == 'approved'
    assert row['geometryType'] is None and row['snapshotId'] == first
    sources.save_snapshot('seoul-plan-renewal', [], as_of=DAY.isoformat(), complete=False, path=path)
    assert sources.load_projects(path)[0] == row
    with pytest.raises(sources.SourceError):
        sources.save_snapshot('seoul-plan-renewal', [raw_row(), raw_row()], as_of=DAY.isoformat(), complete=True, path=path)
    assert sources.load_projects(path)[0] == row
    with pytest.raises(sources.SourceError):
        sources.save_snapshot('seoul-plan-boundary', [raw_row()], as_of=DAY.isoformat(), complete=True, path=path)


def test_official_fetch_count_and_retries():
    responses = [io.BytesIO(json.dumps({'DESCRIPTION': {'id':'ID'}, 'DATA':[raw_row()]}).encode()),
                 io.BytesIO(b'{result:"ok",page: {pageNo:1, pageCount: 1, totalCount: 1, listCount: 1},list:[]}')]
    assert sources.fetch_seoul(opener=mock.Mock(side_effect=responses), sleep=lambda _:None) == [raw_row()]
    with pytest.raises(sources.SourceError):
        sources.fetch_seoul(opener=mock.Mock(side_effect=OSError('do not log credential')), sleep=lambda _:None)
    responses = [io.BytesIO(json.dumps({'DESCRIPTION': {'id':'ID'}, 'DATA':[raw_row()]}).encode()),
                 io.BytesIO(b'{result:"ok",page: {pageNo:1, pageCount: 1, totalCount: 2, listCount: 2},list:[]}')]
    with pytest.raises(sources.SourceError):
        sources.fetch_seoul(opener=mock.Mock(side_effect=responses), sleep=lambda _:None)


def test_review_claim_without_saved_raw_is_rejected(facts, tmp_path):
    _, obs = facts
    with pytest.raises(sources.SourceError, match='공식 원본'):
        save_observation(obs, path=tmp_path/'x.db', registry_lookup=lambda _:IDENTITY)


def test_official_fetch_tls_fallback_keeps_certificate_validation():
    bodies = [json.dumps({'DESCRIPTION': {'id':'ID'}, 'DATA':[raw_row()]}).encode(),
              b'{result:"ok",page: {pageNo:1, pageCount: 1, totalCount: 1, listCount: 1},list:[]}']
    opener = mock.Mock(side_effect=sources.URLError(sources.ssl.SSLCertVerificationError('strict AKI')))
    with mock.patch.object(sources.subprocess, 'run', side_effect=[
        subprocess.CompletedProcess([], 0, stdout=body) for body in bodies
    ]) as run:
        assert sources.fetch_seoul(opener=opener, sleep=lambda _:None) == [raw_row()]
        assert run.call_count == 2
        for call in run.call_args_list:
            command = call.args[0]
            assert command[-1].startswith('https://')
            assert '-k' not in command and '--insecure' not in command
            assert call.kwargs['check'] is True


def test_real_desian_60_and_same_district_no_invented_benefit(tmp_path):
    import future_transformation as f
    import real_estate_search
    entities = real_estate_search._search_entities()
    entity = next(e for e in entities if e.get('name') == '동대문더퍼스트데시앙' and e.get('legalDong') == '장안동')
    identity = {**entity, 'apartmentId': f.apartment_key(entity), 'areaLabel': '60㎡'}
    result = living.analyze(identity, path=tmp_path/'empty.db', day=DAY)
    assert identity['jibun'] == '587'
    assert result['score'] is None
    assert result['projects'][0]['name'] == '장안현대'
    assert result['projects'][0]['distanceMeters'] == 705
    assert result['projects'][0]['benefitClass'] == 'conditional'
    assert result['referenceProjects']
    assert {p['name'] for p in result['referenceProjects']} == {'장안1구역 재개발', '면목선 도시철도'}
    assert all(p['distanceMeters'] is None for p in result['referenceProjects'])
    assert result['coverage'] == {'projects':3, 'mappedProjects':1, 'verifiedMetrics':1, 'totalMetrics':11}
    assert result['displayProjects'][0]['plannedHouseholds'] == 1754
    assert result['displayProjects'][0]['stageAsOf'] == '2026-06-11'
    assert len(sources.bundled_projects()) == 830
    imun = next(e for e in entities if e.get('district') == '동대문구' and e.get('legalDong') == '이문동')
    other = living.analyze({**imun, 'apartmentId':f.apartment_key(imun)}, path=tmp_path/'empty.db', day=DAY)
    assert {p['id'] for p in other['referenceProjects']} != {p['id'] for p in result['referenceProjects']}


def assert_apartment_focused_judgment(result, apartment_name, neighboring_project):
    headline = result['headline']
    detail = result.get('intro', '')
    normalized_name = re.sub(r'\s+', '', apartment_name)
    assert normalized_name in re.sub(r'\s+', '', headline) or '이 단지' in headline
    assert not headline.startswith(neighboring_project)
    assert any(word in headline for word in ('가격', '매수', '생활', '교통', '공급', '신축', '불편', '경쟁'))
    assert neighboring_project in headline + detail
    assert result['judgment']['headline'] == headline
    # Nearby official plans alone do not establish a direct benefit or a price rise.
    assert not re.search(r'직접\s*수혜(?:예요|를\s*받아요|가\s*확실)', headline + detail)
    assert not re.search(r'가격(?:이|은)?\s*(?:반드시|확실히)\s*(?:오르|상승)', headline + detail)


@pytest.mark.parametrize('stage,meters', [
    ('construction', 300),
    ('approved', 300),
    ('association', 300),
    ('designated', 300),
    ('planning', 300),
    ('designated', 1200),
    ('designated', None),
])
def test_living_area_headline_explains_apartment_impact_from_project_facts(stage, meters):
    import living_area_context as context
    report = living.empty_report('test', DAY)
    report['referenceProjects'] = [{
        'id': 'near', 'name': '가상구역', 'projectType': 'redevelopment',
        'stage': stage, 'stageLabel': stage, 'distanceMeters': meters,
    }]
    described = context.describe(report, {**IDENTITY, 'name': '가상단지'})
    assert_apartment_focused_judgment(described, '가상단지', '가상구역')


def test_living_area_headline_uses_nearest_located_project():
    import living_area_context as context
    report = living.empty_report('test', DAY)
    report['referenceProjects'] = [
        {'id':'large', 'name':'먼구역', 'projectType':'redevelopment', 'stage':'planning', 'stageLabel':'계획',
         'siteAreaM2':100000, 'distanceMeters':1500},
        {'id':'near', 'name':'가까운구역', 'projectType':'redevelopment', 'stage':'construction', 'stageLabel':'착공',
         'distanceMeters':300},
    ]
    described = context.describe(report, {**IDENTITY, 'name': '가상단지'})
    assert_apartment_focused_judgment(described, '가상단지', '가까운구역')
    assert described['proximitySummary'].startswith('가까운구역')


@pytest.mark.parametrize('apartment_name,neighboring_project', [
    ('개포 래미안 포레스트', '개포우성6차'),
    ('동대문더퍼스트데시앙', '장안1구역 재개발'),
])
def test_real_report_headline_is_about_the_selected_apartment(tmp_path, apartment_name, neighboring_project):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities() if e.get('name') == apartment_name)
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 18))

    assert result['status'] != 'error'
    assert result['score'] is None
    assert any(p['name'] == neighboring_project for p in result['displayProjects'])
    assert not any(p['benefitClass'] == 'direct' for p in result['displayProjects'])
    selected_id = result['planRating']['components']['housing']['selectedProjectId']
    selected = next(p for p in result['displayProjects'] if p['id'] == selected_id)
    briefing = result['briefing']
    assert_safe_briefing(result)
    assert briefing['verdict'] == 'normal'
    assert result['headline'] == '생활권 변화는 보통이에요. ' + briefing['reason']
    assert briefing['reason'].endswith('새 교통 호재는 약해요.')
    assert briefing['advice'][0].startswith(apartment_name)
    assert selected['name'] in ' '.join(briefing['strengths'])
    rail_text = ' '.join(briefing['weaknesses'])
    assert ('GTX-C' if apartment_name == '개포 래미안 포레스트' else '면목선') in rail_text
    assert '새 교통 가점은 작아요' in rail_text
    assert '출입구와 걸어가는 시간은 확인되지 않았어요' in ' '.join(briefing['caveats'])
    rail = next(p for p in result['displayProjects'] if p['id'] == 'metro-rail:wirye')
    assert '남위례역' in rail['factSummary']
    assert rail['checkedAt'] == '2026-10-19'


def briefing_text(result):
    briefing = result['briefing']
    return ' '.join([briefing['reason'], *briefing['strengths'], *briefing['weaknesses'],
                     *briefing['unknowns'], *briefing['advice'], *briefing['caveats']])


def assert_safe_briefing(result):
    text = briefing_text(result)
    assert result['judgment']['headline'] == result['headline']
    # Nearby official plans alone do not establish a direct benefit or a price rise.
    assert not re.search(r'직접\s*수혜(?:예요|를\s*받아요|가\s*확실)', text)
    assert not re.search(r'가격(?:이|은)?\s*(?:반드시|확실히)\s*(?:오르|상승)', text)


def test_living_area_verdict_requires_balanced_plans_or_direct_benefit_for_positive_label():
    import living_area_context as context
    identity = {**IDENTITY, 'name':'가상단지'}
    project = {'id':'near', 'name':'가상구역', 'projectType':'redevelopment',
               'stage':'construction', 'distanceMeters':300, 'benefitClass':'unverified'}
    report = {'displayProjects':[project], 'planRating':{'score':4.1,'components':{}},
              'judgment':{}}
    assert context.conclude(copy.deepcopy(report), identity)['headline'].startswith('생활권 변화는 보통이에요.')
    report['displayProjects'][0]['benefitClass'] = 'direct'
    assert context.conclude(copy.deepcopy(report), identity)['headline'].startswith('생활권 변화는 좋아요.')
    report['displayProjects'][0]['benefitClass'] = 'unverified'
    report['planRating']['score'] = 2.2
    low = context.conclude(copy.deepcopy(report), identity)
    assert low['headline'].startswith('생활권 변화는 약해요.')
    assert low['briefing']['label'] == '약해요'
    assert "'약해요'는 지금 살기 나쁘다는 뜻이 아니에요" in ' '.join(low['briefing']['caveats'])
    report['planRating']['score'] = None
    pending = context.conclude(report, identity)
    assert pending['headline'].startswith('생활권 변화는 판단을 보류했어요.')
    assert pending['briefing']['label'] == '판단 보류'


def test_living_area_verdict_describes_nearby_housing_cluster_and_planned_station():
    import living_area_context as context

    report = {'displayProjects': [
        {'id': f'zone-{i}', 'name': f'가상구역{i}', 'projectType': 'redevelopment',
         'stage': 'association', 'distanceMeters': distance}
        for i, distance in enumerate((400, 1000, 1800))
    ] + [{'id': 'rail', 'name': '가상철도', 'projectType': 'transport'}],
        'planRating': {'score': 3.9, 'subScores': {'housing': 4.4, 'transport': 3.1},
                       'components': {'housing': {'selectedProjectId': 'zone-0',
                                                  'inputs': [{'projectId': f'zone-{i}', 'distanceMeters': distance}
                                                             for i, distance in enumerate((400, 1000, 1800))]},
                                      'transport': {'selectedProjectId': 'rail', 'inputs': [
                                          {'projectId': 'rail', 'name': '가상역', 'distanceMeters': 1300,
                                           'rawScore': 3.1}]}}}, 'judgment': {}}
    identity = {**IDENTITY, 'name': '가상단지'}

    good = context.conclude(copy.deepcopy(report), identity)
    assert good['headline'] == '생활권 변화는 좋아요. 정비사업이 몰려 있고, 예정역도 가까워요.'
    assert good['briefing']['verdict'] == 'good'
    assert '실제로 누릴 이점이나 집값 상승을 뜻하지 않아요' in ' '.join(good['briefing']['caveats'])

    far_station = copy.deepcopy(report)
    far_station['planRating']['components']['transport']['inputs'][0]['distanceMeters'] = 1800
    assert context.conclude(far_station, identity)['headline'].startswith('생활권 변화는 보통이에요.')

    one_project = copy.deepcopy(report)
    one_project['planRating']['components']['housing']['inputs'] = one_project['planRating']['components']['housing']['inputs'][:1]
    assert context.conclude(one_project, identity)['headline'].startswith('생활권 변화는 보통이에요.')


def test_living_area_headline_says_multiple_projects_contributed_to_housing_score():
    import living_area_context as context

    report = {'displayProjects': [
        {'id':'zone-1', 'name':'첫 구역', 'projectType':'redevelopment', 'stage':'construction',
         'distanceMeters':1000},
        {'id':'rail', 'name':'가상철도', 'projectType':'transport'},
    ], 'planRating':{'score':4.2, 'subScores':{'housing':5.0, 'transport':2.9},
                     'components':{'housing':{'selectedProjectId':'zone-1', 'projectCount':3},
                                   'transport':{'selectedProjectId':'rail', 'inputs':[
                                       {'projectId':'rail', 'name':'가상역', 'distanceMeters':1500,
                                        'rawScore':2.9}]}}}, 'judgment':{}}
    result = context.conclude(report, {**IDENTITY, 'name':'가상단지'})

    assert result['headline'] == '생활권 변화는 보통이에요. 정비사업은 많지만, 새 교통 호재는 약해요.'
    assert result['briefing']['strengths'][0].startswith('직선 2km 안에 정비사업이 3곳이에요.')
    assert '**공사 중인 단계**' in result['briefing']['strengths'][0]
    assert '매일 걸어서 타기엔 조금 먼 거리예요' in result['briefing']['weaknesses'][0]
    assert result['intro'] == ' '.join(result['briefing']['advice'])


def test_forestia_report_leads_with_nearby_housing_and_station_plan(tmp_path):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == '산성역 포레스티아' and e.get('district') == '성남수정구')
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 19))

    assert result['headline'] == '생활권 변화는 좋아요. 정비사업이 몰려 있고, 예정역도 가까워요.'
    assert '출입구와 걸어가는 시간은 확인되지 않았어요' in ' '.join(result['briefing']['caveats'])


def test_pangyo_valley_xi_2_route_is_not_described_as_a_new_station(tmp_path):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == '판교밸리자이 2단지' and e.get('jibun') == '585')
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 19))

    assert result['planRating']['transportCoverage']['status'] == 'station_mapping_incomplete'
    assert result['planRating']['subScores'] == {'housing': None, 'transport': None}
    unknowns = ' '.join(result['briefing']['unknowns'])
    assert result['briefing']['verdict'] == 'pending'
    assert '직선 2km 안의 정비사업을 찾지 못했어요' in unknowns
    assert '신규 예정역이 없어요' not in briefing_text(result)
    assert '다른 철도 노선의 예정역 목록·위치를 아직 확인 중' in unknowns
    assert '0점을 주지 않아요' in result['planRating']['missingReasons']['transport']


def test_living_area_headline_uses_korean_particles_for_numbered_complexes_and_projects():
    import living_area_context as context

    assert context._topic('성원2') == '는'
    assert context._topic('대조1') == '은'
    assert context._with('목동4단지') == '와'
    assert context._with('방학신동아1차') == '와'
    assert context._with('대조1 사업') == '과'


def test_transport_only_report_uses_middle_judgment_for_middle_score(tmp_path):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == '제일풍경채 센텀' and e.get('district') == '시흥시')
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 18))

    assert result['planRating']['subScores'] == {'housing': None, 'transport': 3.1}
    assert result['planRating']['score'] is None
    assert result['headline'] == '생활권 변화는 판단을 보류했어요. 새 철도는 기대되지만, 주거환경 자료가 아직 없어요.'
    assert '신안산선' in ' '.join(result['briefing']['strengths'])


@pytest.mark.parametrize('name,district,label,rail', [
    ('신주아파트', '동대문구', '좋아요.', '동북선'),
    ('남가좌동현대', '서대문구', '약해요.', '서부선'),
])
def test_real_report_shows_good_and_bad_plan_judgments_without_invented_direct_benefit(
        tmp_path, name, district, label, rail):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == name and e.get('district') == district)
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 18))

    assert result['status'] != 'error'
    if rail == '서부선':
        assert rail not in result['headline']
        assert not any(row.get('lineId') == 'seobu'
            for row in result['planRating']['components'].get('transport', {}).get('inputs', []))
        return
    assert result['headline'].startswith(f'생활권 변화는 {label}')
    assert_safe_briefing(result)
    assert result['briefing']['advice'][0].startswith(name)
    assert rail in ' '.join(result['briefing']['strengths'] + result['briefing']['weaknesses'])
    assert not any(p.get('benefitClass') == 'direct' for p in result['displayProjects'])
    caveats = ' '.join(result['briefing']['caveats'])
    assert '출입구와 걸어가는 시간은 확인되지 않았어요' in caveats
    if label == '좋아요.':
        assert '계획 점수는 실제로 누릴 이점이나 집값 상승을 뜻하지 않아요' in caveats


def test_living_area_verdict_uses_highest_scored_station_on_shared_rail_project():
    import living_area_context as context
    report = {'displayProjects':[{'id':'rail','name':'가상철도','projectType':'transport'}],
              'planRating':{'score':3.0,'components':{'transport':{
                  'selectedProjectId':'rail', 'inputs':[
                      {'projectId':'rail','name':'먼역','distanceMeters':1900,'rawScore':1.0},
                      {'projectId':'rail','name':'가까운역','distanceMeters':400,'rawScore':3.0},
                  ]}}}, 'judgment':{}}
    result = context.conclude(report, {**IDENTITY, 'name':'가상단지'})
    assert '가까운역 예정 위치가 직선 400m예요. **걸어서 다닐 만한 거리예요**.' in briefing_text(result)
    assert '먼역' not in briefing_text(result)


def test_living_area_headline_explains_the_housing_project_used_for_the_score():
    import living_area_context as context
    report = {'displayProjects':[
        {'id':'nearest','name':'가까운구역','projectType':'redevelopment','stage':'planning',
         'distanceMeters':200},
        {'id':'rated','name':'점수반영구역','projectType':'redevelopment','stage':'construction',
         'distanceMeters':600},
        {'id':'rail','name':'가상철도','projectType':'transport'},
    ], 'planRating':{'score':2.7,'subScores':{'housing':3.9,'transport':0.9},
                    'components':{'housing':{'selectedProjectId':'rated'},
                                  'transport':{'selectedProjectId':'rail','inputs':[
                                      {'projectId':'rail','name':'가상역','distanceMeters':1800,'rawScore':0.9}]}}},
        'judgment':{}}
    result = context.conclude(report, {**IDENTITY,'name':'가상단지'})
    assert result['headline'] == '생활권 변화는 약해요. 정비사업은 기대되지만, 새 교통 호재는 약해요.'
    assert '점수반영구역' in result['briefing']['strengths'][0]
    assert '가까운구역' not in briefing_text(result)
    assert '새 교통 가점은 작아요' in result['briefing']['weaknesses'][0]


def test_unlicensed_legacy_public_report_is_blocked():
    import future_transformation as f
    r = f.public_facts({'apartmentId':'x', 'asOfDate':DAY.isoformat(), 'projects':[{'name':'blocked'}], 'futureTransformationScore':100})
    assert r['score'] is None and r['projects'] == []
    failed = f.public_facts({'apartmentId':'x', 'asOfDate':DAY.isoformat(), 'status':'error'})
    assert failed['status'] == 'error'
    assert failed['headline'] == '생활권 자료를 불러오지 못했어요.'


def test_corrupt_database_falls_back(tmp_path):
    path=tmp_path/'corrupt.db'
    path.write_bytes(b'broken database')
    result = living.analyze(IDENTITY, path=path, day=DAY)
    assert result['status'] == 'error'
    assert result['headline'] == '생활권 자료를 불러오지 못했어요.'
    assert result['judgment']['shortTerm'] == '자료를 불러오지 못해 평가하지 않았어요.'


def test_official_context_does_not_make_direct_benefit_or_rail_walk_time(tmp_path):
    import living_area_context as context
    identity = {'apartmentId':'4ba5297e34906625','district':'동대문구','legalDong':'장안동','jibun':'587'}
    result = living.analyze(identity, path=tmp_path/'new.db', day=DAY)
    assert result['center']['latitude'] == 37.575066938
    assert result['score'] is None
    rail = next(p for p in result['displayProjects'] if p['projectType'] == 'transport')
    assert rail['routeLengthKm'] == 9.36
    assert rail['distanceMeters'] is None and rail.get('walkingMinutes') is None
    assert not any(p['benefitClass'] == 'direct' for p in result['displayProjects'])
    assert all('rawExcerpt' not in p for p in result['displayProjects'])
    wrong = living.analyze({**identity, 'jibun':'588'}, path=tmp_path/'new.db', day=DAY)
    assert not wrong.get('center')
    assert not any(p.get('distanceMeters') is not None for p in wrong['displayProjects'])


def test_wirye_sinsa_comes_from_shared_transport_catalog_for_every_matching_report(tmp_path):
    day = dt.date(2026, 10, 18)
    identities = [
        {'apartmentId':'484457631ccb1633','province':'경기도','city':'성남시',
         'district':'성남수정구','legalDong':'산성동','jibun':'1336','name':'산성역 헤리스톤'},
        {'apartmentId':'another-sujeong-complex','province':'경기도','city':'성남시',
         'district':'성남수정구','legalDong':'창곡동','jibun':'1','name':'다른 단지'},
        {'apartmentId':'songpa-complex','province':'서울특별시','district':'송파구','name':'송파 단지'},
        {'apartmentId':'gangnam-complex','province':'서울특별시','district':'강남구','name':'강남 단지'},
    ]
    for identity in identities:
        report = living.analyze(identity, path=tmp_path/'new.db', day=day)
        reference = next(p for p in report['capitalTransport']['matchedPlans'] if p['id'] == 'wirye-sinsa')
        assert reference['stageCode'] == 'planning'
        assert reference['regionalReference'] is True
        assert reference['stations'] == []
        assert 'distanceMeters' not in reference and 'walkingMinutes' not in reference
        assert not any(p['name'] == '위례신사선' for p in report['displayProjects'])
    for district in ('성남중원구', '성남분당구'):
        report = living.analyze({**identities[0], 'district':district}, path=tmp_path/'new.db', day=day)
        assert not any(p['id'] == 'wirye-sinsa' for p in report['capitalTransport']['matchedPlans'])


def test_context_license_expiry_and_integrity_fail_closed(monkeypatch):
    import living_area_context as context
    identity = {'apartmentId':'4ba5297e34906625','district':'동대문구','legalDong':'장안동','jibun':'587'}
    monkeypatch.setitem(sources.REGISTRY, 'seoul-apartment-points', {**sources.REGISTRY['seoul-apartment-points'], 'licenseStatus':'blocked'})
    _, obs = context.prepare(identity, sources.bundled_projects(), None, DAY)
    assert not obs.get('center')
    _, obs = context.prepare(identity, sources.bundled_projects(), None, DAY + dt.timedelta(days=121))
    assert not obs.get('center')
    original = context.read
    def corrupt(path):
        bundle = original(path)
        if path == context.CONTEXT_PATH:
            bundle['projects'][0]['plannedHouseholds'] = 9999
        return bundle
    monkeypatch.setattr(context, 'read', corrupt)
    with pytest.raises(ValueError, match='integrity'):
        context.prepare(identity, [], None, DAY)


def test_official_point_matching_requires_exact_lot_or_id(monkeypatch):
    import living_area_context as context
    actual = context.read(context.POINTS_PATH)
    row = next(r for r in actual['rows'] if r['daddr'] == '857' and r['apt_nm'] == '송파파인타운13단지')
    target = {'apartmentId':'test-binding-only', 'district':row['sgg_addr'], 'legalDong':row['emd_addr'], 'jibun':'857','name':row['apt_nm']}
    _, obs = context.prepare(target, [], None, DAY)
    assert obs['center']['sourceRecordId'] == row['apt_cd']
    _, wrong = context.prepare({**target, 'jibun':'858'}, [], None, DAY)
    assert not wrong.get('center')
    _, wrong = context.prepare({**target, 'name':row['apt_nm']+'2'}, [], None, DAY)
    assert not wrong.get('center')


def test_point_refresh_is_atomic_and_preserves_reviewed_binding(tmp_path):
    import living_area_context as context
    path = tmp_path/'points.json'
    original = context.read(context.POINTS_PATH)
    path.write_text(json.dumps(original))
    rows = original['rows']
    with pytest.raises(sources.SourceError):
        context.save_points([rows[0],rows[0]], day=DAY, path=path)
    assert json.loads(path.read_text()) == original
    context.save_points(rows, day=DAY, path=path)
    saved = json.loads(path.read_text())
    assert saved['bindings'] == original['bindings']
    assert saved['rowsDigest'] == sources.digest(rows)
    assert len(saved['rows']) == 2894


def test_map_provider_failure_is_not_silently_replaced():
    html = (sources.config.ROOT/'앱화면/real-estate-search.html').read_text()
    body = re.search(r'    async function loadMapApi\(\) \{.*?\n    \}', html, re.S).group()
    js = "const assert=require('node:assert/strict'); let fallback=0; let fail=true; const provider={native:true}; async function loadKakaoMapApi(){if(fail)throw new Error('domain');return provider;} async function loadLeafletMapApi(){fallback++;}\n"+body+"\n(async()=>{await assert.rejects(loadMapApi(),/domain/);assert.equal(fallback,0);fail=false;assert.equal(await loadMapApi(),provider);})().catch(e=>{console.error(e);process.exitCode=1;});"
    result = subprocess.run(['node'], input=js, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_planned_stop_farther_than_current_station_is_not_a_transport_change():
    import living_area_plan_rating as rating

    current = {'name': '가상역 8호선', 'distanceMeters': 300}
    tram = {'name': '먼트램역', 'lineId': 'wirye', 'stage': 'construction', 'stageLabel': '시운전 중 · 개통 전',
            'distanceMeters': 1500}
    near_tram = {**tram, 'name': '가까운트램역', 'distanceMeters': 250}
    gtx = {'name': '먼GTX역', 'lineId': 'gtx-c', 'stage': 'construction', 'stageLabel': '2026년 9월 착공',
           'distanceMeters': 1700}
    operating = {'name': '기존역', 'lineId': 'wirye', 'serviceStatus': 'operating', 'distanceMeters': 900}

    kept, excluded = rating.split_useful_stations([tram, near_tram, gtx, operating], current)
    assert [row['name'] for row in kept] == ['가까운트램역', '먼GTX역', '기존역']
    assert excluded == [{'name': '먼트램역', 'lineId': 'wirye', 'lineName': '위례선 트램', 'distanceMeters': 1500}]
    assert rating.split_useful_stations([tram], None) == ([tram], [])


def test_briefing_says_no_new_rail_when_every_planned_stop_is_farther_than_current_station():
    import living_area_context as context

    report = {'displayProjects': [
        {'id': 'zone-1', 'name': '가상구역', 'projectType': 'redevelopment', 'stage': 'disposal', 'distanceMeters': 900},
    ], 'planRating': {'score': 3.0, 'subScores': {'housing': 5.0, 'transport': 0},
                      'components': {'housing': {'selectedProjectId': 'zone-1', 'projectCount': 4},
                                     'transport': {'inputs': [], 'noUsefulPlannedStation': True,
                                                   'excludedStations': [{'lineId': 'wirye', 'name': '먼트램역'}]}}},
        'judgment': {}}
    result = context.conclude(report, {**IDENTITY, 'name': '가상단지'})

    assert result['headline'] == '생활권 변화는 보통이에요. 정비사업은 많지만, 새로 생길 철도 호재는 없어요.'
    assert result['briefing']['weaknesses'] == ['근처에 새로 탈 만한 철도 계획은 없어요.']
    assert '먼트램역' not in briefing_text(result)
    assert '지금 걸어서 타는 역보다 멀어서' in ' '.join(result['briefing']['caveats'])


def test_heriston_drops_wirye_tram_and_reports_wirye_sinsa_as_regional_news(tmp_path):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == '산성역 헤리스톤' and e.get('legalDong') == '산성동' and e.get('jibun') == '1336')
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 20))
    transport = result['planRating']['components'].get('transport') or {}
    if not transport.get('currentStation'):
        pytest.skip('현재 이용역 거리 캐시가 없어요.')

    assert transport['currentStation']['name'] == '산성역 8호선'
    assert transport['noUsefulPlannedStation'] is True
    assert {row['lineId'] for row in transport['excludedStations']} == {'wirye'}
    news = ' '.join(result['briefing']['news'])
    assert '위례신사선' in news and '예비타당성조사 통과' in news
    assert '위례선 트램' not in news and '월곶~판교' not in news


def test_gyeonggi_address_with_combined_district_still_matches_city_rail_plans():
    import capital_transport
    import planned_rail

    row = {'province': '경기도', 'city': '성남시', 'district': '성남수정구',
           'address': '경기도 성남수정구 신흥동 6951'}
    assert 'wirye-sinsa' in {line['id'] for line in planned_rail.planned_rail_for_candidate(row)}
    assert capital_transport._location(row) == ('경기도', '성남시')


def test_operating_station_gains_half_points_when_its_line_adds_new_stops():
    import living_area_plan_rating as rating

    center = {'latitude': 37.6190, 'longitude': 126.9200}
    operating = [{'id': 'gtx-a:004', 'name': '연신내역 · GTX-A', 'lineId': 'gtx-a',
                  'projectId': 'metro-rail:gtx-a', 'distanceMeters': 798}]
    rows = rating.line_extension_inputs(operating, center)

    assert [row['name'] for row in rows] == ['연신내역 · GTX-A']
    row = rows[0]
    assert row['kind'] == 'line_extension' and '삼성역' in row['pendingStations']
    new_station = 5 * row['accessFactor'] * row['impactFactor'] * row['maturityFactor']
    assert row['rawScore'] == pytest.approx(new_station * rating.LINE_EXTENSION_SHARE)
    assert rating.line_extension_inputs([], center) == []


def test_miseong_counts_gtx_a_extension_instead_of_withholding_transport(tmp_path):
    import future_transformation as transformation
    import real_estate_search

    entity = next(e for e in real_estate_search._search_entities()
                  if e.get('name') == '미성아파트' and e.get('legalDong') == '불광동' and e.get('jibun') == '248')
    identity = {**entity, 'apartmentId': transformation.apartment_key(entity)}
    result = living.analyze(identity, path=tmp_path / 'empty.db', day=dt.date(2026, 10, 20))
    transport = result['planRating']['components']['transport']

    assert transport['inputs'][0]['kind'] == 'line_extension'
    assert transport['inputs'][0]['name'] == '연신내역 · GTX-A'
    assert result['planRating']['subScores']['transport'] > 0
    text = briefing_text(result)
    assert '이미 운행 중인 연신내역 · GTX-A' in text and '삼성역' in text
    assert '이미 있는 교통이라 변화 점수에는 넣지 않았어요' not in text
