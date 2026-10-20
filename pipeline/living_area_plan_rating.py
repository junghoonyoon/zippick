"""Versioned editorial plan rating; not measured travel gains or price forecasts.

Uses observed plan facts with explicit policy thresholds. Missing facts stay None.
The complete-measurement v2 model is retained separately and never backfilled.
"""
import math

from living_area_scoring_policy import STAGES, distance_decay, rounded
from living_area_rail_policy import line_policy, under_review
import living_area_sources as sources

VERSION = 'living-area-plan-v7-beta'
WEIGHTS = {'housing': .6, 'transport': .4}
HOUSING_HOUSEHOLDS_FULL_SCALE = 6000
HOUSING_AREA_FULL_SCALE_M2 = 400000


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
    zones = {}
    for zone in spatial.get('zones', []):
        project_id = zone.get('projectId')
        if not project_id:
            continue
        previous = zones.get(project_id)
        if (previous is None or (zone.get('containsSubject') and not previous.get('containsSubject'))
                or (not previous.get('containsSubject') and valid(zone.get('distanceMeters'))
                    and (not valid(previous.get('distanceMeters'))
                         or zone['distanceMeters'] < previous['distanceMeters']))):
            zones[project_id] = zone
    housing = []
    housing_without_scale = 0
    by_id = {p['id']:p for p in projects}
    for p in by_id.values():
        if p.get('projectType') not in ('redevelopment','reconstruction'):
            continue
        z = zones.get(p['id'])
        if z and (z.get('containsSubject') or z.get('stageMismatch')):
            continue
        project_stage = z.get('stage') if z and z.get('stage') in STAGES else p.get('stage')
        if project_stage not in STAGES:
            continue
        distance = z.get('distanceMeters') if z and valid(z.get('distanceMeters')) else p.get('distanceMeters')
        size = p.get('plannedHouseholds')
        area = p.get('siteAreaM2')
        if not valid(distance) or not 0 <= distance <= 2000:continue
        if valid(size) and size > 0:
            scale, scale_label, scale_basis = min(size/HOUSING_HOUSEHOLDS_FULL_SCALE,1), f'{size:,.0f}세대 계획', 'planned_households'
        elif valid(area) and area > 0:
            scale, scale_label, scale_basis = min(area/HOUSING_AREA_FULL_SCALE_M2,1), f'공식 구역면적 {area:,.0f}㎡', 'official_area'
        else:
            housing_without_scale += 1
            continue
        proximity, stage = distance_decay(distance), STAGES[project_stage]
        # Each distinct project adds a nonnegative, distance- and stage-adjusted
        # share of the 5-point scale. Later projects cannot lower the total.
        score = 5*scale*(.3 + .4*proximity + .3*stage)
        housing.append({'projectId':p['id'], 'name':p['name'], 'distanceMeters':distance,
                        'distanceBasis':'단지 대표점→참고 구역 경계' if z else p.get('distanceLabel', '사업 대표점 직선거리'),
                        'coordinateSourceUrl':p.get('coordinateSourceUrl'),
                        'plannedHouseholds':size if scale_basis == 'planned_households' else None,
                        'siteAreaM2':area, 'scaleLabel':scale_label, 'scaleBasis':scale_basis,
                        'scaleFraction':scale, 'stage':project_stage,
                        'stageLabel':(z or {}).get('stageLabel') or p.get('stageLabel'),
                        'stageCoefficient':stage, 'proximityCoefficient':proximity, 'rawScore':score,
                        'sourceUrl':p.get('sourceUrl'), 'geometrySourceUrl':z.get('sourceUrl') if z else None})
    if housing:
        scale_total = sum(p['scaleFraction'] for p in housing)
        distance_total = sum(p['scaleFraction'] * p['proximityCoefficient'] for p in housing)
        stage_total = sum(p['scaleFraction'] * p['stageCoefficient'] for p in housing)
        for p in housing:
            # Divide each capped part among its projects. The displayed project
            # contributions then add up to the actual housing score.
            p['contributionScore'] = 5 * p['scaleFraction'] * (
                .3 / max(1, scale_total)
                + .4 * p['proximityCoefficient'] / max(1, distance_total)
                + .3 * p['stageCoefficient'] / max(1, stage_total))
        housing.sort(key=lambda p:(-p['contributionScore'], p['distanceMeters'], p['projectId']))
        best = housing[0]
        households = [p for p in housing if p['scaleBasis'] == 'planned_households']
        area_only = [p for p in housing if p['scaleBasis'] == 'official_area']
        households_total = sum(p['plannedHouseholds'] for p in households)
        area_only_total = sum(p['siteAreaM2'] for p in area_only)
        uncapped_score = sum(p['rawScore'] for p in housing)
        output['subScores']['housing'] = rounded(sum(p['contributionScore'] for p in housing))
        scale_summary = []
        if households:
            scale_summary.append(f'계획 세대수 합계 {households_total:,.0f}세대')
        if area_only:
            scale_summary.append(f'세대수 없는 {len(area_only)}곳은 공식 면적 {area_only_total:,.0f}㎡로 계산')
        output['components']['housing'] = {
            'summary':f'직선 2km 안 정비사업 {len(housing)}곳 · ' + ' · '.join(scale_summary),
            'formula':'직선 2km 안 사업을 모두 더해요. 규모 30% + 거리 40% + 진행 단계 30%예요. 각 부분은 최대 5점 기준으로 계산해요.',
            'policy':('계획 세대수 6,000세대 또는 공식 구역면적 40만㎡를 규모 100%로 봐요. '
                      '세대수가 있으면 면적을 중복해 넣지 않아요. 계획 세대수는 입주 완료나 새로 늘어나는 세대수가 아니에요.'
                      + (f' 규모를 확인하지 못한 {housing_without_scale}곳은 계산에서 제외했어요.'
                         if housing_without_scale else '')),
            'inputs':housing, 'selectedProjectId':best['projectId'],
            'projectCount':len(housing), 'plannedHouseholdsTotal':households_total,
            'areaOnlyProjectCount':len(area_only), 'areaOnlyTotalM2':area_only_total,
            'unscoredProjectCount':housing_without_scale,
            'uncappedScore':rounded(uncapped_score, 2), 'scoreCap':5,
            'fullScaleHouseholds':HOUSING_HOUSEHOLDS_FULL_SCALE,
            'fullScaleAreaM2':HOUSING_AREA_FULL_SCALE_M2}
    rail_by_line = {}
    unscored_rail_lines = set()
    for station in spatial.get('stations', []):
        if under_review(station) or station.get('scoringEligible') is False or station.get('serviceStatus') == 'operating':
            continue
        p = by_id.get(station.get('projectId'))
        station_stage = station.get('stage') or (p or {}).get('stage')
        distance = station.get('distanceMeters')
        if (not p or p.get('projectType') != 'transport' or not valid(distance)
                or not 0 <= distance <= 2000):
            continue
        line_id = station.get('lineId')
        policy = line_policy(line_id, station_stage, station.get('stageLabel') or p.get('stageLabel'))
        if not policy:
            if line_id:
                unscored_rail_lines.add(line_id)
            continue
        # Reference points are not verified entrances; the access factor is a
        # deliberately conservative proxy, not a walking-time estimate.
        access = .4 + .6*distance_decay(distance)
        score = 5*access*policy['impactFactor']*policy['maturityFactor']
        row = {'projectId':p['id'], 'lineId':line_id, 'lineName':policy['lineName'],
               'name':station['name'], 'distanceMeters':distance,
               'positionLabel':station.get('positionLabel'), 'stage':station_stage,
               'stageLabel':policy['stageLabel'], 'planningNote':station.get('planningNote') or p.get('planningNote',''),
               'coordinateSourceUrl':station.get('coordinateSourceUrl'),
               'impactClass':policy['impactClass'], 'impactLabel':policy['impactLabel'],
               'impactFactor':policy['impactFactor'], 'maturity':policy['maturity'],
               'maturityLabel':policy['maturityLabel'], 'maturityFactor':policy['maturityFactor'],
               'accessFactor':access, 'sourceUrl':station.get('planSourceUrl') or policy['sourceUrl'],
               'positionSourceUrl':station.get('sourceUrl'), 'rawScore':score}
        previous = rail_by_line.get(line_id)
        if previous is None or (score, -distance, station['name']) > (
                previous['rawScore'], -previous['distanceMeters'], previous['name']):
            rail_by_line[line_id] = row
    rail = sorted(rail_by_line.values(), key=lambda row:(-row['rawScore'], row['lineId']))
    if rail:
        best = rail[0]
        second = rail[1] if len(rail) > 1 else None
        bonus = min(.6, .15*second['rawScore']) if second else 0
        best['contributionScore'] = best['rawScore']
        if second:
            second['contributionScore'] = bonus
        output['subScores']['transport'] = rounded(min(5, best['rawScore']+bonus))
        output['components']['transport'] = {
            'summary':f'{best["lineName"]} · {best["name"]} 참고 위치까지 직선 {best["distanceMeters"]:,}m'
                      + (f' · 다른 노선 {second["lineName"]}도 반영' if second else ''),
            'formula':'가까운 예정역 위치 × 노선 종류 × 사업 진행 단계로 계산해요. 가장 높은 노선을 기본으로, 다른 노선 1개만 최대 0.6점 더해요.',
            'policy':'예정역 출입구·도보시간은 미확정이에요. 실제 이동시간 단축 점수가 아니에요. '
                     '같은 노선의 역 여러 개는 한 번만 반영해요. 개통된 노선과 KTX·화물 노선은 새 생활철도 점수에서 빼요. '
                     '재추진·사업 방식 재검토 노선은 가점에서 제외해요. 단계가 확인되지 않은 노선은 보류해요.',
            'impactPolicy':'노선 종류: GTX 100% · 광역·급행철도 85% · 도시철도 75% · 경전철 65% · 트램 55%.',
            'maturityPolicy':'진행 단계: 계획 20% · 타당성 검토 35% · 기본계획 55% · 설계·승인 70% · 공사 85% · 시운전 95%.',
            'accessPolicy':'역 참고 위치까지 직선거리: 0m 100% · 800m 76% · 2km 52%. 실제 도보거리는 아니에요.',
            'inputs':rail, 'selectedProjectId':best['projectId'], 'selectedLineId':best['lineId'],
            'secondLineId':second['lineId'] if second else None,
            'secondLineBonus':rounded(bonus, 2), 'unscoredLineCount':len(unscored_rail_lines)}
    output['score'] = aggregate(output['subScores'])
    output['status'] = 'ready' if output['score'] is not None else 'insufficient_data'
    reasons = {'housing':'사업 위치·계획 세대수 또는 공식 구역면적·진행 단계를 함께 확인해야 해요.',
               'transport':'이 단지에서 이용할 새 철도 계획과 위치를 확인하지 못했어요.'}
    output['missingReasons'] = {key:reason for key,reason in reasons.items() if output['subScores'][key] is None}
    if unscored_rail_lines and output['subScores']['transport'] is None:
        output['missingReasons']['transport'] = (
            f'직선 2km 안에 예정역 참고 위치가 있지만, {len(unscored_rail_lines)}개 노선은 단계가 미확인됐거나 이 점수의 대상이 아니어서 보류했어요.')
    output['stagePolicy'] = '주거 사업 단계: 계획 10% · 구역 지정 20% · 조합 설립 35% · 사업 인가 55% · 관리처분 70% · 착공 90%'
    output['distancePolicy'] = '주거 거리 계수: 직선 0m 100% · 800m 60% · 2km 20%. 철도는 이 계수를 바탕으로 참고 위치 접근성을 계산해요.'
    return output


