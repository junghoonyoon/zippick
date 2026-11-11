"""Verify public source identity, preservation, and plan matching behavior."""
import copy
import datetime as dt
import json
from unittest.mock import Mock

import pytest

import apartment_reconstruction as reconstruction
import collect_reconstruction_planning as parcels
import collect_reconstruction_ordinance as ordinance
import collect_seoul_reconstruction_plans as plan_collector
import reconstruction_project_plans as plans
import shared_data
from test_apartment_reconstruction import ENTITY, DAY, entry, ordinance_context


def public_html(address='서울특별시 노원구 월계동 320-11', labels=None):
    labels = labels or ['도시지역', '제3종일반주거지역', '제1종지구단위계획구역(월계3택지)']
    anchors = ''.join(f'<a onclick="openLandLayer(\'visible\')">{label}</a>' for label in labels)
    return f'''<p><img alt="공공누리마크">데이터는 공공누리 출처표시 조건에 따라 자유이용이 가능합니다.</p>
      <table><tr><th>소재지</th><td><div style="display:none"></div>{address}</td></tr>
      <tr><th>면적</th><td id="present_area">24,388 ㎡</td></tr>
      <tr><td id="present_mark1">{anchors}</td></tr></table>'''.encode('cp949')


def plan_row(**changes):
    return {'basic_info_seq': 123.0, 'bsns_name': '예시아파트3단지', 'site_code_nm': '노원구',
            'bsns_addr': '월계동 320-11 일대', 'classify_l_nm': '재건축(공동)',
            'propel_cd_nm': '구역지정', 'propel_dt': '2026-10-01', 'flar_rt': 280,
            'bldglnd_rt': 25, 'suply_hshld': 1000, 'bsns_area': 50000, **changes}


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'isolated')
    monkeypatch.setattr(shared_data, 'cache_path', lambda name: tmp_path / name)
    reconstruction._read.cache_clear()
    plans._index.cache_clear()
    return tmp_path


def test_parcel_page_checks_address_and_attribution_and_never_invents_site_coverage():
    result = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    assert result['pnu'] == '1135010200103200011'
    assert result['zoneNames'] == ['제3종일반주거지역']
    assert result['districtPlans'] == ['제1종지구단위계획구역(월계3택지)']
    assert result['parcelAreaSqm'] == 24388
    assert result['zoneCoverageVerified'] is False
    with pytest.raises(parcels.PlanningError) as wrong:
        parcels.parse_public_page(public_html(address='서울특별시 노원구 월계동 320-9'), ENTITY, day=DAY)
    assert wrong.value.status == 'identity_unverified'
    with pytest.raises(parcels.PlanningError) as no_license:
        parcels.parse_public_page(public_html().replace('공공누리마크'.encode('cp949'), b'none'), ENTITY, day=DAY)
    assert no_license.value.status == 'license_unverified'


def test_parcel_parser_ignores_hidden_address_text():
    raw = public_html().replace(b'<div style="display:none"></div>',
                                b'<div style="display:none"><span>hidden</span></div>')
    assert parcels.parse_public_page(raw, ENTITY, day=DAY)['zoneNames'] == ['제3종일반주거지역']


def test_unverified_site_coverage_displays_ordinance_without_computing_a_gap(source):
    ref = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=ref)
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference']['floorAreaRatio'] == 250
    assert result['planningReference']['buildingCoverageRatio'] == 50
    assert result['planningReference']['districtPlanName'] == '월계3택지'
    assert 'differencePp' not in result
    assert '차이는 계산하지 않았어요' in result['limitation']


def test_parcel_and_project_facts_remain_available_when_building_register_is_missing(source):
    ref = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=ref)
    plan_collector.collect(fetcher=lambda: [plan_row()])
    result = reconstruction.analyze(ENTITY, day=DAY)
    assert result['status'] == 'not_collected'
    assert result['planningReference']['floorAreaRatio'] == 250
    assert result['projectPlan']['plannedFloorAreaRatio'] == 280
    assert 'differencePp' not in result


def test_mixed_zoning_and_unsupported_city_do_not_receive_a_default_ordinance(source):
    ref = parcels.parse_public_page(public_html(labels=['제2종일반주거지역', '제3종일반주거지역']), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=ref)
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference'].get('floorAreaRatio') is None
    assert 'differencePp' not in result
    other = {**ENTITY, 'province': '경기도'}
    assert reconstruction._parcel_reference(other, {'identity': other, 'parcelReference': ref}, DAY).get('floorAreaRatio') is None


