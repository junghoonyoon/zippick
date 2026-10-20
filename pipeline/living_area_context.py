"""Licensed source facts enrich reports independently of complete numeric scores.

Approved apartment coordinates are matched by source ID or reviewed full identity.
Official notices correct stale catalogue names/stages without inventing geometry.
"""
import copy
import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

import config
import living_area_sources as sources

POINTS_PATH = config.ROOT / 'data/living_area_apartment_points.json'
CONTEXT_PATH = config.ROOT / 'data/living_area_official_context.json'


@lru_cache(maxsize=8)
def _read(path, modified):
    return json.loads(Path(path).read_text())


def read(path):
    return copy.deepcopy(_read(str(path), path.stat().st_mtime_ns))


def recent(value, day):
    date = sources.date(value)
    return date is not None and 0 <= (day-date).days <= 120


def prepare(identity, projects, observation, day):
    projects = copy.deepcopy(projects)
    observation = copy.deepcopy(observation) if observation else {
        'apartmentId': identity.get('apartmentId'),
        'identity': {k: identity.get(k) for k in ('district', 'legalDong', 'jibun')},
        'evidence': {}, 'projectLocations': {}, 'projectRoutes': {}, 'measurements': {},
    }
    # Never repair an invalid imported identity by adding trusted evidence to it.
    if (observation.get('apartmentId') != identity.get('apartmentId') or
            any(observation.get('identity', {}).get(k) != identity.get(k) for k in ('district','legalDong','jibun'))):
        return projects, observation
    if CONTEXT_PATH.exists():
        bundle = read(CONTEXT_PATH)
        records = bundle.get('projects', [])
        if sources.digest(records) != bundle.get('projectsDigest'):
            raise ValueError('official context integrity')
        for record in records:
            if ((record['region'] != identity.get('district') and identity.get('district') not in record.get('nearbyRegions', [])) or not recent(record.get('checkedAt'), day)
                    or not sources.allowed(record['sourceId'], day=day)
                    or not sources.date(record.get('publishedAt')) or record['publishedAt'] > day.isoformat()
                    or record.get('stageAsOf', '') > day.isoformat()
                    or (record.get('referenceApartmentIds') and identity.get('apartmentId') not in record['referenceApartmentIds'])):
                continue
            existing = next((p for p in projects if p['id'] == record['id']), None)
            if existing and any(existing.get(k) != record.get(k) for k in ('region','legalDong','jibun')):
                continue
            updated = {k: v for k, v in record.items() if k != 'referenceApartmentIds'}
            if existing:
                updated['previousSource'] = {k: existing.get(k) for k in ('sourceId','sourceRecordId','snapshotId','stageLabel','sourceDate')}
                projects[projects.index(existing)] = updated
            else:
                projects.append(updated)
    if not POINTS_PATH.exists() or not sources.allowed('seoul-apartment-points', day=day):
        return projects, observation
    bundle = read(POINTS_PATH)
    if not recent(bundle.get('checkedAt'), day):
        return projects, observation
    rows = bundle.get('rows', [])
    if sources.digest(rows) != bundle.get('rowsDigest') or len(rows) != bundle.get('totalCount'):
        raise ValueError('apartment points integrity')
    indexed = {r['apt_cd']: r for r in rows}
    evidence = observation.setdefault('evidence', {})

    def location(binding):
        row = indexed.get(binding['sourceRecordId'])
        if not row or any(row.get(k) != binding.get(v) for k,v in (
                ('apt_nm','expectedName'),('apt_rdn_addr','expectedRoadAddress'),('tnohsh','expectedHouseholds'))):
            return None
        district = binding.get('district', binding.get('region'))
        if row.get('sgg_addr') != district or row.get('emd_addr') != binding.get('legalDong'):
            return None
        try:
            latitude, longitude = float(row['ycrd']), float(row['xcrd'])
        except (TypeError, ValueError):
            return None
        if not (33 <= latitude <= 39 and 124 <= longitude <= 132):
            return None
        key = 'seoul-apartment:' + row['apt_cd']
        evidence[key] = {'sourceId':'seoul-apartment-points', 'sourceRecordId':row['apt_cd'],
                         'snapshotId':bundle['rowsDigest'], 'asOfDate':bundle['checkedAt'],
                         'publishedAt':sources.stage_date(row['mdfcn_ymd']), 'collectedAt':bundle['collectedAt'],
                         'verificationStatus':'verified',
                         'raw':{'latitude':latitude,'longitude':longitude,'officialRow':row}}
        return {'latitude':latitude,'longitude':longitude,'geometryType':'point','coordinateBasis':'official_point',
                'verificationStatus':'verified','evidenceIds':[key], 'sourceRecordId':row['apt_cd']}

    def exact_binding(target):
        district = target.get('district', target.get('region'))
        dong, lot = target.get('legalDong'), str(target.get('jibun') or '').strip()
        name = re.sub(r'\s+', '', str(target.get('name') or '')).removesuffix('아파트')
        matches = []
        for row in rows:
            if row.get('sgg_addr') != district or row.get('emd_addr') != dong:
                continue
            code_match = target.get('kaptCode') and row['apt_cd'] == target['kaptCode']
            name_match = re.sub(r'\s+', '', str(row.get('apt_nm') or '')).removesuffix('아파트') == name
            # Only a complete lot number is accepted; never parse a partial address.
            lot_match = bool(re.fullmatch(r'\d+(?:-\d+)?', lot)) and row.get('daddr') == lot
            if code_match or (name and name_match and lot_match):
                matches.append(row)
        if len(matches) != 1:
            return None
        row = matches[0]
        return {'sourceRecordId':row['apt_cd'], 'district':district, 'legalDong':dong,
                'expectedName':row['apt_nm'], 'expectedRoadAddress':row['apt_rdn_addr'],
                'expectedHouseholds':row['tnohsh']}

    if not observation.get('center'):
        for binding in bundle.get('bindings', []):
            if all(identity.get(k) == binding.get(k) for k in ('apartmentId','district','legalDong','jibun')):
                center = location(binding)
                if center:
                    observation['center'] = center
                break
    for binding in bundle.get('projectBindings', []):
        project = next((p for p in projects if p['id'] == binding['projectId']), None)
        if project and all(project.get(k) == binding.get(k) for k in ('name','region','legalDong','jibun')):
            point = location(binding)
            if point:
                observation.setdefault('projectLocations', {}).setdefault(project['id'], point)
    if not observation.get('center') and (binding := exact_binding(identity)):
        if point := location(binding):
            observation['center'] = point
    for project in projects:
        if project['id'] not in observation.setdefault('projectLocations', {}) and (binding := exact_binding(project)):
            if point := location(binding):
                observation['projectLocations'][project['id']] = point
    return projects, observation


