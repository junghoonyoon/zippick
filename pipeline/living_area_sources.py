"""Allowlisted public data adapters and atomic, auditable SQLite snapshots.

No geocoding fallback: an address is not a verified point or a project boundary.
No credentials, request URLs containing keys, or raw exceptions are logged.
"""
import csv
from functools import lru_cache
import datetime as dt
import hashlib
import io
import json
import logging
import re
import sqlite3
import ssl
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config

REGISTRY_PATH = config.ROOT / 'data/living_area_sources.json'
DB_PATH = config.CACHE_DIR / 'living_area.sqlite3'
REGISTRY = json.loads(REGISTRY_PATH.read_text())
BUNDLED_PATH = config.ROOT / 'data/living_area_seoul_snapshot.json'
LOG = logging.getLogger(__name__)
SEOUL_SERVICE = 'vnBsnsNmtn'
STAGE_MAP = {'계획': 'planning', '정비계획수립': 'planning', '구역지정': 'designated',
             '정비구역지정': 'designated', '추진위구성': 'designated',
             '조합설립인가': 'association', '조합설립': 'association',
             '사업시행인가': 'approved', '사업시행계획인가': 'approved',
             '관리처분인가': 'disposal', '관리처분계획인가': 'disposal',
             '착공': 'construction', '공사중': 'construction',
             '준공': 'completed', '준공인가': 'completed', '해제': 'cancelled', '취소': 'cancelled'}


class SourceError(ValueError):
    pass


