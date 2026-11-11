"""Recheck the official current Seoul ordinance version on the primary."""
import datetime as dt
from html.parser import HTMLParser
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.request import Request, urlopen

import apartment_reconstruction as reconstruction
import persistent_json_store as store
import shared_data

FILE = 'reconstruction_ordinance_verification.json'
URL = 'https://www.law.go.kr/ordinInfoP.do?ordinId=2000719'
REFRESH_DAYS = 30
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ordinance-check')
_LOCK = threading.Lock()
_JOB = None
_LAST_ATTEMPT = 0.0


class _CurrentTitle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.parts = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and dict(attrs).get('id') == 'westLi':
            self.capture = True
            self.count += 1

    def handle_data(self, value):
        if self.capture:
            self.parts.append(value)

    def handle_endtag(self, tag):
        if tag == 'a' and self.capture:
            self.capture = False


def parse_current(raw):
    text = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
    parser = _CurrentTitle(); parser.feed(text)
    title = ' '.join(parser.parts)
    if parser.count != 1 or '서울특별시 도시계획 조례' not in title:
        raise ValueError('current ordinance title missing')
    match = re.search(r'\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', title)
    if not match:
        raise ValueError('current ordinance date missing')
    return dt.date(*(int(value) for value in match.groups())).isoformat()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def collect(*, opener=urlopen):
    shared_data.require_writer()
    config = json.loads(reconstruction.ORDINANCES_PATH.read_text(encoding='utf-8'))['records']['서울특별시']
    status, current, error = 'connection_error', None, None
    try:
        req = Request(URL, headers={'User-Agent': 'Zippick/1.0 public-ordinance-verification'})
        with opener(req, timeout=15) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('ordinance response too large')
        current = parse_current(raw)
        status = 'verified' if current == config['effectiveAt'] else 'changed'
    except (URLError, OSError, ValueError, UnicodeError):
        error = {'status': 'connection_error', 'checkedAt': _now()}
    path = shared_data.cache_path(FILE)
    with store.exclusive_file_lock(path):
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'records': {}}
        if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
            raise ValueError('invalid ordinance verification source')
        old = data['records'].get('서울특별시') or {}
        if not isinstance(old, dict):
            raise ValueError('invalid ordinance verification record')
        if error:
            record = {**old, 'lastError': error}
            if not old:
                record.update(status='connection_error', sourceUrl=URL)
        else:
            record = {'status': status, 'effectiveAt': current, 'checkedAt': _now(), 'sourceUrl': URL}
        data['records']['서울특별시'] = record
        data['updatedAt'] = _now()
        store.write_json_atomically(path, data)
    return {'total': 1, 'processed': 1, 'success': int(error is None), 'failed': int(error is not None),
            'unprocessed': 0, 'status': status, 'effectiveAt': current}


def request():
    global _JOB, _LAST_ATTEMPT
    if shared_data.read_only(): return False
    path = shared_data.cache_path(FILE)
    try:
        data = reconstruction._read(str(path), reconstruction._stamp(path))
        record = data['records'].get('서울특별시') or {}
        checked = reconstruction._date(record.get('checkedAt'))
        if checked and 0 <= (dt.date.today() - checked).days < REFRESH_DAYS and not record.get('lastError'):
            return False
    except (OSError, ValueError, TypeError):
        return False
    with _LOCK:
        if _JOB and not _JOB.done(): return True
        if time.monotonic() - _LAST_ATTEMPT < 900: return False
        _LAST_ATTEMPT = time.monotonic()
        _JOB = _POOL.submit(collect)
    return True