def _has_final_consonant(name):
    ending = str(name or '').rstrip(' )]}').rstrip()
    if not ending:
        return False
    last = ending[-1]
    if '가' <= last <= '힣':
        return (ord(last) - ord('가')) % 28 != 0
    if last.isdigit():
        return last in '013678'
    return False


def _topic(name):
    return '은' if _has_final_consonant(name) else '는'


def _with(name):
    return '과' if _has_final_consonant(name) else '와'


def _subject_particle(name):
    return '이' if _has_final_consonant(name) else '가'


def _project_label(name):
    return name + ' 사업' if name and name[-1].isdigit() else name


def housing_judgment(identity, project):
    """Explain possible effects on the selected apartment, never a promised gain."""
    subject = identity.get('name') or '이 단지'
    named_subject = subject + _topic(subject)
    name = _project_label(project['name'])
    meters = project.get('distanceMeters')
    stage = project.get('stage')
    kind = '재건축' if project.get('projectType') == 'reconstruction' else '재개발'
    kind_effect = '재건축으로' if kind == '재건축' else '재개발로'
    planned_move_in = bool(identity.get('plannedMoveInMonth')) and not identity.get('approvedAt')

    if meters is None:
        headline = f'{named_subject} 주변 {kind}이 매수 판단에 미칠 영향을 아직 알기 어려워요.'
    elif meters > 2000:
        headline = f'{named_subject} 주변 {kind}이 있어도 생활환경이 바뀔지는 확인이 필요해요.'
    elif stage == 'construction' and meters <= 800:
        headline = f'{named_subject} 가까운 공사의 불편과 완공 후 변화를 함께 살펴봐야 해요.'
    elif planned_move_in:
        headline = f'{named_subject} 입주할 때 주변 새 아파트와 가격을 비교해야 해요.'
    elif project.get('benefitClass') == 'direct':
        headline = f'{named_subject} 주변 {kind}까지 이어지는 길이 확인됐어요. 완공 뒤 변화를 살펴보세요.'
    elif meters <= 800:
        headline = f'{named_subject} 주변 {kind_effect} 생활환경이 달라질 수 있어요. 새 아파트와 가격을 비교하세요.'
    else:
        headline = f'{named_subject} 주변 {kind}이 있지만, 이 단지에서 누릴 생활환경 변화는 아직 확인되지 않았어요.'

    stage_name = {'planning':'계획', 'designated':'구역 지정', 'association':'조합 설립',
                  'approved':'사업 인가', 'disposal':'관리처분 인가', 'construction':'공사',
                  'completed':'완공'}.get(stage, project.get('stageLabel') or '단계 미확인')
    if meters is None:
        intro = f'{name}의 {stage_name} 자료는 확인했지만, 이 단지와의 거리는 아직 몰라요. 실제 이용할 길을 확인해야 영향을 판단할 수 있어요.'
    else:
        basis = project.get('distanceLabel') or '대표점 직선거리'
        intro = f'{name}{_topic(name)} {stage_name} 단계예요. 단지에서 {basis} {meters:,.0f}m예요. '
        if project.get('benefitClass') == 'direct':
            intro += '보행 연결은 확인됐지만 완공 시점과 가격 효과는 알 수 없어요.'
        elif planned_move_in:
            intro += '이 단지의 입주 때 주변 사업이 어디까지 진행될지 확인해야 해요.'
        else:
            intro += '실제 이용할 길과 완공 시점은 더 확인해야 해요.'
    return headline, intro


