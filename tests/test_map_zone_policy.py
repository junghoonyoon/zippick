import datetime as dt
import json
from pathlib import Path
import pytest
import map_zone_policy as policy
import living_area_metro as metro
from import_living_area_metro import stage


@pytest.mark.parametrize('label', sorted(policy.RENEWAL_TYPES))
def test_official_renewal_type_is_not_dependent_on_a_project_name(label):
    row = {'sourceId':'seoul-plan-boundary','projectTypeLabel':label,'name':'구역명 미확인'}
    assert policy.classify(row)['zoneKind'] == 'renewal'


@pytest.mark.parametrize('label', sorted(policy.REFERENCE_TYPES))
def test_broad_reference_does_not_become_a_renewal_from_name(label):
    row = {'sourceId':'seoul-plan-boundary','projectTypeLabel':label,'name':'재개발아파트'}
    assert policy.classify(row)['zoneKind'] == 'reference'
    assert policy.classify(row, {'projectType':'redevelopment'})['zoneKind'] == 'unknown'


def test_gg_codes_and_layers_must_agree():
    for (layer, code), kind in policy.GG_KINDS.items():
        assert policy.classify({'sourceId':'gg-plan-boundary','sourceLayer':layer,'useCode':code})['zoneKind'] == kind
    for layer, code in [(13,'UDT999'),(14,'UDA999'),(13,'UDR100'),(99,'UDT100')]:
        assert policy.classify({'sourceId':'gg-plan-boundary','sourceLayer':layer,'useCode':code})['zoneKind'] == 'unknown'
    assert policy.classify({'projectTypeLabel':'재개발','sourceId':'unverified'})['zoneKind'] == 'unknown'


def test_opposite_official_project_types_are_not_silently_resolved():
    assert policy.classify({'sourceId':'seoul-plan-boundary','projectTypeLabel':'재건축(공동)'},
                           {'projectType':'redevelopment'})['zoneKind'] == 'unknown'


@pytest.mark.parametrize('label',['준공 예정','준공(일부)','준공 신청','해제 검토','미준공','입주자 모집공고 완료'])
def test_future_partial_or_requested_completion_is_not_completed(label):
    assert stage(label) != 'completed'


def test_full_catalog_has_classification_and_keeps_official_names():
    rows = metro.spatial({'latitude':37.5,'longitude':127},metro.catalog()['projects'],dt.date.today(),
                         bbox=(124,33,132,39),include_routes=False)['zones']
    assert len(rows) == len({r['id'] for r in rows})
    for row in rows:
        assert row['zoneKind'] in policy.LABELS
        assert row['classificationVersion'] == policy.VERSION
        if row['stageMismatch']:
            assert row['stage'] == 'unknown'
            assert row['stageLabel'] == '진행 단계 확인 중'
            assert len(row['stageEvidence']) == 2
        assert row['sourceUrl'] and row['sourceDate'] and row['name'].strip()
        if row['businessNameConfirmed']:
            assert not row['name'].endswith('사업명 미확인')
    assert not policy.coverage()['scopeComplete']
    assert policy.coverage()['regions']['인천광역시'] == 'missing'


def test_a_single_inside_point_with_different_area_does_not_name_a_boundary():
    from shapely.geometry import Point, box
    row={'sourceLayer':13,'useCode':'UDT100','districtCode':'41130','siteAreaM2':10000}
    p={'id':'wrong','projectType':'redevelopment','districtCode':'41131','siteAreaM2':1000}
    assert metro._unnamed_boundary_project(row,box(0,0,100,100),[(p,Point(50,50))]) == (None,None)


def test_seoul_import_retains_official_definitions_and_date():
    raw=json.loads((Path(__file__).parents[1]/'data/redevelopment_zones.geojson').read_text())
    assert raw['sourceDate'] == '2026-09-10'
    for f in raw['features']:
        p=f['properties']
        assert p['projectType'] == raw['codeDefinitions']['types'].get(p['rawTypeCode'],'사업 종류 미확인')
        assert p['stage'] == raw['codeDefinitions']['stages'].get(p['rawStageCode'],'진행 단계 미확인')
