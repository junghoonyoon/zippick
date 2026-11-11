"""Fill missing official district-month records once, on the shared primary.

An empty, successfully queried month is valid evidence. A missing, corrupt, or
incomplete file is never represented as zero transactions. Jobs contain only
district codes and feed kinds; they do not store a user's apartment or budget.
"""
import datetime as dt
import functools
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import molit_transactions as molit
import persistent_json_store as store
import report_price_comparison as comparison
import shared_data

LOOKBACK_MONTHS = 60
MAX_JOBS = 8
RETRY_AFTER_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 0.4
STOP_CODES = {'20', '22', '23', '29', '30', '31', '32', '401', '403', '429'}
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='price-data')
_LOCK = threading.RLock()
_JOBS = {}
_LISTENERS = []
_SYNC_RUNNING = False
_LAST_REQUEST = 0.0
_LOG = logging.getLogger(__name__)


def subscribe(callback):
    with _LOCK:
        if callback not in _LISTENERS:
            _LISTENERS.append(callback)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


@functools.lru_cache(maxsize=16384)
def _inspect(path, mtime_ns, size, code, month, kind):
    try:
        with open(path, encoding='utf-8') as src:
            data = json.load(src)
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            return 'invalid'
        if (str(data.get('lawdCd') or '') != code or str(data.get('dealYmd') or '') != month
                or data.get('transactionKind', kind) != kind):
            return 'invalid'
        timestamp = float(data.get('fetchedAt') or 0)
        if not 0 < timestamp < time.time() + 86400:
            return 'invalid'
        if len(data['items']) >= 1000 and data.get('complete') is not True:
            return 'incomplete'
        if any(not isinstance(item, dict) for item in data['items']):
            return 'invalid'
        return 'empty' if not data['items'] else 'available'
    except (OSError, ValueError, TypeError, OverflowError):
        return 'invalid'


def inspect_month(code, month, kind):
    path = molit._cache_path(code, month, kind)
    try:
        if path.is_symlink():
            return 'invalid'
        info = path.stat()
        if not path.is_file():
            return 'invalid'
        return _inspect(str(path), info.st_mtime_ns, info.st_size, code, month, kind)
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'connection_error'


def target(entity):
    if not entity or entity.get('aggregate') or not entity.get('name'):
        return None
    rows = list(molit.source_rows_for_entity(entity, entity.get('district') or ''))
    # A 1 km peer may lie across an administrative border. Find those peers
    # using the same location/size/age rules as the comparison, never price.
    for peer, _distance in comparison._candidates(entity, comparison.PEER_TIERS[0]):
        if peer.get('district') != entity.get('district'):
            rows.extend(molit.source_rows_for_entity(peer, peer.get('district') or ''))
    codes = sorted({code for row in rows for code in molit.related_lawd_codes(molit._row_lawd_cd(row))})
    if not codes or any(not re.fullmatch(r'\d{5}', code) for code in codes):
        return None
    kinds = set(molit._transaction_kinds_for_apartment(entity['name'], entity.get('district') or '', entity))
    if molit.TRANSACTION_KIND_PRESALE in kinds:
        kinds.add(molit.TRANSACTION_KIND_APARTMENT)
    if not kinds or not kinds <= {molit.TRANSACTION_KIND_APARTMENT, molit.TRANSACTION_KIND_PRESALE}:
        return None
    return tuple((code, month, kind) for code in codes for kind in sorted(kinds)
                 for month in molit._deal_months(LOOKBACK_MONTHS))


def coverage(pairs):
    counts = {'available': 0, 'empty': 0, 'missing': 0, 'invalid': 0,
              'incomplete': 0, 'connection_error': 0}
    pending = []
    for code, month, kind in pairs:
        status = inspect_month(code, month, kind)
        counts[status] += 1
        if status not in ('available', 'empty'):
            pending.append((code, month, kind))
    return counts, pending


def _job_key(pairs):
    return hashlib.sha256(json.dumps(pairs, separators=(',', ':')).encode()).hexdigest()[:20]


def _revision_bump():
    # Also publishes when a collector implementation supplies a valid cache
    # without using molit._write_cached_month (for example during recovery).
    shared_data.bump_data_revision()
    for callback in tuple(_LISTENERS):
        try:
            callback()
        except Exception:
            _LOG.exception('price source invalidation failed')


def _persist(job):
    path = shared_data.cache_path('price_data_collection_log.json')
    with store.exclusive_file_lock(path):
        data = store.read_json_object(path)
        records = data.get('records') if isinstance(data.get('records'), dict) else {}
        records[job['key']] = {k: job.get(k) for k in (
            'status', 'districtCodes', 'feedKinds', 'total', 'reused', 'processed',
            'success', 'empty', 'failed', 'unprocessed', 'startedAt', 'endedAt', 'errorCode')}
        blocked = data.get('blocked') if isinstance(data.get('blocked'), dict) else {}
        if job.get('errorCode') in STOP_CODES and not job.get('blockedExisting'):
            blocked = {'errorCode': job['errorCode'], 'until': time.time() + 600}
        store.write_json_atomically(path, {'version': 1, 'records': records, 'blocked': blocked})


