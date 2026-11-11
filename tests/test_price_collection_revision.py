"""Old in-flight calculations and other processes cannot publish stale results."""
import json
from unittest import mock

import search_server
import momentum_signals


def test_old_budget_result_is_not_saved_under_a_new_source_version(tmp_path, monkeypatch):
    revision = ['first']
    monkeypatch.setattr(search_server.shared_data, 'data_revision', lambda: revision[0])
    monkeypatch.setattr(search_server, 'BUDGET_CACHE_DIR', tmp_path)
    key = search_server._budget_cache_key({'region': '예시구'})
    revision[0] = 'second'
    assert search_server._write_budget_cache(key, {'candidates': [{'name': '이전 결과'}]}) == 0
    assert not (tmp_path / f'{key}.json').exists()
    # Even an evicted key must not be stamped with the current version.
    search_server.BUDGET_KEY_SOURCE_REVISIONS.pop(key)
    assert search_server._write_budget_cache(key, {'candidates': [{'name': '이전 결과'}]}) == 0


def test_other_process_source_version_is_observed_on_next_request(monkeypatch):
    revision = ['first']
    monkeypatch.setattr(search_server.shared_data, 'data_revision', lambda: revision[0])
    monkeypatch.setattr(search_server, '_LAST_SOURCE_REVISION', None)
    search_server._observe_source_revision()
    momentum_signals._DISTRICT_MOMENTUM_CACHE[('example', 'first')] = {'count': 3}
    revision[0] = 'second'
    search_server._observe_source_revision()
    assert momentum_signals._DISTRICT_MOMENTUM_CACHE == {}
    assert search_server._LAST_SOURCE_REVISION == 'second'


def test_inflight_momentum_results_are_keyed_to_their_source_version(monkeypatch):
    revision = ['first']
    monkeypatch.setattr(momentum_signals.shared_data, 'data_revision', lambda: revision[0])
    monkeypatch.setattr(momentum_signals, '_district_region_key', lambda region: region)
    calls = []
    def pairs(_region):
        calls.append(revision[0])
        return [(None, {'status': 'ok', 'momentumPct': 1 if revision[0] == 'first' else 7})] * 3
    monkeypatch.setattr(momentum_signals, '_district_entity_signals', pairs)
    momentum_signals._DISTRICT_MOMENTUM_CACHE.clear()
    assert momentum_signals._district_benchmark('예시구')['momentumPct'] == 1
    revision[0] = 'second'
    assert momentum_signals._district_benchmark('예시구')['momentumPct'] == 7
    assert calls == ['first', 'second']
