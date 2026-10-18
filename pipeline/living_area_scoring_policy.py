"""Versioned beta policy. Inputs are observed quantities, never supplied scores.

Missing metrics are not reweighted. Project counts do not earn points. Each
regional observation covers a surveyed scope with overlapping areas unioned;
project impacts use a weighted mean, not a sum of duplicated benefits.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

VERSION = 'living-area-v2-beta'
REGIONAL = {'housing_conversion': 30, 'new_build_belt': 15,
            'transport_improvement': 15, 'amenity_improvement': 15,
            'project_feasibility': 15, 'supply_demand_stability': 10}
DIRECT = {'accessibility': 30, 'exposure': 25, 'execution': 20,
          'relative_competitiveness': 15, 'negative_impact': 10}
LABELS = dict(zip([*REGIONAL, *DIRECT], [
    '낡은 주거지의 변화', '새 주거지 사이 연결', '교통 변화', '생활시설 변화',
    '사업 진행 정도', '새집 공급과 수요', '사업지까지 접근성', '생활 동선과의 연결',
    '직접 관련 사업의 진행', '새 단지와의 경쟁력', '공사·공급 부담']))
STAGES = {'planning': .1, 'designated': .2, 'association': .35,
          'approved': .55, 'disposal': .7, 'construction': .9}
# These are policy assumptions, not empirically calibrated price predictions.
CORE_M, NEAR_M, MAX_M = 800, 2000, 5000
MAX_AGE_DAYS = 120


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def rounded(value, places=1):
    return float(Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


def distance_decay(meters):
    """Continuous linear decay: 0m=1, 800m=.6, 2km=.2, 5km=0."""
    if not number(meters) or meters < 0:
        return None
    if meters <= CORE_M:
        return 1 - .4 * meters / CORE_M
    if meters <= NEAR_M:
        return .6 - .4 * (meters - CORE_M) / (NEAR_M - CORE_M)
    return max(0, .2 * (MAX_M - meters) / (MAX_M - NEAR_M))


def normalize(key, inputs):
    """Return 0..100 or None. Zero requires a complete, verified observation."""
    def nums(*keys):
        values = [inputs.get(k) for k in keys]
        return values if all(number(v) and v >= 0 for v in values) else None

    ratio = None
    if key in ('housing_conversion', 'new_build_belt', 'exposure'):
        fields = {'housing_conversion': ('convertedLandM2', 'oldResidentialLandM2'),
                  'new_build_belt': ('connectedLengthM', 'assessedLengthM'),
                  'exposure': ('improvedDailyRoutes', 'assessedDailyRoutes')}[key]
        v = nums(*fields)
        if v and v[1] > 0 and v[0] <= v[1] and inputs.get('scopeSurveyComplete') is True:
            if key != 'housing_conversion' or inputs.get('overlapRemoved') is True:
                ratio = v[0] / v[1] / (.5 if key == 'housing_conversion' else 1)
    elif key == 'transport_improvement':
        v = nums('beforeMinutes', 'afterMinutes')
        if v and v[0] > 0 and inputs.get('routeVerified') is True and inputs.get('stationEntranceVerified') is True:
            ratio = (v[0] - v[1]) / 20
    elif key == 'amenity_improvement':
        v = nums('beforeAccessibleFacilities', 'afterAccessibleFacilities', 'assessedFacilities')
        if v and v[2] > 0 and max(v[:2]) <= v[2] and inputs.get('openingScheduleVerified') is True:
            ratio = (v[1] - v[0]) / v[2]
    elif key == 'supply_demand_stability':
        v = nums('plannedHouseholds', 'existingHouseholds', 'annualAbsorptionHouseholds')
        if v and v[1] > 0 and inputs.get('scopeSurveyComplete') is True:
            ratio = 1 - max(0, v[0] - 5 * v[2]) / v[1] / .1
    elif key == 'relative_competitiveness':
        # A transparent, same-area comparison of checked housing attributes.
        v = nums('competitiveAttributes', 'assessedAttributes')
        if v and v[1] > 0 and v[0] <= v[1] and inputs.get('sameAreaCompared') is True:
            ratio = v[0] / v[1]
    elif key == 'negative_impact':
        v = nums('noiseExposure', 'routeDisruption', 'supplyCompetition')
        if v and max(v) <= 1 and inputs.get('scopeSurveyComplete') is True:
            ratio = 1 - sum(v) / 3
    return max(0, min(100, ratio * 100)) if ratio is not None else None


def weighted(values, weights):
    if not all(number(values.get(k)) and 0 <= values[k] <= 100 for k in weights):
        return None
    return sum(values[k] * w / 100 for k, w in weights.items())


def aggregate(values):
    regional, direct = weighted(values, REGIONAL), weighted(values, DIRECT)
    score = rounded((.6 * regional + .4 * direct) / 20) if regional is not None and direct is not None else None
    def sub(keys):
        weights = {k: REGIONAL.get(k, DIRECT.get(k)) for k in keys}
        total = weighted(values, {k: w * 100 / sum(weights.values()) for k, w in weights.items()})
        return rounded(total / 20) if total is not None else None
    return {'score': score, 'regionalScore': rounded(regional, 2) if regional is not None else None,
            'directScore': rounded(direct, 2) if direct is not None else None,
            'subScores': {'housing': sub(['housing_conversion', 'new_build_belt', 'amenity_improvement', 'project_feasibility']),
                          'transport': sub(['transport_improvement']),
                          'competitiveness': sub(['relative_competitiveness', 'negative_impact', 'supply_demand_stability'])}}