def _code(exc):
    if isinstance(exc, molit.OfficialTransactionError):
        return exc.code
    if isinstance(exc, requests.HTTPError):
        return str(getattr(exc.response, 'status_code', '') or 'http_error')
    if isinstance(exc, requests.Timeout):
        return 'timeout'
    if isinstance(exc, requests.RequestException):
        return 'connection_error'
    if isinstance(exc, OSError):
        return 'storage_error'
    return 'invalid_source'


def _run_unlocked(job, pairs):
    global _LAST_REQUEST
    job.update(startedAt=_now(), status='collecting')
    try:
        journal = store.read_json_object(shared_data.cache_path('price_data_collection_log.json'))
        blocked = journal.get('blocked') if isinstance(journal.get('blocked'), dict) else {}
        if float(blocked.get('until') or 0) > time.time():
            job.update(status='error', errorCode=str(blocked.get('errorCode') or 'blocked'), blockedExisting=True)
            return
        if job.get('recoverPublication'):
            _revision_bump()
        for code, month, kind in pairs:
            if inspect_month(code, month, kind) in ('available', 'empty'):
                job['reused'] += 1
                job['processed'] += 1
                continue
            if not molit.configured(kind):
                job.update(status='error', errorCode='credentials_unavailable',
                           failed=job['failed'] + 1, processed=job['processed'] + 1)
                break
            error = None
            for attempt in range(2):
                try:
                    delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST)
                    if delay > 0:
                        time.sleep(delay)
                    _LAST_REQUEST = time.monotonic()
                    molit.fetch_month(code, month, kind)
                    state = inspect_month(code, month, kind)
                    if state not in ('available', 'empty'):
                        raise molit.OfficialTransactionError('invalid_saved_record')
                    _revision_bump()
                    job['success'] += 1
                    job['empty'] += int(state == 'empty')
                    error = None
                    break
                except Exception as exc:
                    # Parsing and validation errors are failed lookups, not empty months.
                    error = _code(exc)
                    if error in STOP_CODES or attempt:
                        break
                    time.sleep(1)
            job['processed'] += 1
            if error:
                job.update(status='error', errorCode=error, failed=job['failed'] + 1)
                break
    except Exception as exc:
        job.update(status='error', errorCode=_code(exc), failed=job['failed'] + 1)
        _LOG.error('price data collection failed: %s', type(exc).__name__)
    finally:
        job['unprocessed'] = max(0, job['total'] - job['processed'])
        job['endedAt'] = _now()
        job['finishedMonotonic'] = time.monotonic()
        final_status = 'error' if job['status'] == 'error' else 'ready'
        job['status'] = 'collecting'
        try:
            _persist({**job, 'status': final_status})
        except (OSError, ValueError, TypeError):
            final_status = 'error'
            job['errorCode'] = 'storage_error'
            _LOG.error('price collection log could not be stored')
        job['status'] = final_status


def _run(job, pairs):
    """Serialize workers across service processes and batch tools."""
    try:
        with store.exclusive_file_lock(shared_data.cache_path('price_data_collection_worker')):
            _run_unlocked(job, pairs)
    except (OSError, ValueError, TypeError):
        job.update(status='error', errorCode='storage_error', endedAt=_now(),
                   finishedMonotonic=time.monotonic(), unprocessed=job['total'] - job['processed'])
        _LOG.error('price collection worker lock failed')


def _schedule_sync():
    global _SYNC_RUNNING
    with _LOCK:
        if _SYNC_RUNNING:
            return
        _SYNC_RUNNING = True
    def run():
        global _SYNC_RUNNING
        try:
            shared_data.sync_once()
        finally:
            with _LOCK:
                _SYNC_RUNNING = False
    threading.Thread(target=run, name='price-source-sync', daemon=True).start()


def _primary_status(entity, retry=False):
    """Ask the public production service to collect, never the upstream API."""
    host = shared_data.SOURCE_HOST
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or host.startswith('-'):
        return {'status': 'error', 'errorCode': 'source_configuration'}
    params = {'name': entity.get('name'), 'region': entity.get('district'),
              'legal_dong': entity.get('legalDong'), 'jibun': entity.get('jibun'),
              'apartment_id': entity.get('apartmentId'), 'kapt_code': entity.get('kaptCode'),
              'complex_no': entity.get('complexNo'), 'retry': '1' if retry else '0'}
    try:
        response = requests.get(f'https://{host}/api/apartment-price-source',
                                params={k: v for k, v in params.items() if v}, timeout=8)
        response.raise_for_status()
        body = response.json()
        value = body.get('priceDataCollection') if isinstance(body, dict) else None
        if not isinstance(value, dict) or value.get('status') not in ('ready', 'collecting', 'queued', 'error'):
            raise ValueError('invalid status')
        return value
    except (requests.RequestException, ValueError, TypeError):
        return {'status': 'error', 'errorCode': 'primary_connection'}


