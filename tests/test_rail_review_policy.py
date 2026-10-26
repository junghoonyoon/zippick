import copy
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import capital_transport
import living_area_context as narrative
import living_area_plan_rating as rating
import living_area_rail_policy as policy
import planned_rail
import rail_station_mapping as registry

DAY = dt.date(2026, 10, 20)


def station(line_id='gangbuk-cross'):
    row = policy._read(policy.PATH.stat().st_mtime_ns)[line_id]
    return dict(id=line_id + ':test', projectId='metro-rail:' + line_id,
                lineId=line_id, lineName=row['name'], name='시험역 · ' + row['name'],
                stage=row['stageCode'], stageLabel=row['stageLabel'],
                latitude=37.58, longitude=127.04, distanceMeters=200,
                scoringEligible=True, serviceStatus='planned', locationStatus='located')


@pytest.mark.parametrize('line_id', ['gangbuk-cross', 'seobu'])
def test_reviewed_lines_are_retained_but_cannot_earn_points(line_id):
    original = station(line_id)
    decorated = policy.annotate(original)
    assert decorated['railReviewStatus'] == 'reconsidering'
    assert decorated['defaultVisible'] is False
    assert decorated['scoringEligible'] is False
    assert decorated['reviewLabel'] == '재추진 중 · 일정 미정'
    assert decorated['stageLabel'] == original['stageLabel']
    assert original['scoringEligible'] is True
    assert policy.line_policy(line_id, original['stage'], original['stageLabel']) is None


def test_normal_plans_and_later_reviewed_construction_are_not_permanently_hidden(monkeypatch):
    assert not policy.under_review({'lineId': 'myeonmok', 'stage': 'planning', 'stageLabel': '기본계획안 의견 수렴'})
    assert policy.line_policy('myeonmok', 'planning', '기본계획안 의견 수렴')
    assert not policy.under_review({'lineId': 'gangbuk-cross', 'stage': 'construction', 'stageLabel': '공사 중'})
    rows = copy.deepcopy(policy._read(policy.PATH.stat().st_mtime_ns))
    rows['gangbuk-cross'].update(stageCode='construction', stageLabel='공사 중', maturity='construction')
    monkeypatch.setattr(policy, '_read', lambda _: rows)
    assert policy.line_policy('gangbuk-cross', 'construction', '공사 중')


@pytest.mark.parametrize('label', ['계획 단계', '도시철도망 계획 승인', '예타 미통과 · 대안 검토'])
def test_mokdong_failure_overrides_older_network_plan_labels(label):
    original = {**station('mokdong'), 'stageLabel': label}
    decorated = policy.annotate(original)
    assert decorated['defaultVisible'] is decorated['scoringEligible'] is False
    assert decorated['reviewLabel'] == '예타 미통과 · 재검토 중'
    assert decorated['reviewSourceUrl'].endswith('nttNo=415662')
    assert decorated['reviewSourceDate'] == '2024-07-11'
    assert policy.line_policy('mokdong', 'planning', label) is None
    assert original['scoringEligible'] is True


@pytest.mark.parametrize('label', ['예타 미통과', '예타탈락', '예타 철회'])
def test_explicit_failed_or_withdrawn_feasibility_is_reference_only(label):
    assert policy.under_review({'lineId': 'unregistered', 'stage': 'planning', 'stageLabel': label})


def test_mokdong_is_reference_only_in_candidate_map_coverage_and_scores():
    identity = {'province': '서울특별시', 'district': '양천구'}
    planned = next(p for p in planned_rail.planned_rail_for_candidate(identity) if p['id'] == 'mokdong')
    assert planned['defaultVisible'] is False
    capital = capital_transport.for_complex(identity)
    assert next(p for p in capital['matchedPlans'] if p['id'] == 'mokdong')['scoringEligible'] is False
    mapped = [s for s in registry.stations(DAY) if s['lineId'] == 'mokdong']
    assert mapped and all(s['defaultVisible'] is s['scoringEligible'] is False for s in mapped)
    normal = next(s for s in registry.stations(DAY) if s['lineId'] == 'dongbuk')
    assert not policy.under_review(normal)
    assert policy.line_policy(normal['lineId'], normal['stage'], normal['stageLabel'])
    pending = {**station('mokdong'), 'distanceMeters': 100}
    result = rating.calculate([], {'stations': [pending]}, DAY)
    assert result['subScores']['transport'] == 0
    assert result['components']['transport']['reconsideredWithoutSchedule']


