"""Cross-check recap conflicts against a complete official building-title snapshot.

The title table is a different official record, not a website copying the recap.
A verified residential floor range can be used even when site ratios remain
unresolved. Missing/contradictory ratios are never inferred from floor counts.
"""
import datetime as dt
from functools import lru_cache
import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import apartment_identity
import shared_data
import building_register_single_site
import building_register_identity

FILE='building_register_crosschecks.json'
VERSION='building-register-crosscheck-v2'
MAX_AGE_DAYS=180
RESOLUTIONS={'verified_title','confirmed_registered_ratio','verified_site_parcels'}
SEOUL_RECAP_URL='https://data.seoul.go.kr/dataList/OA-23051/S/1/datasetView.do'
GG_RECAP_URL='https://gris.gg.go.kr/map/main/grisMapView.do'


def resolved(issue):
    return issue.get('resolution') in RESOLUTIONS


def _fresh(value,day):
    try:return 0 <= (day-dt.date.fromisoformat(str(value or '')[:10])).days <= MAX_AGE_DAYS
    except ValueError:return False


def _address_keys(entity):
    fields=('province','district','legalDong','jibun')
    normal=lambda e:re.sub(r'\s+','', ' '.join(str(e.get(k) or '') for k in fields))
    keys={normal(entity)}
    city=str(entity.get('city') or '');district=str(entity.get('district') or '')
    base=city.removesuffix('시') if city.endswith('시') else ''
    if base and district.startswith(base) and district!=city and district[len(base):].endswith('구'):
        keys.add(normal({**entity,'district':city+' '+district[len(base):]}))
    return keys


def _pnu(entity):
    lot=re.fullmatch(r'(산?)(\d{1,4})(?:-(\d{1,4}))?',apartment_identity.entity_parcel(entity))
    code=str(entity.get('cortarNo') or '')
    return code+('2' if lot[1] else '1')+lot[2].zfill(4)+(lot[3] or '0').zfill(4) if lot and len(code)==10 else None


def _municipal_record(entity,profile,entry,day):
    """Confirm an explicit whole-register attribute, never derive it from bad areas.

    A municipal publication can repeat the same underlying registry error. Its
    agreement confirms the *registered* ratio only, not the physical areas or a
    measurement. Keep that distinction in both provenance and downstream fields.
    """
    pk=profile.get('registerId');hh=_number(profile.get('households'));pnu=_pnu(entity)
    if not pk or not hh:return None,None
    city=entry.get('municipalRecap') or {}
    if (city.get('status')=='ok' and not city.get('lastError') and city.get('sourceUrl')==SEOUL_RECAP_URL
            and entity.get('province')=='서울특별시' and _fresh(city.get('fetchedAt'),day)
            and re.fullmatch(r'[a-f0-9]{64}',str(city.get('fileSha256') or ''))):
        rows=[]
        for r in city.get('records') or []:
            if (str(r.get('건축물대장일련번호'))==pk and r.get('대장종류코드명')=='총괄표제부'
                    and r.get('주용도코드명')=='공동주택' and _number(r.get('세대수'))==hh
                    and pnu and str(r.get('주지번') or '').zfill(4)==pnu[11:15]
                    and str(r.get('부지번') or '').zfill(4)==pnu[15:]
                    and re.sub(r'\s+','',str(r.get('대지위치') or '')) in _address_keys(entity)
                    and (not r.get('법정동코드') or str(r['법정동코드'])==str(entity.get('cortarNo')))):
                rows.append(r)
        if len(rows)==1:
            r=rows[0]
            return {'floorAreaRatio':_number(r.get('용적률')),'buildingCoverageRatio':_number(r.get('건폐율'))},city
    portal=entry.get('portalRecap') or {};vo=(portal.get('response') or {}).get('buldInfoVo') or {}
    listings=portal.get('listings') or []
    matching=[r for r in listings if str(r.get('mgmBldrgstPk'))==pk and str(r.get('regstrKindCd'))=='1']
    if (entity.get('province')=='경기도' and portal.get('status')=='ok' and not portal.get('lastError')
            and portal.get('sourceUrl')==GG_RECAP_URL
            and portal.get('requestUrl')=='https://gris.gg.go.kr/lot/buld/selectLotBuldInfo.do'
            and portal.get('pnu')==_pnu(entity) and _fresh(portal.get('fetchedAt'),day)
            and len(matching)==1 and str(vo.get('mgmBldrgstPk'))==pk
            and str(vo.get('regstrKindCd'))=='1' and vo.get('bjdongNm')==entity.get('legalDong')
            and _number(vo.get('hhldCnt'))==hh):
        return {'floorAreaRatio':_number(vo.get('vlRat')),'buildingCoverageRatio':_number(vo.get('bcRat'))},portal
    return None,None


