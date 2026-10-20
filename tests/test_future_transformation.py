"""Fictional geometry/measurements stay here; never used as pilot data."""
import copy
import datetime as dt
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import future_transformation as f
from future_transformation_spatial import conversion

DAY = dt.date(2026, 10, 12)
CENTER = {'latitude': 37.59, 'longitude': 127.06}


def polygon(west=127.059, east=127.061, south=37.589, north=37.591):
    return {'type': 'Polygon', 'coordinates': [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}


def spatial():
    return {'center': CENTER, 'parcels': [{'id': 'land1', 'approvedAt': '1980-01-01', 'use': 'residential', 'geometryBasis': 'residential_land', 'geometry': polygon(), 'evidenceIds': ['s']}],
            'projects': [{'id': 'p1', 'stage': 'construction', 'expectedCompletionDate': '2028-01-01', 'geometry': polygon(), 'evidenceIds': ['s']}]}


def dossier():
    inputs = {
        'housing_conversion': spatial(),
        'new_build_belt': dict(beforeConnectedLengthM=0, afterConnectedLengthM=1000, eligibleNetworkLengthM=1000),
        'transport_improvement': dict(beforeMinutes=50, afterMinutes=30, routeVerified=True),
        'amenity_improvement': dict(beforeAccessibleFacilities=0, afterAccessibleFacilities=2, plannedFacilities=2, openingScheduleVerified=True),
        'project_feasibility': {'projects': [dict(id='p1', stage='construction', siteAreaM2=1000, expectedCompletionDate='2028-01-01')]},
        'supply_demand_stability': dict(plannedHouseholds=100, existingHouseholds=10000, annualAbsorptionHouseholds=100, transactionChangePct=0, rentChangePct=0),
        'accessibility': dict(distanceMeters=0, distanceBasis='walking'),
        'belt_connection': dict(connectedRoutes=2, assessedRoutes=2, barriersReviewed=True),
        'daily_access': dict(beforeMinutes=20, afterMinutes=5, routeVerified=True),
        'negative_impact': dict(noiseExposure=0, routeDisruption=0, supplyConcentration=0),
    }
    return {'schemaVersion': 1, 'scoringVersion': 'fts-v1', 'apartmentId': 'fixture-only', 'asOfDate': DAY.isoformat(),
            'radiusMeters': 1500, 'horizonYears': 5, 'center': CENTER,
            'sources': [{'id': 's', 'publisher': '테스트용 공식기관', 'url': 'https://www.seoul.go.kr/fixture-only', 'documentId': 's', 'documentTitle': '가상 테스트 자료',
                         'publishedAt': DAY.isoformat(), 'observedAt': DAY.isoformat(), 'verifiedAt': DAY.isoformat(), 'verificationStatus': 'verified', 'licenseStatus': 'reviewed'}],
            'measurements': {key: {'inputs': value, 'verificationStatus': 'verified', 'method': 'gis_land_intersection' if key == 'housing_conversion' else 'raw_inputs_v1',
                                  'effectiveDate': '2028-01-01', 'explanation': '가상 입력으로 계산한 테스트 결과', 'evidenceIds': ['s']} for key, value in inputs.items()},
            'projects': [{'id': 'p1', 'name': '가상 구역', 'stage': 'construction', 'siteAreaM2': 1000, 'geometry': polygon(), 'evidenceIds': ['s'], 'expectedCompletionDate': '2028-01-01', **CENTER}]}


def test_config_and_aggregation_examples_and_missing():
    assert sum(x['weight'] for x in f.CONFIG['metrics']) == 100
    assert sum(x['weight'] for x in f.CONFIG['benefits']) == 100
    for region, benefit, total in [(0, 0, 0), (100, 100, 100), (85, 40, 67), (70, 90, 78)]:
        m = [{**x, 'score': x['weight'] * region / 100} for x in f.CONFIG['metrics']]
        b = [{**x, 'score': x['weight'] * benefit / 100} for x in f.CONFIG['benefits']]
        assert f.aggregate_scores(m, b)[2] == total
        m[0]['score'] = None
        assert f.aggregate_scores(m, b)[2] is None


def test_ready_partial_and_feature_off():
    doc = dossier()
    result = f.evaluate('fixture-only', doc, as_of=DAY)
    assert result['status'] == 'ready'
    assert result['futureTransformationScore'] == 100
    assert result['coverageRatio'] == 1
    assert result == f.evaluate('fixture-only', doc, as_of=DAY)
    doc['measurements']['housing_conversion'] = None
    result = f.evaluate('fixture-only', doc, as_of=DAY)
    assert result['status'] == 'partial'
    assert result['coverageRatio'] == .82
    assert result['regionChangeScore'] is None
    assert result['futureTransformationScore'] is None
    assert f.evaluate('fixture-only', doc, as_of=DAY, scores_enabled=False)['coverageRatio'] == 0
    assert f.evaluate('missing', as_of=DAY)['status'] == 'insufficient_data'


def test_old_data_cannot_show_scores_and_future_data_is_rejected():
    doc = dossier()
    assert f.evaluate('fixture-only', doc, as_of=DAY + dt.timedelta(days=31))['status'] == 'stale'
    assert f.evaluate('fixture-only', doc, as_of=DAY + dt.timedelta(days=31))['futureTransformationScore'] is None
    with pytest.raises(ValueError):
        f.evaluate('fixture-only', doc, as_of=DAY - dt.timedelta(days=1))
    with pytest.raises(ValueError):
        f.evaluate('different-apartment', doc, as_of=DAY)


@pytest.mark.parametrize('stage', ['completed', 'cancelled'])
def test_completed_cancelled_and_unknown_never_add_future_land(stage):
    data = spatial()
    data['projects'][0]['stage'] = stage
    ratio, audit = conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)
    assert ratio == 0
    assert audit['weightedConversionAreaM2'] == 0


