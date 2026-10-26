"""Per-complex evidence -> spatial matching -> beta score -> shared web/PDF JSON.

An unlicensed legacy dossier never becomes licensed by being copied here.
Coordinates and derived observations require their own traceable evidence.
"""
import datetime as dt
import json
import logging
import math
import sqlite3
from pathlib import Path

import living_area_sources as sources
import living_area_scoring_policy as policy

LOG = logging.getLogger(__name__)
BENEFIT_LABELS = {'direct': '직접', 'conditional': '조건부', 'indirect': '간접', 'unverified': '미검증'}


def distance(a, b):
    for p in (a, b):
        if any(not policy.number(p.get(k)) or not lo <= p[k] <= hi
               for k, lo, hi in [('latitude', 32, 39), ('longitude', 124, 132)]):
            return None
    lat1, lat2 = map(math.radians, [a['latitude'], b['latitude']])
    dlon = math.radians(b['longitude'] - a['longitude'])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def evidence_valid(evidence, day):
    return (isinstance(evidence, dict) and sources.allowed(evidence.get('sourceId'), day=day)
            and bool(evidence.get('sourceRecordId')) and bool(evidence.get('snapshotId'))
            and isinstance(evidence.get('raw'), dict) and bool(evidence['raw'])
            and evidence.get('verificationStatus') == 'verified'
            and sources.date(evidence.get('asOfDate')) is not None
            and 0 <= (day - sources.date(evidence['asOfDate'])).days <= policy.MAX_AGE_DAYS
            and sources.date(evidence.get('collectedAt', '')[:10]) is not None
            and sources.date(evidence['asOfDate']) <= sources.date(evidence['collectedAt'][:10]) <= day)


def cited(value, evidence, day):
    ids = value.get('evidenceIds', [])
    return isinstance(ids, list) and bool(ids) and all(evidence_valid(evidence.get(i), day) for i in ids)


def point_valid(point, evidence, day):
    return (isinstance(point, dict) and point.get('verificationStatus') == 'verified'
            and point.get('geometryType') == 'point' and point.get('coordinateBasis') == 'official_point'
            and distance(point, point) is not None and cited(point, evidence, day)
            and all(sources.REGISTRY[evidence[i]['sourceId']].get('pointAllowed') is True for i in point['evidenceIds'])
            and any(evidence[i]['raw'].get('latitude') == point['latitude']
                    and evidence[i]['raw'].get('longitude') == point['longitude'] for i in point['evidenceIds']))


def deduplicate(projects):
    """Same source PK collapses. Exact address/name/type merges only if facts agree.

    Ambiguous collisions are held for review, never counted twice or resolved by
    a name-only guess. Different legal dong or lot numbers remain separate.
    """
    unique, seen = [], {}
    for original in projects:
        p = dict(original)
        p['sourceRecords'] = [{'sourceId': p.get('sourceId'), 'sourceRecordId': p.get('sourceRecordId'),
                               'snapshotId': p.get('snapshotId')}]
        pk = (p.get('sourceId'), p.get('sourceRecordId'))
        address_key = (p.get('region'), p.get('legalDong'), p.get('jibun'), p.get('name'), p.get('projectType'))
        key = ('address', *address_key) if all(address_key) else ('pk', *pk)
        existing = seen.get(('pk', *pk)) or seen.get(key)
        if existing:
            fields = ('stage', 'plannedHouseholds', 'latitude', 'longitude')
            if any(existing.get(f) != p.get(f) for f in fields):
                existing['reviewRequired'] = True
            existing['evidenceIds'] = sorted(set(existing.get('evidenceIds', []) + p.get('evidenceIds', [])))
            for record in p['sourceRecords']:
                if record not in existing['sourceRecords']:
                    existing['sourceRecords'].append(record)
            continue
        unique.append(p)
        seen[key] = seen[('pk', *pk)] = p
    return unique


