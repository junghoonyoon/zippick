"""Import an official building-HUB recap archive into the primary source.

The archive's reference date is distinct from its download date. Only exact,
unambiguous complex matches are imported; newer API observations win.
"""
import collections
import datetime as dt
import json
from pathlib import Path
import building_register_identity
import zipfile

import apartment_reconstruction as reconstruction
import persistent_json_store as store
import shared_data

SOURCE_URL = 'https://www.hub.go.kr/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do'
FIELDS = {0: 'mgmBldrgstPk', 1: 'regstrGbCd', 3: 'regstrKindCd',
          5: 'newOldRegstrGbCd', 7: 'platPlc', 8: 'newPlatPlc', 9: 'bldNm',
          10: 'sigunguCd', 11: 'bjdongCd', 12: 'platGbCd', 13: 'bun', 14: 'ji',
          24: 'platArea', 25: 'archArea', 26: 'bcRat', 27: 'totArea',
          28: 'vlRatEstmTotArea', 29: 'vlRat', 31: 'mainPurpsCdNm',
          33: 'hhldCnt', 35: 'mainBldCnt', 36: 'atchBldCnt', 37: 'atchBldArea',
          49: 'useAprDay', 63: 'crtnDay'}


def import_archive(path, entities, as_of):
    shared_data.require_writer()
    month_only = len(as_of)==7
    day = dt.date.fromisoformat(as_of+"-01" if month_only else as_of)
    acquired = dt.datetime.fromtimestamp(Path(path).stat().st_mtime,dt.timezone.utc).isoformat()
    if day > dt.date.today():
        raise ValueError('future reference date')
    entities = [e for e in entities if e.get('apartmentId') and not e.get('aggregate')]
    wanted = {building_register_identity.parcel_key(p) for e in entities for p in [reconstruction.register_lookup_parcel(e)] if p}
    rows = collections.defaultdict(list)
    total = 0
    with zipfile.ZipFile(path) as archive:
        files = [i for i in archive.infolist() if not i.is_dir()]
        if len(files) != 1 or files[0].filename != 'mart_djy_02.txt':
            raise ValueError('unexpected archive contents')
        with archive.open(files[0]) as stream:
            for raw in stream:
                row = raw.decode('utf-8').rstrip('\r\n').split('|')
                if len(row) != 64:
                    raise ValueError('unexpected recap field count')
                total += 1
                key = ''.join(row[10:15])
                if key in wanted:
                    rows[key].append({name: row[index] for index, name in FIELDS.items()})
        if archive.testzip() is not None:raise ValueError('corrupt archive')
    if not total:
        raise ValueError('empty recap archive')
    candidates, owners, outcomes = {}, collections.defaultdict(set), collections.Counter()
    for entity in entities:
        parcel = reconstruction.register_lookup_parcel(entity)
        if not parcel:
            outcomes['identity_missing'] += 1
            continue
        key = building_register_identity.parcel_key(parcel)
        records = rows.get(key, [])
        snapshot = {'parcel': parcel, 'source': '국토교통부 건축HUB 건축물대장 총괄표제부',
                    'sourceUrl': SOURCE_URL, 'fetchedAt': acquired,
                    'referenceMonth':as_of[:7], 'referenceDatePrecision':'month' if month_only else 'day',
                    'recordType': 'recap', 'totalCount': len(records), 'records': records}
        status = reconstruction.profile(entity, {'snapshot': snapshot})['status']
        outcomes[status] += 1
        if status in ('ready', 'partial'):
            candidates[key] = snapshot
            owners[key].add(str(entity['apartmentId']))
    ambiguous = {key for key, ids in owners.items() if len(ids) > 1}
    for key in ambiguous:
        del candidates[key]
    destination = shared_data.cache_path(reconstruction.FACT_FILE)
    with store.exclusive_file_lock(destination):
        data = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {'version': 1, 'records': {}}
        if not isinstance(data, dict) or not isinstance(data.get('records'), dict):
            raise ValueError('invalid existing register source')
        inserted = preserved = 0
        for key, snapshot in candidates.items():
            old = data['records'].get(key) or {}
            # Never replace an API result, even a newer empty result, with an
            # older bulk observation. Failed queries remain explicit.
            if old.get('snapshot') or old.get('status') == 'no_records':
                preserved += 1
                continue
            entry = {'status': 'ok', 'checkedAt': snapshot['fetchedAt'], 'snapshot': snapshot}
            if old.get('status') in ('connection_error', 'access_denied'):
                entry['lastError'] = {k: v for k, v in old.items() if k != 'snapshot'}
            data['records'][key] = entry
            inserted += 1
        data['updatedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
        store.write_json_atomically(destination, data)
    return {'archiveRows': total, 'entities': len(entities), 'parcelMatches': len(rows),
            'outcomes': dict(outcomes), 'candidateParcels': len(candidates),
            'ambiguousParcels': len(ambiguous), 'inserted': inserted,
            'preserved': preserved, 'asOf': as_of}


TITLE_FIELDS={0:'mgmBldrgstPk',1:'regstrGbCd',3:'regstrKindCd',5:'platPlc',6:'newPlatPlc',7:'bldNm',8:'sigunguCd',9:'bjdongCd',10:'platGbCd',11:'bun',12:'ji',16:'bylotCnt',22:'dongNm',23:'mainAtchGbCd',25:'platArea',26:'archArea',27:'bcRat',28:'totArea',29:'vlRatEstmTotArea',30:'vlRat',35:'mainPurpsCdNm',36:'etcPurps',40:'hhldCnt',43:'grndFlrCnt',44:'ugrndFlrCnt',47:'atchBldCnt',48:'atchBldArea',60:'useAprDay',74:'crtnDay'}

def title_archive_plan(path,entities,as_of):
    reference=dt.date.fromisoformat(as_of+'-01')
    if not 0<=(dt.date.today()-reference).days<=180:raise ValueError('invalid title reference month')
    entities=[e for e in entities if e.get('apartmentId') and not e.get('aggregate') and reconstruction.parcel(e)]
    parcels={building_register_identity.parcel_key(p):p for e in entities for p in [reconstruction.register_lookup_parcel(e)] if p}
    rows=collections.defaultdict(list);count=0
    with zipfile.ZipFile(path) as archive:
        if archive.namelist()!=['mart_djy_03.txt']:raise ValueError('unexpected title archive')
        for raw in archive.open('mart_djy_03.txt'):
            row=raw.decode('utf-8').rstrip('\r\n').split('|')
            if len(row)!=77:raise ValueError('unexpected title field count')
            count+=1;key=''.join(row[8:13])
            if key in parcels:rows[key].append({v:row[i] for i,v in TITLE_FIELDS.items()})
        if archive.testzip() is not None:raise ValueError('corrupt title archive')
    if not count:raise ValueError('empty title archive')
    acquired=dt.datetime.fromtimestamp(Path(path).stat().st_mtime,dt.timezone.utc).isoformat();prepared={}
    for e in entities:
        p=reconstruction.register_lookup_parcel(e);records=rows.get(building_register_identity.parcel_key(p),[])
        if not records:continue
        ids=[str(row.get('mgmBldrgstPk') or '') for row in records]
        if any(not k for k in ids) or len(ids)!=len(set(ids)):continue
        prepared[e['apartmentId']]={'identity':{k:e.get(k,'') for k in ('apartmentId','name','province','district','legalDong','jibun','cortarNo','households')},'status':'ok','checkedAt':acquired,'snapshot':{'parcel':p,'recordType':'title','source':'국토교통부 건축HUB 건축물대장 표제부','sourceUrl':SOURCE_URL,'referenceMonth':as_of,'referenceDatePrecision':'month','fetchedAt':acquired,'totalCount':len(records),'records':records}}
    return prepared,{'archiveRows':count,'preparedSites':len(prepared)}


def import_title_archive(path,entities,as_of):
    shared_data.require_writer()
    prepared,result=title_archive_plan(path,entities,as_of)
    destination=shared_data.cache_path('building_register_crosschecks.json');inserted=preserved=0
    with store.exclusive_file_lock(destination):
        data=store.read_json_object(destination)
        for pk,value in prepared.items():
            previous=data['records'].get(pk) or {};snapshot=previous.get('snapshot') or {}
            if snapshot.get('records') or (previous.get('status')=='no_records' and snapshot.get('parcel') in (None,value['snapshot']['parcel'])):
                preserved+=1;continue
            old_id=previous.get('identity') or {}
            if old_id and any(str(old_id.get(k) or '')!=str(value['identity'].get(k) or '') for k in ('apartmentId','province','district','legalDong','jibun','cortarNo')):raise ValueError('stored title identity mismatch')
            merged={**previous,**value}
            if previous.get('lastError'):merged['previousFailure']=previous['lastError'];merged.pop('lastError',None)
            if snapshot:merged['previousSnapshot']=snapshot
            data['records'][pk]=merged;inserted+=1
        data['updatedAt']=dt.datetime.now(dt.timezone.utc).isoformat();store.write_json_atomically(destination,data)
    return {**result,'inserted':inserted,'preserved':preserved}


if __name__ == '__main__':
    import argparse
    import real_estate_search
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--record-type', choices=['recap','title'],default='recap')
    args = parser.parse_args()
    function=import_archive if args.record_type=='recap' else import_title_archive
    print(json.dumps(function(args.archive, real_estate_search.APARTMENT_MASTER, args.as_of), ensure_ascii=False))