def date(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def allowed(source_id, *, day=None):
    source = REGISTRY.get(source_id, {})
    verified = date(source.get('verifiedAt'))
    day = day or dt.date.today()
    permitted = source.get('licenseStatus') == 'commercial_allowed' or (
        source.get('licenseStatus') == 'reviewed_facts_only' and source.get('scope') == 'factual_metadata_only')
    return (permitted and verified is not None
            and 0 <= (day - verified).days <= 366
            and {'collect', 'derive', 'web', 'pdf'} <= set(source.get('allowedUses', [])))


def connection(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS source_snapshots (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL, as_of TEXT NOT NULL,
            collected_at TEXT NOT NULL, complete INTEGER NOT NULL, raw_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS current_sources (source_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS complex_observations (
            apartment_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    return db


def _count(value):
    try:
        number = float(str(value).replace(',', ''))
        return int(number) if number >= 0 and number.is_integer() else None
    except (ValueError, TypeError, OverflowError):
        return None


def stage_date(value):
    """Seoul JSON export uses epoch milliseconds; Open API uses date text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return dt.datetime.fromtimestamp(value / 1000, dt.timezone(dt.timedelta(hours=9))).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    text = str(value or '')[:10]
    return text if date(text) else None


def normalize(source_id, raw, *, as_of, collected_at, snapshot_id):
    if not allowed(source_id):
        raise SourceError('상업적 이용과 내보내기가 확인되지 않은 자료예요.')
    if source_id == 'seoul-plan-renewal':
        raw = {k.upper(): v for k, v in raw.items()}
        record_id = str(_count(raw.get('BASIC_INFO_SEQ')) or '')
        name, region = raw.get('BSNS_NAME'), raw.get('SITE_CODE_NM')
        address, kind = raw.get('BSNS_ADDR') or '', raw.get('CLASSIFY_L_NM') or ''
        stage, households = raw.get('PROPEL_CD_NM') or '', raw.get('SUPLY_HSHLD')
        stage_as_of = stage_date(raw.get('PROPEL_DT'))
    elif source_id == 'molit-renewal':
        name, region = raw.get('구역명칭'), raw.get('시군구')
        address, kind = '', raw.get('사업유형', '')
        stage = raw.get('현 사업추진단계', raw.get('현 사업 추진단계', ''))
        households = raw.get('공급 예정 세대수', raw.get('공급 예정 세대 수'))
        # Official CSV has no record PK. Stable composite identity is marked explicitly.
        record_id = digest([raw.get('시도'), region, name, kind])[:24]
        stage_as_of = None
    else:
        raise SourceError('이 자료의 정비사업 변환기는 아직 지원하지 않아요.')
    if not record_id or not name or not region:
        raise SourceError('사업 고유값·이름·지역을 확인할 수 없어요.')
    match = re.search(r'([가-힣0-9]+동)\s+(\d+(?:-\d+)?)', address)
    source = REGISTRY[source_id]
    import project_official_links
    detail_url = project_official_links.individual_url(raw.get('CLEANUP_BSNS_URL')) if source_id == 'seoul-plan-renewal' else None
    return {**({'officialDetailUrl': detail_url, 'officialDetailBasis': 'official_record_homepage',
                'officialDetailTitle': str(name), 'officialDetailCheckedAt': collected_at[:10],
                'officialDetailSourceUrl': source['url'], 'officialDetailSourceDate': as_of} if detail_url else {}),
            'id': f'{source_id}:{record_id}', 'sourceId': source_id, 'sourceRecordId': record_id,
            'recordIdMethod': 'source_pk' if source_id == 'seoul-plan-renewal' else 'composite_fields',
            'snapshotId': snapshot_id, 'name': str(name), 'region': str(region),
            'address': address, 'legalDong': match[1] if match else '', 'jibun': match[2] if match else '',
            'projectType': 'reconstruction' if '재건축' in kind else 'redevelopment' if '재개발' in kind else 'other',
            'stage': STAGE_MAP.get(re.sub(r'\s', '', stage), 'unknown'), 'stageLabel': stage or '단계 미확인',
            'stageAsOf': stage_as_of if stage_as_of and stage_as_of <= as_of else None,
            'plannedHouseholds': _count(households), 'householdsStatus': 'planned',
            'sourceUrl': source['url'], 'sourceDate': as_of, 'collectedAt': collected_at,
            'licenseVerifiedAt': source['verifiedAt'], 'licenseUrl': source['licenseUrl'],
            'geometryType': None, 'locationConfidence': 'unverified'}


def save_snapshot(source_id, rows, *, as_of, complete, path=None, collected_at=None):
    if not allowed(source_id) or not date(as_of) or date(as_of) > dt.date.today():
        raise SourceError('자료 출처의 이용조건 또는 기준일을 확인해야 해요.')
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise SourceError('원본 행 목록이 필요해요.')
    collected_at = collected_at or dt.datetime.now(dt.timezone.utc).isoformat()
    snapshot_id = digest({'source': source_id, 'asOf': as_of, 'rows': rows, 'complete': bool(complete)})
    projects = [normalize(source_id, r, as_of=as_of, collected_at=collected_at, snapshot_id=snapshot_id) for r in rows]
    if len({p['id'] for p in projects}) != len(projects):
        raise SourceError('같은 원본 ID가 중복돼 저장을 보류했어요.')
    db = connection(path)
    try:
        with db:
            previous = db.execute('SELECT s.as_of FROM current_sources c JOIN source_snapshots s ON s.id=c.snapshot_id WHERE c.source_id=?', (source_id,)).fetchone()
            if previous and previous[0] > as_of:
                raise SourceError('이전 기준일 자료로 최신 자료를 덮어쓸 수 없어요.')
            db.execute('INSERT OR IGNORE INTO source_snapshots VALUES (?,?,?,?,?,?)',
                       (snapshot_id, source_id, as_of, collected_at, int(complete), json.dumps(rows, ensure_ascii=False)))
            # Samples and incomplete pages can be audited, but never become production input.
            if complete:
                db.execute('INSERT OR REPLACE INTO current_sources VALUES (?,?)', (source_id, snapshot_id))
    finally:
        db.close()
    return snapshot_id


def load_projects(path=None):
    path = Path(path or DB_PATH)
    if not path.exists():
        return bundled_projects()
    db = connection(path)
    try:
        rows = db.execute('SELECT s.id,s.source_id,s.as_of,s.collected_at,s.raw_json FROM current_sources c JOIN source_snapshots s ON s.id=c.snapshot_id WHERE s.complete=1').fetchall()
    finally:
        db.close()
    if not rows:
        return bundled_projects()
    stored = [normalize(source, raw, as_of=as_of, collected_at=collected, snapshot_id=snapshot)
              for snapshot, source, as_of, collected, payload in rows if allowed(source)
              for raw in json.loads(payload)]
    return stored + (bundled_projects() if not any(row[1] == 'seoul-plan-renewal' for row in rows) else [])


def fetch_seoul(*, opener=urlopen, sleep=time.sleep, source_id="seoul-plan-renewal"):
    """Official HTTPS JSON download, checked against the portal's total count.

    The keyed API only documents HTTP:8088. Use the documented public export
    instead; no key crosses an unencrypted connection. Three bounded retries,
    300ms between requests, all rows validated before atomic promotion.
    """
    exports = {
        'seoul-plan-renewal': ('OA-23112', '0', 'BASIC_INFO_SEQ%20DESC'),
        'seoul-apartment-points': ('OA-15818', '1', 'SN'),
    }
    if source_id not in exports or not allowed(source_id):
        raise SourceError('이용조건 확인이 필요해요.')
    inf_id, kind, order = exports[source_id]
    params = f'srvType=S&infId={inf_id}&serviceKind={kind}&pageNo=1&ssUserId=SAMPLE_VIEW&strWhere=&strOrderby={order}'.encode()
    def read_response(url):
        try:
            with opener(Request(url, data=params), timeout=20) as response:
                return response.read().decode('utf-8-sig')
        except URLError as exc:
            if not isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise
            # Some official chains fail Python 3.14's strict AKI check. Try the
            # platform's independently verified TLS client, never disable TLS
            # validation or fall back to HTTP. Both URLs are fixed above/below.
            response = subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', '20',
                                       '--request', 'POST', '--data', params.decode(), url],
                                      capture_output=True, timeout=25, check=True)
            return response.stdout.decode('utf-8-sig')
    def request(url, *, count_only=False):
        for attempt in range(3):
            try:
                raw = read_response(url)
                if count_only:
                    match = re.match(r'\s*\{result:"ok",page:\s*\{pageNo:\d+,\s*pageCount:\s*\d+,\s*totalCount:\s*(\d+),', raw)
                    if not match:
                        raise ValueError("invalid official count header")
                    return int(match[1])
                return json.loads(raw)
            except (HTTPError, URLError, OSError, ValueError, subprocess.SubprocessError):
                LOG.warning('living area source=%s attempt=%s failed', source_id, attempt + 1)
                if attempt == 2:
                    raise SourceError('서울 공식 파일을 받지 못했어요. 기존 자료를 유지합니다.') from None
                sleep(2 ** attempt)
    payload = request('https://datafile.seoul.go.kr/bigfile/iot/sheet/json/download.do')
    sleep(.3)
    total = request('https://data.seoul.go.kr/dataList/dataView.do?onepagerow=1000', count_only=True)
    rows = payload.get('DATA') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or total is None or len(rows) != total or not payload.get('DESCRIPTION'):
        raise SourceError('공식 총건수와 받은 자료가 달라 저장을 보류했어요.')
    return rows


@lru_cache(maxsize=4)
def _read_bundle(path, modified):
    return json.loads(Path(path).read_text())


def bundled_projects():
    if not BUNDLED_PATH.exists() or not allowed('seoul-plan-renewal'):
        return []
    bundle = _read_bundle(str(BUNDLED_PATH), BUNDLED_PATH.stat().st_mtime_ns)
    if bundle['totalCount'] != len(bundle['rows']) or digest(bundle['rows']) != bundle['rawHash']:
        raise SourceError('기본 원본 파일의 무결성을 확인할 수 없어요.')
    return [normalize('seoul-plan-renewal', raw, as_of=bundle['asOfDate'],
                      collected_at=bundle['collectedAt'], snapshot_id=bundle['rawHash']) for raw in bundle['rows']]


def read_export(path):
    content = Path(path).read_bytes()
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp949')
    if Path(path).suffix.lower() == '.csv':
        return list(csv.DictReader(io.StringIO(text)))
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload.get('DATA'), list) and payload.get('DESCRIPTION'):
        return payload['DATA']
    body = payload.get(SEOUL_SERVICE, {})
    rows = body.get('row', [])
    if body.get('list_total_count') != len(rows):
        raise SourceError('샘플·일부 페이지는 운영 자료로 등록할 수 없어요.')
    return rows


def revision():
    path = Path(DB_PATH)
    context_paths = [config.ROOT / 'data' / name for name in (
        'living_area_apartment_points.json', 'living_area_official_context.json',
        'living_area_reference_points.json', 'living_area_map_references.json',
        'living_area_metro_catalog.json', 'planned_rail_metro.json', 'rail_station_mapping.json', 'rail_impact_policy.json',
        'project_official_links.json', 'living_area_seoul_snapshot.json',
        'capital_transport_plan_inventory.json', 'capital_transport_transfer_2026.json',
        'capital_transport_brt_2026.json', 'capital_transport_road_projects.json', 'redevelopment_zones.geojson',
        'redevelopment_project_scales.json', 'redevelopment_occupancy_overrides.json', 'map_zone_stage_codes.json')]
    context_paths.extend(config.ROOT / 'pipeline' / name for name in (
        'living_area_context.py', 'living_area_metro.py', 'living_area_plan_rating.py', 'living_area_rail_policy.py',
        'project_official_links.py',
        'capital_transport.py', 'planned_rail.py', 'rail_station_mapping.py', 'map_zone_policy.py', 'map_zone_stage.py',
        'living_area_map.py', 'living_area_reference_points.py', 'redevelopment_occupancy.py', 'redevelopment_completion.py'))
    context_paths.append(config.ROOT / 'pipeline/cache/living_area_audited_centers.json')
    return digest({'registry': REGISTRY, 'bundle': BUNDLED_PATH.stat().st_mtime_ns if BUNDLED_PATH.exists() else None, 'store': path.stat().st_mtime_ns if path.exists() else None,
                   'context': {p.name: p.stat().st_mtime_ns if p.exists() else None for p in context_paths}})