def project_impact(project, center, observation, evidence, day):
    p = dict(project)
    # Unknown planned station entrances must not inherit a line/area centroid.
    located = (point_valid(p, evidence, day) and point_valid(center, evidence, day)
               and (p.get('projectType') != 'transport' or p.get('stationEntranceVerified') is True))
    meters = distance(center, p) if located else None
    route = (observation or {}).get('projectRoutes', {}).get(p['id'], {})
    route_ok = (cited(route, evidence, day) and route.get('barriersReviewed') is True
                and type(route.get('connected')) is bool and policy.number(route.get('walkingMeters'))
                and route['walkingMeters'] >= 0 and meters is not None and route['walkingMeters'] >= meters * .95)
    broad = route_ok and route.get('regionalConnectionVerified') is True and route.get('connected') is True
    active = p.get('stage') in policy.STAGES and not p.get('reviewRequired')
    if meters is None or not active or (meters > policy.NEAR_M and not broad):
        benefit = 'unverified'
    elif meters <= policy.CORE_M and route_ok and route['connected'] and route.get('expectedBenefitVerified') is True and route['walkingMeters'] <= 1200:
        benefit = 'direct'
    elif meters <= policy.NEAR_M:
        benefit = 'conditional'
    else:
        benefit = 'indirect'
    positives = list(p.get('positiveFactors', []))
    negatives = list(p.get('negativeFactors', []))
    if benefit == 'direct':
        positives.append('사업지까지 이어지는 보행 경로를 확인했어요.')
    elif benefit == 'conditional':
        positives.append('가까운 사업 후보예요. 실제 생활 동선은 더 확인해야 해요.')
    if p.get('plannedHouseholds'):
        negatives.append('새집 공급 계획이 있어 주변 신축과의 경쟁을 살펴야 해요. 확정 입주 물량은 아니에요.')
    if p.get('stage') == 'construction':
        negatives.append('공사 중이에요. 소음과 우회 동선은 현장에서 확인해야 해요.')
    if active:
        negatives.append('사업이 지연되거나 계획이 바뀔 수 있어요.')
    p.update(distanceMeters=policy.rounded(meters, 0) if meters is not None else None,
             distanceMethod='representative_point_straight_line' if meters is not None else None,
             distanceLabel='대표점 직선거리' if meters is not None else '거리 미확인',
             walkingMeters=route.get('walkingMeters') if route_ok else None,
             walkingMinutes=route.get('walkingMinutes') if route_ok and policy.number(route.get('walkingMinutes')) and route['walkingMinutes'] >= 0 else None,
             benefitClass=benefit, benefitLabel=BENEFIT_LABELS[benefit],
             confidence='verified_route' if benefit == 'direct' else 'limited',
             positiveFactors=positives, negativeFactors=negatives,
             distanceFactor=policy.distance_decay(meters),
             stageCoefficient=policy.STAGES.get(p.get('stage')),
             spatialCandidate=meters is not None and meters <= policy.MAX_M and (meters <= policy.NEAR_M or broad))
    # Never pass boundary geometry, raw provider responses, or unverified points to a renderer.
    safe = {k: v for k, v in p.items() if k not in ('geometry', 'raw', 'rawExcerpt', 'latitude', 'longitude')}
    if located:
        safe.update(latitude=p['latitude'], longitude=p['longitude'], geometryType='point')
    return safe


def empty_report(apartment_id, day, reason=None):
    values = {k: None for k in [*policy.REGIONAL, *policy.DIRECT]}
    failed = bool(reason)
    return {'apartmentId': apartment_id, 'modelVersion': policy.VERSION, 'beta': True,
            'asOfDate': day.isoformat(), 'sourceAsOf': None,
            'status': 'error' if failed else 'insufficient_data',
            'confidence': 'insufficient', **policy.aggregate(values), 'projects': [], 'referenceProjects': [],
            'sources': [], 'metrics': [], 'missingMetrics': list(values),
            'headline': '생활권 자료를 불러오지 못했어요.' if failed else '이 단지의 생활권 변화는 아직 평가할 자료가 부족해요.',
            'limitations': [reason] if reason else ['확인된 위치·보행 경로·새집 공급 자료가 더 필요해요.'],
            'findings': ['직접 개선: 단지에서 사업지까지 연결되는 길을 확인해야 해요.',
                         '교통 변화: 공식 역 출입구와 이동시간을 확인해야 해요.',
                         '공급 경쟁: 예정 공급과 주변 수요를 함께 확인해야 해요.',
                         '일정 위험: 사업 일정은 바뀔 수 있어요.'],
            'judgment': {'shortTerm': '자료를 불러오지 못해 평가하지 않았어요.' if failed else '공사 불편과 새집 공급의 영향을 확인하기 전에는 판단을 보류해요.',
                         'longTerm': '확인된 사업도 이 단지의 직접 수혜나 가격 상승을 보장하지 않아요.'},
            'disclaimer': '베타 점수는 생활환경 변화의 참고값이에요. 가격 상승률을 예측하지 않아요.'}


