"""Import official exports or reviewed, exact-complex observations.

Example: python pipeline/import_living_area.py seoul-plan-renewal export.json --as-of 2026-10-13
Incomplete API responses and source-ID collisions are rejected atomically.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import living_area
import living_area_sources as sources


def save_observation(document, *, path=None, registry_lookup=None):
    if registry_lookup is None:
        from future_transformation import registry_entity
        registry_lookup = registry_entity
    apartment_id = document.get('apartmentId')
    entity = registry_lookup(apartment_id)
    if (not entity or not apartment_id or document.get('modelVersion') != living_area.policy.VERSION
            or any(document.get('identity', {}).get(k) != entity.get(k) for k in ('district', 'legalDong', 'jibun'))):
        raise sources.SourceError('단지 고유값·법정동·지번과 산식 버전이 일치해야 해요.')
    evidence = document.get('evidence', {})
    if not evidence or not all(living_area.evidence_valid(e, dt.date.today()) for e in evidence.values()):
        raise sources.SourceError('상업 이용·기준일·원본 근거를 확인해야 해요.')
    db = sources.connection(path)
    try:
        # A claim of verification alone cannot unlock a source. Match the saved raw snapshot.
        for e in evidence.values():
            row = db.execute('SELECT source_id,as_of,raw_json FROM source_snapshots WHERE id=? AND complete=1', (e['snapshotId'],)).fetchone()
            if not row or row[0] != e['sourceId'] or row[1] != e['asOfDate'] or e['raw'] not in json.loads(row[2]):
                raise sources.SourceError('저장된 공식 원본과 분석 근거가 일치하지 않아요.')
        if not living_area.point_valid(document.get('center'), evidence, dt.date.today()):
            raise sources.SourceError('상업 이용과 위치 근거가 확인된 단지 좌표가 필요해요.')
        sources.digest(document)  # Reject non-finite numbers before saving.
        with db:
            db.execute('INSERT OR REPLACE INTO complex_observations VALUES (?,?)', (apartment_id, json.dumps(document, ensure_ascii=False)))
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', choices=['seoul-plan-renewal', 'molit-renewal', 'seoul-apartment-points', 'observations'])
    parser.add_argument('file', type=Path, nargs='?')
    parser.add_argument('--fetch', action='store_true', help='서울시 공식 HTTPS 파일과 총건수를 대조해 수집')
    parser.add_argument('--as-of', help='공식 파일의 데이터 기준일. 수집일로 대체하지 않습니다.')
    args = parser.parse_args()
    try:
        if not args.file and not (args.fetch and args.source in ('seoul-plan-renewal', 'seoul-apartment-points')):
            parser.error('공식 파일 또는 seoul-plan-renewal --fetch가 필요합니다.')
        if args.source == 'seoul-apartment-points':
            if not args.fetch:
                parser.error('단지 좌표는 총건수를 검증하는 --fetch로 갱신합니다.')
            import living_area_context
            living_area_context.save_points(sources.fetch_seoul(source_id=args.source))
        elif args.source == 'observations':
            save_observation(json.loads(args.file.read_text()))
        else:
            rows = sources.fetch_seoul() if args.fetch and args.source == 'seoul-plan-renewal' else sources.read_export(args.file)
            sources.save_snapshot(args.source, rows, as_of=args.as_of, complete=True)
        print('공식 원본과 분석 자료를 저장했습니다.')
    except (sources.SourceError, OSError, ValueError) as exc:
        parser.exit(1, f'등록 보류: {exc}\n')


if __name__ == '__main__':
    main()
