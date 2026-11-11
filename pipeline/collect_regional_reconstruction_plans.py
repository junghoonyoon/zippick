"""Refresh complete, attributed Gyeonggi/Incheon plan inventories on primary.

Only published factual fields are retained; no contact details or XLSX formulas.
Failed/partial refreshes retain the previous snapshot with an explicit error.
"""
import calendar
from concurrent.futures import ThreadPoolExecutor
import csv
import datetime as dt
import hashlib
from html import unescape
import io
import json
import logging
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
import zipfile

import requests

import apartment_development as development
import persistent_json_store as store
import regional_reconstruction_plans as plans
import shared_data

REFRESH_DAYS = 14
MAX_BYTES = 8_000_000
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='regional-plans')
_LOCK = threading.Lock()
_JOB = None
_LAST_ATTEMPT = 0.0
LOG = logging.getLogger(__name__)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _text(value):
    return re.sub(r'\s+', '', str(value or ''))


def _request(session, method, url, **kwargs):
    allowed = {'www.gg.go.kr', 'www.data.go.kr'}
    if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in allowed:
        raise ValueError('unrecognized public source URL')
    with session.request(method, url, timeout=(8, 25), stream=True, **kwargs) as response:
        response.raise_for_status()
        if urlsplit(response.url).hostname not in allowed:
            raise ValueError('public source redirected to a different host')
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('oversized public source')
            chunks.append(chunk)
        return b''.join(chunks)


def _row(key, name, district, address, kind, stage, source_date, source_url, **fields):
    if not all((name, district, kind, stage)):
        raise ValueError('required project fields missing')
    dong, lot = development.address_parts(address)
    record_id = key + ':' + hashlib.sha256(json.dumps([district, name, address, kind], ensure_ascii=False).encode()).hexdigest()[:24]
    return {'id': record_id, 'sourceId': key, 'name': str(name).strip(),
            'province': plans.SOURCES[key]['province'], 'district': str(district).strip(),
            'address': str(address or '').strip(), 'legalDong': dong, 'jibun': lot,
            'projectTypeLabel': str(kind).strip(), 'stageLabel': str(stage).strip(),
            'sourceDate': source_date, 'sourceUrl': source_url,
            **{k: plans.number(v, 1500 if 'FloorAreaRatio' in k else 100 if 'CoverageRatio' in k else 10**10)
               for k, v in fields.items()}}


def _workbook(content):
    """Read values and their published percent format, never guess the unit."""
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 40_000_000:
            raise ValueError('oversized spreadsheet')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(e.itertext()) for e in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        styles = ET.fromstring(archive.read('xl/styles.xml'))
        formats = {e.get('numFmtId'): e.get('formatCode', '') for e in styles.findall('s:numFmts/s:numFmt', ns)}
        xfs = styles.findall('s:cellXfs/s:xf', ns)
        sheets = []
        for filename in archive.namelist():
            if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml', filename):
                continue
            rows = []
            root = ET.fromstring(archive.read(filename))
            for row in root.findall('.//s:sheetData/s:row', ns):
                cells = {}
                for cell in row.findall('s:c', ns):
                    letters = re.match('[A-Z]+', cell.get('r', ''))
                    if not letters:
                        raise ValueError('spreadsheet coordinate missing')
                    col = 0
                    for ch in letters[0]:
                        col = col * 26 + ord(ch) - 64
                    value = cell.find('s:v', ns)
                    value = value.text if value is not None else None
                    if cell.get('t') == 's':
                        value = strings[int(value)] if value is not None else None
                    elif cell.get('t') == 'inlineStr':
                        inline = cell.find('s:is', ns)
                        value = ''.join(inline.itertext()) if inline is not None else None
                    elif value is not None and cell.get('t') not in ('str', 'e', 'b'):
                        value = float(value)
                        style = xfs[int(cell.get('s', '0'))].get('numFmtId')
                        if style in ('9', '10') or '%' in formats.get(style, ''):
                            value *= 100
                    cells[col - 1] = value
                if cells:
                    rows.append(cells)
            sheets.append(rows)
        return sheets


