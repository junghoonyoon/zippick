"""Refresh public metro plan catalogues. No guessed geometry or walk times.

Usage: PYTHONPATH=pipeline python pipeline/import_living_area_metro.py
Downloads public GG Q2 workbook, MOLIT catalogue and ArcGIS query exports;
Kakao coordinates are accepted only when the complete lot address agrees.
"""
import concurrent.futures
import csv
import datetime as dt
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
import config
import living_area_sources as sources
from living_area_scoring_policy import STAGES

OUT = config.ROOT / 'data/living_area_metro_catalog.json'
GG_URL = 'https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx=11673&decodeIdx=5318'
GIS = 'https://gris.gg.go.kr:8888/grisgis/rest/services/'
DAY = dt.date.today().isoformat()


def stage(label):
    text = re.sub(r'\s+', '', str(label or ''))
    from redevelopment_occupancy import completed_stage
    if completed_stage(text) or text in ('취소','청산','해산','개통'):return 'completed'
    if re.search(r'준공|사용승인|입주|해제|취소|해산|청산',text) and re.search(r'예정|신청|심사|부분|일부|미준공|미완료|계획',text):
        return 'unknown'
    if '입주자모집' in text or '분양공고' in text:return 'construction'
    if '예정' in text or '검토' in text or '추진위' in text or '추진중' in text: return 'planning'
    for keys, value in [(('착공','공사중'),'construction'),(('관리처분','철거','이주'),'disposal'),
                        (('사업시행','사업계획승인'),'approved'),(('조합설립','조합인가'),'association'),
                        (('구역지정','정비구역'),'designated'),(('기획','기본계획','후보'),'planning')]:
        if any(k in text for k in keys): return value
    return 'unknown'


def number(value):
    try:
        n=float(str(value).replace(',','').strip()); return n if n > 0 else None
    except (ValueError,TypeError):return None


def workbook_rows(content):
    """Read published cells only; do not execute formulas or import private contacts."""
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',ns)]
        root=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
        result=[]
        for row in root.findall('.//s:row',ns):
            values=[None]*60
            for c in row.findall('s:c',ns):
                letters=re.match('[A-Z]+',c.attrib['r'])[0]; col=0
                for ch in letters:col=col*26+ord(ch)-64
                v=c.find('s:v',ns)
                if v is None:continue
                value=v.text
                if c.attrib.get('t')=='s':value=strings[int(value)]
                else:
                    try:value=float(value)
                    except (TypeError,ValueError):pass
                if col<=60:values[col-1]=value
            result.append(values)
        return result


def gg_projects(rows):
    output=[]
    for row in rows:
        if not isinstance(row[0],(int,float)) or not row[1] or not row[4]:continue
        city,label,kind,name,address = [str(row[i] or '').strip() for i in (1,2,3,4,5)]
        match=re.search(r'([가-힣0-9]+(?:동|리))\s*(\d+(?:-\d+)?)',address)
        district_match=re.search(r'([가-힣]+구)',address)
        district=city.removesuffix('시')+district_match[1] if district_match else city
        pid='gg-quarter:'+sources.digest([city,name,address,kind])[:20]
        output.append({'id':pid,'sourceId':'gg-quarter','sourceRecordId':str(int(row[0])),
            'name':name,'region':district,'city':city,'province':'경기도','address':f'경기도 {city} {address}',
            'legalDong':match[1] if match else '', 'jibun':match[2] if match else '',
            'projectTypeLabel':kind,
            'projectType':'reconstruction' if '재건축' in kind else 'redevelopment' if '재개발' in kind else 'housing_environment' if '주거환경' in kind else 'other',
            'stage':stage(label),'stageLabel':label,'siteAreaM2':number(row[6]),
            'plannedHouseholds':int(number(row[19])) if number(row[19]) else None,
            'existingHouseholds':int(number(row[9])) if number(row[9]) else None,
            'sourceUrl':GG_URL,'sourceDate':'2026-06-30','checkedAt':DAY,
            'householdsStatus':'planned','benefitClass':'unverified','benefitLabel':'직접 수혜 미확인'})
    if len(output)!=542:raise ValueError('GG workbook row count changed; review schema before promotion')
    return output