def test_reconsidered_rail_does_not_add_a_base_score_or_second_line_bonus():
    normal = station('gtx-b')
    pending = station()
    projects = [dict(id=s['projectId'], name=s['lineName'], projectType='transport',
                     stage=s['stage'], stageLabel=s['stageLabel']) for s in [normal, pending]]
    baseline = rating.calculate(projects, {'stations': [normal]}, DAY)
    mixed = rating.calculate(projects, {'stations': [normal, pending]}, DAY)
    assert mixed['subScores']['transport'] == baseline['subScores']['transport']
    assert mixed['components']['transport']['secondLineBonus'] == 0
    assert [s['lineId'] for s in mixed['components']['transport']['inputs']] == ['gtx-b']
    only_pending = rating.calculate(projects, {'stations': [pending]}, DAY)
    assert only_pending['subScores']['transport'] == 0
    assert only_pending['components']['transport']['reconsideredWithoutSchedule']


def test_coverage_separates_reconsidered_stations_without_losing_operating_rail(monkeypatch):
    pending, normal = station(), station('gtx-b')
    operating = {**normal, 'id': 'operating', 'serviceStatus': 'operating', 'scoringEligible': False}
    bundle = dict(integrityValid=True, checkedAt=DAY.isoformat(),
                  lines=[dict(id='gangbuk-cross', mappingComplete=True)],
                  stations=[pending, normal, operating], coverage={})
    monkeypatch.setattr(registry, 'load', lambda: bundle)
    result = registry.complex_coverage({'latitude':37.58, 'longitude':127.04}, DAY)
    assert [s['id'] for s in result['nearbyReviewStations']] == [pending['id']]
    assert [s['id'] for s in result['nearbyPlannedStations']] == [normal['id']]
    assert [s['id'] for s in result['nearbyOperatingStations']] == ['operating']
    assert not result['nearbyReferenceStations']
    assert pending['scoringEligible'] is True


def test_candidate_and_capital_references_retain_review_metadata():
    identity = {'province':'서울특별시', 'district':'동대문구'}
    planned = planned_rail.planned_rail_for_candidate(identity)
    pending = next(p for p in planned if p['id'] == 'gangbuk-cross')
    assert pending['defaultVisible'] is False
    assert pending['stations']
    capital = capital_transport.for_complex(identity)
    assert next(p for p in capital['matchedPlans'] if p['id'] == 'gangbuk-cross')['railReviewStatus'] == 'reconsidering'


def test_only_reconsidered_stations_score_zero_rather_than_pending(monkeypatch):
    import living_area_map
    pending = policy.annotate(station())
    monkeypatch.setattr(living_area_map, 'map_context', lambda *_: {'stations': [pending]})
    monkeypatch.setattr(registry, 'complex_coverage', lambda *_: dict(scopeComplete=True,
        nearbyPlannedStations=[], nearbyReferenceStations=[], nearbyOperatingStations=[],
        nearbyReviewStations=[pending]))
    result = {'displayProjects': [], 'snapshotId': 'test',
              'metroCoverage': {'checkedAt': DAY.isoformat()},
              'mapCenter': {'latitude': 37.58, 'longitude': 127.04}}
    output = rating.attach(result, {}, DAY)['planRating']
    assert output['transportCoverage']['status'] == 'rail_under_review'
    assert output['subScores']['transport'] == 0
    assert 'transport' not in output['missingReasons']
    assert '재추진' in output['components']['transport']['summary']


