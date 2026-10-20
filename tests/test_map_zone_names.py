import datetime as dt

from shapely.geometry import Point, box
import living_area_metro as metro
import search_server


def test_sanseong_and_nearby_unnamed_boundaries_use_official_businesses():
    center = {'latitude':37.454, 'longitude':127.147}
    report = {z['id']:z for z in metro.spatial(center, metro.catalog()['projects'], dt.date.today())['zones']}
    viewport = {z['id']:z for z in search_server._redevelopment_zones_payload({
        'bbox':['127.13,37.43,127.17,37.47'], 'limit':['3000']})['zones']}
    expected = {'gg-zone:13:5504':('산성', '착공'),
                'gg-zone:13:5507':('신흥3', '조합설립'),
                'gg-zone:13:5511':('중2구역 도시환경정비사업', '조합설립')}
    for key, (name, stage) in expected.items():
        zone = report[key]
        assert zone['name'] == viewport[key]['name'] == name
        assert zone['stageLabel'] == viewport[key]['stageLabel'] == stage
        assert zone['businessNameConfirmed'] is True
        assert zone['nameCorrected'] is True
        assert zone['nameSourceUrl'].startswith('https://www.gg.go.kr/')
        assert zone['sourceName'] == '정비구역'
        assert zone['geometry'] == viewport[key]['geometry']


def test_unnamed_boundary_never_guesses_when_projects_are_ambiguous():
    row = {'sourceLayer':13, 'useCode':'UDT100', 'districtCode':'41130', 'siteAreaM2':10000}
    project = {'id':'one', 'name':'첫 사업', 'projectType':'redevelopment',
               'districtCode':'41131', 'siteAreaM2':10000}
    geometry = box(0,0,100,100)
    assert metro._unnamed_boundary_project(row,geometry,[(project,Point(50,50))])[0] == project
    assert metro._unnamed_boundary_project(row,geometry,[(project,Point(110,50))])[0] == project
    for other in ({**project,'districtCode':'41210'}, {**project,'siteAreaM2':20000},
                  {**project,'projectType':'new_supply'}):
        assert metro._unnamed_boundary_project(row,geometry,[(other,Point(110,50))]) == (None,None)
    assert metro._unnamed_boundary_project(row,geometry,[(project,Point(250,50))]) == (None,None)
    duplicate = {**project,'id':'two'}
    assert metro._unnamed_boundary_project(row,geometry,[(project,Point(50,50)),(duplicate,Point(60,60))]) == (None,None)
    assert metro._unnamed_boundary_project({**row,'useCode':'UDT999'},geometry,[(project,Point(50,50))]) == (None,None)


def test_named_sujin_redevelopment_uses_official_stage_on_both_maps():
    center = {'latitude':37.438, 'longitude':127.136}
    report = {z['id']:z for z in metro.spatial(center,metro.catalog()['projects'],dt.date.today())['zones']}
    viewport = {z['id']:z for z in search_server._redevelopment_zones_payload({
        'bbox':['127.12,37.42,127.15,37.45'],'limit':['3000']})['zones']}
    key = 'gg-zone:13:5499'
    zone = report[key]
    assert zone['name'] == viewport[key]['name'] == '수진1 재개발 정비구역'
    assert zone['stageLabel'] == viewport[key]['stageLabel'] == '관리처분'
    assert zone['projectId'] == viewport[key]['projectId'] == 'gg-quarter:9a05d75dbc870c668bc8'
    assert zone['projectType'] == 'redevelopment'
    assert zone['matchMethod'] == 'official_name_address_and_area'
