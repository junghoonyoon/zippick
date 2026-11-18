"""Repair factual source gaps on the primary; never replace verified site scopes.

Run only a committed release. All writes are locked and atomic. API collection
stops on permission/quota errors; an empty or failed response preserves success.
"""
import argparse
import collections
from contextlib import nullcontext
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time

import apartment_identity
import apartment_reconstruction as r
import building_hub
import building_register_identity as identity
import building_register_single_site as single
import persistent_json_store as store
import shared_data

STOP_CODES={'20','21','22','30','31','32','99','401','403','429','missing_key'}

def catalogue():
    import real_estate_search
    seen=set();out=[]
    for e in real_estate_search.APARTMENT_MASTER:
        pk=e.get('apartmentId')
        if e.get('aggregate') or not pk or pk in seen:continue
        seen.add(pk);out.append(e)
    return out

def canonical(value):
    return re.sub(r'[^0-9A-Za-z가-힣]','',str(value or '')).removesuffix('아파트')

def import_basic(path, entities, *, source_date, apply=False):
    source_day=dt.date.fromisoformat(source_date)
    if not 0<=(dt.date.today()-source_day).days<=180:raise ValueError('stale official basic data')
    records={};duplicate=set()
    with Path(path).open(encoding='cp949',newline='') as f:
        for raw in csv.DictReader(f):
            row={k:v.strip() for k,v in raw.items()};pk=row['단지고유번호']
            if pk in records:duplicate.add(pk)
            records[pk]=row
    result=collections.Counter(sourceRows=len(records),duplicateIds=len(duplicate));candidates={}
    dest=shared_data.cache_path(single.FILE);existing=store.read_json_object(dest)['records']
    for e in entities:
        pk=e['apartmentId'];s=(existing.get(pk) or {}).get('snapshot') or {};rows=s.get('records') or []
        # A missing title name needs independent identity evidence, not a fuzzy name.
        if len(rows)!=1 or str(rows[0].get('bldNm') or '').strip():continue
        raw=records.get(pk)
        if not raw or pk in duplicate:result['noUniqueBasic']+=1;continue
        if raw.get('필지고유번호') not in identity.pnu_variants(e,r.parcel(e)) or r.number(raw.get('세대수'))!=r.number(e.get('households')) or not r.number(e.get('households')):
            result['identityConflict']+=1;continue
        names={canonical(raw.get(k)) for k in ('단지명_공시가격','단지명_건축물대장','단지명_도로명주소')}-{''}
        aliases=[e['name'],*(v for v in e.get('aliases') or [] if not apartment_identity.phase_conflicts(e['name'],v))]
        if not names.intersection(canonical(v) for v in aliases):result['nameConflict']+=1;continue
        candidates[pk]=raw
    result['verifiedCandidates']=len(candidates)
    if apply:
        shared_data.require_writer()
        digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with store.exclusive_file_lock(dest):
            current=store.read_json_object(dest)
            for pk,row in candidates.items():
                current['records'][pk]={**current['records'][pk],'officialBasic':{'sourceUrl':'https://www.data.go.kr/data/15106861/fileData.do','sourceDate':source_date,'fetchedAt':dt.datetime.fromtimestamp(Path(path).stat().st_mtime,dt.timezone.utc).isoformat(),'sourceSha256':digest,'record':row}}
            current['updatedAt']=dt.datetime.now(dt.timezone.utc).isoformat();store.write_json_atomically(dest,current)
        result['written']=len(candidates)
    return dict(result)