def describe(result, identity):
    """Fact-first narrative. This never fills missing metrics or changes scores."""
    all_projects = [*result['projects'], *result['referenceProjects']]
    by_id = {p['id']: p for p in all_projects}
    projects = list(by_id.values())
    projects.sort(key=lambda p: (0 if p.get('siteAreaM2') else 1 if p.get('distanceMeters') is not None else 2,
                                 p.get('distanceMeters') or 0, p['id']))
    result['displayProjects'] = projects
    from living_area_rail_policy import under_review
    projects = [p for p in projects if p.get('projectType') != 'transport' or not under_review(p)]
    result['coverage'] = {'projects':len(projects), 'mappedProjects':sum(p.get('geometryType') == 'point' for p in projects),
                          'verifiedMetrics':sum(m['value'] is not None for m in result['metrics']),
                          'totalMetrics':len(result['metrics'])}
    routes=[route for route in result.get('transportRoutes',[]) if not under_review(route)]
    route_insight=None
    if routes:
        route_insight={'kind':'transport','title':'철도 노선과 가까워도 이용할 역은 따로 확인해야 해요.',
            'fact':' · '.join(p['name']+' · '+(p.get('stageLabel') or '단계 미확인') for p in routes),
            'impact':'공개 지도에 표시된 노선 자료예요. 이미 개통한 구간이 포함될 수 있어요.',
            'caution':'노선까지의 거리는 역까지의 거리가 아니에요. 이 자료만으로 새 역세권 수혜를 계산하지 않아요.'}
    if not projects and route_insight:
        subject = identity.get('name') or '이 단지'
        result.update(insights=[route_insight],findings=[route_insight['fact']],
                      headline=f'{subject}{_topic(subject)} 철도 노선만으로 교통이 좋아질지 판단하기 어려워요.',
                      intro=route_insight['fact'])
        return result
    if not projects:
        if any(p.get('projectType') == 'transport' and under_review(p) for p in all_projects):
            result.update(insights=[], findings=[],
                headline='주변의 확인된 변화 자료가 부족해요.',
                intro='재추진 중인 철도는 일정이 정해지지 않아 매수 이유에서 제외했어요.')
        return result
    housing = [p for p in projects if p['projectType'] in ('redevelopment','reconstruction')]
    rail = [p for p in projects if p['projectType'] == 'transport']
    supply = [p for p in projects if p['projectType'] == 'new_supply']
    # Lead with the nearest located housing project; an unlocated large area
    # should not determine the apartment-specific buying verdict.
    lead = min((p for p in housing if p.get('distanceMeters') is not None),
               key=lambda p: (p['distanceMeters'], p['id']), default=housing[0] if housing else projects[0])
    insights = []
    if housing:
        p = lead
        fact = p.get('factSummary') or f'{p.get("stageLabel") or "진행 단계 미확인"} 단계예요.'
        if p.get('plannedHouseholds') and not p.get('factSummary'):
            fact += f' {p["plannedHouseholds"]:,}세대가 계획돼 있어요.'
        insights.append({'kind':'housing','title':'주거환경 개선은 가격 기대 요인이에요.', 'fact':p['name']+' · '+fact,
                         'impact': (p.get('positiveFactors') or ['새 주거지와 생활시설이 생길 가능성이 있어요.'])[0],
                         'caution':'보행 연결과 완공 시점이 확인돼야 이 단지에서 체감할 변화를 판단할 수 있어요.', 'projectId':p['id']})
    if rail:
        p=rail[0]
        insights.append({'kind':'transport','title':'예정 철도의 기대를 역세권 가격으로 계산하긴 일러요.',
                         'fact':p.get('factSummary') or p['stageLabel'],
                         'impact':'새 철도는 지역의 이동 선택지를 늘릴 수 있어요.',
                         'caution':p.get('planningNote') or '표시한 거리는 계획 참고 위치까지의 직선거리예요. 새 역 출입구와 실제 도보시간은 미확정이에요.', 'projectId':p['id']})
    elif route_insight:
        insights.append(route_insight)
    planned=[p for p in housing if p.get('plannedHouseholds')]
    if planned:
        facts=' · '.join(f'{p["name"]} {p["plannedHouseholds"]:,}세대' for p in planned[:2])
        insights.append({'kind':'competition','title':'주변 신축과의 가격 차이가 매수 판단의 핵심이에요.',
                         'fact':facts+' 계획을 확인했어요.',
                         'impact':'주거환경 개선과 별개로 새 아파트와의 가격·상품 비교가 중요해져요.',
                         'caution':'계획 물량이며 확정 입주 물량이나 같은 해 공급량이 아니에요.', 'projectId':planned[0]['id']})
    insights.append({'kind':'schedule','title':'사업이 늦어지면 기대한 변화도 늦어져요.',
                     'fact':'사업별로 현재 단계와 기준일을 아래에 표시했어요.',
                     'impact':'구역 지정 이후에도 조합·인가·공사 절차가 남을 수 있어요.',
                     'caution':'확정되지 않은 착공·입주 날짜를 계산에 넣지 않아요.'})
    result['insights']=insights
    result['findings']=[i['title']+' '+i['fact'] for i in insights]
    result['categoryFacts']={
        'housing':{'label':'주거지 변화','status':'정비계획 확인' if housing else '추가 확인','detail':f'{len(housing)}개 사업의 단계·규모 확인' if housing else '확인된 정비사업 없음'},
        'transport':{'label':'교통 변화','status':'철도 자료 확인' if rail or routes else '추가 확인','detail':rail[0]['stageLabel'] if rail else route_insight['fact'] if route_insight else '현재 연결한 자료에서 새 교통계획을 확인하지 못했어요.'},
        'competitiveness':{'label':'단지 경쟁력','status':'신축 경쟁 검토' if planned else '추가 확인','detail':'공급 계획과 실제 입주는 달라요' if planned else '공급·수요 자료 미확보'}}
    near = lead if housing and lead.get('distanceMeters') is not None else None
    subject = identity.get('name') or '이 단지'
    housing_headline, housing_intro = housing_judgment(identity, lead) if housing else (None, None)
    result['judgment']={'headline': housing_headline if housing else f'{subject}{_topic(subject)} 새 철도 계획만으로 교통 개선을 판단하기 어려워요.',
                        'shortTerm': ('공사 일정과 신축 공급 계획을 지켜보세요. 현재 확인한 사업만으로 매수 가격을 높게 잡을 근거는 부족해요.'),
                        'longTerm': (housing_intro if housing else '계획이 실현된 뒤 이용할 역과 이동시간이 달라지는지 확인해야 해요.')}
    result['headline'] = result['judgment']['headline']
    result['intro'] = result['judgment']['longTerm']
    if housing and identity.get('plannedMoveInMonth') and not identity.get('approvedAt'):
        result['insights'].insert(0, {'kind':'competition','title':'내 단지와 주변 재개발을 구분해서 봐야 해요.',
            'fact':f'{identity.get("name", "이 단지")}{_topic(identity.get("name") or "이 단지")} {identity.get("legalDong")} {identity.get("jibun")}의 입주 예정 단지예요.',
            'impact':'주변 정비사업은 별도 주소의 사업만 비교해요.',
            'caution':'내 단지의 신축 전환을 주변 개발 호재로 다시 더하지 않아요.'})
    if near:
        result['proximitySummary']=f'{near["name"]}까지 {near.get("distanceLabel") or "대표점 직선거리"} {near["distanceMeters"]:,.0f}m예요. 도보거리가 아니에요.'
    if supply and not housing and not rail:
        result['headline']=f'{subject}{_topic(subject)} 입주 예정인 새 아파트와 가격을 비교하세요.'
        result['intro']=supply[0].get('factSummary') or '주변 새 아파트의 입주 계획을 확인했어요.'
        result['judgment'].update(headline=result['headline'],longTerm=result['intro'])
        result['insights'].insert(0,{'kind':'competition','title':'주변 입주 물량은 가격 경쟁에 영향을 줄 수 있어요.',
            'fact':supply[0]['name']+' · '+result['intro'],
            'impact':'같은 평형의 가격과 입주 시점을 비교하세요.',
            'caution':'공고 공급분이며 전체 단지 규모나 확정 입주 물량과 다를 수 있어요.'})
    result['confidence']='partial_verified' if result['score'] is None else 'reviewed'
    return result