def _site_land(entity,profile,entry,day):
    """Require the complete official parent/attached parcel set, not one parcel."""
    portal=entry.get('portalRecap') or {};vo=(portal.get('response') or {}).get('buldInfoVo') or {}
    snapshot=entry.get('siteParcels') or {};rows=snapshot.get('records') or []
    attached=(portal.get('response') or {}).get('exculdLotList') or []
    try:count=int(vo.get('bylotCnt'))
    except (ValueError,TypeError):return None
    if (snapshot.get('status')!='ok' or snapshot.get('parentRegisterId')!=profile.get('registerId')
            or not _fresh(snapshot.get('fetchedAt'),day) or len(attached)!=count
            or snapshot.get('expectedParcelCount')!=count+1 or len(rows)!=count+1):return None
    expected={_pnu(entity)}
    for a in attached:
        address=str(a.get('atchJibun') or '');lot=address.rsplit(' ',1)[-1]
        parcel_entity={**entity,'jibun':lot}
        if not any(re.sub(r'\s+','',address)==key.removeprefix('경기도') for key in _address_keys(parcel_entity)):return None
        pnu=_pnu(parcel_entity)
        if not pnu or pnu in expected:return None
        expected.add(pnu)
    if {r.get('pnu') for r in rows}!=expected:return None
    for row in rows:
        url=urlsplit(str(row.get('sourceUrl') or ''))
        pnu=row.get('pnu');parcel_entity={**entity,'jibun':str(int(pnu[11:15]))+('-'+str(int(pnu[15:])) if int(pnu[15:]) else '')}
        if (url.scheme!='https' or url.hostname!='www.eum.go.kr' or url.path!='/web/ar/lu/luLandDet.jsp'
                or pnu not in expected or parse_qs(url.query).get('pnu')!=[pnu] or row.get('license')!='공공누리 출처표시'
                or not _fresh(row.get('checkedAt'),day) or not _number(row.get('parcelAreaSqm'))
                or re.sub(r'\s+','',str(row.get('address') or '')) not in _address_keys(parcel_entity)):return None
    return round(sum(_number(r['parcelAreaSqm']) for r in rows),4),rows