def collect_title_gaps(entities, *, apply=False, limit=1000):
    registers=store.read_json_object(shared_data.cache_path(r.FACT_FILE))['records']
    dest=shared_data.cache_path(single.FILE);old=store.read_json_object(dest)['records'];targets=[]
    for e in entities:
        if not r.parcel(e):continue
        entry=r.register_entry(e,registers) or {}
        if r.profile(e,entry).get('status') in ('ready','partial'):continue
        prior=old.get(e['apartmentId']) or {};snapshot=prior.get('snapshot') or {}
        # A complete recent observation already answers this parcel. No retry loop.
        if snapshot.get('records') or prior.get('status')=='no_records' and snapshot.get('parcel')==r.register_lookup_parcel(e):continue
        targets.append(e)
    result={'targets':len(targets),'selected':min(len(targets),limit),'processed':0,'success':0,'failed':0,'noRecords':0,'stoppedCode':None,'unprocessed':0}
    if not apply:return result
    shared_data.require_writer();changes={};last=0.0
    pending=shared_data.cache_path('building_register_gap_pending.json')
    for e in targets[:limit]:
        p=r.register_lookup_parcel(e);time.sleep(max(0,1-(time.monotonic()-last)));last=time.monotonic()
        now=dt.datetime.now(dt.timezone.utc).isoformat();record={**(old.get(e['apartmentId']) or {}),'identity':{k:e.get(k,'') for k in ('apartmentId','name','province','district','legalDong','jibun','cortarNo','households')}}
        try:
            snapshot=building_hub.fetch_title_records(p['sigunguCd'],p['bjdongCd'],p['bun'],p['ji'],plat_gb_cd=p['platGbCd'])
            record.update(status='ok' if snapshot['records'] else 'no_records',snapshot=snapshot,checkedAt=now);record.pop('lastError',None)
            result['success' if snapshot['records'] else 'noRecords']+=1
        except building_hub.BuildingHubError as exc:
            record['lastError']={'status':'access_denied' if exc.code in STOP_CODES else 'connection_error','errorCode':exc.code,'checkedAt':now};result['failed']+=1
            if exc.code in STOP_CODES:result['stoppedCode']=exc.code
        changes[e['apartmentId']]=record;result['processed']+=1
        store.write_json_atomically(pending,{'records':changes,'result':result})
        if result['processed']%10==0:print(json.dumps(result),flush=True)
        if result['stoppedCode']:break
    with store.exclusive_file_lock(dest):
        current=store.read_json_object(dest)
        for pk,value in changes.items():
            concurrent=current['records'].get(pk) or {}
            if (concurrent.get('snapshot') or {}).get('records') and not (value.get('snapshot') or {}).get('records'):continue
            merged={**concurrent,**{k:value[k] for k in ('identity','status','snapshot','checkedAt') if k in value}}
            if value.get('lastError'):merged['lastError']=value['lastError']
            else:merged.pop('lastError',None)
            current['records'][pk]=merged
        current['updatedAt']=dt.datetime.now(dt.timezone.utc).isoformat();store.write_json_atomically(dest,current)
    result['unprocessed']=result['selected']-result['processed'];return result

