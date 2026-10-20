"""Resolve reviewed railway station identities without inventing entrance positions.

Run manually: PYTHONPATH=pipeline python pipeline/import_rail_station_mapping.py
No category restriction for future stations. Exact official parcel matches take
priority; existing interchange anchors must be explicitly allowed in the plan.
Failures are recorded, never silently dropped or converted to zero stations.
"""
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

import config
import kakao_station_distances as kakao
from living_area import distance
from living_area_scoring_policy import STAGES

PLANS = config.ROOT / 'data/planned_rail_metro.json'
OUT = config.ROOT / 'data/rail_station_mapping.json'
CACHE = config.CACHE_DIR / 'rail_station_mapping_queries.json'
PROVINCES = {'서울특별시':'서울', '경기도':'경기', '인천광역시':'인천'}


def station_name(value):
    return re.sub(r'\s+', '', str(value).split('(')[0].split(' ')[0]).removesuffix('역')


def place_matches(place, station):
    address=place.get('address_name','').split()
    return (len(address)>=2 and address[0]==PROVINCES.get(station['sido'])
            and address[1]==station['sigungu']
            and station_name(place.get('place_name'))==station['name']
            and ('지하철,전철' in place.get('category_name','')
                 or '기차,철도 > 기차역' in place.get('category_name',''))
            and ('예정' in place.get('place_name','') or station.get('existingInterchange'))
            and not (station.get('preferExistingInterchange') and '예정' in place.get('place_name','')))


def exact_address(doc, address):
    # Address API may return a nearby building for an invalid parcel. Reject it.
    raw=doc.get('address') or {}
    normalized=re.sub(r'\s+', ' ', address.strip())
    normalized=normalized.replace('서울특별시','서울').replace('경기도','경기').replace('인천광역시','인천')
    actual=raw.get('address_name','')
    # Hwaseong introduced districts in 2026. Older official parcel addresses
    # remain equivalent only when city, dong, mountain flag and lot all match.
    if normalized.startswith('경기 화성시 '):
        actual=re.sub(r'^(경기 화성시) (?:동탄|효행|만세|병점)구 ',r'\1 ',actual)
    return re.sub(r'\s+', '',actual)==re.sub(r'\s+', '',normalized)


def resolve(line, station, query, checked_at):
    row={**station, 'id':station['stationId'], 'projectId':'metro-rail:'+line['id'],
         'stationName':station['name'], 'name':station['name']+('' if station['name'].endswith('정거장') else '역')+' · '+line['name'],
         'lineId':line['id'], 'lineName':line['name'], 'routeIds':line.get('routeIds',[]),
         'stage':station.get('stageCode',line['stageCode']), 'stageLabel':station.get('stageLabel',line['stage']),
         'sourceDate':line['sourceDate'], 'sourceUrl':station.get('addressSourceUrl') or line['stationsSourceUrl'],
         'planSourceUrl':line['sourceUrl'], 'planningNote':station.get('planningNote',line.get('planningNote','')),
         'checkedAt':checked_at,'stationEntranceVerified':False,'walkingMeters':None,'walkingMinutes':None,
         'scoringEligible':False,'locationStatus':'unresolved'}
    if station.get('address'):
        docs=query('search/address.json',{'query':station['address'],'size':30}).get('documents',[])
        hits=[d for d in docs if exact_address(d,station['address'])]
        if len(hits)==1:
            d=hits[0];row.update(latitude=float(d['y']),longitude=float(d['x']),
                 coordinateBasis='official_station_parcel_geocode',coordinateSourceUrl='https://developers.kakao.com/docs/latest/ko/local/dev-guide#address-coord',
                 positionLabel='공식 정거장 부지의 주소 대표점 · 출입구 아님',rawAddress=d.get('address'))
    elif station.get('referenceOnly') and station.get('referenceQuery'):
        # Official plans sometimes identify nearby facilities before a station
        # parcel is fixed. These remain visible but never become scored stations.
        label=station['referenceQuery']
        docs=query('search/keyword.json',{'query':f'{station["sido"]} {station["sigungu"]} {label}','size':15}).get('documents',[])
        hits=[d for d in docs if d.get('place_name')==label
              and d.get('address_name','').split()[:2]==[PROVINCES.get(station['sido']),station['sigungu']]]
        if len(hits)==1:
            d=hits[0];row.update(latitude=float(d['y']),longitude=float(d['x']),
                coordinateBasis='official_planning_landmark',coordinateSourceUrl=d['place_url'],
                positionLabel='계획서에 나온 주변 시설 위치 · 역 부지 미확정',referencePlaceName=label)
    else:
        params={'query':station.get('query') or f'{station["sido"]} {station["sigungu"]} {station["name"]}'+('' if station['name'].endswith('정거장') else '역'),'size':15}
        response=query('search/keyword.json',params)
        docs=list(response.get('documents',[]))
        if station.get('placeReference'):
            docs.append(station['placeReference'])
        for page in range(2,4):
            if response.get('meta',{}).get('is_end',True):break
            response=query('search/keyword.json',{**params,'page':page});docs.extend(response.get('documents',[]))
        hits=[d for d in docs if place_matches(d,station)]
        if station.get('placeId'):hits=[d for d in hits if d['id']==station['placeId']]
        future=[d for d in hits if '예정' in d['place_name']]
        if future:hits=future
        points=[{'latitude':float(d['y']),'longitude':float(d['x'])} for d in hits]
        if any(distance(a,b)>400 for a in points for b in points):row['locationStatus']='ambiguous';hits=[]
        if hits:
            d=sorted(hits,key=lambda d:d['id'])[0];planned='예정' in d['place_name']
            row.update(latitude=float(d['y']),longitude=float(d['x']),coordinateBasis='planned_station_place' if planned else 'existing_interchange_reference',
                coordinateSourceUrl=d['place_url'],positionLabel='예정역 장소 대표점 · 출입구 미확정' if planned else '기존 환승역 대표점 · 새 노선 출입구 미확정',
                rawPlace={k:d.get(k) for k in ('id','place_name','address_name','x','y','category_name')})
    if 'latitude' in row and not (math.isfinite(row['latitude']) and math.isfinite(row['longitude'])
                                 and 33 <= row['latitude'] <= 39 and 124 <= row['longitude'] <= 132):
        row.pop('latitude');row.pop('longitude');row['locationStatus']='invalid_coordinates'
    if 'latitude' in row:
        row['locationStatus']='located'
        row['scoringEligible']=bool(row['stage'] in STAGES and station.get('membershipVerified',True)
                                   and station.get('serviceStatus','planned')=='planned' and not station.get('referenceOnly'))
    else:row['unresolvedReason']='동일 이름·지역의 예정역 또는 공식 부지 주소를 확인하지 못했어요.'
    return row