def parse_gyeonggi(content, source_url, *, source_date=None):
    sheets = _workbook(content)
    candidates = [rows for rows in sheets if rows and '일반정비사업' in _text(rows[0].get(0))]
    if len(candidates) != 1:
        raise ValueError('general renewal worksheet missing')
    rows = candidates[0]
    date_match = re.search(r'(\d{4})년도\s*([1-4])/4분기', str(rows[0].get(0)))
    if not date_match:
        raise ValueError('quarter reference date missing')
    year, month = int(date_match[1]), int(date_match[2]) * 3
    published = dt.date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    if source_date and source_date != published or published > dt.date.today().isoformat():
        raise ValueError('quarter reference date mismatch')
    header_i = next((i for i, row in enumerate(rows) if _text(row.get(0)) == '연번'), None)
    if header_i is None:
        raise ValueError('renewal worksheet header missing')
    header = {_text(value): col for col, value in rows[header_i].items()}
    for required in ('시군', '사업단계', '사업유형', '정비구역명', '위치', '용적률', '신축세대수'):
        if required not in header:
            raise ValueError('renewal worksheet schema changed')
    ratio_col = header['용적률']
    if (rows[header_i + 1].get(ratio_col), rows[header_i + 1].get(ratio_col + 1)) != ('기존', '신축'):
        raise ValueError('published ratio columns changed')
    records, seen_ids, declared_count = {}, set(), None
    for row in rows[header_i + 1:]:
        serial = row.get(0)
        if not isinstance(serial, (int, float)):
            if declared_count is None and not seen_ids and isinstance(row.get(header['정비구역명']), (int, float)):
                declared_count = int(row[header['정비구역명']])
            continue
        if not float(serial).is_integer() or serial in seen_ids:
            raise ValueError('duplicate or invalid project serial')
        seen_ids.add(serial)
        city, name, address, kind, stage = [row.get(header[k]) for k in ('시군', '정비구역명', '위치', '사업유형', '사업단계')]
        if not all((city, name, kind, stage)):
            raise ValueError('incomplete published project row')
        gu = re.search(r'([가-힣]+구)', str(address))
        district = str(city).removesuffix('시') + gu[1] if gu else city
        record = _row('gg-renewal', name, district, f'경기도 {city} {address}' if address else '', kind, stage,
                      published, source_url, plannedFloorAreaRatio=row.get(ratio_col + 1),
                      existingFloorAreaRatio=row.get(ratio_col),
                      existingHouseholds=row.get(9),
                      plannedHouseholds=row.get(header['신축세대수']),
                      projectAreaSqm=row.get(header.get('구역면적(㎡)')))
        if record['id'] in records:
            raise ValueError('duplicate published project')
        records[record['id']] = record
    if not records or declared_count != len(records):
        raise ValueError('published project count does not match worksheet')
    return {'records': records, 'sourceDate': published}


def fetch_gyeonggi(session):
    board_url = plans.SOURCES['gg-renewal']['url']
    html = _request(session, 'GET', board_url).decode('utf-8')
    candidates = []
    for content_id, decode_id, body in re.findall(r'<tr[^>]*onclick="selectBoardContent\(\'(\d+)\',\'(\d+)\'\)"[^>]*>(.*?)</tr>', html, re.S):
        title = unescape(re.sub('<[^>]+>', ' ', body))
        match = re.search(r'경기도\s*정비사업\s*추진\s*현황\s*\((\d{4})년\s*([1-4])분기\)', title)
        if match and decode_id == '5318':
            candidates.append(((int(match[1]), int(match[2])), content_id))
    if not candidates:
        raise ValueError('latest quarterly inventory not found')
    (year, quarter), content_id = max(candidates)
    month = quarter * 3
    source_date = dt.date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    source_url = f'https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx={content_id}&decodeIdx=5318'
    html = _request(session, 'GET', source_url).decode('utf-8')
    links = [(url, unescape(re.sub('<[^>]+>', '', title))) for url, title in re.findall(
        r'href="(/cmmn/download\.do\?idx=\d+)"[^>]*>(.*?)</a>', html, re.S)
        if '정비사업' in title and '재정비촉진' not in title and '.xlsx' in title]
    if len(links) != 1:
        raise ValueError('general renewal workbook not uniquely identified')
    # The page provides these numerical administrative facts as public information.
    return parse_gyeonggi(_request(session, 'GET', urljoin(source_url, links[0][0])), source_url, source_date=source_date)


def parse_incheon(content, key, source_date):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp949')
    reader = csv.DictReader(io.StringIO(text))
    headers = {_text(field): field for field in reader.fieldnames or []}
    required = ('구별', '구역명', '위치', '사업유형', '추진단계', '용적률(퍼센트)', '건폐율(퍼센트)') if key == 'incheon-plan' else ('구명', '구역명', '위치', '사업유형', '진행단계')
    if not set(required) <= set(headers):
        raise ValueError('Incheon inventory schema changed')
    records = {}
    for raw in reader:
        if None in raw or any(value is None for value in raw.values()):
            raise ValueError('partial CSV row')
        row = {_text(k): v for k, v in raw.items()}
        if not any(_text(v) for v in row.values()):
            continue
        record = _row(key, row.get('구역명'), row.get('구별') or row.get('구명'), row.get('위치'),
                      row.get('사업유형'), row.get('추진단계') or row.get('진행단계'), source_date,
                      plans.SOURCES[key]['url'], plannedFloorAreaRatio=row.get('용적률(퍼센트)'),
                      plannedBuildingCoverageRatio=row.get('건폐율(퍼센트)'),
                      plannedHouseholds=row.get('세대수'), projectAreaSqm=row.get('면적(제곱미터)'))
        if record['id'] in records:
            raise ValueError('duplicate published project')
        records[record['id']] = record
    if not records:
        raise ValueError('empty official inventory')
    return {'records': records, 'sourceDate': source_date}