CURRENT_STATION_MATCH_METERS = 500


def current_station(identity, center):
    """Nearest operating subway station already cached for this exact complex.

    The cache is keyed by complex identity; the cached coordinate must also sit
    next to the living-area center so a same-name complex is never borrowed.
    """
    from living_area import distance
    try:
        import kakao_station_distances as stations
        record = (stations.cached_station(identity)
                  or stations.cached_station({k:v for k,v in identity.items() if k != 'apartmentId'}))
    except (ImportError, OSError, ValueError):
        return None
    if (not record or not record.get('nearestStationName') or not valid(record.get('nearestStationDistance'))
            or not center):
        return None
    offset = distance(center, {'latitude':record.get('latitude'), 'longitude':record.get('longitude')})
    if offset is None or offset > CURRENT_STATION_MATCH_METERS:
        return None
    return {'name':record['nearestStationName'], 'distanceMeters':round(record['nearestStationDistance']),
            'source':record.get('stationDistanceSource'), 'checkedAt':record.get('stationDistanceUpdatedAt')}


def split_useful_stations(stations, current):
    """A planned stop is a new-transport change only when residents would use it.

    Non-GTX stops farther than the station residents already walk to add no new
    access. GTX stays because people ride buses or cars to reach its express service.
    """
    if not current:
        return list(stations), []
    kept, excluded = [], []
    for station in stations:
        meters = station.get('distanceMeters')
        policy = (line_policy(station.get('lineId'), station.get('stage'), station.get('stageLabel'))
                  if station.get('serviceStatus') != 'operating' and station.get('scoringEligible') is not False
                  and not under_review(station) and valid(meters) and 0 <= meters <= 2000 else None)
        if policy and policy['impactClass'] != 'gtx' and meters >= current['distanceMeters']:
            excluded.append({'name':station.get('name'), 'lineId':station.get('lineId'),
                             'lineName':policy['lineName'], 'distanceMeters':round(meters)})
        else:
            kept.append(station)
    return kept, excluded


