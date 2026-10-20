"""Shared reviewed line/station registry for maps, ratings, and coverage copy."""
import datetime as dt
import hashlib
import json
from functools import lru_cache
import config
from living_area_rail_policy import annotate, review_context

PATH=config.ROOT/'data/rail_station_mapping.json'
PLANS=config.ROOT/'data/planned_rail_metro.json'

@lru_cache(maxsize=2)
def _read(revision, plan_revision):
    bundle=json.loads(PATH.read_text())
    plans=json.loads(PLANS.read_text())
    digest=hashlib.sha256(json.dumps(plans,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    bundle['integrityValid']=bundle.get('plansDigest')==digest
    return bundle

def load():
    return _read(PATH.stat().st_mtime_ns,PLANS.stat().st_mtime_ns) if PATH.exists() and PLANS.exists() else {}

def current(bundle,day):
    try:
        return bundle.get('integrityValid') is True and 0 <= (day-dt.date.fromisoformat(bundle['checkedAt'])).days <= 120
    except (KeyError,TypeError,ValueError):
        return False

def stations(day, fallback=()):
    bundle=load()
    if not bundle or bundle.get('checkedAt','9999-12-31')>day.isoformat():return list(fallback)
    if not current(bundle,day):return []
    return [annotate(s) for s in bundle.get('stations',[]) if s.get('locationStatus')=='located']


def complex_coverage(center, day, radius=2000):
    """Check every registered line, independently of which route shapes exist nearby.

    An incomplete inventory cannot prove that no future station is nearby.
    Operating stations remain visible as current transport, without a new-station bonus.
    """
    from living_area import distance
    bundle = load()
    if not current(bundle, day) or distance(center or {}, center or {}) is None:
        return {'status':'unavailable', 'scopeComplete':False, 'radiusMeters':radius,
                'nearbyPlannedStations':[], 'nearbyOperatingStations':[], 'incompleteLines':[]}
    nearby_planned, nearby_operating, nearby_references, nearby_review = [], [], [], []
    for station in bundle.get('stations', []):
        station = annotate(station)
        if station.get('locationStatus') != 'located':
            continue
        meters = distance(center, station)
        if meters is None or meters > radius:
            continue
        row = {k:station.get(k) for k in ('id','name','lineId','lineName','projectId',
               'stage','stageLabel','serviceStatus','scoringEligible','sourceUrl',
               'planSourceUrl','coordinateSourceUrl','positionLabel',
               'railReviewStatus','defaultVisible','reviewLabel','reviewReason')}
        row['distanceMeters'] = round(meters)
        if station.get('serviceStatus') == 'operating':
            row.update(stage='completed', stageLabel='운행 중',
                       positionLabel='기존역 대표점 · 실제 출입구와 다를 수 있어요.')
            nearby_operating.append(row)
        elif station.get('railReviewStatus') == 'reconsidering':
            nearby_review.append(row)
        elif station.get('scoringEligible'):
            nearby_planned.append(row)
        else:
            nearby_references.append(row)
    incomplete = [{k:line.get(k) for k in ('id','name','listedStations','stationLocationCount',
                  'unlocatedStations','stationListComplete','mappingComplete','unresolvedReason',
                  'sourceUrl','stationsSourceUrl')}
                  for line in bundle.get('lines', [])
                  if line.get('stageCode') != 'completed' and not line.get('mappingComplete')]
    complete = bool(bundle.get('lines')) and not incomplete
    sort = lambda rows: sorted(rows, key=lambda row:(row['distanceMeters'], row['id']))
    return {'status':'ready' if complete else 'partial', 'scopeComplete':complete,
            'scope':bundle.get('scope'), 'checkedAt':bundle.get('checkedAt'), 'radiusMeters':radius,
            'lineCount':len(bundle.get('lines', [])),
            'completeLineCount':sum(bool(line.get('mappingComplete')) for line in bundle.get('lines', [])),
            'listedStations':len(bundle.get('stations', [])),
            'stationLocationCount':bundle.get('coverage',{}).get('stationLocationCount',0),
            'unlocatedStations':bundle.get('coverage',{}).get('unlocatedStations',0),
            'nearbyPlannedStations':sort(nearby_planned),
            'nearbyOperatingStations':sort(nearby_operating),
            'nearbyReferenceStations':sort(nearby_references),
            'nearbyReviewStations':sort(nearby_review), 'incompleteLines':incomplete}

def route_coverage(route_id, center, day):
    from living_area import distance
    bundle=load()
    checked=bundle.get('checkedAt')
    if not current(bundle,day):return {}
    line=next((l for l in bundle.get('lines',[]) if route_id in l.get('routeIds',[])),None)
    if not line:return {}
    refs=[]
    for s in bundle['stations']:
        s = annotate(s)
        if s['lineId']!=line['id'] or s.get('locationStatus')!='located':continue
        meters=distance(center,s)
        if meters is not None:refs.append({k:s.get(k) for k in ('id','name','serviceStatus','scoringEligible','sourceUrl','coordinateSourceUrl')}|{'distanceMeters':round(meters)})
    refs.sort(key=lambda s:s['distanceMeters'])
    future=[s for s in refs if s['serviceStatus']=='planned' and s['scoringEligible']]
    return {**review_context(line['id'], line.get('stageLabel'), line.get('stageCode')),
            'lineId':line['id'],'listedStations':line['listedStations'],'locatedStations':line['locatedStations'],
            'mappingComplete':line['mappingComplete'],'stationListComplete':line.get('stationListComplete',False),
            'unlocatedStations':line['unlocatedStations'],'nearestKnownStation':refs[0] if refs else None,
            'nearestPlannedStation':future[0] if future else None,'checkedAt':checked}
