"""Reviewed apartment context, separate from official boundary names and stages."""
import datetime as dt
import json
from functools import lru_cache

import config

PATH = config.ROOT / 'data/map_zone_developments.json'


@lru_cache(maxsize=2)
def _read(modified):
    return json.loads(PATH.read_text()).get('developments', [])


def for_boundaries(rows, projects, day):
    if not PATH.exists():
        return {}
    boundaries = {row['id']: row for row in rows}
    by_id = {project['id']: project for project in projects}
    result = {}
    for context in _read(PATH.stat().st_mtime_ns):
        row = boundaries.get(context['boundaryId'])
        project = by_id.get(context['projectId'])
        if (not row or row.get('sourceId') != 'seoul-plan-boundary'
                or row.get('sourceName') != context['boundaryName']
                or row.get('districtCode') != context['districtCode']
                or not project or project.get('stage') in ('completed', 'cancelled')
                or any(project.get(key) != context[key]
                    for key in ('name', 'province', 'region', 'legalDong', 'jibun'))):
            continue
        checked = dt.date.fromisoformat(context['checkedAt'])
        if not 0 <= (day - checked).days <= 120:
            continue
        # Construction is only shown with a current construction stage in the
        # official boundary. A later completed/cancelled stage cannot revive it.
        if context['statusLabel'] == '건설 중' and row.get('stage') != 'construction':
            continue
        result[row['id']] = {**context,
            'displayLabel': f"{context['name']} {context['statusLabel']}",
            'matchMethod': 'reviewed_boundary_id_and_exact_project_address'}
    return result
