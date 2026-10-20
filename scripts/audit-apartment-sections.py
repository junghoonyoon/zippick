#!/usr/bin/env python3
"""Offline, repeatable section/name/Naver integrity audit of the complete catalog."""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import apartment_identity as identity
import apartment_sections
import real_estate_search as search
import naver_complex as naver


def audit():
    master = [e for e in search.APARTMENT_MASTER if not e.get('aggregate')]
    omitted = [e for e in master if e.get('district') and not identity.phase_numbers(e['name'])
               and any(identity.phase_numbers(a) for a in e.get('aliases', []))]
    promoted = set()
    source_count = 0
    for path in search.APARTMENT_CSV_PATHS:
        if not path.exists():
            continue
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                source_count += 1
                if search._is_rental_row(row) or (row.get('단지종류명') and row['단지종류명'] != '아파트'):
                    continue
                name = search._apartment_display_name(row)
                if (not identity.phase_numbers(row.get('대표단지명')) and identity.phase_numbers(name)):
                    promoted.add((name, row.get('시도'), row.get('자치구') or row.get('시군구'), row.get('법정동'), identity.parcel_key(row.get('지번'))))
    entries = json.loads(naver.STATIC_OVERRIDES_PATH.read_text())['entries']
    phase_errors = [e for e in entries if identity.phase_conflicts(e['name'], e.get('complexName'))
                    and not naver.verified_phase_alias(e['name'], e)]
    rejected = [e for e in entries if naver.rejected_mapping(e['complexNo'], e['legalDong'], e['jibun'], e.get('region'))]
    unresolved_reviews = [r for r in naver.mapping_reviews() if r['status'] == 'unresolved']
    section_identity_errors = []
    section_mappings = []
    for group in apartment_sections.groups():
        for section in group.get('sections', []):
            latitude = section.get('latitude')
            longitude = section.get('longitude')
            try:
                valid_coordinate = 33 <= float(latitude) <= 39 and 124 <= float(longitude) <= 132
            except (TypeError, ValueError):
                valid_coordinate = False
            resolved = naver.resolve_static(
                section['name'], group['legalDong'], section['jibun'], region=group['district'],
            )
            expected_complex_no = str(section.get('naverComplexNo') or '')
            if not valid_coordinate or not expected_complex_no or not resolved or resolved.get('complexNo') != expected_complex_no:
                section_identity_errors.append({
                    'name': section['name'], 'address': section.get('address'),
                    'coordinates': [latitude, longitude], 'expectedComplexNo': expected_complex_no,
                    'resolvedComplexNo': (resolved or {}).get('complexNo'),
                })
            section_mappings.append({
                'name': section['name'], 'apartmentId': section['apartmentId'],
                'address': section.get('address'), 'coordinates': [latitude, longitude],
                'naverComplexNo': expected_complex_no,
                'naverComplexName': section.get('naverComplexName'),
                'naverScope': section.get('naverScope'),
            })
    # Registry entries are exercised through the same resolver used by cards.
    resolution_errors = []
    for review in naver.mapping_reviews():
        if review['status'] not in {'corrected', 'verified_name_difference'}:
            continue
        for alias in review['aliases']:
            result = naver.resolve_static(alias, review['legalDong'], review['jibun'], region=review['region'])
            if not result or result['complexNo'] != review['complexNo']:
                resolution_errors.append({'name': alias, 'expected': review['complexNo'], 'actual': result})
    imun = search.suggest_apartments('이문아이파크자이')
    for row in imun:
        row.update(naver.resolve_static(row['name'], row['legalDong'], row['jibun'], region=row['region']) or {})
    failures = len(omitted) + len(phase_errors) + len(rejected) + len(resolution_errors) + len(section_identity_errors)
    return {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'scope': '전체 원본 행·단지 마스터·저장된 네이버 연결의 단지 번호 정합성. 네이버 전체 페이지의 실시간 검증을 뜻하지 않음.',
        'counts': {'sourceRows':source_count, 'masterRecords':len(search.APARTMENT_MASTER), 'individualApartments':len(master),
                   'numberedNamesRestoredFromSource':len(promoted), 'naverAliasMappings':len(entries),
                   'remainingOmittedPhaseNames':len(omitted), 'unreviewedNaverPhaseConflicts':len(phase_errors),
                   'knownWrongLinksRemaining':len(rejected), 'reviewedMappingResolutionFailures':len(resolution_errors),
                   'unresolvedReviewedLocations':len(unresolved_reviews),
                   'sectionIdentityMappingErrors':len(section_identity_errors)},
        'status':'passed' if failures == 0 else 'failed',
        'imunSections':imun,
        'restoredNames':[dict(zip(('name','province','region','legalDong','jibun'), values)) for values in sorted(promoted, key=str)],
        'omittedPhaseNames':omitted, 'naverPhaseConflicts':phase_errors, 'rejectedMappings':rejected,
        'resolutionErrors':resolution_errors, 'sectionIdentityMappingErrors':section_identity_errors,
        'sectionMappings':section_mappings,
        'unresolvedReviewedLocations':unresolved_reviews,
        'reviewCounts':dict(Counter(r['status'] for r in naver.mapping_reviews())),
        'limitations':['네이버 일반 단지 페이지가 확인되지 않은 임대단지 연결은 비활성화함.',
                       '이문 1·2단지의 동번호 없는 공통 거래를 개별 단지 거래로 복제하지 않음.',
                       '외부 서비스의 전체 신규 단지 등록 여부·모든 주소를 실시간 전수 확인한 결과는 아님.'],
    }

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT/'docs/apartment-sections-audit.json'))
    args=parser.parse_args()
    report=audit()
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],**report['counts']},ensure_ascii=False))
    raise SystemExit(report['status'] != 'passed')
