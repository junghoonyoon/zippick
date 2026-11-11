"""Collection fills actual missing district months and never treats errors as zero."""
import datetime as dt
import json
import threading
import time
from pathlib import Path

import pytest
import requests

import molit_transactions as molit
import price_data_collection as collect
import report_price_comparison as comparison
import shared_data


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'isolated')
    monkeypatch.setattr(shared_data, 'cache_path', lambda name: tmp_path / name)
    monkeypatch.setattr(molit, 'TRANSACTION_CACHE_DIR', tmp_path / 'molit_transactions')
    monkeypatch.setattr(collect, 'REQUEST_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(collect, 'LOOKBACK_MONTHS', 6)
    monkeypatch.setattr(molit, '_deal_months', lambda months=6: ['202610', '202609', '202408', '202407', '202308', '202307'])
    monkeypatch.setattr(molit, '_transaction_kinds_for_apartment', lambda *a: ('apartment',))
    monkeypatch.setattr(molit, 'configured', lambda *a: True)
    monkeypatch.setattr(molit, 'enabled', lambda *a: True)
    monkeypatch.setattr(molit, 'transaction_kind_for_apartment', lambda *a: 'apartment')
    monkeypatch.setattr(molit, 'source_rows_for_entity', lambda entity, region='': [{
        '대표단지명': entity['name'], '법정동': entity['legalDong'], '지번': entity['jibun'], 'lawdCd': '99999'}])
    collect._JOBS.clear()
    collect._inspect.cache_clear()
    molit._MONTH_MEMORY_CACHE.clear()
    yield tmp_path
    # Tests wait for their workers before fixture data is removed.
    for job in list(collect._JOBS.values()):
        deadline = time.monotonic() + 5
        while job['status'] in ('queued', 'collecting') and time.monotonic() < deadline:
            time.sleep(.005)
    collect._JOBS.clear()
    collect._inspect.cache_clear()
    molit._MONTH_MEMORY_CACHE.clear()


def entity(name='대상', lot='1'):
    return {'apartmentId': name, 'name': name, 'province': '서울특별시', 'district': '예시구',
            'legalDong': '예시동', 'jibun': lot, 'households': 500, 'approvedAt': '1995-01-01'}


def write_month(code, month, kind, items):
    molit._write_cached_month(code, month, items, kind)


def wait_until_done(target):
    until = time.monotonic() + 5
    state = collect.request(target)
    while state['status'] in ('queued', 'collecting') and time.monotonic() < until:
        time.sleep(.005)
        state = collect.request(target)
    return state


def trade(name, lot, month, day, price, area=84.0):
    return {'apartment': name, 'legalDong': '예시동', 'jibun': lot, 'exclusiveArea': area,
            'floor': str(day), 'dealDate': f'{month[:4]}-{month[4:]}-{day:02d}',
            'dealAmountManwon': int(price * 10000), 'dealAmountEok': price,
            'transactionKind': 'apartment'}


def test_missing_months_are_collected_once_then_real_price_comparison_uses_them(source, monkeypatch):
    subject, p1, p2 = entity(), entity('비교하나', '2'), entity('비교둘', '3')
    monkeypatch.setattr(comparison.real_estate_search, 'APARTMENT_MASTER', [subject, p1, p2])
    monkeypatch.setattr(comparison, '_entity_coordinates', lambda entity: (37.5, 127.1))
    monkeypatch.setattr(comparison, '_peer_distance_meters', lambda *args: 500)
    months = molit._deal_months(6)
    calls = []
    def fetch(code, month, kind='apartment'):
        cached = molit._read_cached_month(code, month, allow_stale=True, transaction_kind=kind)
        if cached is not None:
            return cached
        calls.append((code, month, kind))
        # Two transactions per complex per month; all comparisons are real
        # results of matching, period selection and historical calculation.
        items = [trade(name, lot, month, day, price) for name, lot, price in [
            ('대상', '1', 10), ('비교하나', '2', 11), ('비교둘', '3', 12)] for day in (10, 20)]
        write_month(code, month, kind, items)
        return items
    monkeypatch.setattr(molit, 'fetch_month', fetch)
    # One existing empty month is a completed lookup and must not be fetched.
    write_month('99999', months[0], 'apartment', [])
    first = collect.request(subject)
    assert first['status'] in ('queued', 'collecting')
    state = wait_until_done(subject)
    assert state['status'] == 'ready'
    assert len(calls) == 5 and all(month != months[0] for _, month, _ in calls)
    log = json.loads((source / 'price_data_collection_log.json').read_text())['records']
    entry = next(iter(log.values()))
    assert (entry['total'], entry['success'], entry['failed'], entry['unprocessed']) == (5, 5, 0, 0)
    result = comparison.compare({}, subject, [], '84.0', today=dt.date(2026, 11, 11))
    assert result['status'] == 'ready' and result['method'] == 'usual_gap', result
    assert len(result['peers']) == 2 and result['shiftPp'] is not None
    assert collect.request(subject)['status'] == 'ready'
    assert len(calls) == 5


def test_permission_or_quota_failure_stops_batch_preserves_existing_and_can_resume(source, monkeypatch):
    target = entity()
    months = molit._deal_months(6)
    old = [trade('대상', '1', months[0], 10, 10)]
    write_month('99999', months[0], 'apartment', old)
    calls = []
    def denied(code, month, kind):
        calls.append(month)
        raise molit.OfficialTransactionError('22')
    monkeypatch.setattr(molit, 'fetch_month', denied)
    assert collect.request(target)['status'] in ('queued', 'collecting')
    state = wait_until_done(target)
    assert state['status'] == 'error' and state['errorCode'] == '22'
    assert (state['failed'], state['unprocessed']) == (1, 4)
    assert len(calls) == 1
    assert json.loads(molit._cache_path('99999', months[0]).read_text())['items'] == old
    log = json.loads((source / 'price_data_collection_log.json').read_text())
    assert log['blocked']['errorCode'] == '22'
    log['blocked']['until'] = 0
    (source / 'price_data_collection_log.json').write_text(json.dumps(log))
    monkeypatch.setattr(collect, 'RETRY_AFTER_SECONDS', 0)
    monkeypatch.setattr(molit, 'fetch_month', lambda code, month, kind: write_month(code, month, kind, []))
    collect.request(target, retry=True)
    final = wait_until_done(target)
    assert final['status'] == 'ready'
    assert final['available'] == 1 and final['empty'] == 5


def test_corrupt_and_wrong_identity_months_are_not_counted_as_empty(source):
    path = molit._cache_path('99999', '202610')
    path.parent.mkdir(parents=True)
    path.write_text('{broken')
    assert collect.inspect_month('99999', '202610', 'apartment') == 'invalid'
    path.write_text(json.dumps({'lawdCd': '12345', 'dealYmd': '202610', 'fetchedAt': time.time(), 'items': []}))
    assert collect.inspect_month('99999', '202610', 'apartment') == 'invalid'
    write_month('99999', '202610', 'apartment', [])
    assert collect.inspect_month('99999', '202610', 'apartment') == 'empty'


def test_replica_never_fetches_directly_and_waits_for_primary_snapshot(source, monkeypatch):
    monkeypatch.setenv('ZIPPICK_DATA_MODE', 'replica')
    observed = []
    monkeypatch.setattr(collect, '_primary_status', lambda entity, retry=False: {'status': 'ready'})
    monkeypatch.setattr(collect, '_schedule_sync', lambda: observed.append('sync'))
    monkeypatch.setattr(molit, 'fetch_month', lambda *a: pytest.fail('replica called public API'))
    state = collect.request(entity())
    assert state['status'] == 'collecting' and state['stage'] == 'syncing'
    assert observed == ['sync']


def test_incomplete_pagination_does_not_replace_last_good_month(source, monkeypatch):
    old = [trade('대상', '1', '202610', 10, 10)]
    write_month('99999', '202610', 'apartment', old)
    path = molit._cache_path('99999', '202610')
    value = json.loads(path.read_text()); value['fetchedAt'] = 1
    path.write_text(json.dumps(value))
    monkeypatch.setattr(molit, '_official_api_xml', lambda *args: '<response><header><resultCode>000</resultCode></header><body><totalCount>1</totalCount><items/></body></response>')
    assert molit.fetch_month('99999', '202610') == old
    assert json.loads(path.read_text())['items'] == old


def test_missing_source_failure_is_not_an_empty_month_and_retry_resumes(source, monkeypatch):
    calls = []
    def fetch(code, month, kind):
        calls.append(month)
        if len(calls) == 2:
            raise molit.OfficialTransactionError('30')
        write_month(code, month, kind, [trade('대상', '1', month, 10, 10)])
    monkeypatch.setattr(molit, 'fetch_month', fetch)
    collect.request(entity())
    failed = wait_until_done(entity())
    assert failed['status'] == 'error' and failed['errorCode'] == '30'
    assert failed['success'] == 1 and failed['failed'] == 1
    saved_month = calls[0]
    assert collect.inspect_month('99999', saved_month, 'apartment') == 'available'
    journal = source / 'price_data_collection_log.json'
    data = json.loads(journal.read_text()); data['blocked']['until'] = 0
    journal.write_text(json.dumps(data))
    monkeypatch.setattr(collect, 'RETRY_AFTER_SECONDS', 0)
    collect.request(entity(), retry=True)
    assert wait_until_done(entity())['status'] == 'ready'
    assert calls.count(saved_month) == 1


def test_duplicate_open_requests_share_one_job(source, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def fetch(code, month, kind):
        calls.append(month)
        started.set()
        assert release.wait(2)
        write_month(code, month, kind, [])
    monkeypatch.setattr(molit, 'fetch_month', fetch)
    first = collect.request(entity())
    assert first['status'] in ('queued', 'collecting') and started.wait(2)
    second = collect.request(entity('같은지역다른단지', '2'))
    assert second['status'] in ('queued', 'collecting')
    assert len(collect._JOBS) == 1
    release.set()
    assert wait_until_done(entity())['status'] == 'ready'
    assert len(calls) == 6


def test_gateway_quota_code_is_kept_without_secret_text():
    xml = '<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SECRET</returnAuthMsg><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>'
    with pytest.raises(molit.OfficialTransactionError) as error:
        molit._parse_items(xml)
    assert error.value.code == '22' and 'SECRET' not in str(error.value)


def test_malformed_cached_items_are_refetched_instead_of_reused(source, monkeypatch):
    month = molit._deal_months(6)[0]
    path = molit._cache_path('99999', month)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'lawdCd': '99999', 'dealYmd': month,
                                'fetchedAt': time.time(), 'items': ['broken']}))
    assert collect.inspect_month('99999', month, 'apartment') == 'invalid'
    assert molit._read_cached_month('99999', month, allow_stale=True) is None
    calls = []
    def fetch_xml(_endpoint, params, _timeout):
        calls.append(params['DEAL_YMD'])
        return '<response><header><resultCode>000</resultCode></header><body><totalCount>0</totalCount><items/></body></response>'
    monkeypatch.setattr(molit, '_official_api_xml', fetch_xml)
    assert molit.fetch_month('99999', month) == []
    assert collect.inspect_month('99999', month, 'apartment') == 'empty'
    assert calls == [month]


