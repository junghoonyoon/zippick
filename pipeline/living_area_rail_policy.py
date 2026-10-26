"""Explicit, reviewable product weights for planned passenger rail.

These are comparative product assumptions, not measured travel-time gains.
The reviewed station registry supplies the official stage and source for each line.
"""
import json
import re
from functools import lru_cache

import config

PATH = config.ROOT / 'data/rail_impact_policy.json'

IMPACT = {
    'gtx': ('GTX', 1.00),
    'regional': ('광역·급행철도', .85),
    'metro': ('도시철도', .75),
    'light': ('경전철', .65),
    'tram': ('트램', .55),
}
MATURITY = {
    'concept': ('계획 단계', .20),
    'feasibility': ('타당성 검토', .35),
    'basic_plan': ('기본계획', .55),
    'design': ('설계·승인', .70),
    'construction': ('공사 중', .85),
    'commissioning': ('시운전', .95),
}


@lru_cache(maxsize=2)
def _read(revision):
    return json.loads(PATH.read_text())['lines']


def review_context(line_id=None, stage_label=None, stage_code=None):
    """Retain reconsidered plans as references, outside default maps and scores."""
    row = _read(PATH.stat().st_mtime_ns).get(line_id, {}) if PATH.exists() else {}
    label = stage_label or row.get('stageLabel', '')
    code = stage_code or row.get('stageCode')
    if code in ('construction', 'completed', 'cancelled'):
        return {}
    # A generic or older planning label must not override a reviewed failure.
    reviewed = (row.get('reviewStatus') == 'reconsidering'
                or row.get('feasibilityStatus') in ('failed', 'withdrawn'))
    if not reviewed and not re.search(r'재추진|재검토|예타\s*(?:미통과|탈락|철회)', label):
        return {}
    return {'railReviewStatus': 'reconsidering', 'defaultVisible': False,
            'scoringEligible': False,
            'reviewLabel': row.get('reviewLabel', '재추진 중 · 일정 미정'),
            'reviewReason': row.get('reviewReason', '사업을 다시 검토하고 있어요. 교통 가점과 매수 이유에서 제외해요.'),
            **{key: row[key] for key in ('reviewSourceUrl', 'reviewSourceDate', 'reviewedAt') if key in row}}


def annotate(row):
    line_id = row.get('lineId') or row.get('id', '').removeprefix('metro-rail:')
    label = row.get('stageLabel') or (row.get('stage') if row.get('stageCode') else None)
    code = row.get('stageCode') or row.get('stage')
    return {**row, **review_context(line_id, label, code)}


def under_review(row):
    return annotate(row).get('railReviewStatus') == 'reconsidering'


def line_policy(line_id, stage_code, stage_label=None):
    """Withhold a line when the reviewed policy or stage evidence does not match."""
    if not line_id or not PATH.exists():
        return None
    row = _read(PATH.stat().st_mtime_ns).get(line_id)
    if not row or row['stageCode'] != stage_code:
        return None
    # The data import must be reviewed again if the source's stage wording changes.
    if stage_label and row['stageLabel'] != stage_label:
        return None
    if review_context(line_id, stage_label, stage_code):
        return None
    impact = IMPACT.get(row['impactClass'])
    maturity = MATURITY.get(row['maturity'])
    if not impact or not maturity:
        return None
    return {'lineId':line_id, 'lineName':row['name'],
            'impactClass':row['impactClass'], 'impactLabel':impact[0],
            'impactFactor':impact[1], 'maturity':row['maturity'],
            'maturityLabel':maturity[0], 'maturityFactor':maturity[1],
            'stageLabel':row['stageLabel'], 'sourceUrl':row.get('sourceUrl')}