def exact_point(target):
    import kakao_station_distances as kakao
    dong=target.get('legalDong') or ''
    lot_match=re.fullmatch(r'(?:'+re.escape(dong)+r'\s+)?(\d+(?:-\d+)?)',str(target.get('jibun') or ''))
    if not dong or not lot_match:return None
    expected_lot=lot_match[1]
    province=target.get('province') or '서울특별시'
    district=target['region']
    readable=re.sub(r'^(수원|성남|안양|안산|고양|용인|부천)(?=.{1,3}구$)',r'\1시 ',district)
    query=f'{province} {readable} {dong} {expected_lot}'
    payload=kakao._request_json('search/address.json',{'query':query,'size':10})
    if (payload.get('meta') or {}).get('total_count',0)>10:return None
    matches=[]
    for doc in payload.get('documents',[]):
        a=doc.get('address') or {}; lot=str(a.get('main_address_no') or '')
        if a.get('sub_address_no') and a['sub_address_no']!='0':lot+='-'+a['sub_address_no']
        rawdistrict=str(a.get('region_2depth_name') or '').replace('시 ','')
        # City-only identities may acquire a new administrative gu (e.g. Hwaseong).
        # Never relax an identity that explicitly names a gu.
        city_ok=(district.endswith('시') and a.get('region_2depth_name','').split(' ')[0]==district)
        raw_dong=str(a.get('region_3depth_name') or '')
        dong_ok=raw_dong==dong or (dong.endswith('리') and ' ' not in dong and raw_dong.split(' ')[-1]==dong)
        if (a.get('region_1depth_name') not in (('경기',) if province=='경기도' else ('서울',))
            or not (rawdistrict==district or city_ok) or not dong_ok
            or lot!=expected_lot or a.get('mountain_yn')!='N'):continue
        latitude,longitude=float(a['y']),float(a['x'])
        if not (33 < latitude < 39 and 124 < longitude < 132):continue
        matches.append({'latitude':latitude,'longitude':longitude,'rawAddress':a,
                        'coordinateBasis':'address_geocode','checkedAt':DAY,
                        'sourceUrl':'https://developers.kakao.com/docs/latest/ko/local/dev-guide#address-coord'})
    return matches[0] if len(matches)==1 else None


def fetch_features(path):
    endpoint=GIS+path+'/query'
    j=requests.get(endpoint,params={'f':'geojson','where':'1=1','outFields':'*','outSR':4326,'returnGeometry':'true'},timeout=45).json()
    if 'features' not in j or j.get('exceededTransferLimit'):raise ValueError('incomplete GIS export')
    return j['features']


def main():
    content=requests.get('https://www.gg.go.kr/cmmn/download.do?idx=898836',timeout=45).content
    projects=gg_projects(workbook_rows(content))
    seoul=sources.load_projects()
    projects += [{**p,'province':'서울특별시','checkedAt':DAY} for p in seoul if p['sourceId']=='seoul-plan-renewal']
    # National supply is a second source, only exact city + name matches; no fuzzy identity merge.
    url='https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003667489&fileDetailSn=1&insertDataPrcus=N'
    raw=requests.get(url,timeout=45).content
    national=list(csv.DictReader(io.StringIO(raw.decode('cp949'))))
    norm=lambda s:re.sub(r'\s+','',str(s or ''))
    for p in projects:
        hits=[r for r in national if norm(r['구역명칭'])==norm(p['name']) and norm(r['시군구'])==norm(p['region'])]
        if len(hits)==1 and not p.get('plannedHouseholds') and (n:=number(hits[0]['공급 예정 세대수'])):
            p['plannedHouseholds']=int(n);p['householdsSourceUrl']='https://www.data.go.kr/data/15160169/fileData.do';p['householdsAsOf']='2026-05-18'
    old=json.loads(OUT.read_text()) if OUT.exists() else {}; known={p['id']:p for p in old.get('projects',[])}
    def locate(p):
        previous=known.get(p['id'],{}).get('point')
        if previous and all(known[p['id']].get(k)==p.get(k) for k in ('region','legalDong','jibun')) and previous.get('checkedAt')==DAY:p['point']=previous
        # Completed projects still need coordinates to retire stale map boundaries.
        elif p['stage'] != 'unknown':
            try:p['point']=exact_point(p)
            except Exception:p['point']=None
        return p
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:projects=list(pool.map(locate,projects))
    projects += fetch_supply()
    stations = fetch_station_references()
    features=[]
    for layer in (12,13,14,15):
        for f in fetch_features('bdsMap_Public/MapServer/'+str(layer)):
            f['properties']['sourceLayer']=layer
            features.append(f)
    rails=fetch_features('bdsMap_Monitoring/MapServer/7')
    bundle={'version':1,'checkedAt':DAY,'sourceDate':'2026-06-30','projects':projects,
            'projectsDigest':sources.digest(projects),'nationalRows':national,'nationalAsOf':'2026-05-18',
            'ggBoundaries':features,'railRoutes':rails,'railStations':stations,'useContext':'noncommercial',
            'coverage':{'seoulProjects':len(seoul),'gyeonggiProjects':542,'locatedProjects':sum(bool(p.get('point')) for p in projects),
                        'gyeonggiBoundaries':len(features),'railRoutes':sum(bool(f.get('geometry')) for f in rails), 'railStationReferences':len(stations), 'supplyNotices':sum(p['projectType']=='new_supply' for p in projects),
                        'scopeComplete':False,'note':'공개 목록에 수록된 사업 기준이며 모든 개발계획의 전수조사가 아닙니다.'}}
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(bundle,ensure_ascii=False,separators=(',',':'))+'\n');tmp.replace(OUT)
    print(json.dumps(bundle['coverage'],ensure_ascii=False))



