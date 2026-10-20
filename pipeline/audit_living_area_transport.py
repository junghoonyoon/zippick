"""Audit every registered Seoul/Gyeonggi complex, with resumable exact geocoding.

Use --collect to query missing full-lot coordinates; default is offline.
Never turn a missing plan or failed lookup into a zero improvement score.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import config
import future_transformation as future
import living_area_metro as metro
import living_area_sources as sources
import real_estate_search
from import_living_area_metro import exact_point
from living_area import distance
from living_area_scoring_policy import STAGES, distance_decay, rounded

POINTS = config.ROOT / 'pipeline/cache/living_area_audited_centers.json'
REPORT = config.ROOT / 'docs/living-area-transport-audit.json'
KEYS = ('apartmentId','province','district','legalDong','jibun')


def identity(entity):
    return {k: (str(entity.get(k) or '') if k == 'jibun' else entity.get(k)) for k in KEYS} | {'apartmentId':future.apartment_key(entity)}


def save(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
    tmp.replace(path)


def classify(point, stations, day):
    if not point:return {'status':'location_unresolved','score':None}
    valid=[]
    for s in stations:
        if not metro.station_active(s,day) or s.get('scoringEligible') is False:continue
        meters=distance(point,s)
        if meters is not None and meters<=2000:
            meters=round(meters)
            valid.append((5*(.6*distance_decay(meters)+.4*STAGES[s['stage']]),s,meters))
    if not valid:return {'status':'no_verified_station_within_2km','score':None}
    score,station,meters=max(valid,key=lambda row:row[0])
    return {'status':'scored','score':rounded(score),'stationId':station['id'],
            'plan':station['lineName'],'station':station['name'],'distanceMeters':meters,
            'stage':station['stage'],'sourceUrl':station['planSourceUrl']}


def run(collect=False, workers=6, retry_unmatched=False):
    day=dt.date.today()
    entities=[e for e in real_estate_search._search_entities() if metro.supported(e)]
    points=json.loads(POINTS.read_text()) if POINTS.exists() else {}
    existing=json.loads(metro.CENTER_PATH.read_text()) if metro.CENTER_PATH.exists() else {}
    for key,item in existing.items():
        if item.get('point') and key not in points:points[key]=item
    targets={sources.digest(identity(e)):identity(e) for e in entities if future.apartment_key(e)}
    pending=[(key,item) for key,item in targets.items() if not (
        key in points and points[key].get('identity')==item and
        points[key].get('day')==day.isoformat() and points[key].get('status')!='lookup_failed'
        and not (retry_unmatched and points[key].get('status')=='address_not_matched'))]
    if collect:
        def lookup(pair):
            key,item=pair
            status='location_unresolved';point=None
            if all(item.values()):
                try:
                    point=exact_point({**item,'region':item['district']})
                    status='located' if point else 'address_not_matched'
                except Exception:status='lookup_failed'
            return key,{'identity':item,'day':day.isoformat(),'point':point,'status':status}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for index,(key,row) in enumerate(pool.map(lookup,pending),1):
                points[key]=row
                if index%250==0:
                    save(POINTS,points)
                    print(json.dumps({'processed':index,'totalPending':len(pending),
                                     'states':dict(Counter(x.get('status','located') for x in points.values()))}),flush=True)
        save(POINTS,points)
    stations=metro.station_references(day)
    rows=[];baseline_scored=0
    baseline=[s for s in stations if s['projectId'] in {'metro-rail:gtx-b','metro-rail:gtx-c','metro-rail:dongbuk','metro-rail:gangbuk-cross'}]
    for e in entities:
        item=identity(e);saved=points.get(sources.digest(item),{})
        checked=sources.date(saved.get('day'))
        point=saved.get('point') if saved.get('identity')==item and checked and 0<=(day-checked).days<=120 else None
        row={**item,'name':e.get('name'),**classify(point,stations,day)}
        if not point:row['status']=saved.get('status') or 'not_collected'
        if not item['apartmentId']:row['status']='aggregate_search_result'
        if classify(point,baseline,day)['status']=='scored':baseline_scored+=1
        rows.append(row)
    summary={'asOfDate':day.isoformat(),'registryRows':len(entities),'uniqueComplexes':len(targets),
             'baselineFourLinesScored':baseline_scored,
             'planLines':len({s['projectId'] for s in stations}),'stationReferences':len(stations),
             'states':dict(Counter(r['status'] for r in rows)),
             'byProvince':{p:dict(Counter(r['status'] for r in rows if r['province']==p)) for p in ('서울특별시','경기도')},
             'note':'등록 단지 전체와 수집된 계획역의 연결 검사. 계획 전수조사 또는 수혜 없음의 증명이 아님.',
             'rows':rows}
    save(REPORT,summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False,indent=2),flush=True)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect',action='store_true')
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--retry-unmatched',action='store_true')
    args=parser.parse_args()
    run(args.collect,max(1,min(args.workers,8)),args.retry_unmatched)
