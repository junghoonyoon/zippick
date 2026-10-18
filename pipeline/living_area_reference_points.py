"""Reviewed address references; never verified direct benefit or walking routes.

Runs after strict evaluation. Full lot identities and provider responses must
agree; geocoding cannot establish an entrance, boundary, or measured metric.
"""
import config
import living_area_sources as sources
from living_area_context import read, recent

PATH = config.ROOT / 'data/living_area_reference_points.json'


def point_for(target, records, day, *, subject=False):
    from living_area import distance
    matches = []
    for record in records:
        binding = record.get('identity', {})
        if not all(target.get(k) and target.get(k) == binding.get(k) for k in ('district','legalDong','jibun')):
            continue
        if subject and target.get('apartmentId') != binding.get('apartmentId'):
            continue
        if not subject and target.get('id') != binding.get('projectId'):
            continue
        raw = record.get('rawAddress', {})
        lot = str(raw.get('main_address_no') or '')
        if raw.get('sub_address_no'):
            lot += '-' + str(raw['sub_address_no'])
        district = str(raw.get('region_2depth_name') or '').replace('시 ', '')
        if (record.get('provider') != 'kakao_local' or record.get('coordinateBasis') != 'address_geocode'
                or not recent(record.get('checkedAt'), day) or raw.get('region_1depth_name') != '경기'
                or district != binding['district'] or raw.get('region_3depth_name') != binding['legalDong']
                or lot != binding['jibun'] or raw.get('mountain_yn') != 'N'):
            continue
        try:
            if float(raw['y']) != record['latitude'] or float(raw['x']) != record['longitude']:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if distance(record, record) is not None:
            matches.append(record)
    return matches[0] if len(matches) == 1 else None


def attach(result, identity, projects, day):
    from living_area import distance
    if not PATH.exists() or result.get('apartmentId') != identity.get('apartmentId'):
        return result
    bundle = read(PATH)
    records = bundle.get('points', [])
    if sources.digest(records) != bundle.get('pointsDigest'):
        raise ValueError('reference points integrity')
    center = point_for(identity, records, day, subject=True)
    if not center:
        return result
    # Never overwrite an official measurement center with a geocoded address.
    result['mapCenter'] = {k:center[k] for k in ('latitude','longitude','coordinateBasis','checkedAt','sourceUrl')}
    references = {p['id']:p for p in result.get('referenceProjects', [])}
    scored_ids = {p['id'] for p in result.get('projects', [])}
    used = set()
    for project in projects:
        if (project['id'] in scored_ids or not sources.allowed(project.get('sourceId'), day=day)
                or not project.get('sourceRecordId') or not project.get('snapshotId')
                or not recent(project.get('sourceDate'), day)):
            continue
        if all(project.get(k) == identity.get(v) for k,v in (
                ('region','district'),('legalDong','legalDong'),('jibun','jibun'))):
            references.pop(project['id'], None)
            continue
        point = point_for({**project, 'district':project.get('region')}, records, day)
        meters = distance(center, point) if point else None
        if meters is None or meters > 2000:
            continue
        source = sources.REGISTRY[project['sourceId']]
        references[project['id']] = {
            **{k:v for k,v in project.items() if k not in ('geometry','raw','rawExcerpt')},
            'latitude':point['latitude'], 'longitude':point['longitude'], 'geometryType':'point',
            'coordinateBasis':'address_geocode', 'distanceMeters':round(meters),
            'distanceMethod':'address_point_straight_line', 'distanceLabel':'주소 대표점 직선거리',
            'positionLabel':'공식 발표 주소의 카카오 대표점 · 구역 경계·출입구 아님',
            'coordinateSourceUrl':point['sourceUrl'], 'coordinateCheckedAt':point['checkedAt'],
            'walkingMeters':None, 'walkingMinutes':None, 'benefitClass':'unverified',
            'benefitLabel':'직접 수혜 미확인', 'scopeLabel':'주변 정비계획 · 주소 위치 확인',
            'confidence':'address_reference', 'sourceUrl':source['url'],
            'licenseUrl':source['licenseUrl'], 'licenseVerifiedAt':source['verifiedAt'],
        }
        used.add(project['sourceId'])
    result['referenceProjects'] = list(references.values())
    existing = {s['id'] for s in result['sources']}
    result['sources'] += [{'id':key, **sources.REGISTRY[key]} for key in sorted(used-existing)]
    if used:
        result['sourceAsOf'] = min(p['sourceDate'] for p in references.values())
    result['snapshotId'] = sources.digest({'strict':result.get('snapshotId'), 'references':list(references.values()),
                                           'mapCenter':result['mapCenter'], 'pointsDigest':bundle['pointsDigest']})
    return result
