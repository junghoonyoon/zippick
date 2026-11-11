"""Collect attributed, public parcel facts on the shared primary only.

토지이음의 public land-use page is not an open API. Requests are limited,
validated against the returned address and its attribution notice, and stored
as representative-parcel facts. They never establish an entire site limit.
"""
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import apartment_identity
import apartment_reconstruction as reconstruction
import persistent_json_store as store
import shared_data

SOURCE_URL = 'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp'
MAX_BYTES = 3_000_000
REFRESH_DAYS = 30
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='parcel-planning')
_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_JOBS = {}
_LAST_REQUEST = 0.0
_BLOCKED_UNTIL = 0.0
_STOP_CODES = {'401', '403', '429'}


class PlanningError(RuntimeError):
    def __init__(self, status, code=''):
        super().__init__(status)
        self.status, self.code = status, str(code)


class _PublicParcel(HTMLParser):
    """Read visible address, area and land-use labels; ignore hidden inputs."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_header = False
        self.last_header = ''
        self.in_address = False
        self.in_area = False
        self.in_mark = False
        self.in_label = False
        self.hidden_depth = 0
        self.address = []
        self.area = []
        self.header = []
        self.label = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        void = tag in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        if self.hidden_depth:
            if not void:
                self.hidden_depth += 1
            return
        if ('hidden' in attrs or attrs.get('aria-hidden') == 'true'
                or re.search(r'display\s*:\s*none', attrs.get('style', ''), re.I)):
            if not void:
                self.hidden_depth = 1
            return
        if tag == 'th':
            self.in_header, self.header = True, []
        elif tag == 'td':
            self.in_address = self.last_header == '소재지'
            self.in_area = attrs.get('id') == 'present_area'
            self.in_mark = attrs.get('id') == 'present_mark1'
            self.last_header = ''
        elif tag == 'a' and self.in_mark and attrs.get('onclick', '').startswith('openLandLayer('):
            self.in_label, self.label = True, []

    def handle_data(self, value):
        if self.hidden_depth:
            return
        if self.in_header:
            self.header.append(value)
        if self.in_address:
            self.address.append(value)
        if self.in_area:
            self.area.append(value)
        if self.in_label:
            self.label.append(value)

    def handle_endtag(self, tag):
        if self.hidden_depth:
            self.hidden_depth -= 1
            return
        if tag == 'th' and self.in_header:
            self.last_header = ''.join(self.header).strip()
            self.in_header = False
        elif tag == 'a' and self.in_label:
            self.labels.append(''.join(self.label).strip())
            self.in_label = False
        elif tag == 'td':
            self.in_address = self.in_area = self.in_mark = False


def _normal(value):
    return re.sub(r'\s+', '', str(value or '')).replace('번지', '')


def parse_public_page(raw, entity, *, day=None):
    if len(raw) > MAX_BYTES:
        raise PlanningError('invalid_source', 'oversize')
    try:
        text = raw.decode('cp949') if isinstance(raw, bytes) else str(raw)
    except UnicodeDecodeError:
        raise PlanningError('invalid_source', 'encoding') from None
    if '공공누리마크' not in text or '출처표시 조건에 따라 자유이용' not in text:
        raise PlanningError('license_unverified', 'attribution_missing')
    parser = _PublicParcel()
    parser.feed(text)
    address = _normal(''.join(parser.address))
    expected = _normal(' '.join(str(entity.get(k) or '') for k in ('province', 'district', 'legalDong', 'jibun')))
    if not expected or address != expected:
        raise PlanningError('identity_unverified', 'address_mismatch')
    if not parser.labels:
        raise PlanningError('invalid_source', 'zoning_missing')
    zones = [name for name in parser.labels if re.fullmatch(
        r'(?:제[123]종)?(?:전용주거|일반주거)지역|준주거지역|(?:중심|일반|근린|유통)상업지역|(?:전용|일반|준)공업지역|(?:보전|생산|자연)녹지지역|(?:보전|생산|계획)관리지역|농림지역|자연환경보전지역',
        re.sub(r'\([^()]*\)$', '', re.sub(r'\s+', '', name)))]
    plans = [name for name in parser.labels if '지구단위계획구역' in name]
    if not zones:
        raise PlanningError('no_records', 'no_zoning')
    area_text = ''.join(parser.area).strip()
    match = re.fullmatch(r'([\d,]+(?:\.\d+)?)\s*㎡', area_text)
    area = reconstruction.number(match.group(1)) if match else None
    if not area:
        raise PlanningError('invalid_source', 'area_missing')
    pnu = reconstruction.parcel_pnu(entity)
    return {'pnu': pnu, 'address': ''.join(parser.address).strip(), 'parcelAreaSqm': area,
            'zoneNames': list(dict.fromkeys(re.sub(r'\s+', '', zone) for zone in zones)),
            'districtPlans': list(dict.fromkeys(plans)), 'checkedAt': (day or dt.date.today()).isoformat(),
            'sourceUrl': SOURCE_URL + '?' + urlencode({'chk': '0', 'isNoScr': 'script', 'mode': 'search',
                                                       'pnu': pnu, 'scale': '', 'selGbn': 'umd'}),
            'source': '국토교통부 토지이음 토지이용계획', 'license': '공공누리 출처표시',
            'scope': 'representative_parcel', 'zoneCoverageVerified': False}


def fetch(entity, *, opener=urlopen, day=None):
    global _LAST_REQUEST
    pnu = reconstruction.parcel_pnu(entity)
    if not pnu:
        raise PlanningError('identity_unverified', 'parcel_missing')
    url = SOURCE_URL + '?' + urlencode({'chk': '0', 'isNoScr': 'script', 'mode': 'search',
                                        'pnu': pnu, 'scale': '', 'selGbn': 'umd'})
    try:
        with _REQUEST_LOCK:
            delay = max(0.0, 1.0 - (time.monotonic() - _LAST_REQUEST))
            if delay:
                time.sleep(delay)
            _LAST_REQUEST = time.monotonic()
            request = Request(url, headers={'User-Agent': 'Zippick/1.0 public-land-use-reference', 'Accept': 'text/html'})
            with opener(request, timeout=15) as response:
                raw = response.read(MAX_BYTES + 1)
        return parse_public_page(raw, entity, day=day)
    except HTTPError as exc:
        raise PlanningError('access_denied' if str(exc.code) in _STOP_CODES else 'connection_error', str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise PlanningError('connection_error', 'network') from None


def _save(entity, *, reference=None, error=None):
    shared_data.require_writer()
    path = shared_data.cache_path(reconstruction.PLANNING_FILE)
    key = str(entity['apartmentId'])
    identity = {k: entity.get(k, '') for k in ('apartmentId', 'province', 'district', 'legalDong', 'jibun', 'cortarNo')}
    if reference is not None and not reconstruction._parcel_reference(entity, {'identity': identity, 'parcelReference': reference}, dt.date.today()):
        raise ValueError('invalid parcel reference')
    with store.exclusive_file_lock(path):
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'records': {}}
        if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
            raise ValueError('invalid planning store')
        previous = data['records'].get(key) or {}
        if not isinstance(previous, dict):
            raise ValueError('invalid planning record')
        old_id = previous.get('identity') or {}
        if old_id and any(str(old_id.get(k)) != str(identity.get(k)) for k in ('apartmentId', 'district', 'legalDong', 'jibun')):
            raise ValueError('planning identity mismatch')
        entry = {**previous, 'identity': identity}
        if reference is not None:
            entry['parcelReference'] = reference
            entry.pop('lastError', None)
        elif error:
            entry['lastError'] = {'status': error.status, 'errorCode': error.code,
                                  'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat()}
        data['records'][key] = entry
        data['updatedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
        store.write_json_atomically(path, data)


def collect(entities, *, refresh=False, fetcher=fetch, sleep=time.sleep):
    shared_data.require_writer()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    path = shared_data.cache_path(reconstruction.PLANNING_FILE)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'records': {}}
    if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
        raise ValueError('invalid planning store')
    stats = {'startedAt': started, 'total': len(entities), 'processed': 0, 'success': 0, 'reused': 0,
             'noRecords': 0, 'identityMissing': 0, 'failed': 0, 'unprocessed': 0, 'requests': 0, 'stoppedCode': None}
    seen = {}
    for entity in entities:
        key, pnu = str(entity.get('apartmentId') or ''), reconstruction.parcel_pnu(entity)
        if not key or not pnu:
            stats['processed'] += 1; stats['identityMissing'] += 1
            continue
        if key in seen:
            stats['processed'] += 1
            if seen[key] == pnu: stats['reused'] += 1
            else: stats['identityMissing'] += 1
            continue
        seen[key] = pnu
        old = data['records'].get(key) or {}
        old_id = old.get('identity') or {}
        if old_id and any(str(old_id.get(k)) != str(entity.get(k)) for k in ('apartmentId', 'district', 'legalDong', 'jibun')):
            stats['processed'] += 1; stats['identityMissing'] += 1
            continue
        existing = old.get('parcelReference') or old.get('ordinanceReference') or {}
        checked = reconstruction._date(existing.get('checkedAt'))
        if not refresh and checked and 0 <= (dt.date.today() - checked).days < REFRESH_DAYS and not old.get('lastError'):
            stats['processed'] += 1; stats['reused'] += 1
            continue
        error = None
        for attempt in range(2):
            stats['requests'] += 1
            try:
                reference = fetcher(entity)
                _save(entity, reference=reference)
                stats['success'] += 1
                error = None
                break
            except PlanningError as exc:
                error = exc
                if exc.status != 'connection_error' or exc.code in _STOP_CODES or attempt:
                    break
                sleep(1)
        stats['processed'] += 1
        if error:
            _save(entity, error=error)
            if error.status == 'no_records': stats['noRecords'] += 1
            elif error.status == 'identity_unverified': stats['identityMissing'] += 1
            else: stats['failed'] += 1
            if error.code in _STOP_CODES:
                stats['stoppedCode'] = error.code
                break
    stats['unprocessed'] = stats['total'] - stats['processed']
    stats['finishedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    return stats


def request(entity):
    global _BLOCKED_UNTIL
    if shared_data.read_only():
        return False
    key = str(entity.get('apartmentId') or '')
    if not key or not reconstruction.parcel_pnu(entity):
        return False
    path = shared_data.cache_path(reconstruction.PLANNING_FILE)
    try:
        old = reconstruction._read(str(path), reconstruction._stamp(path))['records'].get(key) or {}
    except (ValueError, OSError, TypeError):
        return False
    previous = old.get('parcelReference') or old.get('ordinanceReference') or {}
    old_id = old.get('identity') or {}
    if old_id and any(str(old_id.get(k)) != str(entity.get(k)) for k in ('apartmentId', 'district', 'legalDong', 'jibun')):
        return False
    checked = reconstruction._date(previous.get('checkedAt'))
    if checked and 0 <= (dt.date.today() - checked).days < REFRESH_DAYS and not old.get('lastError'):
        return False
    with _LOCK:
        job = _JOBS.get(key)
        if job and not job[0].done(): return True
        if time.monotonic() < _BLOCKED_UNTIL or (job and time.monotonic() - job[1] < 60): return False
        if sum(not row[0].done() for row in _JOBS.values()) >= 20: return False
        def run():
            global _BLOCKED_UNTIL
            try:
                result = collect([entity])
                if result['stoppedCode']: _BLOCKED_UNTIL = time.monotonic() + 900
            except (OSError, ValueError):
                import logging
                logging.getLogger(__name__).exception('parcel planning persistence failed for %s', key)
        for old_key, (future, when) in list(_JOBS.items()):
            if future.done() and time.monotonic() - when > 900: del _JOBS[old_key]
        _JOBS[key] = (_POOL.submit(run), time.monotonic())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--district', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    import budget_candidates
    entities = budget_candidates._find_entities(args.name, args.district)
    print(json.dumps(collect(entities, refresh=args.refresh), ensure_ascii=False))


if __name__ == '__main__':
    main()
