"""Individual public project pages, separate from data/GIS provenance URLs."""
import datetime as dt
import json
import re
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

import config

SNAPSHOT = config.ROOT / 'data/living_area_seoul_snapshot.json'
REVIEWED = config.ROOT / 'data/project_official_links.json'


def individual_url(value):
    try:
        url = urlsplit(value or '')
        host = url.hostname or ''
        if (url.scheme != 'https' or url.username or url.password or url.port not in (None, 443)
                or not (host.endswith('.go.kr') or host in ('ms.smc.seoul.kr', 'www.kr.or.kr'))):
            return None
        if (host in ('data.seoul.go.kr', 'www.data.go.kr', 'data.go.kr', 'gris.gg.go.kr')
                or re.search(r'/rest/|mapserver|datasetview|/opendata/', url.path, re.I)):
            return None
        query = parse_qs(url.query)
        if host == 'cleanup.seoul.go.kr':
            return value if any(query.get(k) for k in ('cafeUrl', 'cafeId', 'othbcListSn')) else None
        if re.search(r'/archives/\d+|\.(pdf|hwp|hwpx|jpg|png)$', url.path, re.I):
            return value
        if url.path.endswith('/recordView.do') and query.get('key'):
            return value
        return value if any(query.get(k) for k in
                            ('seq', 'id', 'idx', 'bIdx', 'nttNo', 'nttSn', 'pcode', 'articleId')) else None
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=2)
def _rows(modified):
    return json.loads(SNAPSHOT.read_text())


@lru_cache(maxsize=2)
def _reviewed(modified):
    return json.loads(REVIEWED.read_text())['links']


def _metadata(url, title, basis, checked_at, source_url=None, source_date=None):
    if not individual_url(url):
        return {}
    return {'officialDetailUrl': url, 'officialDetailTitle': title,
            'officialDetailBasis': basis, 'officialDetailCheckedAt': checked_at,
            'officialDetailSourceUrl': source_url or url, 'officialDetailSourceDate': source_date}


def for_project(project, day=None):
    day = day or dt.date.today()
    if individual_url(project.get('officialDetailUrl')) and project.get('officialDetailBasis'):
        return {k:v for k,v in project.items() if k.startswith('officialDetail')}
    ids = {project.get('id'), project.get('projectId'), project.get('lineId'),
           *(project.get('routeIds') or [])} - {None}
    # An official record PK, rather than an apartment/project name, owns its URL.
    if SNAPSHOT.exists():
        snapshot = _rows(SNAPSHOT.stat().st_mtime_ns)
        if snapshot['asOfDate'] > day.isoformat():
            snapshot = {**snapshot, 'rows': []}
        for row in snapshot['rows']:
            pid = 'seoul-plan-renewal:' + str(int(row['basic_info_seq']))
            if pid not in ids or not row.get('cleanup_bsns_url'):
                continue
            if project.get('name') and project['name'] != row['bsns_name']:
                return {}
            if project.get('region') and project['region'] != row['site_code_nm']:
                return {}
            if project.get('address') and project['address'] != (row.get('bsns_addr') or ''):
                return {}
            return _metadata(row['cleanup_bsns_url'], row['bsns_name'], 'official_record_homepage',
                             snapshot['collectedAt'][:10],
                             'https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do',
                             snapshot['asOfDate'])
    if REVIEWED.exists():
        for link in _reviewed(REVIEWED.stat().st_mtime_ns):
            if not ids.intersection(link['ids']) or (link['sourceDate'] or link['checkedAt']) > day.isoformat():
                continue
            if project.get('name') and project['name'] not in link['names'] and not project.get('lineId'):
                continue
            return _metadata(link['url'], link['title'], 'reviewed_project_id', link['checkedAt'],
                             source_date=link['sourceDate'])
    return {}


def for_boundary(boundary, project=None, day=None):
    if project and (detail := for_project(project, day)):
        return detail
    if detail := for_project(boundary, day):
        return detail
    if not SNAPSHOT.exists():
        return {}
    # Boundary-only rows lack the source PK. Accept only an unambiguous official
    # name + district + lot identity; equal names at different lots stay separate.
    snapshot = _rows(SNAPSHOT.stat().st_mtime_ns)
    if snapshot['asOfDate'] > (day or dt.date.today()).isoformat():
        return {}
    matches = [r for r in snapshot['rows']
               if r['bsns_name'] == (boundary.get('sourceName') or boundary.get('name'))
               and str(r.get('site_code')) == str(boundary.get('districtCode'))]
    addresses = {re.sub(r'\s+|일대', '', r.get('bsns_addr') or '') for r in matches}
    urls = {r['cleanup_bsns_url'] for r in matches if individual_url(r.get('cleanup_bsns_url'))}
    if len(addresses) == 1 and len(urls) == 1:
        row = next(r for r in matches if r.get('cleanup_bsns_url') in urls)
        return _metadata(row['cleanup_bsns_url'], row['bsns_name'], 'exact_official_name_district_lot',
                         snapshot['collectedAt'][:10], source_date=snapshot['asOfDate'])
    return {}