@pytest.mark.parametrize('end', [None, '2032-01-01', '2026-01-01'])
def test_missing_past_and_outside_horizon_dates_never_add_land(end):
    data = spatial()
    data['projects'][0]['expectedCompletionDate'] = end
    expected = 0 if end == '2032-01-01' else None
    assert conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)[0] == expected


def test_overlap_deduplication_radius_clip_and_stage_priority():
    data = spatial()
    one = conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)
    data['projects'].append({**data['projects'][0], 'id': 'second-document', 'stage': 'approved'})
    data['parcels'].append({**data['parcels'][0], 'id': 'same-land-other-source'})
    two = conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)
    assert one[0] == two[0] == pytest.approx(.9)
    assert one[1]['eligibleOldResidentialLandAreaM2'] == two[1]['eligibleOldResidentialLandAreaM2']
    data['projects'] = [{**data['projects'][0], 'geometry': polygon(127.09, 127.10)}]
    assert conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)[0] == 0
    data = spatial()
    # A wide polygon crosses a small radius: only the intersection is counted.
    clipped = conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 50)
    assert clipped[1]['eligibleOldResidentialLandAreaM2'] < one[1]['eligibleOldResidentialLandAreaM2']
    assert clipped[1]['eligibleOldResidentialLandAreaM2'] == pytest.approx(3.14159 * 50**2, rel=.001)


@pytest.mark.parametrize('change', ['no_parcels', 'new_parcel', 'nonresidential', 'invalid_geometry', 'missing_center'])
def test_invalid_or_ineligible_spatial_inputs_are_missing(change):
    data = spatial()
    if change == 'no_parcels': data['parcels'] = []
    if change == 'new_parcel': data['parcels'][0]['approvedAt'] = '2020-01-01'
    if change == 'nonresidential': data['parcels'][0]['use'] = 'commercial'
    if change == 'invalid_geometry': data['parcels'][0]['geometry'] = {'type': 'Polygon', 'coordinates': []}
    if change == 'missing_center': data['center'] = {}
    assert conversion(data, DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)[0] is None