VERDICT_POLICY_VERSION = 'living-area-verdict-v14'
VERDICT_LABELS = {'good':('좋아요', '좋아요.'), 'normal':('보통', '보통이에요.'),
                  'weak':('약해요', '약해요.'), 'pending':('판단 보류', '판단을 보류했어요.')}
STAGE_MEANING = {'planning':'계획만 나온 초기 단계', 'designated':'구역 지정만 된 초기 단계',
                 'association':'조합을 만든 중간 단계', 'approved':'사업 인가를 받은 중반 단계',
                 'disposal':'관리처분 인가를 받은 착공 바로 전 단계', 'construction':'공사 중인 단계',
                 'completed':'공사가 끝난 단계'}
EARLY_STAGES = {'planning', 'designated'}


def _station_distance_meaning(meters):
    if meters <= 800:
        return '걸어서 다닐 만한 거리예요'
    if meters <= 1500:
        return '매일 걸어서 타기엔 조금 먼 거리예요'
    return '매일 걸어서 타기엔 먼 거리예요'


def conclude(result, identity):
    """Lead with a buying judgment after the housing and rail plan scores exist.

    A nearby plan is not a verified price gain or a usable new station.
    """
    subject = identity.get('name') or '이 단지'
    named_subject = subject + _topic(subject)
    projects = result.get('displayProjects', [])
    housing = [p for p in projects if p.get('projectType') in ('redevelopment', 'reconstruction')]
    plan = result.get('planRating') or {}
    score = plan.get('score')
    components = plan.get('components') or {}
    housing_component = components.get('housing') or {}
    housing_count = housing_component.get('projectCount') or 0
    lead = next((p for p in housing if p.get('id') == housing_component.get('selectedProjectId')), None)
    if lead is None:
        lead = min((p for p in housing if p.get('distanceMeters') is not None),
                   key=lambda p: (p['distanceMeters'], p['id']), default=housing[0] if housing else None)
    lead_name = _project_label(lead['name']) if lead else None
    rail_component = components.get('transport') or {}
    rail_input = max((row for row in rail_component.get('inputs', [])
                      if row.get('projectId') == rail_component.get('selectedProjectId')),
                     key=lambda row: row.get('rawScore', -1), default=None)
    rail_project = next((p for p in projects if p.get('id') == (rail_input or {}).get('projectId')), None)
    rail_name = rail_project['name'] if rail_project else (rail_input or {}).get('name')
    from living_area_rail_policy import under_review
    route = next((route for route in result.get('transportRoutes') or [] if not under_review(route)), None)
    direct = lead is not None and lead.get('benefitClass') == 'direct'
    planned_move_in = bool(identity.get('plannedMoveInMonth')) and not identity.get('approvedAt')
    sub_scores = plan.get('subScores') or {}
    housing_score = sub_scores.get('housing')
    transport_score = sub_scores.get('transport')
    map_station_only = (plan.get('transportCoverage') or {}).get('status') == 'map_reference_only'
    stations_outside = (plan.get('transportCoverage') or {}).get('status') == 'mapped_stations_outside_2km'
    station_mapping_incomplete = (plan.get('transportCoverage') or {}).get('status') == 'station_mapping_incomplete'
    transport_reason = (rail_component.get('summary') or (plan.get('missingReasons') or {}).get('transport')
                        or '새 철도 계획의 역 위치·진행 단계 자료가 부족해 교통 점수를 계산하지 못했어요.')
    strong_plans = (score is not None and score >= 3.8 and lead is not None and rail_input is not None
                    and (housing_score or 0) >= 3.5 and (transport_score or 0) >= 3.5)
    # Multiple scored housing plans and a nearby scored station can describe a
    # changing neighborhood even when the single best rail plan is only moderate.
    nearby_housing = {row.get('projectId') for row in housing_component.get('inputs', [])
                      if row.get('projectId') and isinstance(row.get('distanceMeters'), (int, float))
                      and 0 <= row['distanceMeters'] <= 2000}
    clustered_plans = (score is not None and score >= 3.8 and lead is not None and rail_input is not None
                       and (housing_score or 0) >= 3.5 and (transport_score or 0) >= 3.0
                       and len(nearby_housing) >= 3
                       and any(row.get('projectId') in nearby_housing and isinstance(row.get('distanceMeters'), (int, float))
                               and row['distanceMeters'] <= 800 for row in housing_component.get('inputs', []))
                       and isinstance(rail_input.get('distanceMeters'), (int, float))
                       and rail_input['distanceMeters'] <= 1500)
    lead_row = next((row for row in housing_component.get('inputs', [])
                     if lead and row.get('projectId') == lead.get('id')), None) or {}
    lead_meters = lead_row.get('distanceMeters', (lead or {}).get('distanceMeters'))
    lead_stage = lead_row.get('stage') or (lead or {}).get('stage')
    households_total = housing_component.get('plannedHouseholdsTotal')
    rail_meters = (rail_input or {}).get('distanceMeters')
    housing_known = housing_score is not None
    transport_known = transport_score is not None

    # Briefing frame: verdict -> one-line reason -> strengths/weaknesses -> advice.
    # "**" marks the one phrase per line that the report screen shows in bold.
    strengths, weaknesses, unknowns, caveats = [], [], [], []
    if lead:
        brief_lead = lead_name if re.search(r'(구역|사업|재개발|재건축|아파트|단지|차)$', lead_name) else lead_name + ' 사업'
        named_lead = brief_lead + _topic(brief_lead)
        stage_text = STAGE_MEANING.get(lead_stage) or ((lead.get('stageLabel') or '진행 단계 미확인') + ' 단계')
        if isinstance(lead_meters, (int, float)):
            lead_text = (f'가장 영향이 큰 {named_lead} 직선 {lead_meters:,.0f}m 떨어져 있고, **{stage_text}**예요.'
                         if housing_count > 1 else
                         f'{named_lead} 직선 {lead_meters:,.0f}m 떨어져 있고, **{stage_text}**예요.')
        else:
            lead_text = f'{named_lead} **{stage_text}**예요. 이 단지와의 거리는 확인 중이에요.'
        if housing_count > 1:
            lead_text = (f'직선 2km 안에 정비사업이 {housing_count}곳이에요. '
                         + (('세대수가 확인된 곳의 ' if housing_component.get('areaOnlyProjectCount') else '')
                            + f'계획 세대는 모두 {households_total:,.0f}세대예요. ' if households_total else '')
                         + lead_text)
        if direct:
            lead_text += f' 단지에서 {brief_lead}까지 걸어가는 길도 확인됐어요.'
        if (housing_score if housing_known else score if score is not None else 3.0) >= 3.0:
            strengths.append(lead_text)
        else:
            weaknesses.append(lead_text + ' 규모와 거리를 따지면 가점은 작아요.')
    elif score is None:
        unknowns.append('현재 자료에서 직선 2km 안의 정비사업을 찾지 못했어요.')
    else:
        weaknesses.append('직선 2km 안에 확인된 정비사업이 없어요.')

    if rail_input:
        station = rail_input.get('name') or rail_name
        line = rail_input.get('lineName') or rail_name
        station_label = station if not line or line in station else f'{line} {station}'
        if isinstance(rail_meters, (int, float)):
            rail_text = f'{station_label} 예정 위치가 직선 {rail_meters:,.0f}m예요. **{_station_distance_meaning(rail_meters)}**.'
            if (transport_score if transport_known else 3.0) >= 3.0:
                strengths.append(rail_text)
            else:
                weaknesses.append(rail_text + ' 새 교통 가점은 작아요.')
            caveats.append('새 노선 출입구와 걸어가는 시간은 확인되지 않았어요.')
        else:
            unknowns.append(f'{station_label} 계획은 있지만, 이 단지에서 이용할 역 위치는 확인 중이에요.')
    elif transport_score == 0 and stations_outside:
        weaknesses.append('직선 2km 안에 새로 생길 예정역이 없어요.')
    elif map_station_only or stations_outside or station_mapping_incomplete or not route:
        unknowns.append(transport_reason)
    else:
        route_meters = route.get('distanceMeters')
        unknowns.append(f'{route["name"]}' + (f'까지 직선 {route_meters:,.0f}m예요. ' if route_meters is not None else ' 노선 자료만 확인했어요. ')
                        + '이용할 역 위치를 몰라 교통 점수는 계산하지 않았어요.')

    if score is None:
        verdict = 'pending'
        if housing_known and not transport_known:
            reason = ('정비사업은 기대되지만, 교통 자료가 아직 없어요' if housing_score >= 3.0 else
                      '정비사업 가점은 작고, 교통 자료는 아직 없어요')
            advice = [f'{named_subject} 주거환경만 보면 기대할 만해요.' if housing_score >= 3.0 else
                      f'{named_subject} 주변 주거환경 변화가 크지 않아요.',
                      '교통 자료가 들어오면 판정을 다시 내려요.']
        elif transport_score == 0 and stations_outside and not housing_known:
            reason = '2km 안에 새 예정역이 없고, 주거환경 자료는 아직 없어요'
            advice = ['새 철도로 교통이 좋아질 계획은 확인되지 않았어요.', '주거환경 자료가 들어오면 판정을 다시 내려요.']
        elif transport_known and not housing_known:
            reason = ('새 철도는 기대되지만, 주거환경 자료가 아직 없어요' if transport_score >= 3.0 else
                      '새 철도 가점은 작고, 주거환경 자료는 아직 없어요')
            advice = [f'{named_subject} 새 철도 계획만 확인했어요.', '주거환경 자료가 들어오면 판정을 다시 내려요.']
        else:
            reason = ('주변 사업은 보이지만, 판단할 자료가 아직 부족해요' if lead and (rail_input or route) else
                      '정비사업은 보이지만, 판단할 자료가 아직 부족해요' if lead else
                      '철도 계획은 보이지만, 판단할 자료가 아직 부족해요' if rail_input or route else
                      '판단할 자료가 아직 부족해요')
            advice = ['사업 위치와 새 역 자료가 확인되면 다시 평가할 수 있어요.']
    elif direct and score >= 3.5:
        verdict = 'good'
        reason = '정비사업 구역까지 걸어가는 길이 이어져 있어요'
        advice = [f'{lead_name}에 새 아파트와 생활시설이 들어서면 {subject}에서도 가까이 누릴 수 있어요.',
                  '완공 시점에 맞춰 주변 새 아파트와 가격 차이를 살펴보세요.']
    elif strong_plans:
        verdict = 'good'
        reason = '정비사업과 새 역, 두 계획이 함께 있어요'
        advice = [f'{named_subject} 주변이 새 아파트 동네로 바뀌고, 새 역도 계획된 곳이에요.',
                  '두 계획이 함께 있는 단지는 비교 후보로 먼저 볼 만해요.',
                  '다만 기대가 이미 가격에 들어갔는지 주변 새 아파트 가격과 비교해 보세요.']
    elif clustered_plans:
        verdict = 'good'
        reason = '정비사업이 몰려 있고, 예정역도 가까워요'
        advice = [f'{named_subject} 한두 곳이 아니라 동네 전체가 바뀌는 곳이에요.',
                  '사업마다 속도가 달라서 몇 년에 걸쳐 바뀐다고 보세요.',
                  '가장 빠른 사업의 진행 상황부터 확인하세요.']
    else:
        verdict = 'weak' if score < 3.0 else 'normal'
        if lead and rail_name and housing_known and transport_known and housing_score >= 3.5 and transport_score < 3.0:
            reason = ('정비사업은 많지만, 새 교통 호재는 약해요' if housing_count >= 3 else
                      '정비사업은 기대되지만, 새 교통 호재는 약해요')
            advice = [f"{named_subject} '교통이 좋아지는 곳'보다 '동네가 새 아파트로 바뀌는 곳'에 가까워요.",
                      '매수 판단의 근거는 새 철도보다 주변 정비사업이에요.',
                      '사업이 끝날 때마다 새 아파트와 이 단지의 가격 차이를 비교해 보세요.']
        elif lead and rail_name and housing_known and transport_known and transport_score >= 3.5 and housing_score < 3.0:
            reason = '새 역은 기대되지만, 동네 변화는 작아요'
            advice = [f'{named_subject} 새 역이 생기면 출퇴근이 편해질 수 있어요.',
                      '하지만 동네 모습은 크게 바뀌지 않아요.',
                      '착공과 개통 일정이 실제로 진행되는지가 가장 중요해요.']
        elif planned_move_in and verdict == 'normal':
            reason = '주변 사업이 입주 때까지 얼마나 진행될지가 관건이에요'
            advice = [f'{named_subject} 입주 직후에 주변이 아직 공사 중일 수 있어요.',
                      '주변 사업이 끝나면 이 단지와 새 아파트가 서로 비교 대상이 돼요.',
                      '입주 시기와 주변 공사 일정을 겹쳐서 보세요.']
        elif verdict == 'weak':
            if lead and lead_stage in EARLY_STAGES and isinstance(lead_meters, (int, float)) and lead_meters > 1000:
                reason = '계획은 있지만, 아직 초기이고 거리도 멀어요'
                advice = [f'{named_subject} 몇 년 뒤 주변이 바뀔 수는 있지만, 지금 가격에 넣기에는 이른 단계예요.',
                          '사업이 조합 설립이나 인가로 넘어가면 다시 볼 만해요.']
            else:
                reason = ('주변 계획은 있지만, 가점이 될 만큼 크지 않아요' if lead or rail_name else
                          '주변에 큰 변화 계획이 아직 없어요')
                advice = [f'{named_subject} 변화를 기대하고 사는 단지는 아니에요.',
                          '지금의 교통, 학교, 상권이 마음에 드는지로 판단하세요.']
        else:
            reason = ('정비사업과 새 철도 계획이 있지만, 효과는 보통이에요' if lead and rail_name else
                      '정비사업은 있지만, 새 교통 계획은 확인되지 않았어요' if lead else
                      '새 철도 계획은 있지만, 주변 정비사업은 확인되지 않았어요' if rail_name else
                      '확인된 계획의 실제 효과는 더 지켜봐야 해요')
            advice = [f'{named_subject} 변화 계획은 있지만, 바로 체감할 정도는 아니에요.',
                      '가장 가까운 사업의 진행 단계를 지켜보세요.']

    if lead_meters is not None or rail_meters is not None:
        caveats.insert(0, '거리는 모두 직선 기준이에요. 실제 걸어가는 길과 달라요.')
    operating_stations = (plan.get('transportCoverage') or {}).get('nearbyOperatingStations', [])
    if operating_stations:
        current = operating_stations[0]
        caveats.append(f'지금 이용하는 {current["name"]}까지는 직선 {current["distanceMeters"]:,}m예요. '
                       '이미 있는 교통이라 변화 점수에는 넣지 않았어요.')
    if verdict == 'good' and not direct:
        caveats.append('계획 점수는 실제로 누릴 이점이나 집값 상승을 뜻하지 않아요.')
    if verdict == 'weak':
        caveats.append("'약해요'는 지금 살기 나쁘다는 뜻이 아니에요. 앞으로 바뀔 거리가 적다는 뜻이에요.")

    label, sentence = VERDICT_LABELS[verdict]
    headline = f'생활권 변화는 {sentence} {reason}.'
    intro = ' '.join(advice)
    result['briefing'] = {'verdict':verdict, 'label':label, 'reason':reason + '.',
                          'strengths':strengths, 'weaknesses':weaknesses, 'unknowns':unknowns,
                          'advice':advice, 'caveats':caveats}
    result['headline'] = headline
    result['intro'] = intro
    result.setdefault('judgment', {}).update(headline=headline, shortTerm=reason + '.', longTerm=intro,
                                             policyVersion=VERDICT_POLICY_VERSION)
    if result.get('snapshotId'):
        result['snapshotId'] = sources.digest({'planSnapshot':result['snapshotId'],
                                               'judgmentVersion':VERDICT_POLICY_VERSION,
                                               'headline':headline, 'intro':intro,
                                               'briefing':result['briefing']})
    return result