def evaluate(identity, projects, observation=None, *, day=None):
    day = day or dt.date.today()
    apartment_id = identity.get('apartmentId', '')
    result = empty_report(apartment_id, day)
    observation = observation or {}
    if observation and (not apartment_id or observation.get('apartmentId') != apartment_id
                        or any(observation.get('identity', {}).get(k) != identity.get(k) for k in ('district', 'legalDong', 'jibun'))):
        result['limitations'] = ['저장된 분석과 단지 주소가 달라 평가를 보류했어요.']
        return result
    evidence = observation.get('evidence', {})
    center = observation.get('center', {})
    # Source-provided project attributes and separately reviewed spatial observations stay distinct.
    overrides = observation.get('projectLocations', {})
    safe_projects = []
    for p in projects:
        if (p.get('region') != identity.get('district') and p['id'] not in overrides
                and not point_valid(p, evidence, day)):
            continue
        if not sources.allowed(p.get('sourceId'), day=day) or not p.get('sourceRecordId') or not p.get('snapshotId'):
            continue
        observed = sources.date(p.get('sourceDate'))
        if not observed or not 0 <= (day-observed).days <= policy.MAX_AGE_DAYS:
            continue
        source = sources.REGISTRY[p['sourceId']]
        p = {**p, 'sourceUrl': source['url'], 'licenseUrl': source['licenseUrl'], 'licenseVerifiedAt': source['verifiedAt']}
        location = overrides.get(p['id'], {})
        if point_valid(location, evidence, day):
            p.update({k: location[k] for k in ('latitude', 'longitude', 'geometryType', 'coordinateBasis', 'verificationStatus', 'evidenceIds')})
        safe_projects.append(p)
    impacts = [project_impact(p, center, observation, evidence, day) for p in deduplicate(safe_projects)]
    local = [p for p in impacts if p['spatialCandidate'] and p['benefitClass'] != 'unverified']
    rank = {'direct': 0, 'conditional': 1, 'indirect': 2}
    local.sort(key=lambda p: (rank[p['benefitClass']], p['distanceMeters'], p['id']))
    references = [p for p in impacts if p not in local and p.get('region') == identity.get('district')
                  and (p.get('regionalReference') is True or
                       (p.get('legalDong') and p.get('legalDong') == identity.get('legalDong')))]
    result.update(projects=local, referenceProjects=references)
    values = {k: None for k in [*policy.REGIONAL, *policy.DIRECT]}
    audits = {}
    center_ok = point_valid(center, evidence, day)
    if center_ok:
        result['center'] = {k: center[k] for k in ('latitude', 'longitude', 'geometryType', 'evidenceIds')}
    measurements = observation.get('measurements', {})
    for key, measurement in measurements.items():
        if key not in values or key in ('project_feasibility', 'accessibility', 'execution'):
            continue
        if (center_ok and measurement.get('method') == 'observed_inputs_v2'
                and measurement.get('verificationStatus') == 'verified' and cited(measurement, evidence, day)
                and measurement.get('scope') == {'apartmentId': apartment_id, 'radiusMeters': policy.NEAR_M}
                and isinstance(measurement.get('inputs'), dict)):
            if key in ('new_build_belt', 'transport_improvement', 'amenity_improvement'):
                effective = sources.date(measurement.get('effectiveDate'))
                if not effective or not day <= effective <= day + dt.timedelta(days=5*365):
                    continue
            values[key] = policy.normalize(key, measurement['inputs'])
            audits[key] = {'inputs': measurement['inputs'], 'evidenceIds': measurement['evidenceIds'], 'method': measurement['method']}
    # Compute from matched unique projects, not counts or free-form supplied ratings.
    candidates = [p for p in local if p['stageCoefficient'] is not None]
    if candidates:
        weights = [p['distanceFactor'] for p in candidates]
        if sum(weights) > 0:
            values['project_feasibility'] = sum(p['stageCoefficient'] * w for p, w in zip(candidates, weights)) / sum(weights) * 100
            audits['project_feasibility'] = {'projectIds': [p['id'] for p in candidates], 'method': 'distance_weighted_stage_mean'}
        connected = [p for p in candidates if p['walkingMeters'] is not None and p['benefitClass'] == 'direct']
        if connected:
            values['accessibility'] = max(policy.distance_decay(p['walkingMeters']) for p in connected) * 100
            values['execution'] = sum(p['stageCoefficient'] for p in connected) / len(connected) * 100
            for key in ('accessibility', 'execution'):
                audits[key] = {'projectIds': [p['id'] for p in connected], 'method': 'best_verified_walking_access' if key == 'accessibility' else 'unique_direct_stage_mean'}
    result.update(policy.aggregate(values))
    result['metrics'] = [{'key': k, 'label': policy.LABELS[k], 'group': 'regional' if k in policy.REGIONAL else 'direct',
                          'weight': policy.REGIONAL.get(k, policy.DIRECT.get(k)),
                          'value': policy.rounded(v, 2) if v is not None else None,
                          'audit': audits.get(k), 'status': 'verified' if v is not None else 'insufficient_data'} for k, v in values.items()]
    result['missingMetrics'] = [k for k, v in values.items() if v is None]
    result['status'] = 'ready' if result['score'] is not None else 'insufficient_data'
    result['confidence'] = 'reviewed' if result['score'] is not None else 'insufficient'
    used = {p['sourceId'] for p in local + references}
    used.update(e['sourceId'] for e in evidence.values() if evidence_valid(e, day))
    result['evidence'] = {key: {k: e[k] for k in ('sourceId', 'sourceRecordId', 'snapshotId', 'asOfDate', 'collectedAt')}
                          for key, e in evidence.items() if evidence_valid(e, day)}
    result['sources'] = [{'id': key, **sources.REGISTRY[key]} for key in sorted(used)]
    dates = [p['sourceDate'] for p in local + references]
    dates += [e['asOfDate'] for e in evidence.values() if evidence_valid(e, day)]
    result['sourceAsOf'] = min(dates) if dates else None
    direct = [p for p in local if p['benefitClass'] == 'direct']
    if direct:
        result['headline'] = f'{direct[0]["name"]}까지 이어지는 길을 확인했어요. 공급 경쟁도 함께 살펴야 해요.'
        result['findings'][0] = f'직접 개선: {direct[0]["name"]}의 위치와 보행 연결을 확인했어요.'
    elif local:
        result['headline'] = '가까운 사업은 있지만, 이 단지의 직접 수혜는 조건을 더 확인해야 해요.'
    if values['transport_improvement'] is not None:
        i = measurements['transport_improvement']['inputs']
        result['findings'][1] = f'교통 변화: 확인한 경로는 {i["beforeMinutes"]}분에서 {i["afterMinutes"]}분으로 바뀌는 계획이에요.'
    if result['score'] is not None:
        result['limitations'] = ['베타 산식이며 거리 구간과 배점은 향후 실제 자료로 보정해야 해요.']
    result['snapshotId'] = sources.digest({'identity': identity, 'projects': safe_projects, 'observation': observation,
                                           'day': day.isoformat(), 'policy': policy.VERSION, 'registry': sources.REGISTRY})
    return result


