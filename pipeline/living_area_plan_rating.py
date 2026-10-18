"""Versioned editorial plan rating; not measured travel gains or price forecasts.

Uses observed plan facts with explicit policy thresholds. Missing facts stay None.
The complete-measurement v2 model is retained separately and never backfilled.
"""
import math

from living_area_scoring_policy import STAGES, distance_decay, rounded
import living_area_sources as sources

VERSION = 'living-area-plan-v3-beta'
WEIGHTS = {'housing': .6, 'transport': .4}


def valid(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def aggregate(scores):
    if not all(valid(scores.get(k)) and 0 <= scores[k] <= 5 for k in WEIGHTS):
        return None
    return rounded(sum(scores[k]*weight for k,weight in WEIGHTS.items()))


def calculate(projects, spatial, day):
    """All coefficients below are declared product policy, not observed outcomes."""
    output = {'version': VERSION, 'status':'insufficient_data', 'score':None,
              'subScores':dict.fromkeys(WEIGHTS), 'weights':WEIGHTS,
              'basis':'계획 기준 · 베타', 'asOfDate':day.isoformat(), 'components':{},
              'disclaimer':'사업 계획을 비교하는 참고 점수예요. 실제 교통 개선이나 가격 상승률을 예측하지 않아요.'}
    zones = {z['projectId']:z for z in spatial.get('zones', [])}
    housing = []
    by_id = {p['id']:p for p in projects}
    for p in by_id.values():
        if p.get('projectType') not in ('redevelopment','reconstruction') or p.get('stage') not in STAGES:
            continue
        z = zones.get(p['id'])
        distance = z.get('distanceMeters') if z else p.get('distanceMeters')
        size = p.get('plannedHouseholds')
        area = p.get('siteAreaM2')
        if z and z.get('containsSubject'):continue
        if not valid(distance) or not 0 <= distance <= 2000:continue
        if valid(size) and size > 0:
            scale, scale_label = min(size/1500,1), f'{size:,.0f}세대 계획'
        elif valid(area) and area > 0:
            scale, scale_label = min(area/100000,1), f'구역 {area:,.0f}㎡'
        else:continue
        proximity, stage = distance_decay(distance), STAGES[p['stage']]
        score = 5*(.4*proximity + .3*scale + .3*stage)
        housing.append({'projectId':p['id'], 'name':p['name'], 'distanceMeters':distance,
                        'distanceBasis':'단지 대표점→참고 구역 경계' if z else p.get('distanceLabel', '사업 대표점 직선거리'),
                        'coordinateSourceUrl':p.get('coordinateSourceUrl'),
                        'plannedHouseholds':size, 'siteAreaM2':area, 'scaleLabel':scale_label, 'stage':p['stage'], 'stageCoefficient':stage,
                        'proximityCoefficient':proximity, 'rawScore':score,
                        'sourceUrl':p.get('sourceUrl'), 'geometrySourceUrl':z.get('sourceUrl') if z else None})
    if housing:
        best = max(housing, key=lambda p:p['rawScore'])
        output['subScores']['housing'] = rounded(best['rawScore'])
        output['components']['housing'] = {
            'summary':f'{best["name"]} · {best["scaleLabel"]} · 직선 {best["distanceMeters"]:,}m',
            'formula':'거리 40% + 규모 30% + 사업 단계 30%. 여러 사업을 더하지 않고 가장 높은 1개를 반영해요.',
            'policy':'규모는 1,500세대 이상을 만점으로 봐요. 세대수가 없으면 공식 구역면적 10만㎡를 기준으로 비교해요. 직선거리와 단계 배점은 집픽의 비교 기준이에요.',
            'inputs':housing, 'selectedProjectId':best['projectId']}
    rail = []
    for station in spatial.get('stations', []):
        p = by_id.get(station.get('projectId'))
        distance = station.get('distanceMeters')
        # A landmark is explicitly a planning reference, never an entrance/walking route.
        if (not p or p.get('projectType') != 'transport' or p.get('stage') not in STAGES
                or not valid(distance) or not 0 <= distance <= 2000):
            continue
        rail.append({'projectId':p['id'], 'name':station['name'], 'distanceMeters':distance,
                     'positionLabel':station['positionLabel'], 'stage':p['stage'],
                     'stageLabel':p.get('stageLabel'), 'planningNote':p.get('planningNote',''),
                     'coordinateSourceUrl':station.get('coordinateSourceUrl'),
                     'stageCoefficient':STAGES[p['stage']], 'sourceUrl':p.get('sourceUrl'),
                     'positionSourceUrl':station.get('sourceUrl'),
                     'rawScore':5*(.6*distance_decay(distance)+.4*STAGES[p['stage']])})
    if rail:
        best = max(rail, key=lambda p:p['rawScore'])
        output['subScores']['transport'] = rounded(best['rawScore'])
        output['components']['transport'] = {
            'summary':f'{best["name"]} · 참고 위치까지 직선 {best["distanceMeters"]:,}m'+(f' · {best["stageLabel"]}' if best.get('stageLabel') else ''),
            'formula':'계획 경유지와의 거리 60% + 추진 단계 40%. 가장 높은 1개 계획을 반영해요.',
            'policy':'예정역 출입구·도보시간은 미확정이에요. 실제 이동시간 단축 점수가 아니에요. '+best.get('planningNote',''), 'inputs':rail,
            'selectedProjectId':best['projectId']}
    output['score'] = aggregate(output['subScores'])
    output['status'] = 'ready' if output['score'] is not None else 'insufficient_data'
    reasons = {'housing':'사업 위치·계획 세대수·진행 단계를 함께 확인해야 해요.',
               'transport':'이 단지에서 이용할 새 철도 계획과 위치를 확인하지 못했어요.'}
    output['missingReasons'] = {key:reason for key,reason in reasons.items() if output['subScores'][key] is None}
    output['stagePolicy'] = '계획 10% · 구역 지정 20% · 조합 설립 35% · 사업 인가 55% · 관리처분 70% · 착공 90%'
    output['distancePolicy'] = '직선 0m 100% · 800m 60% · 2km 20%, 구간 사이는 비례 계산'
    return output


def attach(result, identity, day):
    from living_area_map import map_context
    # Each map source checks its own review date. An old pilot file must not
    # suppress independently refreshed metro station references.
    try:
        spatial = map_context(identity,result)
    except (OSError, ValueError, KeyError):
        spatial = {'zones': [], 'stations': []}
    rating = calculate(result.get('displayProjects',[]),spatial,day)
    if rating['subScores']['transport'] is not None:
        transport_status='scored'
    elif not result.get('metroCoverage'):
        transport_status='catalogue_unavailable'
        rating['missingReasons']['transport']='이 지역의 최신 철도계획 자료를 확인하지 못했어요. 교통이 나쁘다는 뜻은 아니에요.'
    elif not (result.get('center') or result.get('mapCenter')):
        transport_status='location_unresolved'
        rating['missingReasons']['transport']='단지의 정확한 위치를 확인하지 못해 계획역과의 거리를 계산하지 못했어요.'
    else:
        transport_status='no_verified_station_within_2km'
        rating['missingReasons']['transport']='현재 수집한 자료에서 2km 안의 새 철도 경유역을 확인하지 못했어요. 기존 교통 편의와는 별개이며, 계획이 전혀 없다는 뜻은 아니에요.'
    if spatial.get('routes') and rating['subScores']['transport'] is None:
        transport_status='route_only'
        names=' · '.join(route['name'] for route in spatial['routes'])
        rating['missingReasons']['transport']=names+' 자료는 확인했어요. 현재 연결한 자료에 이 단지에서 이용할 신규·변경 역 위치가 없어 점수는 보류했어요.'
    rating['transportCoverage']={'status':transport_status,'radiusMeters':2000,
                                'checkedAt':result.get('metroCoverage',{}).get('checkedAt'),
                                'stationReferences':result.get('metroCoverage',{}).get('railStationReferences'),
                                'scopeComplete':False}
    result['planRating'] = rating
    result['snapshotId'] = sources.digest({'analysis':result['snapshotId'], 'planRating':rating})
    return result