def test_bad_xml_counts_failed_request_without_counting_it_as_empty(source, monkeypatch):
    monkeypatch.setattr(molit, '_official_api_xml', lambda *args: '<broken')
    monkeypatch.setattr(collect.time, 'sleep', lambda _: None)
    collect.request(entity())
    state = wait_until_done(entity())
    assert state['status'] == 'error' and state['errorCode'] == 'invalid_source'
    assert state['failed'] == 1 and state['processed'] == 1
    assert state['unprocessed'] == state['total'] - state['processed']
    assert collect.coverage(collect.target(entity()))[0]['empty'] == 0


def test_a_successful_non_worker_write_also_changes_source_revision(source):
    before = shared_data.data_revision()
    write_month('99999', '202610', 'apartment', [])
    assert shared_data.data_revision() != before


def test_nearby_peer_across_district_border_is_included_in_collection(source, monkeypatch):
    target = entity()
    neighbor = {**entity('인접비교단지', '20'), 'district': '다른구'}
    monkeypatch.setattr(comparison, '_candidates', lambda _entity, _tier: [(neighbor, 400)])
    monkeypatch.setattr(molit, 'source_rows_for_entity', lambda row, _region='': [{
        'lawdCd': '88888' if row['district'] == '다른구' else '99999'}])
    pairs = collect.target(target)
    assert {code for code, _month, _kind in pairs} == {'88888', '99999'}
    assert len(pairs) == 12


