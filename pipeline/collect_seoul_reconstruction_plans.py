"""Refresh the complete attributed Seoul plan snapshot on the primary."""
import datetime as dt
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import living_area_sources
import persistent_json_store as store
import reconstruction_project_plans as plans
import shared_data

REFRESH_DAYS = 30
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='seoul-plans')
_JOB = None
_LAST_ATTEMPT = 0.0
LOG = logging.getLogger(__name__)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _save_failure(status):
    path = shared_data.cache_path(plans.FILE)
    with store.exclusive_file_lock(path):
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'records': {}}
        if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
            raise ValueError('invalid Seoul plan source')
        data['lastError'] = {'status': status, 'checkedAt': _now()}
        if not data['records']:
            data['status'] = status
        store.write_json_atomically(path, data)


def collect(*, fetcher=None):
    shared_data.require_writer()
    fetcher = fetcher or living_area_sources.fetch_seoul
    started = _now()
    try:
        rows = fetcher()
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError('empty or malformed official plan response')
        records = {}
        for raw in rows:
            row = {str(k).lower(): v for k, v in raw.items()}
            raw_id = row.get('basic_info_seq')
            try:
                number = float(raw_id)
                record_id = str(int(number)) if number.is_integer() and number > 0 else ''
            except (TypeError, ValueError, OverflowError):
                record_id = ''
            if not record_id or record_id in records or not row.get('bsns_name') or not row.get('site_code_nm'):
                raise ValueError('invalid or duplicate official project identifier')
            records[record_id] = row
        path = shared_data.cache_path(plans.FILE)
        with store.exclusive_file_lock(path):
            payload = {'version': 1, 'status': 'ready', 'sourceId': 'seoul-plan-renewal',
                       'sourceUrl': plans.SOURCE_URL, 'checkedAt': _now(), 'totalCount': len(records),
                       'records': records}
            store.write_json_atomically(path, payload)
        return {'startedAt': started, 'finishedAt': _now(), 'total': 1, 'processed': 1,
                'success': 1, 'failed': 0, 'unprocessed': 0, 'records': len(records)}
    except (living_area_sources.SourceError, ValueError, OSError):
        try:
            _save_failure('connection_error')
        except (OSError, ValueError):
            LOG.warning('Unable to annotate malformed Seoul reconstruction source')
        LOG.warning('Seoul reconstruction source unavailable; kept last verified snapshot')
        return {'startedAt': started, 'finishedAt': _now(), 'total': 1, 'processed': 1,
                'success': 0, 'failed': 1, 'unprocessed': 0}


def request():
    global _JOB, _LAST_ATTEMPT
    if shared_data.read_only():
        return False
    path = shared_data.cache_path(plans.FILE)
    try:
        index = plans._index(path, plans._stamp(path))
        data = index['data'] if index else {}
        checked = plans.development.date(str(data.get('checkedAt') or '')[:10])
        if checked and 0 <= (dt.date.today() - checked).days < REFRESH_DAYS and not data.get('lastError'):
            return False
    except (OSError, ValueError, TypeError):
        # A complete new snapshot can replace a damaged one. A failed refresh
        # must leave the damaged source untouched for diagnosis.
        pass
    with _LOCK:
        if _JOB and not _JOB.done(): return True
        if time.monotonic() - _LAST_ATTEMPT < 900: return False
        _LAST_ATTEMPT = time.monotonic()
        _JOB = _POOL.submit(collect)
    return True