def _apply_registered(entity,profile,entry,day):
    values,source=_municipal_record(entity,profile,entry,day)
    if not values:return profile
    out=dict(profile);cross=dict(out['crosscheck']);out['crosscheck']=cross
    out['fieldSources']={k:dict(v) for k,v in profile.get('fieldSources',{}).items()}
    cross['verifiedFields']=list(cross.get('verifiedFields') or [])
    cross['unresolvedFields']=list(cross.get('unresolvedFields') or [])
    issues=[dict(x) for x in profile.get('fieldIssues',[])];out['fieldIssues']=issues
    verified=[]
    for issue in issues:
        field=issue['field'];value=values.get(field)
        if (resolved(issue) or issue.get('code')!='area_ratio_mismatch' or not value
                or field=='buildingCoverageRatio' and value>100
                or abs(value-issue['reportedValue'])>.01):continue
        out[field]=issue['reportedValue']
        issue.update(resolution='confirmed_registered_ratio',resolvedValue=out[field])
        out.setdefault('fieldSources',{})[field]={'sourceUrl':source['sourceUrl'],'fetchedAt':source['fetchedAt'],
            'registerId':profile['registerId'],'scope':'whole_registered_site','kind':'registered_attribute_confirmation',
            'independentAreaValidation':False}
        verified.append(field)
    if not verified:return out
    # The same registry error may be republished. Do not let restored percentages
    # make suspect areas available to relief, unit-count or financial calculations.
    area_conflict=any(x.get('code')=='area_ratio_mismatch' for x in issues)
    if area_conflict and 'landAreaSqm' not in cross['verifiedFields']:
        out['originalLandAreaSqm']=out.get('landAreaSqm');out['landAreaSqm']=None
        out['originalFloorAreaForRatioSqm']=out.get('floorAreaForRatioSqm');out['floorAreaForRatioSqm']=None
        out['areaIntegrity']={'status':'unresolved','excludedFields':['landAreaSqm','floorAreaForRatioSqm']}
        land_proof=_site_land(entity,profile,entry,day)
        if land_proof:
            land,parcels=land_proof
            out['cadastralLandAreaSqm']=land
            # A current cadastral total is not necessarily the historic permitted
            # site area. Only link it when the original registered numerator agrees.
            far=out.get('floorAreaRatio');numerator=profile.get('floorAreaForRatioSqm')
            if far and numerator and abs(numerator/land*100-far)<=1:
                out.update(landAreaSqm=land,floorAreaForRatioSqm=numerator)
                out['areaIntegrity']={'status':'verified','excludedFields':[],'parcelCount':len(parcels)}
                cross['verifiedFields'].append('landAreaSqm')
                out.setdefault('fieldSources',{})['landAreaSqm']={'sourceUrl':GG_RECAP_URL,'scope':'complete_registered_parcels',
                    'parcelSources':[r['sourceUrl'] for r in parcels],'fetchedAt':source['fetchedAt']}
                for issue in issues:
                    area=numerator if issue['field']=='floorAreaRatio' else issue.get('numeratorAreaSqm')
                    if issue['field'] in verified and area and abs(area/land*100-out[issue['field']])<=1:
                        issue['resolution']='verified_site_parcels'
                        out['fieldSources'][issue['field']]['independentAreaValidation']=True
    cross['verifiedFields']=list(dict.fromkeys(cross['verifiedFields']+verified))
    cross['unresolvedFields']=[x['field'] for x in issues if not resolved(x)]
    cross['unresolvedAreaFields']=list((out.get('areaIntegrity') or {}).get('excludedFields') or [])
    cross.update(status='verified_partial' if cross['unresolvedFields'] or out.get('areaIntegrity',{}).get('status')=='unresolved' else 'verified',
                 sourceUrl=source['sourceUrl'],checkedAt=source['fetchedAt'],
                 reason='국토부와 지자체 공개 대장의 단지·주소·대장 번호·세대수가 맞고 기재된 비율도 같아요. 이 기재값을 사용하며, 면적을 독립적으로 확인한 것으로 보지는 않아요.')
    if out.get('areaIntegrity',{}).get('status')=='unresolved':
        cross['reason']+=' 서로 맞지 않는 대지·연면적은 계산에서 제외했어요.'
    elif out.get('areaIntegrity',{}).get('status')=='verified':
        cross['reason']+=' 부속 지번을 포함한 전체 토지 면적도 대조해 면적 계산이 맞는지 확인했어요.'
    out['status']='ready' if out.get('floorAreaRatio') and out.get('buildingCoverageRatio') else 'partial'
    return out


def _number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) and n>0 and not isinstance(v,bool) else None
    except (ValueError,TypeError):return None


def _stamp(path):
    try:
        s=path.stat();return s.st_mtime_ns,s.st_size
    except OSError:return None


def revision():
    return VERSION,_stamp(Path(__file__)),_stamp(shared_data.cache_path(FILE))


@lru_cache(maxsize=4)
def _read(path,stamp):
    if stamp is None:return {}
    d=json.loads(Path(path).read_text())
    if not isinstance(d,dict) or not isinstance(d.get('records'),dict):raise ValueError('invalid title crosscheck store')
    return d['records']