def test_collection_preserves_good_reference_on_failure_and_stops_after_auth_error(source):
    ref = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=ref)
    def denied(_): raise parcels.PlanningError('access_denied', '403')
    result = parcels.collect([ENTITY, {**ENTITY, 'apartmentId': 'next', 'jibun': '321'}], refresh=True, fetcher=denied)
    assert (result['total'], result['success'], result['failed'], result['unprocessed'], result['stoppedCode']) == (2, 0, 1, 1, '403')
    record = json.loads((source / reconstruction.PLANNING_FILE).read_text())['records'][ENTITY['apartmentId']]
    assert record['parcelReference'] == ref
    assert record['lastError']['errorCode'] == '403'
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'stale'
    assert result['planningReference']['zoneName'] == '제3종일반주거지역'
    assert not result['summary']


def test_report_request_collects_once_and_reuses_the_shared_parcel(source, monkeypatch):
    original = parcels.collect
    reference = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    fetcher = Mock(return_value=reference)
    monkeypatch.setattr(parcels, 'collect', lambda entities: original(entities, fetcher=fetcher))
    monkeypatch.setattr(parcels, '_JOBS', {})
    monkeypatch.setattr(parcels, '_BLOCKED_UNTIL', 0.0)
    assert parcels.request(ENTITY) is True
    parcels._JOBS[ENTITY['apartmentId']][0].result(timeout=5)
    assert parcels.request(ENTITY) is False
    fetcher.assert_called_once()
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference']['floorAreaRatio'] == 250


def test_project_refresh_populates_shared_source_and_is_reused(source, monkeypatch):
    original = plan_collector.collect
    fetcher = Mock(return_value=[plan_row()])
    monkeypatch.setattr(plan_collector, 'collect', lambda: original(fetcher=fetcher))
    monkeypatch.setattr(plan_collector, '_JOB', None)
    monkeypatch.setattr(plan_collector, '_LAST_ATTEMPT', 0.0)
    assert plan_collector.request() is True
    plan_collector._JOB.result(timeout=5)
    assert plan_collector.request() is False
    fetcher.assert_called_once()
    assert plans.for_apartment(ENTITY, day=DAY)['plannedFloorAreaRatio'] == 280


def test_same_id_cannot_reuse_or_overwrite_another_parcels_reference(source):
    reference = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=reference)
    wrong = {**ENTITY, 'jibun': '320-9'}
    fetcher = Mock(return_value=reference)
    result = parcels.collect([wrong], fetcher=fetcher)
    assert (result['identityMissing'], result['reused'], result['success']) == (1, 0, 0)
    fetcher.assert_not_called()
    result = reconstruction.analyze(wrong, entry(), day=DAY)
    assert result['status'] == 'identity_unverified'


def test_zone_with_restriction_suffix_has_no_unverified_default_ordinance(source):
    reference = parcels.parse_public_page(public_html(labels=['제2종일반주거지역(7층이하)']), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=reference)
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference'].get('floorAreaRatio') is None


def test_replica_never_fetches_parcel_or_project_sources(monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'replica')
    fetcher = Mock()
    assert parcels.request(ENTITY) is False
    assert plan_collector.request() is False
    assert ordinance.request() is False
    with pytest.raises(shared_data.SharedDataError): parcels.collect([ENTITY], fetcher=fetcher)
    with pytest.raises(shared_data.SharedDataError): plan_collector.collect(fetcher=fetcher)
    with pytest.raises(shared_data.SharedDataError): ordinance.collect(opener=fetcher)
    fetcher.assert_not_called()


