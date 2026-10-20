"""The report and candidate viewport must agree on every overlapping boundary."""
import datetime as dt
import subprocess
from pathlib import Path

import pytest
import living_area_metro as metro
import search_server


@pytest.mark.parametrize('center', [
    {'latitude': 37.491, 'longitude': 126.889},  # 구로·살구마을
    {'latitude': 37.568, 'longitude': 127.067},  # 장안동
    {'latitude': 37.442, 'longitude': 127.153},  # 성남
])
def test_report_boundaries_match_viewport(center):
    projects = metro.catalog().get('projects', [])
    report = metro.spatial(center, projects, dt.date.today())['zones']
    lat, lon = center['latitude'], center['longitude']
    bbox = (lon-.035, lat-.025, lon+.035, lat+.025)
    viewport = search_server._redevelopment_zones_payload({
        'bbox': [','.join(map(str, bbox))], 'limit': ['3000']})
    indexed = {z['id']: z for z in viewport['zones']}
    assert report
    for zone in report:
        other = indexed[zone['id']]
        for key in ('name', 'geometry', 'stageLabel', 'sourceUrl', 'sourceName', 'projectId', 'zoneKind', 'classificationReason', 'classificationVersion'):
            assert other[key] == zone[key], (zone['name'], key)
        assert other['projectTypeCode'] == zone['projectType']
        assert other['projectTypeLabel'] == zone['projectTypeLabel']


def test_both_renderers_share_colors_and_preserve_polygon_holes():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    functions = html.split('    function redevelopmentZoneIsRenewal(', 1)[1].split('    function isPriceRelevantRedevelopmentZone', 1)[0]
    script = 'function redevelopmentZoneIsRenewal(' + functions
    script += '''
const assert = require('node:assert/strict');
for (const [kind, color] of [['renewal','#e86a32'], ['reference','#1185d8'], ['unknown','#6b7280']]) {
  const a = redevelopmentZonePolygonStyle({zoneKind:kind,projectType:'재개발'});
  const b = redevelopmentZonePolygonStyle({zoneKind:kind,projectTypeLabel:'도시재생'});
  assert.deepEqual(a,b); // Server classification wins over display names.
  assert.equal(a.strokeColor,color);
  assert.equal(a.clickable,false);
}
assert.equal(redevelopmentZonePolygonStyle({geometry:{},name:'재개발'}).strokeColor,'#6b7280');
assert.equal(redevelopmentZonePolygonStyle({zoneKind:'renewal',projectTypeLabel:'정비구역',businessNameConfirmed:false}).strokeColor,'#e86a32');
assert.equal(redevelopmentZonePolygonStyle({zoneKind:'renewal'}).zIndex,3);
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
    candidate = html.split('async function renderCandidateMapRedevelopmentZones', 1)[1].split('function scheduleCandidateMapRedevelopmentZones', 1)[0]
    report = html.split('async function mountZippickReportRedevelopmentZones', 1)[1].split('async function mountZippickReportMap', 1)[0]
    assert 'redevelopmentZonePolygonStyle(zone)' in candidate
    assert 'redevelopmentZonePolygonStyle(zone)' in report
    assert 'path:polygon' in candidate
    assert '.filter(isPriceRelevantRedevelopmentZone)' not in candidate


def test_cached_report_boundary_cannot_break_official_project_join():
    import future_transformation as future
    import living_area_map as maps
    entity = {'apartmentId': 'map-consistency', 'province': '서울특별시',
              'district': '구로구', 'legalDong': '구로동', 'jibun': '314'}
    center = {'latitude': 37.491, 'longitude': 126.889}
    shared = metro.spatial(center, metro.catalog()['projects'], dt.date.today())['zones']
    bogus = next(z for z in shared if z['id'] == '11000UQ120PS202411014232')
    analysis = {'modelVersion':'living-area-v2-beta', 'apartmentId':future.apartment_key(entity),
                'asOfDate': dt.date.today().isoformat(), 'center':center,
                'metroCoverage':{'status':'partial'},
                'displayProjects':[{**bogus, 'id':'boundary:'+bogus['id'],
                                    'stageLabel':'오래된 단계'}]}
    report = maps.map_context(entity, analysis)['zones']
    indexed = {z['id']:z for z in shared}
    for z in report:
        for key in ('projectId', 'name', 'stageLabel', 'geometry'):
            assert z[key] == indexed[z['id']][key]


def test_clicked_boundary_popup_uses_visible_click_not_offscreen_center():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    body = html.split('    function showCandidateMapRedevelopmentLabel(',1)[1].split('    function showCandidateMapFocusedRedevelopmentZone',1)[0]
    script = '''
const assert = require('node:assert/strict');
const candidateMap = {};
const clicked = {latitude:37.4,longitude:127.1};
const distantCenter = {latitude:38,longitude:128};
const document = {createElement:()=>({firstElementChild:{}})};
function clearCandidateMapRedevelopmentLabels() {}
function redevelopmentZoneCenter() {return distantCenter;}
function redevelopmentZoneLabel() {return '산성';}
const kakao={maps:{CustomOverlay:class {constructor(options){this.options=options;} setZIndex(){}}}};
''' + 'function showCandidateMapRedevelopmentLabel(' + body + '''
const layer={};
showCandidateMapRedevelopmentLabel(kakao,layer,{name:'산성'},[],{latLng:clicked});
assert.equal(layer.label.options.position,clicked);
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True)
