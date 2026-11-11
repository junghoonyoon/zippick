"""Source completeness, percent units and physical identity for metro plans."""
import datetime as dt
from html import escape
import io
import json
from pathlib import Path
import zipfile

import pytest

import apartment_development as development
import collect_regional_reconstruction_plans as collector
import regional_reconstruction_plans as plans
import shared_data

DAY = dt.date(2026, 11, 12)
ENTITY = {'apartmentId': 'example-1', 'name': '예시1차아파트', 'province': '경기도',
          'district': '수원영통구', 'legalDong': '원천동', 'jibun': '35', 'approvedAt': '1987-01-01'}
GG_URL = 'https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx=11882&decodeIdx=5318'


def workbook(*, ratio_col=30, count=1, ceiling=2.5):
    def letter(col):
        text, col = '', col + 1
        while col:
            col, mod = divmod(col - 1, 26)
            text = chr(65 + mod) + text
        return text
    rows = [{0:'경기도 일반 정비사업 추진현황 세부내역 (2026년도 3/4분기 자료)'},
            {0:'연번', 1:'시군', 2:'사업단계', 3:'사업유형', 4:'정비구역명', 5:'위치',
             6:'구역면적\n(㎡)', 19:'신축세대수', ratio_col:'용적률'},
            {ratio_col:'기존', ratio_col+1:'신축'}, {4:count},
            {0:1, 1:'수원시', 2:'추진위원회', 3:'재건축', 4:'예시1차아파트', 5:'영통구 원천동 35번지',
             6:40000, 19:1200, ratio_col:1.6, ratio_col+1:ceiling}]
    xml = []
    for index, row in enumerate(rows, 1):
        cells = []
        for col, value in row.items():
            ref = f'{letter(col)}{index}'
            if isinstance(value, (float, int)):
                style = ' s="1"' if index == 5 and col in (ratio_col, ratio_col+1) else ''
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        xml.append(f'<row r="{index}">{"".join(cells)}</row>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('xl/styles.xml', '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="0"/><xf numFmtId="9"/></cellXfs></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(xml) + '</sheetData></worksheet>')
    return output.getvalue()


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'isolated')
    monkeypatch.setattr(shared_data, 'cache_path', lambda name: tmp_path / name)
    monkeypatch.setattr(collector, '_now', lambda: DAY.isoformat() + 'T00:00:00+00:00')
    plans._read.cache_clear()
    return tmp_path


@pytest.mark.parametrize('column', [30, 31])
def test_quarterly_columns_can_move_without_changing_percent_units(column):
    result = collector.parse_gyeonggi(workbook(ratio_col=column), GG_URL)
    row = next(iter(result['records'].values()))
    assert result['sourceDate'] == '2026-09-30'
    assert row['plannedFloorAreaRatio'] == 250
    assert row['existingFloorAreaRatio'] == 160
    assert row['district'] == ENTITY['district']
    assert not {'전화번호', 'owner', 'householdIncrease', 'generalSaleHouseholds'}.intersection(row)


def test_missing_page_or_wrong_quarter_cannot_become_a_complete_snapshot():
    with pytest.raises(ValueError, match='count'):
        collector.parse_gyeonggi(workbook(count=2), GG_URL)
    with pytest.raises(ValueError, match='date mismatch'):
        collector.parse_gyeonggi(workbook(), GG_URL, source_date='2026-06-30')


def test_exact_parcel_name_district_and_phase_are_required(source):
    collector._save('gg-renewal', collector.parse_gyeonggi(workbook(), GG_URL))
    result = plans.for_apartment(ENTITY, day=DAY)
    assert result['status'] == 'ready'
    assert result['plannedFloorAreaRatio'] == 250
    assert result['plannedBuildingCoverageRatio'] is None
    assert result['missingFields'] == ['plannedBuildingCoverageRatio']
    for patch in [{'jibun':'36'}, {'legalDong':'망포동'}, {'district':'수원장안구'}, {'name':'예시2차아파트'}]:
        assert plans.for_apartment({**ENTITY, **patch}, day=DAY)['status'] == 'not_found'
    for area in ('59', '84'):
        assert plans.for_apartment({**ENTITY, 'areaLabel':area, 'priceEok':99}, day=DAY) == result


def test_quarterly_zone_alias_does_not_relax_the_physical_parcel(source):
    payload = collector.parse_gyeonggi(workbook(), GG_URL)
    next(iter(payload['records'].values()))['name'] = '영통3구역(예시1차아파트)'
    collector._save('gg-renewal',payload)
    assert plans.for_apartment(ENTITY,day=DAY)['status'] == 'ready'
    assert plans.for_apartment({**ENTITY,'jibun':'36'},day=DAY)['status'] == 'not_found'


def incheon_payload(key, *, address='가좌동 122', stage='정비구역지정'):
    row = collector._row(key, '예시1차A', '서해구', address, '재건축', stage,
                         '2026-03-31' if key == 'incheon-plan' else '2026-10-31', plans.SOURCES[key]['url'],
                         **({'plannedFloorAreaRatio':250, 'plannedBuildingCoverageRatio':25} if key == 'incheon-plan' else {}))
    return {'records': {row['id']: row}, 'sourceDate':row['sourceDate']}