def test_reconsidered_projects_and_routes_do_not_enter_the_buying_narrative():
    pending = station()
    project = {**pending, 'id': pending['projectId'], 'projectType':'transport', 'name':'강북횡단선'}
    result = {'projects': [], 'referenceProjects': [project], 'metrics': [],
              'transportRoutes': [policy.annotate({'id':'gangbuk-cross', 'name':'강북횡단선'})]}
    result = narrative.describe(result, {'name':'시험단지'})
    assert result['displayProjects'][0]['id'] == project['id']
    assert result['findings'] == result['insights'] == []
    assert '강북횡단선' not in result['headline']
    assert '매수 이유에서 제외' in result['intro']


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js required')
def test_map_toggle_and_report_references_do_not_promote_reviewed_lines():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    names = ['zippickRailUnderReview', 'zippickLivingRailVisible', 'zippickReviewRailReferences',
             'zippickLivingTransportHtml']
    helpers = '\n'.join(re.search(r'    function ' + name + r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in names)
    script = helpers + r'''
const assert=require('node:assert/strict');
const esc=String;
const zippickFutureSourceIsOfficial=url=>String(url).startsWith('https://www.seoul.go.kr/');
const zippickLivingProjectSourceUrl=p=>p.sourceUrl;
const zippickFutureSourceLink=url=>`<a href="${url}">공식 자료</a>`;
const pending={id:'metro-rail:gangbuk-cross',name:'강북횡단선',projectType:'transport',
  stage:'planning',stageLabel:'재추진 계획 · 착공 전',sourceUrl:'https://www.seoul.go.kr/plan',sourceDate:'2026-10-01'};
const normal={...pending,id:'metro-rail:gtx-b',name:'GTX-B',stage:'construction',stageLabel:'착공'};
assert(!zippickLivingRailVisible(pending));
assert(zippickLivingRailVisible(pending,true));
assert(zippickLivingRailVisible(normal));
assert(!zippickLivingRailVisible({...pending,stageLabel:'예타 미통과'}));
assert(!zippickLivingTransportHtml({displayProjects:[pending,normal]}).includes('강북횡단선'));
const refs=zippickReviewRailReferences({plannedRail:[{...pending,id:'gangbuk-cross'}]},
  {displayProjects:[pending,normal],capitalTransport:{matchedPlans:[{...pending,id:'gangbuk-cross'}]}});
assert.equal(refs.length,1,'중복 경로에서 같은 노선을 여러 번 표시하지 않는다');
const reference=zippickLivingTransportHtml({displayProjects:refs,includeReviewRail:true});
assert(reference.includes('재추진 중 · 일정 미정'));
assert(reference.includes('교통 가점과 매수 이유에서 제외'));
const failed={...pending,id:'metro-rail:mokdong',name:'목동선',stageLabel:'계획 단계',
  railReviewStatus:'reconsidering',reviewLabel:'예타 미통과 · 재검토 중',
  reviewReason:'예비타당성조사를 통과하지 못했어요.',
  reviewSourceUrl:'https://www.seoul.go.kr/news/news_report.do?nttNo=415662',reviewSourceDate:'2024-07-11'};
assert(!zippickLivingTransportHtml({displayProjects:[failed]}).includes('목동선'));
const failedReference=zippickLivingTransportHtml({displayProjects:[failed],includeReviewRail:true});
assert(failedReference.includes(failed.reviewLabel));
assert(failedReference.includes(failed.reviewReason));
assert(failedReference.includes(failed.reviewSourceUrl));
assert(failedReference.includes(failed.reviewSourceDate));
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_reconsidered_zero_keeps_housing_total_and_does_not_zero_unknown_lines():
    pending = station()
    result = rating.calculate([], {'stations': [pending]}, DAY)
    assert result['subScores']['transport'] == 0
    assert rating.aggregate({'housing': 3.2, 'transport': result['subScores']['transport']}) == 3.2
    unknown = {**station('gtx-b'), 'lineId': 'unknown', 'projectId': 'unknown'}
    project = {'id': 'unknown', 'projectType': 'transport', 'stage': 'planning'}
    mixed = rating.calculate([project], {'stations': [pending, unknown]}, DAY)
    assert mixed['subScores']['transport'] is None