def attach(result, identity, day):
    from living_area_map import map_context
    # Each map source checks its own review date. An old pilot file must not
    # suppress independently refreshed metro station references.
    try:
        spatial = map_context(identity,result)
    except (OSError, ValueError, KeyError):
        spatial = {'zones': [], 'stations': []}
    current = current_station(identity, result.get('center') or result.get('mapCenter'))
    useful, farther = split_useful_stations(spatial.get('stations', []), current)
    spatial = {**spatial, 'stations':useful}
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
        rating['missingReasons']['transport']='현재 자료에서 직선 2km 안에 교통 점수를 계산할 수 있는 예정역을 찾지 못했어요. 새 역 계획이 없거나 위치·진행 단계 자료가 부족할 수 있어요. 기존 교통이 불편하다는 뜻은 아니에요.'
    visible_routes = [route for route in spatial.get('routes', []) if not under_review(route)]
    if (visible_routes and rating['subScores']['transport'] is None
            and result.get('metroCoverage') and (result.get('center') or result.get('mapCenter'))):
        transport_status='route_only'
        names=' · '.join(route['name'] for route in visible_routes)
        rating['missingReasons']['transport']=names+' 자료는 확인했어요. 현재 연결한 자료에 이 단지에서 이용할 신규·변경 역 위치가 없어 점수는 보류했어요.'
        coverages=[r.get('stationCoverage') or {} for r in visible_routes]
        if coverages and all(c.get('mappingComplete') and c.get('stationListComplete') and
                            (not c.get('nearestPlannedStation') or
                             (valid(c['nearestPlannedStation'].get('distanceMeters'))
                              and c['nearestPlannedStation']['distanceMeters'] > 2000))
                            for c in coverages):
            transport_status='mapped_stations_outside_2km'
            planned=[c['nearestPlannedStation'] for c in coverages if c.get('nearestPlannedStation')]
            operating=[c['nearestKnownStation'] for c in coverages if c.get('nearestKnownStation') and c['nearestKnownStation'].get('serviceStatus')=='operating']
            nearest=min(planned,key=lambda s:s['distanceMeters'],default=None)
            reason='확인한 주변 노선에서 직선 2km 안에 신규 예정역이 없어 교통 개선 가점은 0점이에요.'
            if nearest:reason+=f' 가장 가까운 신규 예정역은 {nearest["name"]}, 직선 {nearest["distanceMeters"]:,}m예요.'
            if operating:
                opened=min(operating,key=lambda s:s['distanceMeters'])
                reason+=f' {opened["name"]}: 이미 개통해 새 역 계획 점수에서 제외해요.'
            rating['missingReasons']['transport']=reason
    map_references = sorted((station for station in spatial.get('stations', [])
                             if station.get('scoringEligible') is False
                             and not under_review(station)
                             and station.get('serviceStatus') != 'operating'
                             and valid(station.get('distanceMeters'))
                             and station['distanceMeters'] <= 2000),
                            key=lambda station: station['distanceMeters'])
    if map_references and rating['subScores']['transport'] is None:
        transport_status='map_reference_only'
        nearest=map_references[0]
        names='·'.join(station['name'].split(' · ')[0] for station in map_references[:3])
        rating['missingReasons']['transport']=(
            f'지도에는 {names}의 참고 위치가 보여요. 가장 가까운 {nearest["name"].split(" · ")[0]}까지 직선 {nearest["distanceMeters"]:,}m예요. '
            '역 부지의 위치 또는 해당 노선의 정차·진행 단계를 더 확인해야 해서 교통 점수는 보류했어요. '
            '새 출입구와 실제 걸어가는 시간도 확인되지 않았어요.')
    if rating['subScores']['transport'] is None:
        unscored = {station.get('lineId') for station in spatial.get('stations', [])
                    if station.get('lineId') and station.get('scoringEligible') is not False and not under_review(station)
                    and station.get('serviceStatus') != 'operating'
                    and valid(station.get('distanceMeters')) and station['distanceMeters'] <= 2000
                    and line_policy(station['lineId'], station.get('stage'), station.get('stageLabel')) is None}
        if unscored:
            transport_status = 'line_stage_unverified'
            rating['missingReasons']['transport'] = (
                f'직선 2km 안에 예정역 참고 위치가 있지만, {len(unscored)}개 노선은 단계가 미확인됐거나 이 점수의 대상이 아니어서 보류했어요. '
                '교통이 나쁘다는 뜻은 아니에요.')
    import rail_station_mapping
    coverage = rail_station_mapping.complex_coverage(result.get('center') or result.get('mapCenter'), day)
    if (rating['subScores']['transport'] is None and coverage.get('nearbyReviewStations')
            and not coverage.get('nearbyPlannedStations') and not map_references and not visible_routes):
        transport_status = 'rail_under_review'
        rating['missingReasons']['transport'] = '재추진 중인 노선은 일정이 정해지지 않아 교통 가점에서 제외했어요.'
    # A single fully mapped nearby route is not an exhaustive station search.
    # Check the entire shared registry before asserting absence or assigning zero.
    if (rating['subScores']['transport'] is None
            and transport_status in ('mapped_stations_outside_2km','route_only','no_verified_station_within_2km')
            and coverage.get('status') == 'partial'):
        transport_status = 'station_mapping_incomplete'
        rating['missingReasons']['transport'] = (
            '다른 철도 노선의 예정역 목록·위치를 아직 확인 중이라 새 철도 가점을 보류했어요. '
            '현재 연결된 역이 없다는 이유로 0점을 주지 않아요.')
    if (rating['subScores']['transport'] is None and coverage['scopeComplete']
            and not coverage['nearbyPlannedStations'] and not coverage['nearbyReferenceStations']
            and not coverage.get('nearbyReviewStations')
            and transport_status not in ('catalogue_unavailable','location_unresolved','line_stage_unverified','map_reference_only')):
        transport_status = 'mapped_stations_outside_2km'
        rating['subScores']['transport'] = 0
        rating['components']['transport'] = {
            'summary':'등록된 철도 노선의 역 목록과 위치를 모두 확인했어요. 직선 2km 안에 신규 예정역이 없어 새 철도 가점은 0점이에요.',
            'formula':'직선 2km 안에 신규 예정역이 없으면 교통 개선 가점은 0점이에요.',
            'policy':'확인한 주변 노선의 역 목록과 위치를 기준으로 해요. 이미 개통한 역은 새 역 가점에서 제외해요. 현재 교통이 불편하다는 뜻은 아니에요.',
            'inputs':[], 'noPlannedStationWithinRadius':True}
        rating['missingReasons'].pop('transport', None)
        rating['score'] = aggregate(rating['subScores'])
        rating['status'] = 'ready' if rating['score'] is not None else 'insufficient_data'
    if rating['subScores']['transport'] is None and farther:
        transport_status = 'planned_stations_farther_than_current'
        rating['subScores']['transport'] = 0
        rating['components']['transport'] = {
            'summary':'직선 2km 안 예정역은 있지만, 지금 걸어서 타는 역보다 멀어 새 교통 가점은 0점이에요.',
            'formula':'새 예정역이 지금 가장 가까운 역보다 가깝거나, GTX처럼 더 빠른 길을 열 때만 교통 가점을 줘요.',
            'policy':(f'지금 가장 가까운 역은 {current["name"]}, 직선 {current["distanceMeters"]:,}m예요. '
                      '이미 있는 역은 생활권 변화로 보지 않고, 새 예정역이 쓸모 있는지 가리는 기준으로만 써요. '
                      '제외한 예정역: ' + ' · '.join(f'{row["name"]} {row["distanceMeters"]:,}m' for row in farther[:3])),
            'inputs':[], 'excludedStations':farther, 'currentStation':current,
            'noUsefulPlannedStation':True}
        rating['missingReasons'].pop('transport', None)
        rating['score'] = aggregate(rating['subScores'])
        rating['status'] = 'ready' if rating['score'] is not None else 'insufficient_data'
    elif farther and rating['components'].get('transport'):
        rating['components']['transport']['excludedStations'] = farther
    if rating['subScores']['transport'] is not None and not coverage['scopeComplete']:
        rating['components']['transport']['coverageIncomplete'] = True
    rating['transportCoverage']={**coverage, 'status':transport_status,'radiusMeters':2000,
                                'checkedAt':result.get('metroCoverage',{}).get('railStationCheckedAt') or result.get('metroCoverage',{}).get('checkedAt'),
                                'stationReferences':result.get('metroCoverage',{}).get('railStationReferences'),
                                'scopeComplete':coverage['scopeComplete']}
    result['planRating'] = rating
    result['snapshotId'] = sources.digest({'analysis':result['snapshotId'], 'planRating':rating})
    return result