def test_latest_stage_and_older_plan_keep_their_separate_dates_and_exact_address(source):
    collector._save('incheon-plan', incheon_payload('incheon-plan'))
    collector._save('incheon-renewal', incheon_payload('incheon-renewal', stage='조합설립인가'))
    entity = {**ENTITY, 'province':'인천광역시', 'district':'인천서해구', 'legalDong':'가좌동', 'jibun':'122'}
    result = plans.for_apartment(entity, day=DAY)
    assert result['stageLabel'] == '조합설립인가'
    assert result['stageSourceDate'] == '2026-10-31'
    assert result['sourceDate'] == '2026-03-31'
    assert result['plannedFloorAreaRatio'] == 250
    collector._save('incheon-plan', incheon_payload('incheon-plan', address='가좌동 123'))
    result = plans.for_apartment(entity, day=DAY)
    assert result['stageLabel'] == '조합설립인가'
    assert result['plannedFloorAreaRatio'] is None  # same name cannot borrow another parcel's ratio


def test_newer_completion_cannot_revive_an_older_active_plan(source):
    collector._save('incheon-plan', incheon_payload('incheon-plan'))
    collector._save('incheon-renewal', incheon_payload('incheon-renewal', stage='준공'))
    entity = {**ENTITY, 'province':'인천광역시', 'district':'서해구', 'legalDong':'가좌동', 'jibun':'122'}
    assert plans.for_apartment(entity, day=DAY)['status'] == 'completed'


def test_administrative_parent_alias_keeps_the_exact_address_and_does_not_merge_successor_gu(source):
    collector._save('incheon-plan', incheon_payload('incheon-plan'))
    entity = {**ENTITY, 'province':'인천광역시', 'district':'인천서구', 'legalDong':'가좌동', 'jibun':'122'}
    result = plans.for_apartment(entity, day=DAY)
    assert result['status'] == 'ready'
    assert result['districtMatchMethod'] == 'official_administrative_successor'
    assert result['districtMatchSourceUrl'] == plans.DISTRICT_CHANGE_URL
    assert plans.for_apartment({**entity,'district':'검단구'},day=DAY)['status'] != 'ready'
    assert plans.for_apartment({**entity,'jibun':'123'},day=DAY)['status'] != 'ready'


def test_failed_refresh_keeps_good_facts_and_continues_other_sources(source):
    collector._save('gg-renewal', collector.parse_gyeonggi(workbook(), GG_URL))
    def failed():
        raise ValueError('partial provider response')
    result = collector.collect(keys=['gg-renewal','incheon-plan'], fetchers={
        'gg-renewal':failed, 'incheon-plan':lambda:incheon_payload('incheon-plan')})
    assert (result['success'],result['failed'],result['unprocessed']) == (1,1,0)
    model = plans.for_apartment(ENTITY, day=DAY)
    assert model['status'] == 'stale'
    assert model['plannedFloorAreaRatio'] == 250
    assert len(plans.load()['records']['incheon-plan']['records']) == 1


def test_replica_never_collects_and_incomplete_exports_are_rejected(source, monkeypatch):
    collector._save('gg-renewal', collector.parse_gyeonggi(workbook(), GG_URL))
    exported = plans.load()
    exported['records']['gg-renewal']['totalCount'] += 1
    with pytest.raises(ValueError, match='incomplete'):
        plans.validate(exported)
    monkeypatch.setenv('ZIPPICK_DATA_MODE','replica')
    assert collector.request(ENTITY) is False
    with pytest.raises(shared_data.SharedDataError):
        collector.collect(fetchers={})


def test_first_report_collects_all_due_regional_sources_once(source, monkeypatch):
    monkeypatch.setattr(collector, '_JOB', None)
    monkeypatch.setattr(collector, '_LAST_ATTEMPT', -1000)
    original = collector.collect
    calls = []
    def collect(**kwargs):
        calls.append(kwargs['keys'])
        return original(**kwargs, fetchers={
            'gg-renewal':lambda:collector.parse_gyeonggi(workbook(), GG_URL),
            'incheon-renewal':lambda:incheon_payload('incheon-renewal'),
            'incheon-plan':lambda:incheon_payload('incheon-plan')})
    monkeypatch.setattr(collector,'collect',collect)
    assert collector.request(ENTITY) is True
    assert collector._JOB.result(timeout=5)['success'] == 3
    assert collector.request(ENTITY) is False
    assert collector.request({**ENTITY,'province':'인천광역시'}) is False
    assert len(calls) == 1


def test_shared_snapshot_validates_regional_counts_before_publication(source):
    collector._save('gg-renewal',collector.parse_gyeonggi(workbook(),GG_URL))
    path = source / plans.FILE
    shared_data._validate_snapshot(source,{plans.FILE:[path.stat().st_size,1]})
    data=json.loads(path.read_text())
    data['records']['gg-renewal']['totalCount'] += 1
    path.write_text(json.dumps(data,ensure_ascii=False))
    with pytest.raises(shared_data.SharedDataError,match='정비계획 전체 건수'):
        shared_data._validate_snapshot(source,{plans.FILE:[path.stat().st_size,2]})
