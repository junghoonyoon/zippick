#!/usr/bin/env python3
"""Check official inventory and coverage of the current search index."""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))

import capital_transport  # noqa: E402
import planned_rail  # noqa: E402
import real_estate_search  # noqa: E402


def main():
    catalog = capital_transport.inventory()
    expected = {'rail': 29, 'road': 7, 'brt': 8, 'transfer': 32}
    counts = {category: len(rows) for category, rows in catalog['categories'].items()}
    assert counts == expected, (counts, expected)
    assert all(isinstance(row, str) and row.strip() for group in catalog['categories'].values() for row in group)
    assert catalog['period'] == '2021-2025' and catalog['sourceUrl'].startswith('https://www.molit.go.kr/')
    assert next(plan for plan in catalog['newerPlans'] if '환승센터' in plan['name'])['capitalProjectCount'] == 35
    reviewed = planned_rail._load()['lines']
    transfer = capital_transport.transfer_plan()
    brt = capital_transport.brt_plan()
    road = capital_transport.road_plan()
    assert len(transfer['projects']) == 35
    assert collections.Counter(row[3] for row in transfer['projects']) == {'신규': 9, '계속': 25, '추가검토': 1}
    assert len({row[0] for row in transfer['projects']}) == 35
    assert len(brt['projects']) == 11
    assert collections.Counter(row[2] for row in brt['projects']) == {'신규': 5, '계속': 6}
    assert len({row[0] for row in brt['projects']}) == 11
    assert len(road['projects']) == 5
    assert len({row['id'] for row in road['projects']}) == 5
    assert sum(not row['scopes'] for row in road['projects']) == 1
    assert all(row['sourceUrl'].startswith('https://') and row['sourceDate'] and row['route']
               for row in road['projects'])
    assert len({row['id'] for row in reviewed}) == len(reviewed)
    assert all(row.get('stageCode') in ('planning', 'construction') and
               row.get('sourceDate') and row.get('sourceUrl', '').startswith('https://') and
               (row.get('stations') or row.get('regionalScopes')) for row in reviewed)

    stats = collections.Counter()
    for entity in real_estate_search._search_entities():
        if entity.get('province') not in capital_transport.CAPITAL_PROVINCES:
            continue
        report = capital_transport.for_complex(entity)
        assert report['status'] == 'partial', entity.get('name')
        assert report['inventory']['counts'] == expected
        assert all((project['category'] in ('transfer', 'brt', 'road') or project['id'] in {row['id'] for row in reviewed}) and
                   project['sourceUrl'].startswith('https://') and
                   'distanceMeters' not in project for project in report['matchedPlans'])
        for project in report['matchedPlans']:
            if project['id'] == 'wirye-sinsa':
                assert project['category'] == 'rail' and project['regionalReference']
                assert not project['stations'] and 'walkingMinutes' not in project
                stats['wirye_sinsa_references'] += 1
        stats['capital_complexes'] += 1
        stats[entity['province']] += 1
        stats['with_mapped_project' if report['matchedPlans'] else 'without_mapped_project'] += 1
    assert stats['capital_complexes'] > 18000, stats
    print('Historical official inventory:', counts, 'total', sum(counts.values()))
    print('Separately reviewed rail lines:', len(reviewed), 'current transfer projects:', len(transfer['projects']),
          'current BRT projects:', len(brt['projects']), 'reviewed road projects:', len(road['projects']))
    print('Search-index coverage:', dict(stats))
    assert stats['wirye_sinsa_references'] > 0
    print('Road inventory: 2 current Incheon congestion-road projects; 3 metro-road status snapshots dated 2025-06.')
    print('Full capital railway and road networks: PARTIAL — individual projects require source and location review.')


if __name__ == '__main__':
    main()