def request(entity, *, retry=False, enqueue=True):
    pairs = target(entity)
    if not pairs:
        return {'status': 'error', 'errorCode': 'identity_unverified',
                'message': '단지의 실거래 지역을 확인하지 못했어요.'}
    counts, missing = coverage(pairs)
    if not missing:
        # The last file can appear just before the worker publishes its new
        # source revision. Wait for that publication before calculating.
        with _LOCK:
            running = _JOBS.get(_job_key(pairs))
            if running and running.get('status') in ('queued', 'collecting'):
                return {'status': running['status'], 'message': '수집한 실거래를 확인하고 있어요.', 'counts': counts}
            if running and running.get('status') == 'error' and running.get('errorCode') == 'storage_error':
                elapsed = time.monotonic() - running.get('finishedMonotonic', time.monotonic())
                if retry and elapsed >= RETRY_AFTER_SECONDS:
                    recovery = {**running, 'status': 'queued', 'recoverPublication': True,
                                'total': 0, 'processed': 0, 'success': 0, 'empty': 0,
                                'failed': 0, 'unprocessed': 0, 'errorCode': ''}
                    _JOBS[running['key']] = recovery
                    _POOL.submit(_run, recovery, ())
                    return {'status': 'queued', 'message': '수집한 실거래를 다시 연결하고 있어요.', 'counts': counts}
                return {'status': 'error', 'errorCode': 'storage_error', 'counts': counts,
                        'message': '수집한 실거래를 저장하지 못했어요. 잠시 뒤 다시 불러와 주세요.'}
        return {'status': 'ready', 'total': len(pairs), 'reused': len(pairs),
                'available': counts['available'], 'empty': counts['empty'], 'missing': 0,
                'sourceRevision': shared_data.data_revision(), 'sourceStatus': shared_data.status().get('status')}
    if counts['connection_error']:
        return {'status': 'error', 'errorCode': 'source_read_error', 'counts': counts,
                'message': '실거래 원본을 읽지 못했어요. 잠시 뒤 다시 불러와 주세요.'}
    if shared_data.read_only():
        remote = _primary_status(entity, retry=retry) if enqueue else _primary_status(entity)
        if remote.get('status') == 'ready':
            _schedule_sync()
            return {'status': 'collecting', 'stage': 'syncing', 'counts': counts,
                    'message': '운영에서 받은 실거래를 연결하고 있어요.'}
        return {**remote, 'counts': counts}
    key = _job_key(pairs)
    with _LOCK:
        job = _JOBS.get(key)
        if job and job.get('status') == 'ready' and missing:
            _JOBS.pop(key, None)
            job = None
        if job and job.get('status') == 'error':
            elapsed = time.monotonic() - job.get('finishedMonotonic', time.monotonic())
            if retry and elapsed >= RETRY_AFTER_SECONDS:
                _JOBS.pop(key, None)
                job = None
        if not job and enqueue:
            active = sum(j.get('status') in ('queued', 'collecting') for j in _JOBS.values())
            if active >= MAX_JOBS:
                return {'status': 'error', 'errorCode': 'queue_full',
                        'message': '실거래 수집 요청이 많아요. 잠시 뒤 다시 불러와 주세요.'}
            job = {'key': key, 'status': 'queued', 'districtCodes': sorted({p[0] for p in pairs}),
                   'feedKinds': sorted({p[2] for p in pairs}), 'total': len(missing),
                   'reused': len(pairs) - len(missing), 'processed': 0, 'success': 0,
                   'empty': 0, 'failed': 0, 'unprocessed': len(missing), 'startedAt': None,
                   'endedAt': None, 'errorCode': ''}
            _JOBS[key] = job
            _POOL.submit(_run, job, missing)
        if not job:
            return {'status': 'error', 'errorCode': 'not_started', 'counts': counts,
                    'message': '실거래 수집이 아직 시작되지 않았어요. 다시 불러와 주세요.'}
        state = {k: job.get(k) for k in ('status', 'total', 'reused', 'processed', 'success',
                 'empty', 'failed', 'unprocessed', 'startedAt', 'endedAt', 'errorCode')}
        state['unprocessed'] = max(0, state['total'] - state['processed'])
        state['counts'] = counts
        state['message'] = ('가격 비교에 필요한 실거래를 수집하고 있어요.' if state['status'] in ('queued', 'collecting')
                            else '실거래를 불러오지 못했어요. 잠시 뒤 다시 불러와 주세요.' if state['status'] == 'error'
                            else '수집한 실거래를 확인하고 있어요.')
        return state