def fetch_supply():
    """APT offered units are minimum competition evidence, never total complex units."""
    import applyhome_supply as api
    all_rows=api.fetch_all(api.service_key(),verbose=False)
    projects=[]
    for r in all_rows:
        province,region=api.normalize_region(api._pick(r,'address'),api._pick(r,'area'))
        month=api._month(api._pick(r,'moveIn')); published=api._pick(r,'noticeDate')
        if province not in ('서울특별시','경기도') or not month or month<DAY[:7] or not published or published>DAY:continue
        address=api._pick(r,'address');match=re.search(r'([가-힣0-9]+(?:동|리))\s*(\d+(?:-\d+)?)',address)
        pid=api._pick(r,'noticeNo');n=number(api._pick(r,'households'))
        if not pid or not n:continue
        projects.append({'id':'applyhome:'+pid,'sourceId':'applyhome-apt','sourceRecordId':pid,
             'name':api._pick(r,'name'),'province':province,'region':region,'address':address,
             'legalDong':match[1] if match else '', 'jibun':match[2] if match else '',
             'projectType':'new_supply','stage':'announced','stageLabel':'입주 예정 · 모집공고 기준',
             'offeredHouseholds':int(n),'plannedHouseholds':None,'plannedMoveInMonth':month,
             'sourceDate':published,'checkedAt':DAY,'sourceUrl':api.DATA_PORTAL_URL,
             'factSummary':f'{month} 입주 계획 · 공고 공급 {int(n):,}세대(전체 단지 규모와 다를 수 있어요)',
             'scopeLabel':'주변 분양 공고 · 입주 계획','benefitClass':'unverified','benefitLabel':'공급 비교 자료'})
    def locate(p):
        try:p['point']=exact_point(p)
        except Exception:p['point']=None
        return p
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(locate,projects))


def fetch_station_references(bundle=None):
    import kakao_station_distances as kakao
    from living_area import distance
    lines=bundle if bundle is not None else json.loads((config.ROOT/'data/planned_rail_metro.json').read_text())
    def locate(pair):
        line,station=pair
        # A listed station does not imply construction. Unknown/completed plans
        # cannot become new transport improvements through geocoding.
        if line.get('stageCode') not in STAGES:return None
        published=sources.date(line.get('sourceDate') or lines['checkedAt'])
        if not published or published>dt.date.fromisoformat(DAY):return None
        docs=kakao._request_json('search/keyword.json',{'query':f'{station["sido"]} {station["sigungu"]} {station["name"]}역','category_group_code':'SW8','size':15}).get('documents',[])
        matches=[d for d in docs if d.get('category_group_code')=='SW8' and d.get('place_name','').split(' ')[0]==station['name']+'역' and station['sigungu'] in d.get('address_name','')]
        if not matches:return None
        # Multiple railway operators may have separate place records at one interchange.
        points=[{'latitude':float(d['y']),'longitude':float(d['x'])} for d in matches]
        if any(distance(a,b)>400 for a in points for b in points):return None
        d=sorted(matches,key=lambda x:x['id'])[0]
        return {'id':line['id']+':'+d['id'],'projectId':'metro-rail:'+line['id'],'name':station['name']+'역 · '+line['name'],
            'latitude':float(d['y']),'longitude':float(d['x']),'positionLabel':'기존 환승역 대표점 · 새 노선 출입구 미확정',
            'sourceUrl':line['stationsSourceUrl'],'coordinateSourceUrl':d.get('place_url'),'checkedAt':DAY,
            'stage':line['stageCode'],'stageLabel':line['stage'],'lineName':line['name'],'sourceDate':published.isoformat(),
            'planningNote':line.get('planningNote',''),
            'planSourceUrl':line['sourceUrl'],'rawPlace':{k:d.get(k) for k in ('id','place_name','address_name','x','y','category_group_code')},
            'stationEntranceVerified':False,'walkingMeters':None,'walkingMinutes':None}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        return [r for r in pool.map(locate,[(line,s) for line in lines['lines'] for s in line['stations']]) if r]

if __name__=='__main__':main()