def test_raw_input_rules_and_negative_effect_direction():
    assert f.measurement_ratio('transport_improvement', {'beforeMinutes': 50, 'afterMinutes': 20}) is None
    assert f.measurement_ratio('new_build_belt', {'complexCount': 10}) is None
    assert f.measurement_ratio('supply_demand_stability', {'plannedHouseholds': 1000}) is None
    low = dict(noiseExposure=.1, routeDisruption=.1, supplyConcentration=.1)
    high = dict(noiseExposure=.9, routeDisruption=.9, supplyConcentration=.9)
    assert f.measurement_ratio('negative_impact', low) > f.measurement_ratio('negative_impact', high)
    assert f.measurement_ratio('accessibility', {'distanceMeters': 1500, 'distanceBasis': 'walking'}) == 0


@pytest.mark.parametrize('problem', ['url', 'unknown_source', 'infinity', 'future_source', 'duplicate', 'floor_area', 'scope', 'center'])
def test_import_rejects_untrusted_or_invalid_input(problem):
    doc = dossier()
    if problem == 'url': doc['sources'][0]['url'] = 'https://www.seoul.go.kr.evil.example/data'
    if problem == 'unknown_source': doc['measurements']['accessibility']['evidenceIds'] = ['missing']
    if problem == 'infinity': doc['measurements']['accessibility']['inputs']['distanceMeters'] = float('inf')
    if problem == 'future_source': doc['sources'][0]['publishedAt'] = '2099-01-01'
    if problem == 'duplicate': doc['measurements']['housing_conversion']['inputs']['parcels'] *= 2
    if problem == 'floor_area': doc['measurements']['housing_conversion']['inputs']['parcels'][0]['geometryBasis'] = 'floor_area'
    if problem == 'scope': doc['radiusMeters'] = 3000
    if problem == 'center': doc['center'] = {}
    with pytest.raises(ValueError): f.validate_document(doc)


def test_storage_idempotency_history_cache_and_error_isolation(tmp_path):
    path = tmp_path / 'analysis.sqlite3'
    doc = dossier()
    args = dict(path=path, known_apartment_ids={'fixture-only'})
    rev = f.import_document(doc, **args)
    assert f.import_document(doc, **args) == rev
    row = dict(apartmentId='fixture-only', district='동대문구', legalDong='이문동', **CENTER)
    first = f.analyze(row, path=path, scores_enabled=True, as_of=DAY)
    assert first['status'] == 'ready'
    assert f.analyze(row, path=path, scores_enabled=True, as_of=DAY) == first
    assert f.analyze(row, path=path, scores_enabled=True, as_of=DAY.isoformat()) == first
    doc['projects'][0]['stageLabel'] = '공사 진행 재확인'
    assert f.import_document(doc, **args) != rev
    second = f.analyze(row, path=path, scores_enabled=True, as_of=DAY)
    assert second['snapshotId'] != first['snapshotId']
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM project_events').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 2
    doc['asOfDate'] = '2026-10-11'
    for s in doc['sources']:
        s.update(publishedAt='2026-10-11', observedAt='2026-10-11', verifiedAt='2026-10-11')
    with pytest.raises(ValueError): f.import_document(doc, **args)
    broken = tmp_path / 'broken.sqlite3'
    broken.write_text('invalid database')
    failed = f.analyze(row, path=broken)
    assert failed['status'] == 'error'
    assert failed['livingArea']['status'] == 'error'
    assert failed['livingArea']['headline'] == '생활권 자료를 불러오지 못했어요.'


