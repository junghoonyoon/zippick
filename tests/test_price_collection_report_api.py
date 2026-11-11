"""Report handler must wait for missing source data before calculating a score."""
import threading
import time
from urllib.parse import urlencode

import pytest

import molit_transactions as molit
import price_data_collection as collect
import report_price_comparison as comparison
import search_server
from test_price_data_collection import entity, source, trade, write_month


def invoke(path, params):
    response = []
    handler = object.__new__(search_server.Handler)
    handler.path = path + '?' + urlencode(params)
    handler._apply_rate_limit = lambda parsed: True
    handler._json = lambda payload, status=200: response.append((status, payload))
    handler.do_GET()
    assert len(response) == 1
    return response[0]


def test_report_endpoint_waits_then_recomputes_price_after_collection(source, monkeypatch):
    subject, p1, p2 = entity(), entity('비교하나', '2'), entity('비교둘', '3')
    monkeypatch.setattr(search_server.budget_candidates, 'resolve_apartment_identity',
                        lambda *args, **kwargs: {'entity': subject})
    monkeypatch.setattr(comparison.real_estate_search, 'APARTMENT_MASTER', [subject, p1, p2])
    monkeypatch.setattr(comparison, '_entity_coordinates', lambda entity: (37.5, 127.1))
    monkeypatch.setattr(comparison, '_peer_distance_meters', lambda *args: 500)
    started, release = threading.Event(), threading.Event()
    def fetch(code, month, kind='apartment'):
        existing = molit._read_cached_month(code, month, allow_stale=True, transaction_kind=kind)
        if existing is not None:
            return existing
        started.set()
        assert release.wait(3)
        items = [trade(name, lot, month, day, price) for name, lot, price in [
            ('대상', '1', 10), ('비교하나', '2', 11), ('비교둘', '3', 12)] for day in (10, 20)]
        write_month(code, month, kind, items)
        return items
    monkeypatch.setattr(molit, 'fetch_month', fetch)
    def report(*args):
        result = comparison.compare({}, subject, [], '84.0')
        return {'report': {'priceComparison': result}}
    monkeypatch.setattr(search_server, '_apartment_report', report)
    params = {'name': '대상', 'region': '예시구', 'legal_dong': '예시동', 'jibun': '1',
              'apartment_id': '대상', 'area_label': '84.0'}
    status, first = invoke('/api/apartment-report', params)
    assert status == 200 and first['report']['priceComparison']['status'] == 'loading'
    assert first['report']['priceDataCollection']['status'] in ('queued', 'collecting')
    assert started.wait(2)
    status, progress = invoke('/api/apartment-price-source', params)
    assert status == 200 and progress['priceDataCollection']['status'] in ('queued', 'collecting')
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _, progress = invoke('/api/apartment-price-source', params)
        if progress['priceDataCollection']['status'] == 'ready':
            break
        time.sleep(.005)
    status, final = invoke('/api/apartment-report', params)
    assert status == 200
    model = final['report']['priceComparison']
    assert model['status'] == 'ready' and model['method'] == 'usual_gap'
    assert len(model['peers']) == 2 and model['shiftPp'] is not None
    assert final['report']['priceDataCollection']['status'] == 'ready'


def test_no_matching_entity_is_not_misreported_as_zero_trades(source, monkeypatch):
    monkeypatch.setattr(search_server.budget_candidates, 'resolve_apartment_identity',
                        lambda *args, **kwargs: {'entity': None, 'status': 'ambiguous'})
    status, body = invoke('/api/apartment-report', {'name': '단지', 'region': '예시구', 'apartment_id': 'x'})
    assert status == 409 and '정확히 찾지' in body['error']


def test_source_change_during_report_recomputes_instead_of_returning_stale_data(source, monkeypatch):
    subject = entity()
    monkeypatch.setattr(search_server.budget_candidates, 'resolve_apartment_identity',
                        lambda *args, **kwargs: {'entity': subject})
    for month in molit._deal_months(6):
        write_month('99999', month, 'apartment', [])
    calls = []
    def report(*args):
        calls.append(shared_data.data_revision())
        if len(calls) == 1:
            shared_data.bump_data_revision()
        return {'report': {'priceComparison': {'status': 'ready', 'shiftPp': len(calls)}}}
    import shared_data
    monkeypatch.setattr(search_server, '_apartment_report', report)
    status, result = invoke('/api/apartment-report', {'name': '대상', 'region': '예시구', 'apartment_id': '대상'})
    assert status == 200 and len(calls) == 2
    assert result['report']['priceComparison']['shiftPp'] == 2
    assert result['report']['priceDataCollection']['sourceRevision'] == calls[-1]
