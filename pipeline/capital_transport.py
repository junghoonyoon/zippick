"""Conservative capital-region transport context for every complex report.

The 2021-25 metropolitan plan is an inventory, not proof of current progress.
Only separately reviewed station facts may be shown as regional references.
No plan in this module changes distance, map geometry, or living-area scores.
"""
import json
from functools import lru_cache
from pathlib import Path

import planned_rail

INVENTORY_PATH = Path(__file__).resolve().parents[1] / 'data/capital_transport_plan_inventory.json'
TRANSFER_PATH = Path(__file__).resolve().parents[1] / 'data/capital_transport_transfer_2026.json'
BRT_PATH = Path(__file__).resolve().parents[1] / 'data/capital_transport_brt_2026.json'
ROAD_PATH = Path(__file__).resolve().parents[1] / 'data/capital_transport_road_projects.json'
CAPITAL_PROVINCES = {'서울특별시', '경기도', '인천광역시'}


@lru_cache(maxsize=4)
def _inventory(modified):
    return json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))


def inventory():
    return _inventory(INVENTORY_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _transfer(modified):
    return json.loads(TRANSFER_PATH.read_text(encoding='utf-8'))


def transfer_plan():
    return _transfer(TRANSFER_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _brt(modified):
    return json.loads(BRT_PATH.read_text(encoding='utf-8'))


def brt_plan():
    return _brt(BRT_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _road(modified):
    return json.loads(ROAD_PATH.read_text(encoding='utf-8'))


def road_plan():
    return _road(ROAD_PATH.stat().st_mtime_ns)


def _location(identity):
    province = str(identity.get('province') or '').strip()
    city = str(identity.get('city') or '').strip()
    district = str(identity.get('district') or '').strip()
    for key in ('mapAddress', 'address', 'displayRegion'):
        parts = str(identity.get(key) or '').split()
        if parts and parts[0] in CAPITAL_PROVINCES:
            province = parts[0]
            if len(parts) > 1:
                if province == '경기도':
                    city = parts[1]
                else:
                    district = parts[1]
            break
    return province, city if province == '경기도' else district


def for_complex(identity):
    """Return the same evidence envelope for every search/report entry point."""
    identity = identity if isinstance(identity, dict) else {}
    rail = planned_rail.planned_rail_for_candidate(identity)
    catalog = inventory()
    transfer = transfer_plan()
    brt = brt_plan()
    road = road_plan()
    province, sigungu = _location(identity)
    in_scope = province in CAPITAL_PROVINCES
    projects = [{
        'id': line['id'], 'name': line['name'], 'category': 'rail',
        'stage': line['stage'], 'stageCode': line.get('stageCode'),
        'stations': line['stations'], 'relation': line['relation'],
        'sourceUrl': line['sourceUrl'], 'sourceDate': line.get('sourceDate'),
        'verifiedAt': line.get('verifiedAt'),
        'regionalReference': line.get('regionalReference', False),
        'note': line.get('planningNote') or '같은 시·구의 계획역이에요. 단지에서 가까운 역이나 직접 수혜를 뜻하지 않아요.',
    } for line in rail]
    for number, (name, source_province, place_region, classification) in enumerate(transfer['projects'], start=1):
        if (source_province, place_region) != (province, sigungu):
            continue
        projects.append({
            'id': f'transfer-2026-{number:02d}', 'name': name, 'category': 'transfer',
            'stage': '기본계획 반영 · ' + ('추가 검토' if classification == '추가검토' else classification),
            'stageCode': 'planning', 'relation': '같은 시·구의 환승센터 계획 · 지명 기준',
            'sourceUrl': transfer['sourceUrl'], 'sourceDate': transfer['publishedAt'],
            'verifiedAt': transfer['reviewedAt'],
            'note': transfer['matchNote'],
        })
    scope_key = f'{province}:{sigungu}'
    for number, (name, route, classification, scopes) in enumerate(brt['projects'], start=1):
        if scope_key not in scopes:
            continue
        projects.append({
            'id': f'brt-2026-{number:02d}', 'name': name, 'category': 'brt',
            'stage': '기본계획 반영 · ' + classification, 'stageCode': 'planning',
            'route': route, 'relation': '공식 구간 지명이 같은 시·구에 있는 BRT 계획',
            'sourceUrl': brt['sourceUrl'], 'sourceDate': brt['publishedAt'],
            'verifiedAt': brt['reviewedAt'], 'note': brt['matchNote'],
        })
    for item in road['projects']:
        if scope_key not in item['scopes']:
            continue
        projects.append({
            'id': item['id'], 'name': item['name'], 'category': 'road',
            'stage': item['stage'], 'stageCode': 'planning',
            'route': item['route'], 'relation': '공식 구간 지명이 같은 시·구에 있는 도로 계획',
            'sourceUrl': item['sourceUrl'], 'sourceDate': item['sourceDate'],
            'verifiedAt': road['reviewedAt'],
            'note': '같은 시·구의 도로 계획이에요. 단지에서 가까운 도로나 차량 이동시간 개선을 뜻하지 않아요.',
        })
    import project_official_links
    from living_area_rail_policy import annotate
    projects = [{**(annotate(p) if p['category'] == 'rail' else p),
                 **project_official_links.for_project(p)} for p in projects]
    return {
        'status': 'partial' if in_scope else 'out_of_scope',
        'scope': '서울·경기·인천',
        'matchedPlans': projects,
        'matchBasis': '공식 발표 예정역의 시·구',
        'inventory': {
            'plan': catalog['plan'], 'period': catalog['period'],
            'counts': {kind: len(rows) for kind, rows in catalog['categories'].items()},
            'sourceUrl': catalog['sourceUrl'], 'reviewedAt': catalog['reviewedAt'],
            'currentStatus': catalog['currentStatus'],
            'newerPlans': catalog['newerPlans'],
            'currentTransferCount': len(transfer['projects']),
            'currentBrtCount': len(brt['projects']),
            'reviewedRoadCount': len(road['projects']),
            'unmappedRoadCount': sum(not item['scopes'] for item in road['projects']),
        },
        'limitation': '계획 반영은 착공이나 이 단지의 직접 수혜를 뜻하지 않아요. 일부 철도·도로의 위치와 최신 단계는 확인 중이에요.',
    }