def test_projects_scope_and_missing_location_suppress_scores(tmp_path):
    doc = dossier()
    doc['projects'] += [{**doc['projects'][0], 'id': 'far', 'longitude': 127.1}, {**doc['projects'][0], 'id': 'done', 'stage': 'completed'}]
    path = tmp_path / 'projects.sqlite3'
    f.import_document(doc, path=path, known_apartment_ids={'fixture-only'})
    row = dict(apartmentId='fixture-only', district='동대문구', legalDong='이문동', **CENTER)
    result = f.analyze(row, path=path, scores_enabled=True, as_of=DAY)
    assert len(result['projects']) == 2
    assert result['referenceProjects'][0]['id'] == 'far'
    assert next(p for p in result['projects'] if p['id'] == 'done')['phase'] == 'current'
    del row['latitude']
    missing = f.analyze(row, path=path, scores_enabled=True, as_of=DAY)
    assert missing['futureTransformationScore'] is None
    assert not missing['projects']


def test_pilot_facts_are_real_registry_entities_and_have_no_fake_measurements():
    for doc in json.loads(f.PILOT_PATH.read_text()):
        f.validate_document(doc)
        entity = f.registry_entity(doc['apartmentId'])
        assert entity and f.supported(entity)
        assert not doc['measurements']
        assert f.evaluate(doc['apartmentId'], doc, as_of=DAY)['futureTransformationScore'] is None
    hwigyeong = next(d for d in json.loads(f.PILOT_PATH.read_text()) if d['identity']['legalDong'] == '이문동')
    completed = next(p for p in hwigyeong['projects'] if p['id'] == 'ddm-hwigyeong3')
    assert completed['stage'] == 'completed'
    assert completed['actualCompletionDate'] == '2025-06-26'


