"""Verified one-to-one administrative code changes, without changing site identity.

Only the Ministry's explicit whole legal-dong transitions are used. A split
legal-dong, a different lot, an unmatched name or a future change is not an alias.
"""
import datetime as dt
from functools import lru_cache
import json
from pathlib import Path
import re
import apartment_identity

PATH=Path(__file__).resolve().parents[1]/'data/building_register_code_changes.json'
VERSION='register-identity-bridge-v2'

@lru_cache(maxsize=1)
def _read(stamp):
    data=json.loads(PATH.read_text())
    if data.get('version')!='official-register-code-changes-v1':raise ValueError('invalid code change source')
    return data

def revision():
    st=PATH.stat();return VERSION,st.st_mtime_ns,st.st_size

def _split_change(entity,data,code,day):
    """A split needs two independent official records for this exact site."""
    bound=data.get('parcelChanges',{}).get(str(entity.get('apartmentId') or '')) or {}
    expected=bound.get('expected') or {}
    if entity.get('aggregate') or entity.get('sectionIdentity') or not expected:return None
    if any(str(entity.get(k) or '')!=str(expected.get(k) or '') for k in
           ('apartmentId','name','province','district','legalDong','jibun','cortarNo','households')):return None
    row=bound.get('change') or {};proof=bound.get('corroboration') or {}
    if row not in data.get('ambiguous',{}).get(code,[]):return None
    basic=proof.get('basic') or {};register=proof.get('register') or {}
    b=basic.get('record') or {};r=register.get('record') or {}
    try:
        if day<dt.date.fromisoformat(basic['sourceDate']) or day<dt.date.fromisoformat(register['referenceMonth']+'-01'):return None
    except (KeyError,TypeError,ValueError):return None
    if (basic.get('sourceUrl')!='https://www.data.go.kr/data/15106861/fileData.do'
        or register.get('sourceUrl')!='https://www.hub.go.kr/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do'
        or any(not re.fullmatch(r'[0-9a-f]{64}',str(p.get('sourceSha256') or '')) for p in (basic,register))
        or register.get('uniqueCandidateCount')!=1):return None
    lot=apartment_identity.entity_parcel(entity);match=re.fullmatch(r'(산?)(\d{1,4})(?:-(\d{1,4}))?',lot)
    if not match:return None
    suffix=('2' if match[1] else '1')+match[2].zfill(4)+(match[3] or '0').zfill(4)
    if (b.get('단지고유번호')!=str(entity['apartmentId']) or b.get('필지고유번호')!=code+suffix
        or b.get('주소')!=row['fromRegion']+' '+row['fromName']+' '+lot
        or str(b.get('세대수'))!=str(entity.get('households'))
        or str(r.get('hhldCnt'))!=str(entity.get('households'))
        or not re.fullmatch(r'[1-9]\d*',str(entity.get('households') or ''))
        or str(r.get('regstrKindCd'))!='1' or '공동주택' not in str(r.get('mainPurpsCdNm'))
        or not r.get('mgmBldrgstPk')
        or str(r.get('sigunguCd'))+str(r.get('bjdongCd'))!=row['toCode']
        or str(r.get('platGbCd'))!=('1' if match[1] else '0')
        or str(r.get('bun'))!=match[2].zfill(4) or str(r.get('ji'))!=(match[3] or '0').zfill(4)):return None
    normalize=lambda v:re.sub(r'[^0-9A-Za-z가-힣]','',str(v or '')).removesuffix('아파트')
    names={normalize(b.get(k)) for k in ('단지명_공시가격','단지명_건축물대장','단지명_도로명주소')}-{''}
    if normalize(r.get('bldNm')) not in names or apartment_identity.phase_conflicts(entity['name'],r.get('bldNm')):return None
    return {**row,'parcelScopeVerified':True}