def import_planning_pages(path, entities, *, apply=False, return_records=False):
    import collect_reconstruction_planning as collector
    from urllib.parse import parse_qs,urlsplit
    path=Path(path);manifest=json.loads(path.read_text());pages=manifest.get('pages')
    if not isinstance(pages,dict):raise ValueError('invalid planning page manifest')
    by_id={e['apartmentId']:e for e in entities};prepared={};result=collections.Counter(total=len(pages))
    fields=('apartmentId','province','district','legalDong','jibun','cortarNo')
    today=dt.date.today()
    for pk,item in pages.items():
        entity=by_id.get(pk)
        if not entity or any(str((item.get('identity') or {}).get(k) or '')!=str(entity.get(k) or '') for k in fields):result['identityMismatch']+=1;continue
        name=item.get('file') or ''
        if Path(name).name!=name or not name.endswith('.html'):raise ValueError('invalid page filename')
        raw=(path.parent/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item.get('sha256'):raise ValueError('planning page checksum mismatch')
        observed=dt.datetime.fromisoformat(item['observedAt']);day=observed.date()
        if observed.tzinfo is None or not 0<=(today-day).days<=180:raise ValueError('invalid planning observation date')
        query=identity.query_entity(entity);source=urlsplit(item.get('sourceUrl') or '');expected=urlsplit(collector.SOURCE_URL)
        if (source.scheme!=expected.scheme or source.netloc!=expected.netloc or source.path!=expected.path
            or parse_qs(source.query).get('pnu')!=[r.parcel_pnu(query)]):raise ValueError('planning source URL mismatch')
        model={'identity':{k:entity.get(k,'') for k in fields}}
        try:
            reference=collector.parse_public_page(raw,query,day=day);reference['observedAt']=item['observedAt']
            model['parcelReference']=reference
            if not r._parcel_reference(entity,model,today):raise ValueError('unverified parsed planning page')
            result['verified']+=1
        except collector.PlanningError as exc:
            model['lastError']={'status':exc.status,'errorCode':exc.code,'checkedAt':item['observedAt']}
            result['sourceUnverified']+=1;result['classification_'+exc.status]+=1
        prepared[pk]=model
    if apply:
        shared_data.require_writer();destination=shared_data.cache_path(r.PLANNING_FILE)
        with store.exclusive_file_lock(destination):
            data=store.read_json_object(destination)
            for pk,value in prepared.items():
                previous=data['records'].get(pk) or {};old_id=previous.get('identity') or {}
                if old_id and any(str(old_id.get(k) or '')!=str(value['identity'].get(k) or '') for k in fields):result['storedIdentityMismatch']+=1;continue
                data['records'][pk]={**previous,**value}
                if not value.get('lastError'):data['records'][pk].pop('lastError',None)
                result['written']+=1
            data['updatedAt']=dt.datetime.now(dt.timezone.utc).isoformat();store.write_json_atomically(destination,data)
    return {**result,'records':prepared} if return_records else dict(result)


def migrate_identities(entities, *, apply=False):
    corrections=json.loads((Path(__file__).resolve().parents[1]/'data/apartment_identity_corrections.json').read_text())['corrections']
    result=collections.Counter()
    for name in (single.FILE,r.PLANNING_FILE):
        path=shared_data.cache_path(name)
        if apply:shared_data.require_writer()
        with store.exclusive_file_lock(path) if apply else nullcontext():
            data=store.read_json_object(path)
            for e in entities:
                if not e.get('identityCorrection'):continue
                pk=e['apartmentId'];old=data['records'].get(pk)
                if not old:continue
                current_id={k:e.get(k,'') for k in ('apartmentId','name','province','district','legalDong','jibun','cortarNo','households')}
                fields=('apartmentId','province','district','legalDong','jibun','cortarNo')
                if all(str((old.get('identity') or {}).get(k) or '')==str(current_id.get(k) or '') for k in fields):continue
                expected=corrections[pk]['expected']
                if any(str((old.get('identity') or {}).get(k) or '')!=str(expected.get(k) or '') for k in fields):result['identityConflict']+=1;continue
                result['migrated']+=1
                if apply:data['records'][pk]={'identity':current_id,'status':'not_collected','previousIdentity':old}
            if apply:store.write_json_atomically(path,data)
    return dict(result)


def planning_targets(entities,planning):
    targets=[]
    for e in entities:
        prior=planning.get(e['apartmentId']) or {};err=prior.get('lastError') or {}
        changes=identity.changes(e)
        split=any(row.get('parcelScopeVerified') for row in changes)
        current_pnu=r.parcel_pnu(identity.query_entity(e))
        if ((err.get('errorCode') in ('address_mismatch','attribution_missing','network')
             and (changes or err.get('status')=='connection_error'))
            or (e.get('identityCorrection') and not prior.get('parcelReference'))
            or (split and (err or (prior.get('parcelReference') or {}).get('pnu')!=current_pnu))):
            targets.append(e)
    return targets

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['official-basic','title-gaps','planning-gaps','administrative-recaps','migrate-identities','planning-pages']);p.add_argument('--source',type=Path);p.add_argument('--source-date',default='2026-08-31');p.add_argument('--limit',type=int,default=1000);p.add_argument('--apply',action='store_true');a=p.parse_args()
    entities=catalogue()
    if a.action=='migrate-identities':
        result=migrate_identities(entities,apply=a.apply)
    elif a.action=='planning-pages':
        if not a.source:p.error('--source is required')
        result=import_planning_pages(a.source,entities,apply=a.apply)
    elif a.action=='official-basic':
        if not a.source:p.error('--source is required')
        result=import_basic(a.source,entities,source_date=a.source_date,apply=a.apply)
    elif a.action=='title-gaps':result=collect_title_gaps(entities,apply=a.apply,limit=a.limit)
    elif a.action=='administrative-recaps':
        targets=[e for e in entities if (identity.changes(e) or e.get('identityCorrection')) and r.parcel(e)]
        if a.apply:
            import collect_building_register
            result=collect_building_register.collect(targets[:a.limit])
        else:result={'targets':len(targets),'selected':min(len(targets),a.limit)}
    else:
        planning=store.read_json_object(shared_data.cache_path(r.PLANNING_FILE))['records']
        targets=planning_targets(entities,planning)
        if a.apply:
            import collect_reconstruction_planning
            result=collect_reconstruction_planning.collect(targets[:a.limit],refresh=True)
        else:result={'targets':len(targets),'selected':min(len(targets),a.limit)}
    if a.apply:
        store.write_json_atomically(shared_data.cache_path('register_source_repair_'+a.action+'.json'),result)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