@pytest.mark.skipif(not shutil.which('node'), reason='Node required')
def test_frontend_states_links_and_no_null_coercion():
    html = (f.config.ROOT / '앱화면/real-estate-search.html').read_text()
    names = ['zippickFutureSourceLink', 'zippickFutureReferenceProjects', 'zippickLifestyleProjectInsight', 'zippickLivingTransportHtml', 'zippickLifestylePlanRating', 'zippickLifestyleChangeHtml', 'zippickLifestyleChangeRatingData', 'zippickReportMapHtml']
    functions = '\n'.join(re.search(r'    function '+n+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for n in names)
    sites = re.search(r'    const ZIPPICK_REPORT_PROJECT_SITES = \{.*?\n    \};', html, re.S).group()
    script = "const assert = require('node:assert/strict'); const esc = v => String(v).replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;'); const candidateDisplayName = item => item.name || '이 단지'; const candidateMapAddress = item => item.address || '';\n" + sites + '\n' + functions
    script += '\nconst result = ' + json.dumps(f.evaluate('fixture-only', dossier(), as_of=DAY)) + ';\n'
    script += r'''
assert.match(zippickLifestyleChangeHtml({futureTransformation:result}), /평가 자료 부족/);
assert.doesNotMatch(zippickLifestyleChangeHtml({futureTransformation:result}), /100 \/ 5/);
const model = {modelVersion:'living-area-v2-beta',status:'ready',score:3.7,
 subScores:{housing:4,transport:null,competitiveness:3},projects:[],referenceProjects:[]};
assert.equal(zippickLifestyleChangeRatingData({futureTransformation:model}),3.7);
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/3.7 \/ 5/);
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/4.0 \/ 5/);
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/— \/ 5/);
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/점수 근거 보기/);
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/평가 보류/);
assert.doesNotMatch(zippickLifestyleChangeHtml({futureTransformation:model}),/신축 대비 경쟁력/);
const project={name:'<script>',stage:'approved',sourceUrl:'https://www.seoul.go.kr/notice',
 sourceRecordId:'p',licenseVerifiedAt:'2026-10-15',sourceDate:'2026-10-13',distanceMeters:430,distanceLabel:'대표점 직선거리'};
const rendered=zippickLifestyleChangeHtml({futureTransformation:{...model,projects:[project]}});
assert.match(rendered,/430m[\s\S]*대표점 직선거리/);
const attributed={...project,id:'wondang',name:'원당아파트 가로주택정비사업',
 reportedHouseholds:108,reportedHouseholdsBasis:'2024년 공람안 기준',
 reportedHouseholdsSourceUrl:'https://www.arunews.com/news/articleView.html?idxno=43736'};
const attributedHtml=zippickLifestyleChangeHtml({futureTransformation:{...model,projects:[attributed]}});
assert.match(attributedHtml,/108세대 계획 · 2024년 공람안 기준/);
assert.match(attributedHtml,/2024년 공람안 보도/);
assert.match(rendered,/계획 세대수 미확인/);
const homes=Array.from({length:5},(_,i)=>({...project,id:`home-${i}`,name:`주택 ${i+1}`,distanceMeters:100+i*100}));
const rail={...project,id:'rail',name:'면목선',projectType:'transport',distanceMeters:638};
const rankedHtml=zippickLifestyleChangeHtml({futureTransformation:{...model,projects:[...homes,rail]}});
assert.ok(rankedHtml.indexOf('면목선') < rankedHtml.indexOf('주택 4'));
const addressRef = {id:'seongnam-reference',...project,geometryType:'point',latitude:37.457,longitude:127.154,coordinateBasis:'address_geocode'};
const mapHtml = zippickReportMapHtml({futureTransformation:{...model,projects:[],displayProjects:[addressRef],mapCenter:{latitude:37.454,longitude:127.151}}},{redevelopment:true});
assert.match(mapHtml,/seongnam-reference/);
assert.match(mapHtml,/data-zpr-map-latitude="37.454"/);
assert.match(mapHtml,/address_geocode/);

assert.match(rendered,/&lt;script&gt;/);
assert.doesNotMatch(rendered,/<script>/);
assert.doesNotMatch(zippickLifestyleChangeHtml({futureTransformation:{...model,projects:[{...project,licenseVerifiedAt:null}]}}),/&lt;script&gt;/);
for (const status of ['insufficient_data','stale','error']) {
 const html=zippickLifestyleChangeHtml({futureTransformation:{...model,status,score:null}});
 assert.match(html,/data-zpr-map-redevelopment="true"/);
 assert.doesNotMatch(html,/0.0 \/ 5/);
 if (status === 'error') {
   assert.match(html,/생활권 자료를 불러오지 못했어요/);
   assert.match(html,/다시 열어 주세요/);
   assert.doesNotMatch(html,/zpr-living-subs/);
   assert.doesNotMatch(html,/확인한 주변 사업/);
 } else if (status === 'stale') {
   assert.match(html,/최신 자료 확인 필요/);
 } else {
   assert.match(html,/평가 보류/);
 }
}
const noScores={modelVersion:'living-area-v2-beta',status:'insufficient_data',
 planRating:{version:'living-area-plan-v5-beta',status:'insufficient_data',score:null,
   subScores:{housing:null,transport:null}}};
assert.match(zippickLifestyleChangeHtml({futureTransformation:noScores}),/평가 자료 부족/);
const failedWithOldProjects={modelVersion:'living-area-v2-beta',status:'error',
 displayProjects:[{id:'old-project',name:'오래된 구역',projectType:'redevelopment',latitude:37.5,longitude:127.0}],
 projects:[],referenceProjects:[]};
assert.doesNotMatch(zippickLifestyleChangeHtml({futureTransformation:failedWithOldProjects}),/오래된 구역/);
assert.equal(zippickFutureSourceLink('javascript:alert(1)'), '');
assert.equal(zippickFutureSourceLink('https://seoul.go.kr.evil.example/'), '');
assert.match(zippickFutureSourceLink('https://www.seoul.go.kr/notice'), /noopener/);
const districtOnly = zippickLifestyleChangeHtml({lifestyleChange:{redevelopmentProjects:[project]}});
assert.doesNotMatch(districtOnly,/&lt;script&gt;/);
assert.equal(zippickLifestyleChangeRatingData({futureTransformation:{...model,score:null}}),null);
assert.equal(zippickLifestyleChangeRatingData({futureTransformation:{...model,score:0}}),0);
const planned={...model,status:'insufficient_data',score:null,planRating:{version:'living-area-plan-v3-beta',status:'ready',score:3.3,subScores:{housing:3.8,transport:2.6},weights:{housing:.6,transport:.4},components:{}}};
assert.equal(zippickLifestyleChangeRatingData({futureTransformation:planned}),3.3);
const planHtml=zippickLifestyleChangeHtml({futureTransformation:planned});
assert.match(planHtml,/3.8 \/ 5/); assert.match(planHtml,/2.6 \/ 5/); assert.doesNotMatch(planHtml,/2.8 \/ 5/);
assert.match(planHtml,/주거환경 개선 60%/); assert.match(planHtml,/교통 개선 40%/);
assert.doesNotMatch(planHtml,/신축 대비 경쟁력/);

'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node required')
def test_redevelopment_map_preserves_project_type_and_stage_for_orange_points():
    html = (f.config.ROOT / '앱화면/real-estate-search.html').read_text()
    names = ['zippickReportMapHtml', 'zippickLivingIsRenewalPoint']
    functions = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group()
                          for name in names)
    script = "const assert = require('node:assert/strict'); const esc = v => String(v).replaceAll('&','&amp;').replaceAll('\\\"','&quot;'); const candidateDisplayName = item => item.name || '이 단지'; const candidateMapAddress = item => item.address || '';\n" + functions
    script += r'''
const project = {id:'gg-quarter:bank-hyundai',name:'은행동현대아파트',projectType:'reconstruction',
 stageLabel:'예정구역',geometryType:'point',licenseVerifiedAt:'2026-10-16',
 latitude:37.4519,longitude:127.1634,distanceMeters:1088};
const supply = {...project,id:'supply',name:'일반 공급',projectType:'new_supply'};
const rendered = zippickReportMapHtml({futureTransformation:{modelVersion:'living-area-v2-beta',
 displayProjects:[project,supply],mapCenter:{latitude:37.45,longitude:127.16}}},{redevelopment:true});
const encoded = rendered.match(/data-zpr-map-projects="([^"]+)"/)[1];
const points = JSON.parse(encoded.replaceAll('&quot;','"').replaceAll('&amp;','&'));
assert.equal(points.length,2);
assert.equal(points[0].projectType,'reconstruction');
assert.equal(points[0].stageLabel,'예정구역');
assert.equal(zippickLivingIsRenewalPoint(points[0]),true);
assert.equal(zippickLivingIsRenewalPoint(points[1]),false);
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    map_body = html.split('    async function mountZippickReportRedevelopmentZones(', 1)[1].split('    async function mountZippickReportMap(', 1)[0]
    assert 'isRenewalPoint ? " is-renewal"' in map_body
    assert 'isRenewalPoint ? "사업 대표점 · "' in map_body
    assert '재개발·재건축 사업 대표점' in map_body


