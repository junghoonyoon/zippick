import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import living_area_metro as metro
import map_zone_context as context
import search_server

DAY = dt.date(2026, 10, 19)
ZONE_ID = '11000UQ120PS202603260007'


def binding():
    return json.loads(context.PATH.read_text())['developments'][0]


def identities():
    item = binding()
    row = {'id': ZONE_ID, 'sourceId': 'seoul-plan-boundary',
           'sourceName': item['boundaryName'], 'districtCode': item['districtCode'],
           'stage': 'construction'}
    project = {'id': item['projectId'], **{k: item[k] for k in
               ('name', 'province', 'region', 'legalDong', 'jibun')}}
    return row, project


def test_context_adds_an_apartment_without_replacing_the_official_boundary():
    row, project = identities()
    original = dict(row)
    result = context.for_boundaries([row], [project], DAY)[ZONE_ID]
    assert result['displayLabel'] == '서울원 아이파크 건설 중'
    assert result['relationship'] == 'included_apartment'
    assert result['sourceUrl'] and result['statusSourceUrl'] and result['checkedAt']
    assert row == original


@pytest.mark.parametrize('key,value', [('id', 'other-id'), ('name', '다른 아이파크'),
    ('region', '성동구'), ('legalDong', '공릉동'), ('jibun', '85-8')])
def test_project_id_and_full_address_must_match(key, value):
    row, project = identities()
    project[key] = value
    assert context.for_boundaries([row], [project], DAY) == {}


@pytest.mark.parametrize('key,value', [('id', 'other-zone'), ('sourceName', '다른 물류부지'),
    ('districtCode', '11200'), ('sourceId', 'other-source'), ('stage', 'completed'),
    ('stage', 'unknown')])
def test_unrelated_or_no_longer_building_boundaries_do_not_get_the_label(key, value):
    row, project = identities()
    row[key] = value
    assert context.for_boundaries([row], [project], DAY) == {}


def test_future_or_expired_reviews_are_not_shown_as_current_construction():
    row, project = identities()
    for day in [DAY - dt.timedelta(days=1), DAY + dt.timedelta(days=121)]:
        assert context.for_boundaries([row], [project], day) == {}


@pytest.mark.parametrize('stage', ['completed', 'cancelled'])
def test_finished_or_cancelled_apartments_are_not_shown_as_building(stage):
    row, project = identities()
    project['stage'] = stage
    assert context.for_boundaries([row], [project], DAY) == {}


def test_report_and_viewport_maps_share_the_same_context_and_original_geometry():
    report = {z['id']: z for z in metro.spatial(
        {'latitude': 37.6245, 'longitude': 127.0653}, metro.catalog()['projects'], DAY)['zones']}
    viewport = {z['id']: z for z in search_server._redevelopment_zones_payload({
        'bbox': ['127.05,37.61,127.08,37.64'], 'limit': ['3000']})['zones']}
    zone = report[ZONE_ID]
    assert zone['name'] == zone['sourceName'] == viewport[ZONE_ID]['name'] == '광운대역 물류부지'
    assert zone['stageLabel'] == viewport[ZONE_ID]['stageLabel'] == '착공'
    assert zone['zoneKind'] == 'reference'
    assert zone['developmentContext'] == viewport[ZONE_ID]['developmentContext']
    assert zone['developmentContext']['displayLabel'] == '서울원 아이파크 건설 중'
    assert zone['geometry'] == viewport[ZONE_ID]['geometry']
    assert zone['projectId'] == 'boundary:' + ZONE_ID


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js required')
def test_map_labels_keep_both_the_official_project_and_apartment_context():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    names = ['mapZoneDevelopmentLabelHtml', 'mapZoneDevelopmentDetailHtml',
             'redevelopmentZoneLabel', 'redevelopmentZoneNameLabel']
    helpers = '\n'.join(re.search(r'    function ' + name + r'\([^\n]*\) \{.*?\n    \}', html, re.S).group()
                        for name in names)
    script = helpers + r'''
const assert = require('node:assert/strict');
const esc = s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');
const redevelopmentZoneTitle = z=>z.name;
const redevelopmentZoneAlias = ()=>null;
const redevelopmentZoneStageLabel = s=>s;
const redevelopmentZonePolygonStyle = ()=>({fillColor:'#1185d8'});
const zippickFutureSourceLink = (url,label)=>`<a href="${url}">${label}</a>`;
const zone = {name:'광운대역 물류부지',stage:'착공',developmentContext:{
  displayLabel:'서울원 아이파크 건설 중',description:'복합개발 안에 짓는 아파트예요.',
  sourceUrl:'https://example.test/apartment',statusSourceUrl:'https://example.test/status',checkedAt:'2026-10-19'}};
for (const render of [redevelopmentZoneLabel,redevelopmentZoneNameLabel]) {
  const label = render(zone);
  assert(label.indexOf('광운대역 물류부지') < label.indexOf('서울원 아이파크 건설 중'));
  assert(label.includes('착공'));
  assert(!render({...zone,developmentContext:null}).includes('서울원 아이파크'));
}
assert(mapZoneDevelopmentDetailHtml(zone).includes('복합개발 안에'));
assert(mapZoneDevelopmentDetailHtml(zone).includes(zone.developmentContext.statusSourceUrl));
assert(!mapZoneDevelopmentLabelHtml({developmentContext:{displayLabel:'<script>'}}).includes('<script>'));
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