def analyze(identity, *, path=None, day=None):
    day = day or dt.date.today()
    path = Path(path or sources.DB_PATH)
    try:
        observation = None
        if path.exists():
            db = sources.connection(path)
            try:
                row = db.execute('SELECT payload FROM complex_observations WHERE apartment_id=?', (identity.get('apartmentId', ''),)).fetchone()
                observation = json.loads(row[0]) if row else None
            finally:
                db.close()
        import living_area_context as context
        projects, observation = context.prepare(identity, sources.load_projects(path), observation, day)
        result = evaluate(identity, projects, observation, day=day)
        import living_area_reference_points
        result = living_area_reference_points.attach(result, identity, projects, day)
        import living_area_metro
        result = living_area_metro.attach(result, identity, day)
        result = context.describe(result, identity)
        import living_area_plan_rating
        result = living_area_plan_rating.attach(result, identity, day)
        import apartment_development
        result = apartment_development.attach(result, identity, day)
        import capital_transport
        result['capitalTransport'] = capital_transport.for_complex(identity)
        return context.conclude(result, identity)
    except (ValueError, OSError, TypeError, KeyError, sqlite3.Error) as exc:
        LOG.warning('living area unavailable: %s', type(exc).__name__)
        result = empty_report(identity.get('apartmentId', ''), day, '자료를 불러오지 못했어요. 잠시 뒤 리포트를 다시 열어 주세요.')
        result['status'] = 'error'
        try:
            import capital_transport
            result['capitalTransport'] = capital_transport.for_complex(identity)
        except (ValueError, OSError, TypeError, KeyError):
            result['capitalTransport'] = {'status': 'error', 'matchedPlans': []}
        import apartment_development
        result = apartment_development.attach(result, identity, day)
        return result
