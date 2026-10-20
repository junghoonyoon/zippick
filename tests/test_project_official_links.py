import datetime as dt

import living_area_sources as sources
import project_official_links as links


def test_official_homepages_are_preserved_from_source_records():
    projects = sources.bundled_projects()
    rows = [p for p in projects if p.get('officialDetailUrl')]
    assert len(rows) == 383
    p = next(p for p in rows if p['id'] == 'seoul-plan-renewal:10064')
    assert p['officialDetailUrl'] == 'https://cleanup.seoul.go.kr/cafe/mainIndx.do?cafeUrl=banghakzone3'
    assert p['sourceUrl'].startswith('https://data.seoul.go.kr/')  # Keep data provenance separately.


def test_source_pk_and_identity_own_the_project_link():
    p = {'id': 'seoul-plan-renewal:10064', 'name': '방학3구역', 'region': '도봉구',
         'address': '방학동 685 일대'}
    assert links.for_project(p)['officialDetailUrl'].endswith('cafeUrl=banghakzone3')
    assert links.for_project({**p, 'id': 'not-the-project'}) == {}
    assert links.for_project({**p, 'region': '다른 구'}) == {}
    assert links.for_project({**p, 'address': '방학동 99'}) == {}


def test_boundary_only_rows_get_individual_pages_by_reviewed_identity():
    detail = links.for_boundary({'id': '11320UQ120PS202605210001', 'name': '방학신동아1단지아파트'})
    assert detail['officialDetailUrl'].endswith('seq=622475')
    detail = links.for_boundary({'id': 'unknown', 'name': '불광5', 'districtCode': '11380'})
    assert detail['officialDetailUrl'].endswith('cafeUrl=Bulkwang5')
    assert links.for_boundary({'id': 'unknown', 'name': '불광5', 'districtCode': '11320'}) == {}


def test_rail_sources_use_individual_notices_instead_of_gis():
    for p in [{'id': 'dobongsan-okjeong', 'name': '도봉산~옥정 광역철도'},
              {'id': 'gg-rail:649', 'name': '도봉산~옥정 광역철도'}]:
        assert links.for_project(p)['officialDetailUrl'].endswith('seq=626638')
    station = {'id': 'gtx-c:003', 'lineId': 'gtx-c', 'name': '창동역 · GTX-C'}
    assert links.for_project(station)['officialDetailUrl'].endswith('seq=640498')
    assert links.for_project(station, dt.date(2026, 1, 1)) == {}
    assert links.for_project({'id': 'gg-rail:649', 'name': '다른 노선'}) == {}


def test_data_endpoints_and_generic_lists_never_become_detail_links():
    for url in [
        'https://gris.gg.go.kr:8888/grisgis/rest/services/bdsMap_Monitoring/MapServer/7',
        'https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do',
        'https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx=11673',
        'https://www.eum.go.kr/web/gs/gv/gvGosiList.jsp',
        'https://cleanup.seoul.go.kr/',
        'https://cleanup.seoul.go.kr.evil.com/cafe/mainIndx.do?cafeUrl=wrong',
        'javascript:alert(1)',
    ]:
        assert links.individual_url(url) is None
    assert links.individual_url('https://www.eum.go.kr/web/gs/gv/gvGosiDet.jsp?seq=622475')