def save_points(rows, *, day=None, path=None):
    """Promote a complete official export; preserve reviewed identity bindings."""
    day = day or dt.date.today()
    path = path or POINTS_PATH
    if not sources.allowed('seoul-apartment-points', day=day) or not rows:
        raise sources.SourceError('공식 단지 좌표의 이용조건과 전체 파일을 확인해야 해요.')
    keys = ('sn','apt_cd','apt_nm','sgg_addr','emd_addr','daddr','apt_rdn_addr',
            'xcrd','ycrd','tnohsh','use_aprv_ymd','mdfcn_ymd')
    sanitized = [{k:r.get(k) for k in keys} for r in rows]
    ids = [r['apt_cd'] for r in sanitized]
    if any(not k for k in ids) or len(ids) != len(set(ids)):
        raise sources.SourceError('공식 단지 고유값이 없거나 중복돼요.')
    old = read(path) if path.exists() else {}
    payload = {'sourceId':'seoul-apartment-points', 'checkedAt':day.isoformat(),
               'collectedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
               'totalCount':len(rows), 'originalRowsDigest':sources.digest(rows),
               'rowsDigest':sources.digest(sanitized), 'rows':sanitized,
               'bindings':old.get('bindings', []), 'projectBindings':old.get('projectBindings', [])}
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)