def test_changed_ordinance_suppresses_old_numerical_limits(source):
    ref = parcels.parse_public_page(public_html(), ENTITY, day=DAY)
    parcels._save(ENTITY, reference=ref)
    check = {'status': 'changed', 'effectiveAt': '2026-11-01', 'checkedAt': DAY.isoformat(),
             'sourceUrl': ordinance.URL}
    (source / ordinance.FILE).write_text(json.dumps({'records': {'서울특별시': check}}, ensure_ascii=False))
    result = reconstruction.analyze(ENTITY, entry(), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference']['ordinanceStatus'] == 'changed'
    assert result['planningReference'].get('floorAreaRatio') is None
    assert '조례가 바뀌어' in result['limitation']


def test_changed_ordinance_also_suppresses_the_manual_reference(source):
    check = {'status': 'changed', 'effectiveAt': '2026-11-01', 'checkedAt': DAY.isoformat(),
             'sourceUrl': ordinance.URL}
    (source / ordinance.FILE).write_text(json.dumps({'records': {'서울특별시': check}}, ensure_ascii=False))
    result = reconstruction.analyze(ENTITY, entry(), ordinance_context(lawAsOf='2026-07-13'), day=DAY)
    assert result['status'] == 'reference_partial'
    assert result['planningReference']['ordinanceStatus'] == 'changed'
    assert result['planningReference'].get('floorAreaRatio') is None
    assert 'differencePp' not in result
    assert '조례가 바뀌어' in result['limitation']


def test_ordinance_verification_uses_current_visible_title_and_preserves_failed_checks(source):
    title = '<a id="westLi"><span>서울특별시 도시계획 조례</span><span>[시행 2026. 7. 13.]</span></a>'
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *_): return title.encode('utf-8')
    assert ordinance.parse_current(title) == '2026-07-13'
    with pytest.raises(ValueError): ordinance.parse_current(title.replace('서울특별시', '부산광역시'))
    result = ordinance.collect(opener=lambda *a, **k: Response())
    assert result['status'] == 'verified'
    from urllib.error import URLError
    def offline(*a, **k): raise URLError('offline')
    result = ordinance.collect(opener=offline)
    saved = json.loads((source / ordinance.FILE).read_text())['records']['서울특별시']
    assert result['failed'] == 1
    assert saved['status'] == 'verified' and saved['lastError']['status'] == 'connection_error'


def test_project_plan_requires_same_complex_and_never_becomes_a_site_ceiling(source):
    counts = plan_collector.collect(fetcher=lambda: [plan_row()])
    assert counts['success'] == 1
    value = plans.for_apartment(ENTITY, day=DAY)
    assert value['status'] == 'ready'
    assert value['plannedFloorAreaRatio'] == 280
    assert value['plannedBuildingCoverageRatio'] == 25
    assert value['plannedHouseholds'] == 1000
    assert value['scope'] == 'official_project_area'
    result = reconstruction.analyze(ENTITY, entry(), {}, day=DAY)
    assert result['projectPlan']['plannedFloorAreaRatio'] == 280
    assert result['basis'] is None
    assert 'differencePp' not in result
    assert plans.for_apartment({**ENTITY, 'jibun': '320-9'}, day=DAY)['status'] == 'not_found'
    assert plans.for_apartment({**ENTITY, 'name': '예시아파트2단지'}, day=DAY)['status'] == 'not_found'


def test_ambiguous_projects_and_stale_or_broken_refresh_are_explicit(source):
    plan_collector.collect(fetcher=lambda: [plan_row(), plan_row(basic_info_seq=456.0, flar_rt=300)])
    assert plans.for_apartment(ENTITY, day=DAY)['status'] == 'ambiguous'
    path = source / plans.FILE
    before = json.loads(path.read_text())
    result = plan_collector.collect(fetcher=lambda: [])
    assert result['failed'] == 1
    after = json.loads(path.read_text())
    assert after['records'] == before['records']
    assert after['lastError']['status'] == 'connection_error'
    plan_collector.collect(fetcher=lambda: [plan_row()])
    data = json.loads(path.read_text()); data['checkedAt'] = '2020-01-01T00:00:00+00:00'
    path.write_text(json.dumps(data))
    assert plans.for_apartment(ENTITY, day=DAY)['status'] == 'stale'


def test_broken_project_snapshot_is_retried_and_replaced_only_after_a_complete_fetch(source, monkeypatch):
    path = source / plans.FILE
    path.write_text('{broken')
    bad = plan_collector.collect(fetcher=lambda: [])
    assert bad['failed'] == 1
    assert path.read_text() == '{broken'
    original = plan_collector.collect
    monkeypatch.setattr(plan_collector, 'collect', lambda: original(fetcher=lambda: [plan_row()]))
    monkeypatch.setattr(plan_collector, '_JOB', None)
    monkeypatch.setattr(plan_collector, '_LAST_ATTEMPT', 0.0)
    assert plan_collector.request() is True
    assert plan_collector._JOB.result(timeout=5)['success'] == 1
    assert plans.for_apartment(ENTITY, day=DAY)['plannedFloorAreaRatio'] == 280
