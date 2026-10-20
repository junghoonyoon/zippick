import datetime as dt
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box
import living_area_metro as metro
import map_zone_stage


def test_missing_seoul_code_uses_official_definition_with_matching_business_type():
    props = {'stage': '진행 단계 미확인', 'rawStageCode': 'PP1902', 'rawTypeCode': 'BZ306'}
    found = map_zone_stage.definition(props)
    assert found['label'] == '입주자 모집공고 완료'
    assert found['sourceUrl'] == 'https://urban.seoul.go.kr/bsns/getPropelCdByCd.json'
    assert map_zone_stage.definition({**props, 'rawTypeCode': 'BZ101'}) is None
    assert map_zone_stage.definition({**props, 'rawStageCode': 'PP9999'}) is None
    assert map_zone_stage.definition({**props, 'stage': '공식 원문 유지'}) is None


def test_nearby_address_requires_matching_name_district_area_and_unique_project():
    row = {'sourceLayer': 13, 'useCode': 'UDT100', 'sourceName': '태평3 재개발 정비구역',
           'districtCode': '41130', 'siteAreaM2': 10000}
    p = {'id': 'one', 'name': '태평3', 'projectType': 'redevelopment',
         'districtCode': '41131', 'siteAreaM2': 10000}
    g = box(0, 0, 100, 100)
    assert metro._named_boundary_project(row, g, [(p, Point(130, 50))]) == p
    for wrong in ({**p, 'name': '태평4'}, {**p, 'name': '태평3-1'},
                  {**p, 'districtCode': '41210'}, {**p, 'siteAreaM2': 12000},
                  {**p, 'projectType': 'reconstruction'}):
        assert metro._named_boundary_project(row, g, [(wrong, Point(130, 50))]) is None
    assert metro._named_boundary_project(row, g, [(p, Point(201, 50))]) is None
    assert metro._named_boundary_project(row, g, [(p, Point(130, 50)), ({**p, 'id': 'two'}, Point(140, 50))]) is None
    assert metro._named_boundary_project({**row, 'useCode': 'UDT999'}, g, [(p, Point(130, 50))]) is None


def test_real_missing_stages_are_supplemented_without_changing_boundary_or_color():
    zones = metro.spatial({'latitude': 37.5, 'longitude': 127}, metro.catalog()['projects'],
                          dt.date.today(), bbox=(124, 33, 132, 39), include_routes=False)['zones']
    byid = {z['id']: z for z in zones}
    expected = {'gg-zone:13:5500': '조합설립', 'gg-zone:13:5501': '사업시행',
                'gg-zone:13:5498': '관리처분', 'gg-zone:13:5597': '착공'}
    for id, label in expected.items():
        assert byid[id]['stageLabel'] == label
        assert byid[id]['zoneKind'] == 'renewal'
        assert byid[id]['stageSourceDate'] == '2026-06-30'
    supplemented = [z for z in zones if z['stageReasonCode'] == 'official_code_supplement']
    # Completed complexes supplied again are retired even when their old code was supplemented.
    assert not supplemented  # all supplemented codes were rental supply notices, not development sites
    assert '11000UQ120PS202602240068' not in byid  # occupied 래미안길음센터피스
    assert all(z['stageLabel'] == '입주자 모집공고 완료' and z['zoneKind'] == 'reference' for z in supplemented)
    assert all(z['stageReason'] for z in zones if z['stageLabel'] == '진행 단계 미확인')
    assert all(z['stageStatus'] == 'source_detail' for z in zones if z['stageLabel'] == '건축심의')


def test_unmapped_official_project_label_is_preserved_instead_of_missing_placeholder():
    projects = [dict(p) for p in metro.catalog()['projects']]
    p = next(p for p in projects if p['id'] == 'gg-quarter:29412eee4557763a1881')
    p.update(stage='unknown', stageLabel='건축심의')
    zones = metro.spatial({'latitude': 37.454, 'longitude': 127.147}, projects, dt.date.today())['zones']
    z = next(z for z in zones if z['id'] == 'gg-zone:13:5504')
    assert z['stageLabel'] == '건축심의'
    assert z['stageStatus'] == 'source_detail'
    assert z['stage'] == 'unknown'  # Do not invent a scoring milestone.


def test_code_snapshot_changes_invalidate_both_derived_caches(tmp_path, monkeypatch):
    import living_area_sources as sources
    p = tmp_path / 'codes.json'
    p.write_text('{}')
    monkeypatch.setattr(map_zone_stage, 'PATH', p)
    before = map_zone_stage.revision()
    p.write_text('{"codes":[]}')
    assert map_zone_stage.revision() != before
    root = Path(__file__).parents[1]
    assert 'map_zone_stage_codes.json' in (root / 'pipeline/living_area_sources.py').read_text()