def entry_for(entity):
    return building_register_single_site.entry_for(entity)


def apply(entity,profile,entry,*,day=None):
    day=day or dt.date.today()
    out=_apply_titles(entity,profile,entry,day=day)
    if not entry or any(str((entry.get('identity') or {}).get(k) or '')!=str(entity.get(k) or '')
                        for k in ('apartmentId','province','district','legalDong','jibun','cortarNo')):
        return out
    return _apply_registered(entity,out,entry,day)


def _apply_titles(entity,profile,entry,*,day=None):
    """Return independently verified fields and unresolved conflicts separately."""
    day=day or dt.date.today();out=dict(profile)
    result={'version':VERSION,'status':'not_collected','verifiedFields':[],
            'unresolvedFields':[x['field'] for x in profile.get('fieldIssues',[])],
            'sourceUrl':None,'checkedAt':None}
    out['crosscheck']=result
    if not entry:return out
    if entry.get('lastError') or entry.get('status')!='ok':
        result.update(status=(entry.get('lastError') or entry).get('status','connection_error'))
        return out
    identity=entry.get('identity') or {};snapshot=entry.get('snapshot') or {}
    if any(str(identity.get(k) or '')!=str(entity.get(k) or '') for k in ('apartmentId','province','district','legalDong','jibun','cortarNo')):
        result['status']='identity_unverified';return out
    source=urlsplit(str(snapshot.get('sourceUrl') or ''))
    try:checked=dt.date.fromisoformat(str(snapshot.get('fetchedAt') or '')[:10])
    except ValueError:result['status']='invalid_source';return out
    if not(source.scheme=='https' and (source.hostname or '').endswith('.go.kr')):
        result['status']='invalid_source';return out
    if not 0<=(day-checked).days<=MAX_AGE_DAYS:
        result['status']='stale';return out
    parcel=snapshot.get('parcel') or {};rows=snapshot.get('records')
    code=str(entity.get('cortarNo') or '')
    lot=apartment_identity.entity_parcel(entity)
    import re
    match=re.fullmatch(r'(산?)(\d{1,4})(?:-(\d{1,4}))?',lot)
    if not match or len(code)!=10:
        result['status']='identity_unverified';return out
    expected={'sigunguCd':code[:5],'bjdongCd':code[5:],'platGbCd':'1' if match[1] else '0',
              'bun':match[2].zfill(4),'ji':(match[3] or '0').zfill(4)}
    if parcel not in building_register_identity.variants(entity, expected, day=day) or not isinstance(rows,list) or len(rows)!=snapshot.get('totalCount'):
        result['status']='invalid_source';return out
    expected=parcel
    if not rows:result['status']='no_records';return out
    ids=[];res=[]
    for row in rows:
        if not isinstance(row,dict) or not row.get('mgmBldrgstPk') or any(str(row.get(k,'')).zfill(len(v))!=v for k,v in expected.items()):
            result['status']='invalid_source';return out
        ids.append(str(row['mgmBldrgstPk']))
        if (not _number(row.get('hhldCnt')) and row.get('mainPurpsCdNm')=='공동주택'
                and str(row.get('mainAtchGbCd'))=='0' and _number(row.get('grndFlrCnt'))
                and (re.fullmatch(r'\s*\d+동\s*',str(row.get('dongNm') or ''))
                     or '아파트' in str(row.get('etcPurps') or ''))):
            result['status']='identity_unverified';return out
        if (_number(row.get('hhldCnt')) and row.get('mainPurpsCdNm')=='공동주택'
                and str(row.get('mainAtchGbCd'))=='0' and str(row.get('regstrKindCd')) in ('2','3')):
            if apartment_identity.phase_conflicts(entity.get('name'),row.get('bldNm')):
                result['status']='identity_unverified';return out
            res.append(row)
    expected_households=_number(profile.get('households'))
    if (len(ids)!=len(set(ids)) or not res or not expected_households
            or sum(_number(x.get('hhldCnt')) or 0 for x in res)!=expected_households):
        result['status']='identity_unverified';return out
    floors=[_number(x.get('grndFlrCnt')) for x in res]
    # One title may cover multiple physical buildings. A title count alone
    # does not establish the coverage of the residential floor range.
    names=[str(row.get('dongNm') or '').strip() for row in res]
    named_buildings=(len(res)>1 and all(names) and len(names)==len(set(names))
        and not any(re.search(r'[,/·~]|외|및|전체|합계|일괄|통합',name) for name in names))
    all_main=[row for row in rows if str(row.get('mainAtchGbCd'))=='0']
    count_verified=bool(_number(profile.get('mainBuildingCount'))==len(all_main))
    floor_coverage_verified=named_buildings or count_verified
    result.update(status='checked_unresolved',sourceUrl=snapshot['sourceUrl'],checkedAt=snapshot['fetchedAt'],
                  registeredResidentialTitleCount=len(res),matchedHouseholds=expected_households,
                  reason='동별 공식 대장을 대조했지만 단지 전체 비율을 독립적으로 확인할 수 없어 원본의 충돌 값은 계속 제외했어요.')
    if floor_coverage_verified and all(x and x.is_integer() and x<=200 for x in floors):
        out.update(minFloors=min(floors),maxFloors=max(floors),floorScope='all_residential_buildings',
                   floorSourceUrl=snapshot['sourceUrl'],floorFetchedAt=snapshot['fetchedAt'],residentialBuildingCount=len(res))
        result.update(status='verified_partial',verifiedFields=['minFloors','maxFloors'],
                      reason='전체 주거동의 층수와 세대수 합계가 맞는 공식 대장을 확인했어요. 단지 전체 용적률·건폐율의 충돌은 아직 해결되지 않았어요.')
    # A per-building ratio is not a whole-site ratio. Only a sole above-ground
    # main building, independently covering all registered households, can
    # directly corroborate the whole-site ratio. Never sum ratios or average
    # land areas across buildings.
    above_ground=[r for r in rows if _number(r.get('archArea'))]
    if len(res)==1 and len(above_ground)==1 and above_ground[0] is res[0]:
        row=res[0]
        if not all(building_register_single_site._zero(row.get(k)) for k in ('bylotCnt','atchBldCnt','atchBldArea')):
            return out
        land=_number(row.get('platArea'))
        fields=[('floorAreaRatio','vlRat','vlRatEstmTotArea'),('buildingCoverageRatio','bcRat','archArea')]
        originals={x['field']:x for x in profile.get('fieldIssues',[])}
        for field,raw,numerator in fields:
            ratio=_number(row.get(raw));area=_number(row.get(numerator));old=originals.get(field)
            if (land and ratio and area and (field!='buildingCoverageRatio' or ratio<=100)
                    and abs(ratio-area/land*100)<=1
                    and (not old or abs(ratio-old['reportedValue'])<=.1)):
                out[field]=ratio
                if old:
                    out['fieldIssues']=[{**x,'resolution':'verified_title','resolvedValue':ratio} if x['field']==field else dict(x) for x in out['fieldIssues']]
                result['verifiedFields'].append(field)
                result['unresolvedFields']=[x for x in result['unresolvedFields'] if x!=field]
                out['originalLandAreaSqm']=profile.get('landAreaSqm');out['landAreaSqm']=land
                if 'landAreaSqm' not in result['verifiedFields']:result['verifiedFields'].append('landAreaSqm')
                out.setdefault('fieldSources',{})[field]={'sourceUrl':snapshot['sourceUrl'],'fetchedAt':snapshot['fetchedAt'],
                                                       'registerId':str(row['mgmBldrgstPk']),'scope':'sole_main_building_whole_site'}
        if any(k in result['verifiedFields'] for k,_,_ in fields):
            result.update(status='verified_partial' if result['unresolvedFields'] else 'verified',
                          reason='전체 세대수를 포함하는 단일 주건축물의 공식 대장과 면적 계산으로 비율을 대조했어요. 확인한 항목만 평가에 사용했어요.')
            out['status']='ready' if out.get('floorAreaRatio') and out.get('buildingCoverageRatio') else 'partial'
    return out
