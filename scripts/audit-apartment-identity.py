#!/usr/bin/env python3
"""Audit actual master parcel collisions, optionally checking Jev's guarded choice."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import apartment_identity as identity
import budget_candidates as budget
import real_estate_search as search
import typesafe_jev


def audit():
    buckets = defaultdict(list)
    for entity in search.APARTMENT_MASTER:
        parcel = identity.entity_parcel(entity)
        if parcel:
            buckets[(entity.get('province'), entity.get('district'), entity.get('legalDong'), search.compact(parcel))].append(entity)
    groups, failures = [], []
    for key, entities in buckets.items():
        parcels = sorted({identity.entity_parcel(entity) for entity in entities})
        if len(parcels) < 2:
            continue
        checks = []
        for entity in entities:
            expected = identity.entity_parcel(entity)
            matches = budget._find_entities(entity['name'], entity.get('district'), entity.get('legalDong'), expected)
            actual = sorted({identity.entity_parcel(match) for match in matches})
            passed = bool(matches) and actual == [expected]
            check = {'name': entity['name'], 'requestedParcel': expected, 'matchedParcels': actual, 'passed': passed}
            checks.append(check)
            if not passed:
                failures.append(check)
        groups.append({'province': key[0], 'district': key[1], 'legalDong': key[2], 'parcels': parcels, 'checks': checks})
    return {'masterCount': len(search.APARTMENT_MASTER), 'collisionGroupCount': len(groups), 'checkedEntityCount': sum(len(g['checks']) for g in groups), 'failureCount': len(failures), 'groups': groups}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--live-jev', action='store_true')
    args = parser.parse_args()
    report = audit()
    if args.live_jev:
        # Synthetic public-style records exercise the service without sending user data.
        query = {'name': '테스트 햇살마을', 'region': '테스트구', 'legalDong': '테스트동', 'jibun': '1-11'}
        candidates = [
            {'name': '테스트 햇살마을', 'district': '테스트구', 'legalDong': '테스트동', 'jibun': '11-1'},
            {'name': '테스트 햇살마을 아파트', 'aliases': ['테스트 햇살마을'], 'district': '테스트구', 'legalDong': '테스트동', 'jibun': '1-11'},
        ]
        result = typesafe_jev.choose_apartment_identity(query, candidates)
        report['jevCheck'] = result
        report['jevExpectedIndex'] = 1
        report['jevPassed'] = result.get('status') == 'matched' and result.get('selectedIndex') == 1
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'groups'}, ensure_ascii=False))
    raise SystemExit(1 if report['failureCount'] or report.get('jevPassed') is False else 0)
