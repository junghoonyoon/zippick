"""Evidence-gated lifestyle analysis. No network calls or guessed measurements.

Reviewed measurements are imported per exact apartment/scope. GIS must be done
upstream: this service never substitutes zone area or household counts for land.
"""
import datetime as dt
import hashlib
import json
import logging
import math
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import config
import living_area
import living_area_sources

CONFIG = json.loads((config.ROOT / 'data/future_transformation_scoring.json').read_text())
DB_PATH = config.CACHE_DIR / 'future_transformation.sqlite3'
PILOT_PATH = config.ROOT / 'data/future_transformation_pilots.json'
BUILDING_SUMMARY_PATH = config.ROOT / 'data/building_hub_pilot_summary.json'
LOG = logging.getLogger(__name__)
FUTURE_DATED_KEYS = {'new_build_belt', 'transport_improvement', 'amenity_improvement', 'accessibility', 'belt_connection', 'daily_access'}
DISCLAIMER = '공식 개발계획과 주변 환경 자료로 살펴본 생활환경 변화 가능성이에요. 매매가격 상승을 보장하지 않아요.'


def _date(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            return None
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def official_url(value):
    try:
        url = urlsplit(value or '')
        host = url.hostname or ''
        return url.scheme == 'https' and not url.username and not url.password and (host.endswith('.go.kr') or host == 'go.kr')
    except ValueError:
        return False


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _connection(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL, as_of TEXT NOT NULL, imported_at TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS revisions_apartment ON revisions(apartment_id, as_of)')
    db.execute('CREATE TABLE IF NOT EXISTS project_events (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision_id TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, apartment_id TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


def validate_document(document):
    """Reject malformed or unauditable imports before changing the store."""
    if not isinstance(document, dict) or document.get('schemaVersion') != 1:
        raise ValueError('schemaVersion must be 1')
    if document.get('scoringVersion') != CONFIG['version']:
        raise ValueError('scoringVersion mismatch')
    if not isinstance(document.get('apartmentId'), str) or not document['apartmentId'].strip():
        raise ValueError('exact apartmentId required')
    as_of = _date(document.get('asOfDate'))
    if not as_of or as_of > dt.date.today():
        raise ValueError('valid non-future asOfDate required')
    if document.get('radiusMeters') != CONFIG['radiusMeters'] or document.get('horizonYears') != CONFIG['horizonYears']:
        raise ValueError('scope does not match scoring configuration')
    sources = document.get('sources', [])
    if not isinstance(sources, list):
        raise ValueError('sources must be a list')
    ids = set()
    for source in sources:
        if not isinstance(source, dict) or not source.get('id') or source['id'] in ids:
            raise ValueError('unique source IDs required')
        ids.add(source['id'])
        if not official_url(source.get('url')):
            raise ValueError('official HTTPS source URL required')
        if source.get('verificationStatus') != 'verified' or source.get('licenseStatus') != 'reviewed':
            raise ValueError('source verification and reuse review required')
        for key in ('publisher', 'documentId', 'documentTitle'):
            if not source.get(key):
                raise ValueError(f'source {key} required')
        for key in ('publishedAt', 'observedAt', 'verifiedAt'):
            if not _date(source.get(key)) or _date(source[key]) > as_of:
                raise ValueError(f'source {key} must be known at asOfDate')
        if _date(source['publishedAt']) > _date(source['observedAt']) or _date(source['observedAt']) > _date(source['verifiedAt']):
            raise ValueError('source chronology is invalid')
    if document.get('measurements'):
        center = document.get('center') or {}
        if any(not _number(center.get(k)) or not lo <= center[k] <= hi for k, lo, hi in [('latitude', 32, 39), ('longitude', 124, 132)]):
            raise ValueError('verified analysis center required')
    keys = {m['key'] for m in CONFIG['metrics'] + CONFIG['benefits']}
    measurements = document.get('measurements', {})
    if not isinstance(measurements, dict) or set(measurements) - keys:
        raise ValueError('unknown measurement')
    for key, measurement in measurements.items():
        if measurement is None:
            continue
        if not isinstance(measurement, dict) or measurement.get('verificationStatus') != 'verified':
            raise ValueError('verified measurement required')
        if not measurement.get('method') or not measurement.get('explanation'):
            raise ValueError('measurement method and explanation required')
        evidence = measurement.get('evidenceIds')
        if not isinstance(evidence, list) or not evidence or not set(evidence) <= ids:
            raise ValueError('measurement evidence missing')
        if not isinstance(measurement.get('inputs'), dict):
            raise ValueError('raw measurement inputs required')
        inputs = measurement['inputs']
        if key in FUTURE_DATED_KEYS and not _date(measurement.get('effectiveDate')):
            raise ValueError('official effectiveDate required for future improvements')
        if key == 'housing_conversion':
            if measurement['method'] != 'gis_land_intersection':
                raise ValueError('GIS land intersection required')
            if inputs.get('center') != document.get('center'):
                raise ValueError('GIS center does not match analysis scope')
            for group in ('parcels', 'projects'):
                if not isinstance(inputs.get(group), list):
                    raise ValueError('GIS parcels and projects required')
                identifiers = set()
                for item in inputs[group]:
                    if not item.get('id') or item['id'] in identifiers:
                        raise ValueError('duplicate GIS feature ID')
                    identifiers.add(item['id'])
                    if group == 'parcels' and item.get('geometryBasis') != 'residential_land':
                        raise ValueError('land polygons required, not building floor area')
                    if group == 'projects':
                        official_project = next((p for p in document.get('projects', []) if p.get('id') == item['id']), None)
                        if not official_project or any(item.get(k) != official_project.get(k) for k in ('stage', 'expectedCompletionDate', 'geometry', 'evidenceIds')):
                            raise ValueError('GIS project must match registered official project facts')
                    if not item.get('evidenceIds') or not set(item['evidenceIds']) <= set(evidence):
                        raise ValueError('GIS feature evidence required')
        else:
            if key == 'project_feasibility':
                original = {p['id']: p for p in document.get('projects', [])}
                for project in inputs.get('projects', []):
                    source_project = original.get(project.get('id'))
                    if not source_project or any(project.get(k) != source_project.get(k) for k in ('stage', 'expectedCompletionDate', 'siteAreaM2')):
                        raise ValueError('feasibility inputs must match official project facts')
                    if not set(source_project.get('evidenceIds', [])) <= set(evidence):
                        raise ValueError('feasibility must cite all project evidence')
                    if _distance(document['center'], source_project) is None or _distance(document['center'], source_project) > CONFIG['radiusMeters']:
                        raise ValueError('feasibility project location is outside or unverified')
            if measurement['method'] != 'raw_inputs_v1':
                raise ValueError('raw_inputs_v1 method required')
            # Missing or invalid raw inputs are rejected at import, not filled with zero.
            if measurement_ratio(key, inputs) is None:
                raise ValueError('invalid or incomplete raw inputs: ' + key)
    project_ids = set()
    for project in document.get('projects', []):
        if not project.get('id') or project['id'] in project_ids or not project.get('name'):
            raise ValueError('unique project ID and name required')
        project_ids.add(project['id'])
        if not project.get('evidenceIds') or not set(project['evidenceIds']) <= ids:
            raise ValueError('project evidence required')
        for key, low, high in (('latitude', 32, 39), ('longitude', 124, 132)):
            if project.get(key) is not None and (not _number(project[key]) or not low <= project[key] <= high):
                raise ValueError('invalid project coordinates')
        if project.get('stage') not in {*CONFIG['stageWeights'], 'completed', 'cancelled', 'unknown'}:
            raise ValueError('invalid project stage')
        if project.get('expectedCompletionDate') and not _date(project['expectedCompletionDate']):
            raise ValueError('invalid completion date')
        if project.get('actualCompletionDate'):
            if project['stage'] != 'completed' or not _date(project['actualCompletionDate']) or _date(project['actualCompletionDate']) > as_of:
                raise ValueError('actual completion date must be past and completed')
    corrections = document.get('factCorrections', [])
    if not isinstance(corrections, list):
        raise ValueError('factCorrections must be a list')
    correction_ids = set()
    for correction in corrections:
        if not isinstance(correction, dict) or correction.get('projectId') not in project_ids or correction['projectId'] in correction_ids:
            raise ValueError('fact correction must identify one registered project')
        correction_ids.add(correction['projectId'])
        if not isinstance(correction.get('reason'), str) or len(correction['reason'].strip()) < 20:
            raise ValueError('fact correction reason required')
        evidence = correction.get('evidenceIds')
        project = next(p for p in document['projects'] if p['id'] == correction['projectId'])
        if not isinstance(evidence, list) or not evidence or not set(evidence) <= ids or not set(evidence) <= set(project['evidenceIds']):
            raise ValueError('fact correction must cite project evidence')
    _hash(document)  # reject NaN/Infinity even in ancillary fields
    return document


def import_document(document, *, path=None, known_apartment_ids=None):
    validate_document(document)
    if known_apartment_ids is None:
        entity = registry_entity(document['apartmentId'])
        if not entity or not supported(entity):
            raise ValueError('exact apartment must belong to a pilot region')
        known_apartment_ids = {document['apartmentId']}
        identity = document.get('identity') or {}
        if any(identity.get(k) != entity.get(k) for k in ('district', 'legalDong', 'jibun')):
            raise ValueError('apartment identity/address mismatch')
    if document['apartmentId'] not in known_apartment_ids:
        raise ValueError('apartmentId is not in the existing apartment registry')
    if known_apartment_ids is not None and not document['apartmentId']:
        raise ValueError('exact ID required')
    revision = _hash(document)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    db = _connection(path or DB_PATH)
    try:
        with db:
            # Preserve old records but never make an older effective date current.
            latest = db.execute('SELECT as_of, payload FROM revisions WHERE apartment_id=? ORDER BY as_of DESC, imported_at DESC LIMIT 1', (document['apartmentId'],)).fetchone()
            if latest and document['asOfDate'] < latest[0]:
                raise ValueError('older observations cannot replace the current revision')
            if latest:
                previous_document = json.loads(latest[1])
                old_projects = {p['id']: p for p in previous_document.get('projects', [])}
                previous_sources = {s['id']: s for s in previous_document.get('sources', [])}
                current_sources = {s['id']: s for s in document.get('sources', [])}
                corrections = {c['projectId']: c for c in document.get('factCorrections', [])}
                for project in document.get('projects', []):
                    old_project = old_projects.get(project['id'])
                    if old_project and any(project.get(k) != old_project.get(k) for k in ('stage', 'expectedCompletionDate', 'plannedHouseholds')):
                        old_date = max(previous_sources[k]['publishedAt'] for k in old_project['evidenceIds'])
                        new_date = max(current_sources[k]['publishedAt'] for k in project['evidenceIds'])
                        if new_date <= old_date:
                            correction = corrections.get(project['id'])
                            old_urls = {previous_sources[k]['url'] for k in old_project['evidenceIds']}
                            correction_urls = {current_sources[k]['url'] for k in correction['evidenceIds']} if correction else set()
                            if not correction_urls - old_urls:
                                raise ValueError('conflicting project facts require a newer official source or a cited correction')
                old_sources = {s['id']: s for s in json.loads(latest[1]).get('sources', [])}
                for source in document.get('sources', []):
                    old = old_sources.get(source['id'])
                    if old and (_date(source['publishedAt']) < _date(old['publishedAt']) or _date(source['verifiedAt']) < _date(old['verifiedAt'])):
                        raise ValueError('older source cannot replace newer source')
            db.execute('INSERT OR IGNORE INTO revisions VALUES (?, ?, ?, ?, ?)', (revision, document['apartmentId'], document['asOfDate'], now, json.dumps(document, ensure_ascii=False)))
            for project in document.get('projects', []):
                event = {'project': project, 'sources': document['sources'], 'asOfDate': document['asOfDate']}
                db.execute('INSERT OR IGNORE INTO project_events VALUES (?, ?, ?, ?)', (_hash(event), project['id'], revision, json.dumps(event, ensure_ascii=False)))
    finally:
        db.close()
    LOG.info('future transformation import apartment_id=%s revision=%s', document['apartmentId'], revision)
    return revision


def _horizon(day):
    try:
        return day.replace(year=day.year + CONFIG['horizonYears'])
    except ValueError:
        return day.replace(year=day.year + CONFIG['horizonYears'], day=28)


def measurement_ratio(key, inputs):
    def values(*names):
        result = [inputs.get(name) for name in names]
        return result if all(_number(v) and v >= 0 for v in result) else None
    ratio = None
    if key == 'new_build_belt':
        numbers = values('beforeConnectedLengthM', 'afterConnectedLengthM', 'eligibleNetworkLengthM')
        if numbers and numbers[2] > 0 and max(numbers[:2]) <= numbers[2]:
            ratio = (numbers[1] - numbers[0]) / numbers[2]
    elif key in ('transport_improvement', 'daily_access'):
        numbers = values('beforeMinutes', 'afterMinutes')
        if numbers and numbers[0] > 0 and inputs.get('routeVerified') is True:
            ratio = (numbers[0] - numbers[1]) / CONFIG['fullTransportSavingMinutes' if key == 'transport_improvement' else 'fullWalkingSavingMinutes']
    elif key == 'amenity_improvement':
        numbers = values('beforeAccessibleFacilities', 'afterAccessibleFacilities', 'plannedFacilities')
        if numbers and numbers[2] > 0 and inputs.get('openingScheduleVerified') is True:
            ratio = (numbers[1] - numbers[0]) / numbers[2]
    elif key == 'project_feasibility':
        projects = inputs.get('projects', [])
        if not projects and inputs.get('scopeSurveyComplete') is True:
            return 0.0
        if projects and all(p.get('stage') in CONFIG['stageWeights'] and _number(p.get('siteAreaM2')) and p['siteAreaM2'] > 0
                            and _date(p.get('expectedCompletionDate')) for p in projects):
            ratio = sum(p['siteAreaM2'] * CONFIG['stageWeights'][p['stage']] for p in projects) / sum(p['siteAreaM2'] for p in projects) / CONFIG['feasibilityFullWeight']
    elif key == 'supply_demand_stability':
        numbers = values('plannedHouseholds', 'existingHouseholds', 'annualAbsorptionHouseholds')
        if numbers and numbers[1] > 0 and all(_number(inputs.get(k)) for k in ('transactionChangePct', 'rentChangePct')):
            excess = max(0, numbers[0] - CONFIG['horizonYears'] * numbers[2]) / numbers[1]
            # Negative observed market trends increase the burden, never improve the score.
            trend = max(0, -inputs['transactionChangePct']) / 100 + max(0, -inputs['rentChangePct']) / 100
            ratio = 1 - excess / CONFIG['supplyExcessRatio'] - trend
    elif key == 'accessibility':
        numbers = values('distanceMeters')
        if numbers and inputs.get('distanceBasis') in ('walking', 'straight_line'):
            ratio = 1 - numbers[0] / CONFIG['maxWalkingDistanceMeters']
    elif key == 'belt_connection':
        numbers = values('connectedRoutes', 'assessedRoutes')
        if numbers and numbers[1] > 0 and numbers[0] <= numbers[1] and inputs.get('barriersReviewed') is True:
            ratio = numbers[0] / numbers[1]
    elif key == 'negative_impact':
        numbers = values('noiseExposure', 'routeDisruption', 'supplyConcentration')
        if numbers and max(numbers) <= 1:
            ratio = 1 - sum(numbers) / len(numbers)
    return max(0, min(1, ratio)) if ratio is not None else None


def housing_conversion(measurement, as_of):
    from future_transformation_spatial import conversion
    inputs = {**measurement['inputs'], 'oldBuildingYears': CONFIG['oldBuildingYears']}
    ratio, audit = conversion(inputs, as_of, _horizon(as_of), CONFIG['stageWeights'], CONFIG['radiusMeters'])
    return (min(1, ratio / CONFIG['conversionFullRatio']) if ratio is not None else None), audit


def apartment_key(entity):
    if entity.get('apartmentId'):
        return str(entity['apartmentId'])
    if not entity.get('dedupeKey'):
        return ''
    # Reuse the existing leader API's ID. Never manufacture a new apartment entity.
    import apartment_leaders
    return apartment_leaders._entity_id(entity)


def registry_entity(apartment_id):
    import real_estate_search
    matches = [e for e in real_estate_search._search_entities() if apartment_key(e) == apartment_id]
    identities = {(e.get('province'), e.get('district'), e.get('legalDong'), e.get('jibun')) for e in matches}
    return matches[0] if len(identities) == 1 else None


def supported(entity):
    district = entity.get('district') or entity.get('region') or ''
    return district in ('성남수정구', '성남중원구') or (district in ('동대문구', '서울특별시 동대문구') and entity.get('legalDong') in ('이문동', '휘경동'))


def building_register_evidence(apartment_id, entity, *, path=None):
    """Return checked dong-wide building facts only for the exact pilot apartment."""
    summary_path = Path(path or BUILDING_SUMMARY_PATH)
    if not apartment_id or not summary_path.exists():
        return None
    try:
        entries = json.loads(summary_path.read_text())
        entry = next((item for item in entries if item.get('apartmentId') == apartment_id), None)
        if not entry or any(entry.get('identity', {}).get(key) != entity.get(key)
                            for key in ('district', 'legalDong', 'jibun')):
            return None
        areas = entry.get('areas') or []
        if not areas or any(not isinstance(area.get('recordCount'), int)
                            or area['recordCount'] < 0 or not _date(area.get('fetchedAt'))
                            or len(str(area.get('dongCode', ''))) != 10
                            or not area.get('legalDong') for area in areas):
            return None
        for area in areas:
            keys = ('residentialRecordCount', 'approvalDateCount', 'age30RecordCount', 'age30SharePct')
            if not any(key in area for key in keys):
                continue  # Older exports still show their verified total count.
            residential = area.get('residentialRecordCount')
            dated = area.get('approvalDateCount')
            old = area.get('age30RecordCount')
            share = area.get('age30SharePct')
            if (any(type(value) is not int for value in (residential, dated, old))
                    or not 0 <= old <= dated <= residential <= area['recordCount']
                    or share != (round(old / dated * 100, 1) if dated else None)):
                return None
        if not official_url(entry.get('sourceUrl')):
            return None
        return {'scope': 'legal_dong', 'source': entry.get('source'),
                'sourceUrl': entry['sourceUrl'], 'areas': areas}
    except (OSError, ValueError, TypeError, AttributeError):
        LOG.warning('invalid building HUB report summary for apartment_id=%s', apartment_id)
        return None


def evaluate(apartment_id, document=None, *, as_of=None, scores_enabled=True):
    """Deterministic result; zero is evidence, None is unknown, stale is withheld."""
    day = as_of or dt.date.today()
    if isinstance(day, str):
        day = _date(day)
    if not day:
        raise ValueError('invalid analysis date')
    if document:
        validate_document(document)
        if document['apartmentId'] != apartment_id or _date(document['asOfDate']) > day:
            raise ValueError('apartment or analysis date mismatch')
    document = document or {}
    sources = {s['id']: s for s in document.get('sources', [])}
    measurements = document.get('measurements', {})
    rows = []
    for spec in CONFIG['metrics'] + CONFIG['benefits']:
        row = {**spec, 'score': None, 'status': 'not_available', 'evidenceIds': [], 'explanation': spec['missing']}
        measurement = measurements.get(spec['key'])
        if measurement and scores_enabled:
            evidence = [sources[sid] for sid in measurement['evidenceIds']]
            stale = any((day - _date(s['verifiedAt'])).days > CONFIG['staleDays']['measurement'] for s in evidence)
            row.update(evidenceIds=measurement['evidenceIds'], explanation=measurement['explanation'], method=measurement['method'])
            if spec['key'] in FUTURE_DATED_KEYS and not day <= _date(measurement['effectiveDate']) <= _horizon(day):
                row['explanation'] = '공식 예정 시점이 이번 평가 기간에 들어오지 않아 계산하지 않았어요.'
            elif stale:
                row['status'] = 'stale'
                row['explanation'] = '자료 갱신 확인이 필요해요. ' + row['explanation']
            else:
                ratio = measurement_ratio(spec['key'], measurement['inputs'])
                if spec['key'] == 'housing_conversion':
                    ratio, row['calculation'] = housing_conversion(measurement, day)
                    if ratio is None:
                        row['explanation'] = row['calculation'].get('reason', spec['missing'])
                elif spec['key'] == 'project_feasibility':
                    projects = measurement['inputs'].get('projects', [])
                    if any(not day <= _date(p['expectedCompletionDate']) <= _horizon(day) for p in projects):
                        ratio = None
                if spec['key'] == 'accessibility' and measurement['inputs'].get('distanceBasis') == 'straight_line':
                    row['explanation'] += ' 직선거리 기준이며 실제 도보 경로는 미확인이에요.'
                if ratio is not None:
                    row.update(score=round(spec['weight'] * ratio, 2), status='verified')
        rows.append(row)
    metrics, benefits = rows[:6], rows[6:]
    region, benefit, total = aggregate_scores(metrics, benefits)
    ready = total is not None
    stale = any(r['status'] == 'stale' for r in rows)
    coverage = sum(r['weight'] * CONFIG['regionWeight'] for r in metrics if r['score'] is not None) + sum(r['weight'] * CONFIG['benefitWeight'] for r in benefits if r['score'] is not None)
    status = 'ready' if ready else 'stale' if stale else 'partial' if coverage or document.get('projects') else 'insufficient_data'
    return {
        'apartmentId': apartment_id, 'asOfDate': day.isoformat(),
        'radiusMeters': CONFIG['radiusMeters'], 'horizonYears': CONFIG['horizonYears'],
        'scoringVersion': CONFIG['version'], 'dataVersion': _hash(document),
        'scoresEnabled': scores_enabled, 'status': status,
        'regionChangeScore': region, 'apartmentBenefitScore': benefit,
        'futureTransformationScore': total, 'coverageRatio': round(coverage / 100, 4),
        'confidence': ('limited' if measurements.get('accessibility', {}).get('inputs', {}).get('distanceBasis') == 'straight_line' else 'reviewed') if ready else 'insufficient',
        'metrics': metrics, 'benefits': benefits, 'sources': list(sources.values()),
        'projects': [], 'referenceProjects': [],
        'limitations': [] if ready else ['지역의 변화와 이 단지가 받는 영향을 모두 확인하기 전에는 전체 점수를 계산하지 않아요.'],
        'disclaimer': DISCLAIMER,
    }


def _distance(a, b):
    if any(not _number(p.get(k)) for p in (a, b) for k in ('latitude', 'longitude')):
        return None
    lat1, lat2 = math.radians(a['latitude']), math.radians(b['latitude'])
    dlat = lat2 - lat1
    dlng = math.radians(b['longitude'] - a['longitude'])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return round(6371000 * 2 * math.asin(min(1, math.sqrt(value))))


def analyze(row, entity=None, *, as_of=None, path=None, scores_enabled=None):
    """Read saved evidence only. A failure must never break the main report."""
    apartment_id = apartment_key(entity or row)
    day = as_of or dt.date.today()
    if isinstance(day, str):
        day = _date(day)
    if day is None:
        raise ValueError('invalid analysis date')
    enabled = os.environ.get('ZIPPICK_FUTURE_TRANSFORMATION_SCORES', '0') == '1' if scores_enabled is None else scores_enabled
    db = None
    try:
        document = None
        store_path = Path(path or DB_PATH)
        if apartment_id and store_path.exists():
            db = _connection(store_path)
            latest = db.execute('SELECT payload FROM revisions WHERE apartment_id=? AND as_of<=? ORDER BY as_of DESC, imported_at DESC LIMIT 1', (apartment_id, day.isoformat())).fetchone()
            if latest:
                document = json.loads(latest[0])
        if document is None and apartment_id and PILOT_PATH.exists():
            pilots = json.loads(PILOT_PATH.read_text())
            document = next((d for d in pilots if d['apartmentId'] == apartment_id and _date(d['asOfDate']) <= day), None)
        coordinates = {**(entity or {}), **row}
        position_ready = _distance(coordinates, coordinates) is not None
        scope_ready = supported(entity or row)
        if document and document.get('identity') and entity:
            if any(document['identity'].get(k) != entity.get(k) for k in ('district', 'legalDong', 'jibun')):
                raise ValueError('stored identity mismatch')
        center_matches = not (document or {}).get('measurements') or (position_ready and _distance(coordinates, document.get('center') or {}) is not None and _distance(coordinates, document['center']) <= 50)
        result = evaluate(apartment_id, document, as_of=day, scores_enabled=enabled and position_ready and scope_ready and center_matches)
        if not center_matches:
            result['limitations'].append('등록된 분석 중심과 단지 위치가 달라 점수를 표시하지 않았어요.')
        if not position_ready:
            result['limitations'].append('단지 좌표가 없어 반경 안의 사업과 직접 영향을 확인하지 못했어요.')
        result['scopeSupported'] = supported(entity or row)
        result['buildingRegister'] = building_register_evidence(apartment_id, entity or row)
        if not result['scopeSupported']:
            result['limitations'].append('현재는 성남 원도심과 이문·휘경의 공식 자료를 먼저 확인하고 있어요.')
        coordinates = {**(entity or {}), **row}
        for project in (document or {}).get('projects', []):
            distance = _distance(coordinates, project)
            sources = [s for s in result['sources'] if s['id'] in project['evidenceIds']]
            primary = max(sources, key=lambda s: s['publishedAt'])
            end = _date(project.get('expectedCompletionDate'))
            phase = 'current' if project['stage'] == 'completed' else 'cancelled' if project['stage'] == 'cancelled' else 'within_horizon' if end and day <= end <= _horizon(day) else 'outside_horizon' if end and end > _horizon(day) else 'schedule_unknown'
            entry = {**project, 'distanceMeters': distance, 'distanceBasis': '직선거리', 'phase': phase,
                     'sourceUrl': primary['url'], 'sourceDate': primary['publishedAt'],
                     'verifiedAt': primary['verifiedAt'], 'stale': (day - _date(primary['verifiedAt'])).days > CONFIG['staleDays']['project']}
            result['projects' if distance is not None and distance <= CONFIG['radiusMeters'] else 'referenceProjects'].append(entry)
        if not ready_result(result) and any(p['stale'] for p in result['projects'] + result['referenceProjects']):
            result['status'] = 'stale'
        result['projects'].sort(key=lambda p: (p['phase'] != 'within_horizon', p['distanceMeters']))
        result['livingArea'] = living_area.analyze({**(entity or row), 'apartmentId': apartment_id}, day=day)
        # All versioned inputs, scope, date, configuration and coordinates affect snapshots.
        snapshot_id = _hash({'result': result, 'config': CONFIG, 'coordinates': {k: coordinates.get(k) for k in ('latitude', 'longitude')}})
        result['snapshotId'] = snapshot_id
        result['computedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
        result['expiresAt'] = (day + dt.timedelta(days=1)).isoformat()
        if document and db is None:
            db = _connection(store_path)
        if db is not None:
            with db:
                saved = db.execute('SELECT payload FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
                if saved:
                    return json.loads(saved[0])
                db.execute('INSERT INTO snapshots VALUES (?, ?, ?)', (snapshot_id, apartment_id, json.dumps(result, ensure_ascii=False)))
        LOG.info('future transformation apartment_id=%s status=%s coverage=%s snapshot=%s', apartment_id, result['status'], result['coverageRatio'], snapshot_id)
        return result
    except Exception:
        LOG.exception('future transformation failed for apartment_id=%s', apartment_id)
        result = evaluate(apartment_id, as_of=day, scores_enabled=False)
        result.update(status='error', errorReason='생활권 자료를 불러오지 못했어요. 잠시 뒤 리포트를 다시 열어 주세요.')
        result['livingArea'] = living_area.empty_report(apartment_id, day, result['errorReason'])
        result['livingArea']['status'] = 'error'
        try:
            import capital_transport
            result['livingArea']['capitalTransport'] = capital_transport.for_complex({**(entity or {}), **row})
        except (ValueError, OSError, TypeError, KeyError):
            result['livingArea']['capitalTransport'] = {'status': 'error', 'matchedPlans': []}
        return result
    finally:
        if db is not None:
            db.close()


def ready_result(result):
    return result.get('status') == 'ready'


def public_facts(result):
    """Only the licensed per-complex model is public; never revive legacy scores."""
    if result.get('livingArea'):
        return result['livingArea']
    day = _date(result.get('asOfDate')) or dt.date.today()
    public = living_area.empty_report(result.get('apartmentId', ''), day)
    if result.get('status') == 'error':
        public.update(status='error', errorReason=result.get('errorReason'))
    return public


def data_revision():
    """Ignore snapshot writes; invalidate candidate caches only for input changes."""
    revision = ''
    try:
        if DB_PATH.exists():
            db = _connection(DB_PATH)
            try:
                row = db.execute('SELECT id FROM revisions ORDER BY imported_at DESC LIMIT 1').fetchone()
                revision = row[0] if row else ''
            finally:
                db.close()
    except sqlite3.Error:
        revision = 'unavailable'
    return _hash({'revision': revision, 'config': CONFIG, 'livingArea': living_area_sources.revision(), 'livingPolicy': living_area.policy.VERSION,
                  'pilots': PILOT_PATH.read_text() if PILOT_PATH.exists() else '',
                  'buildingSummary': BUILDING_SUMMARY_PATH.read_text() if BUILDING_SUMMARY_PATH.exists() else '',
                  'enabled': os.environ.get('ZIPPICK_FUTURE_TRANSFORMATION_SCORES', '0')})


def aggregate_scores(metrics, benefits):
    def total(rows):
        return round(sum(r['score'] for r in rows), 2) if rows and all(_number(r.get('score')) and 0 <= r['score'] <= r['weight'] for r in rows) else None
    region, benefit = total(metrics), total(benefits)
    overall = math.floor(CONFIG['regionWeight'] * region + CONFIG['benefitWeight'] * benefit + 0.5) if region is not None and benefit is not None else None
    return region, benefit, overall