def build(plans, query, checked_at):
    pairs=[(l,s) for l in plans['lines'] for s in l['stations']]
    def run(pair):
        l,s=pair
        try:return resolve(l,s,query,checked_at)
        except (kakao.KakaoLocalError,ValueError,KeyError,TypeError) as error:
            return {**s,'id':s['stationId'],'lineId':l['id'],'lineName':l['name'],
                    'locationStatus':'collection_failed','scoringEligible':False,'checkedAt':checked_at,
                    'unresolvedReason':type(error).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(run,pairs))
    lines=[]
    for l in plans['lines']:
        ss=[s for s in rows if s['lineId']==l['id']]
        located=sum(s['locationStatus']=='located' for s in ss)
        station_points=sum(s['locationStatus']=='located' and s.get('coordinateBasis')!='official_planning_landmark' for s in ss)
        lines.append({k:v for k,v in l.items() if k!='stations'}|{
            'listedStations':len(ss),'locatedStations':located,'unlocatedStations':len(ss)-located,
            'scoringStations':sum(s['scoringEligible'] for s in ss),'stationLocationCount':station_points,
            'landmarkReferences':located-station_points,
            'mappingComplete':bool(l.get('stationListComplete') and ss and station_points==len(ss)
                                   and all(s.get('membershipVerified') for s in ss))})
    return {'schemaVersion':1,'checkedAt':checked_at,'scope':plans['scope'],
        'plansDigest':hashlib.sha256(json.dumps(plans,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'lines':lines,'stations':rows,
        'coverage':{'lineCount':len(lines),'listedStations':len(rows),'locatedStations':sum(s['locationStatus']=='located' for s in rows),
                    'scoringStations':sum(s['scoringEligible'] for s in rows),
                    'stationLocationCount':sum(l['stationLocationCount'] for l in lines),
                    'landmarkReferences':sum(l['landmarkReferences'] for l in lines),
                    'unlocatedStations':sum(s['locationStatus']!='located' for s in rows),
                    'completeLines':sum(l['mappingComplete'] for l in lines),
                    'scopeComplete':all(l['mappingComplete'] or l['stageCode']=='completed' for l in lines)}}


def main():
    import threading
    day=dt.date.today().isoformat();lock=threading.Lock()
    cache=json.loads(CACHE.read_text()) if CACHE.exists() else {}
    def query(endpoint,params):
        key=json.dumps([day,endpoint,params],ensure_ascii=False,sort_keys=True)
        with lock:hit=cache.get(key)
        if hit is not None:return hit
        result=kakao._request_json(endpoint,params)
        with lock:cache[key]=result
        return result
    result=build(json.loads(PLANS.read_text()),query,day)
    CACHE.parent.mkdir(parents=True,exist_ok=True);CACHE.write_text(json.dumps(cache,ensure_ascii=False))
    temporary=OUT.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');temporary.replace(OUT)
    print(json.dumps(result['coverage'],ensure_ascii=False))
    for l in result['lines']:print(l['id'],l['locatedStations'],'/',l['listedStations'],l['stageCode'])

if __name__=='__main__':main()