def changes(entity,*,day=None):
    day=day or dt.date.today()
    try:data=_read(revision())
    except (OSError,ValueError,TypeError):return []
    code=str(entity.get('cortarNo') or '');name=str(entity.get('legalDong') or '');province=str(entity.get('province') or '')
    if not re.fullmatch(r'\d{10}',code) or not province or not name:return []
    result=[];seen=set()
    for _ in range(4):
        row=(_split_change(entity,data,code,day) if code in data.get('ambiguous',{})
             else data.get('changes',{}).get(code))
        if not row:break
        try:effective=dt.date.fromisoformat(row['effectiveAt'])
        except (KeyError,ValueError,TypeError):return []
        if day<effective:break
        if (code in seen or row.get('fromCode')!=code or row.get('fromName')!=name
            or not str(row.get('fromRegion') or '').startswith(province+' ')
            or not str(row.get('toRegion') or '').startswith(province+' ')
            or not re.fullmatch(r'\d{10}',str(row.get('toCode') or ''))
            or not str(row.get('sourceUrl') or '').startswith('https://www.mois.go.kr/frt/bbs/')
            or not re.fullmatch(r'[0-9a-f]{64}',str(row.get('sourceSha256') or ''))):return []
        seen.add(code);result.append(dict(row));code=row['toCode'];name=row['toName']
    return result

def variants(entity,parcel,*,day=None):
    if not parcel:return []
    result=[dict(parcel)]
    for row in changes(entity,day=day):
        result.append({**parcel,'sigunguCd':row['toCode'][:5],'bjdongCd':row['toCode'][5:]})
    return result

def parcel_key(parcel):
    return ''.join(parcel[k] for k in ('sigunguCd','bjdongCd','platGbCd','bun','ji'))

def pnu_variants(entity,parcel,*,day=None):
    return [p['sigunguCd']+p['bjdongCd']+('2' if p['platGbCd']=='1' else '1')+p['bun']+p['ji'] for p in variants(entity,parcel,day=day)]

def display_dong_names(entity,*,day=None):
    """EUM labels a split dong with its exact, official destination district."""
    day=day or dt.date.today();name=str(entity.get('legalDong') or '');names=[name]
    try:data=_read(revision())
    except (OSError,ValueError,TypeError):return names
    region=' '.join((str(entity.get('province') or ''),str(entity.get('district') or '')))
    for choices in data.get('ambiguous',{}).values():
        for row in choices:
            if (row.get('toCode')==entity.get('cortarNo') and row.get('toName')==name
                and row.get('toRegion')==region and row.get('effectiveAt','9999')<=day.isoformat()):
                district=region.rsplit(' ',1)[-1]
                if re.fullmatch(r'[가-힣]+구',district):names.append(name+'('+district+')')
    return list(dict.fromkeys(names))

def query_entity(entity,*,day=None):
    rows=changes(entity,day=day)
    if not rows:
        try:data=_read(revision())
        except (OSError,ValueError,TypeError):return dict(entity)
        matches=[v for v in data.get('changes',{}).values() if v.get('toCode')==entity.get('cortarNo') and v.get('toName')==entity.get('legalDong') and str(v.get('toRegion') or '').startswith(str(entity.get('province'))+' ') and v.get('effectiveAt','9999')<=str(day or dt.date.today())]
        regions={v['toRegion'] for v in matches}
        return {**entity,'district':next(iter(regions))[len(entity['province'])+1:]} if len(regions)==1 else dict(entity)
    row=rows[-1];out={**entity,'cortarNo':row['toCode'],'legalDong':row['toName'],'district':row['toRegion'][len(entity['province'])+1:]}
    # Retain the exact 읍/면/리 and lot tokens; replace only the verified region/name.
    address=str(entity.get('address') or '')
    first=rows[0];prefix=first['fromRegion']
    if address.startswith(prefix+' '):
        address=row['toRegion']+address[len(prefix):]
        if first['fromName']!=row['toName']:
            address=re.sub(r'(?<=\s)'+re.escape(first['fromName'])+r'(?=\s|$)',row['toName'],address,count=1)
        out['address']=address
    return out
