"""Publish only checked building-register counts for the two pilot reports."""

import datetime as dt
import json
import sqlite3

import config
from building_hub import DB_PATH, SOURCE_URL


OUTPUT_PATH = config.ROOT / 'data/building_hub_pilot_summary.json'
PILOT_PATH = config.ROOT / 'data/future_transformation_pilots.json'
PILOT_AREAS = {
    '484457631ccb1633': [('산성동', '4113110500')],
    '449db7d556b8ba86': [('이문동', '1123011000'), ('휘경동', '1123010900')],
}
RESIDENTIAL_PURPOSES = {'단독주택', '공동주택'}


def residential_age_summary(records, fetched_date):
    """Count residential title records with a verifiable approval date."""
    as_of = dt.date.fromisoformat(fetched_date)
    try:
        cutoff = as_of.replace(year=as_of.year - 30)
    except ValueError:  # February 29
        cutoff = as_of.replace(year=as_of.year - 30, day=28)
    residential_count = dated_count = old_count = 0
    for record in records:
        if not isinstance(record, dict) or record.get('mainPurpsCdNm') not in RESIDENTIAL_PURPOSES:
            continue
        residential_count += 1
        raw_date = str(record.get('useAprDay') or '')
        if len(raw_date) != 8 or not raw_date.isascii() or not raw_date.isdigit():
            continue
        try:
            approved = dt.datetime.strptime(raw_date, '%Y%m%d').date()
        except ValueError:
            continue
        if approved > as_of:
            continue
        dated_count += 1
        old_count += approved <= cutoff
    return {
        'residentialRecordCount': residential_count,
        'approvalDateCount': dated_count,
        'age30RecordCount': old_count,
        'age30SharePct': round(old_count / dated_count * 100, 1) if dated_count else None,
    }


def build_summary(db_path=DB_PATH, pilot_path=PILOT_PATH):
    pilots = {item['apartmentId']: item for item in json.loads(pilot_path.read_text())}
    result = []
    with sqlite3.connect(db_path) as db:
        for apartment_id, area_definitions in PILOT_AREAS.items():
            identity = pilots[apartment_id]['identity']
            areas = []
            for name, dong_code in area_definitions:
                row = db.execute('SELECT fetched_at, source_url, total_count, payload FROM dong_snapshots '
                                 'WHERE dong_id=? ORDER BY fetched_at DESC LIMIT 1', (dong_code,)).fetchone()
                if not row:
                    raise ValueError(f'{name} 건축물대장 자료가 없습니다.')
                fetched_at, source_url, count, raw = row
                snapshot = json.loads(raw)
                if (source_url != SOURCE_URL or snapshot.get('sourceUrl') != SOURCE_URL
                        or snapshot.get('dong') != {'sigunguCd': dong_code[:5], 'bjdongCd': dong_code[5:]}
                        or count < 0 or count != snapshot.get('totalCount')
                        or count != len(snapshot.get('records', []))):
                    raise ValueError(f'{name} 건축물대장 자료를 검증할 수 없습니다.')
                fetched_date = dt.datetime.fromisoformat(fetched_at).date().isoformat()
                areas.append({'legalDong': name, 'dongCode': dong_code,
                              'recordCount': count, 'fetchedAt': fetched_date,
                              **residential_age_summary(snapshot['records'], fetched_date)})
            result.append({'apartmentId': apartment_id, 'identity': identity,
                           'source': '국토교통부 건축HUB 건축물대장 표제부',
                           'sourceUrl': SOURCE_URL, 'areas': areas})
    return result


def main():
    summary = build_summary()
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(f'리포트용 건축물대장 건수 저장 완료: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