def test_price_comparison_reuses_old_valid_month_without_an_upstream_call(source, monkeypatch):
    month = molit._deal_months(6)[0]
    write_month('99999', month, 'apartment', [trade('대상', '1', month, 10, 10)])
    path = molit._cache_path('99999', month)
    data = json.loads(path.read_text()); data['fetchedAt'] = 1
    path.write_text(json.dumps(data))
    molit._MONTH_MEMORY_CACHE.clear()
    monkeypatch.setattr(molit, '_official_api_xml', lambda *args: pytest.fail('valid saved month was refetched'))
    assert comparison._transactions(entity(), '84')[0]['dealAmountEok'] == 10


def test_cached_month_reuses_memory_without_writer_lock_after_another_month_changes(source, monkeypatch):
    month = molit._deal_months(6)[0]
    write_month('99999', month, 'apartment', [trade('대상', '1', month, 10, 10)])
    first = molit.fetch_month('99999', month)
    revision = shared_data.data_revision()
    write_month('88888', month, 'apartment', [])
    assert shared_data.data_revision() != revision
    monkeypatch.setattr(molit.persistent_json_store, 'exclusive_file_lock',
                        lambda *_: pytest.fail('fresh month should not take a write lock'))
    assert molit.fetch_month('99999', month) is first
