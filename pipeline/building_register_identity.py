"""Verified one-to-one administrative code changes, without changing site identity.

Only the Ministry's explicit whole legal-dong transitions are used. A split
legal-dong, a different lot, an unmatched name or a future change is not an alias.
"""
import datetime as dt
from functools import lru_cache
import json
from pathlib import Path
import re

PATH=Path(__file__).resolve().parents[1]/'data/building_register_code_changes.json'
VERSION='register-identity-bridge-v1'

@lru_cache(maxsize=1)
def _read(stamp):
    data=json.loads(PATH.read_text())
    if data.get('version')!='official-register-code-changes-v1':raise ValueError('invalid code change source')
    return data

def revision():
    st=PATH.stat();return VERSION,st.st_mtime_ns,st.st_size

def changes(entity,*,day=None):
    day=day or dt.date.today()
    try:data=_read(revision())
    except (OSError,ValueError,TypeError):return []
    code=str(entity.get('cortarNo') or '');name=str(entity.get('legalDong') or '');province=str(entity.get('province') or '')
    if not re.fullmatch(r'\d{10}',code) or not province or not name:return []
    result=[];seen=set()
    for _ in range(4):
        if code in data.get('ambiguous',{}):return []
        row=data.get('changes',{}).get(code)
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

def query_entity(entity,*,day=None):
    rows=changes(entity,day=day)
    if not rows:return dict(entity)
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