def fetch_incheon(session, key):
    url = plans.SOURCES[key]['url']
    html = _request(session, 'GET', url).decode('utf-8')
    metadata = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    datasets = [json.loads(item) for item in metadata]
    dataset = next((item for item in datasets if item.get('@type') == 'Dataset'), {})
    if '제한 없음' not in str((dataset.get('license') or {}).get('name')):
        raise ValueError('public inventory attribution not verified')
    date_match = re.search(r'_(\d{4})(\d{2})(\d{2})$', dataset.get('alternateName', ''))
    if not date_match:
        raise ValueError('published inventory date missing')
    source_date = dt.date(*(int(v) for v in date_match.groups())).isoformat()
    if source_date > dt.date.today().isoformat():
        raise ValueError('future-dated public inventory')
    match = re.search(r"fn_fileDataDown\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'", html)
    if not match or match[1] not in url:
        raise ValueError('public download identity missing')
    pk, detail, attachment, serial = match.groups()
    response = json.loads(_request(session, 'POST', 'https://www.data.go.kr/tcs/dss/selectFileDataDownload.do', data={
        'publicDataPk': pk, 'publicDataDetailPk': detail, 'atchFileId': attachment,
        'fileDetailSn': serial, 'publicDataTyCode': 'PR0051'}))
    info = response.get('dataSetFileDetailInfo') or {}
    if response.get('status') is not True or info.get('publicDataPk') != pk or not str(info.get('dataNm', '')).endswith(''.join(date_match.groups())):
        raise ValueError('public download does not match dataset')
    params = {'atchFileId': response['atchFileId'], 'fileDetailSn': response['fileDetailSn']}
    check = json.loads(_request(session, 'POST', 'https://www.data.go.kr/cmm/cmm/check-limit.json', data=params))
    if check.get('needCaptcha') is not False:
        raise ValueError('public download needs user verification')
    params['dataNm'] = info['dataNm']
    content = _request(session, 'GET', 'https://www.data.go.kr/cmm/cmm/fileDownload.do', params=params)
    result = parse_incheon(content, key, source_date)
    count = plans.number(info.get('atchFileCo'))
    if count is None or not count.is_integer() or int(count) != len(result['records']):
        raise ValueError('published CSV row count does not match download')
    return result


def _save(key, payload=None):
    path = shared_data.cache_path(plans.FILE)
    with store.exclusive_file_lock(path):
        data = plans.validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else {'version': 1, 'records': {}}
        old = data['records'].get(key) or {'records': {}, 'totalCount': 0, 'sourceUrl': plans.SOURCES[key]['url']}
        if payload is None:
            source = {**old, 'lastError': {'status': 'connection_error', 'checkedAt': _now()}}
        else:
            if old.get('sourceDate', '') > payload['sourceDate']:
                raise ValueError('public source cannot move backwards')
            source = {**payload, 'sourceUrl': plans.SOURCES[key]['url'], 'checkedAt': _now(),
                      'status': 'ready', 'totalCount': len(payload['records'])}
        data['records'][key] = source
        data['updatedAt'] = _now()
        plans.validate(data)
        store.write_json_atomically(path, data)


def collect(*, fetchers=None, keys=None):
    shared_data.require_writer()
    keys = list(keys or plans.SOURCES)
    started, success, failed = _now(), 0, 0
    with requests.Session() as session:
        session.headers['User-Agent'] = 'Zippick/1.0 public-renewal-facts'
        for key in keys:
            try:
                payload = fetchers[key]() if fetchers else fetch_gyeonggi(session) if key == 'gg-renewal' else fetch_incheon(session, key)
                _save(key, payload)
                success += 1
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError):
                failed += 1
                try:
                    _save(key)
                except (OSError, ValueError, TypeError):
                    LOG.warning('Could not annotate the failed regional plan snapshot for %s', key)
    return {'startedAt': started, 'finishedAt': _now(), 'total': len(keys), 'processed': len(keys),
            'success': success, 'failed': failed, 'unprocessed': 0}


def request(entity=None):
    global _JOB, _LAST_ATTEMPT
    if shared_data.read_only():
        return False
    scoped = [key for key, source in plans.SOURCES.items() if entity is None or source['province'] == entity.get('province')]
    if not scoped:
        return False
    try:
        data = plans.load()['records']
    except (OSError, ValueError, TypeError):
        data = {}
    today = dt.date.today()
    due = []
    for key in plans.SOURCES:
        source = data.get(key) or {}
        checked = development.date(str(source.get('checkedAt') or '')[:10])
        if not checked or not 0 <= (today - checked).days < REFRESH_DAYS or source.get('lastError'):
            due.append(key)
    if not set(due).intersection(scoped):
        return False
    with _LOCK:
        if _JOB and not _JOB.done():
            return True
        if time.monotonic() - _LAST_ATTEMPT < 900:
            return False
        _LAST_ATTEMPT = time.monotonic()
        _JOB = _POOL.submit(collect, keys=due)
    return True