def test_public_report_payload_removes_radius_and_scores():
    result = f.evaluate('fixture-only', dossier(), as_of=DAY)
    assert result['futureTransformationScore'] == 100
    result['projects'] = [{'id': 'sample', 'distanceMeters': 430, 'distanceBasis': '직선거리',
                           'name': '확인된 사업'}]
    result['buildingRegister'] = {'scope': 'legal_dong', 'areas': [{'age30SharePct': 82.0}]}
    public = f.public_facts(result)
    assert public['projects'] == []
    assert public['score'] is None
    assert public['modelVersion'] == 'living-area-v2-beta'
    assert not {'radiusMeters', 'horizonYears', 'futureTransformationScore',
                'regionChangeScore', 'apartmentBenefitScore', 'benefits',
                'coverageRatio', 'scoringVersion', 'buildingRegister'} & public.keys()


def test_http_endpoint_uses_exact_registry_id_and_preserves_unknown(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen
    from urllib.error import HTTPError
    import search_server
    server = ThreadingHTTPServer(('127.0.0.1', 0), search_server.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        with mock.patch.object(f, 'DB_PATH', tmp_path / 'api.sqlite3'):
            for doc in json.loads(f.PILOT_PATH.read_text()):
                with urlopen(base + '/api/apartments/' + doc['apartmentId'] + '/future-transformation') as response:
                    payload = json.load(response)
                assert payload['apartmentId'] == doc['apartmentId']
                assert 'futureTransformationScore' not in payload
                assert 'radiusMeters' not in payload
                assert 'metrics' in payload
                assert payload['modelVersion'] == 'living-area-v2-beta'
                assert payload['score'] is None
                assert payload['status'] in ('partial', 'stale', 'insufficient_data')
                assert all(p['licenseVerifiedAt'] and p['sourceRecordId'] for p in payload['referenceProjects'])
                assert 'buildingRegister' not in payload
            map_url = base + '/api/apartments/4ba5297e34906625/living-area-map'
            with urlopen(map_url) as response:
                map_payload = json.load(response)
            assert len(map_payload['zones']) > 2
            assert len(map_payload['stations']) >= 3
            from urllib.request import Request
            with urlopen(Request(map_url, headers={'X-Forwarded-For': '203.0.113.1'})) as response:
                public_map = json.load(response)
            assert public_map['zones'] == map_payload['zones']
            assert public_map['useContext'] == 'noncommercial'
            assert public_map['stations'] == map_payload['stations']
            with pytest.raises(HTTPError) as error:
                urlopen(base + '/api/apartments/nonexistent/future-transformation')
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_flag_and_data_revision_invalidate_cache_without_snapshot_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(f, 'DB_PATH', tmp_path / 'cache.sqlite3')
    first = f.data_revision()
    f.import_document(dossier(), path=f.DB_PATH, known_apartment_ids={'fixture-only'})
    second = f.data_revision()
    assert second != first
    f.analyze(dict(apartmentId='fixture-only', district='동대문구', legalDong='이문동', **CENTER), scores_enabled=True, as_of=DAY)
    assert f.data_revision() == second
    monkeypatch.setenv('ZIPPICK_FUTURE_TRANSFORMATION_SCORES', '1')
    assert f.data_revision() != second


def test_building_register_requires_exact_pilot_identity(tmp_path):
    pilot = json.loads(f.PILOT_PATH.read_text())[0]
    evidence = f.building_register_evidence(pilot['apartmentId'], pilot['identity'])
    assert evidence['scope'] == 'legal_dong'
    assert evidence['areas'][0]['legalDong'] == '산성동'
    assert evidence['areas'][0]['recordCount'] == 385
    assert evidence['areas'][0]['residentialRecordCount'] == 322
    assert evidence['areas'][0]['approvalDateCount'] == 322
    assert evidence['areas'][0]['age30RecordCount'] == 106
    assert evidence['areas'][0]['age30SharePct'] == 32.9
    assert f.building_register_evidence(pilot['apartmentId'], {**pilot['identity'], 'jibun': '1337'}) is None
    assert f.building_register_evidence('unknown', pilot['identity']) is None
    assert f.building_register_evidence(pilot['apartmentId'], pilot['identity'], path=tmp_path / 'missing.json') is None
    original = json.loads(f.BUILDING_SUMMARY_PATH.read_text())
    original[0]['areas'][0]['age30SharePct'] = 99.9
    bad_path = tmp_path / 'bad-summary.json'
    bad_path.write_text(json.dumps(original))
    assert f.building_register_evidence(pilot['apartmentId'], pilot['identity'], path=bad_path) is None


def test_old_publication_rechecked_today_is_not_stale(tmp_path, monkeypatch):
    pilot = json.loads(f.PILOT_PATH.read_text())[0]
    source = pilot['sources'][0]
    assert source['publishedAt'] < source['verifiedAt']
    pilot_path = tmp_path / 'pilots.json'
    pilot_path.write_text(json.dumps([pilot], ensure_ascii=False))
    monkeypatch.setattr(f, 'PILOT_PATH', pilot_path)
    row = {'apartmentId': pilot['apartmentId'], **pilot['identity']}
    result = f.analyze(row, as_of=DAY, path=tmp_path / 'rechecked.sqlite3', scores_enabled=False)
    assert result['status'] == 'partial'
    assert result['futureTransformationScore'] is None
    assert all(not project['stale'] for project in result['referenceProjects'])

    source['observedAt'] = source['verifiedAt'] = '2026-06-01'
    pilot_path.write_text(json.dumps([pilot], ensure_ascii=False))
    stale = f.analyze(row, as_of=DAY, path=tmp_path / 'older.sqlite3', scores_enabled=False)
    assert stale['status'] == 'stale'


def test_gis_dependency_failure_is_safe():
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.startswith('shapely'):
            raise ImportError('optional dependency unavailable')
        return original(name, *args, **kwargs)
    with mock.patch('builtins.__import__', side_effect=guarded):
        ratio, audit = conversion(spatial(), DAY, dt.date(2031, 10, 12), f.CONFIG['stageWeights'], 1500)
    assert ratio is None
    assert '공간 계산 모듈' in audit['reason']


def test_future_metrics_require_schedule_in_horizon():
    doc = dossier()
    doc['measurements']['transport_improvement']['effectiveDate'] = '2033-01-01'
    result = f.evaluate('fixture-only', doc, as_of=DAY)
    assert result['metrics'][2]['score'] is None
    assert result['status'] == 'partial'
    del doc['measurements']['transport_improvement']['effectiveDate']
    with pytest.raises(ValueError): f.validate_document(doc)


def test_same_date_project_conflict_keeps_previous_revision(tmp_path):
    doc = dossier()
    options = dict(path=tmp_path / 'conflict.sqlite3', known_apartment_ids={'fixture-only'})
    f.import_document(doc, **options)
    doc['projects'][0]['stage'] = 'approved'
    doc['measurements']['project_feasibility']['inputs']['projects'][0]['stage'] = 'approved'
    doc['measurements']['housing_conversion']['inputs']['projects'][0]['stage'] = 'approved'
    with pytest.raises(ValueError, match='conflicting'):
        f.import_document(doc, **options)
    with sqlite3.connect(options['path']) as db:
        assert db.execute('SELECT count(*) FROM revisions').fetchone()[0] == 1


def test_cited_correction_preserves_wrong_prior_status_in_history(tmp_path):
    doc = dossier()
    doc['measurements'] = {}
    options = dict(path=tmp_path / 'correction.sqlite3', known_apartment_ids={'fixture-only'})
    f.import_document(doc, **options)
    project = doc['projects'][0]
    project['stage'] = 'completed'
    doc['sources'].append({**doc['sources'][0], 'id': 's2',
                           'url': 'https://www.seoul.go.kr/fixture-completion', 'documentId': 's2'})
    project['evidenceIds'] = ['s2']
    with pytest.raises(ValueError, match='cited correction'):
        f.import_document(doc, **options)
    doc['factCorrections'] = [{'projectId': project['id'],
                               'reason': '기존 계획표에는 준공 상태가 누락되었고 별도 공식 현황에 준공인가가 확인되었다.',
                               'evidenceIds': ['s2']}]
    f.import_document(doc, **options)
    with sqlite3.connect(options['path']) as db:
        assert db.execute('SELECT count(*) FROM revisions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM project_events').fetchone()[0] == 2
    result = f.analyze(dict(apartmentId='fixture-only', district='동대문구', legalDong='이문동', **CENTER),
                       path=options['path'], as_of=DAY)
    assert result['projects'][0]['phase'] == 'current'
    assert result['futureTransformationScore'] is None


def test_gis_cannot_resurrect_a_completed_registered_project():
    doc = dossier()
    doc['projects'][0]['stage'] = 'completed'
    with pytest.raises(ValueError, match='GIS project must match'):
        f.validate_document(doc)
