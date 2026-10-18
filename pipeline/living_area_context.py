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
    result['coverage'] = {'projects':len(projects), 'mappedProjects':sum(p.get('geometryType') == 'point' for p in projects),
                          'verifiedMetrics':sum(m['value'] is not None for m in result['metrics']),
                          'totalMetrics':len(result['metrics'])}
    routes=result.get('transportRoutes',[])
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


VERDICT_POLICY_VERSION = 'living-area-verdict-v7'


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
    route = next(iter(result.get('transportRoutes') or []), None)
    direct = lead is not None and lead.get('benefitClass') == 'direct'
    planned_move_in = bool(identity.get('plannedMoveInMonth')) and not identity.get('approvedAt')
    sub_scores = plan.get('subScores') or {}
    housing_score = sub_scores.get('housing')
    transport_score = sub_scores.get('transport')
    strong_plans = (score is not None and score >= 3.8 and lead is not None and rail_input is not None
                    and (housing_score or 0) >= 3.5 and (transport_score or 0) >= 3.5)
    contrast_decision = None
    partial_headline = None
    if lead and rail_name and housing_score is not None and transport_score is not None:
        if housing_score >= 3.5 and transport_score < 3.0:
            contrast_decision = f'{named_subject} {lead_name} 계획이 눈여겨볼 만하지만 {rail_name}의 교통 가점은 작아요.'
        elif transport_score >= 3.5 and housing_score < 3.0:
            contrast_decision = f'{named_subject} {rail_name} 계획이 눈여겨볼 만하지만 {lead_name}의 주거 변화 가점은 작아요.'

    if score is None:
        verdict = '판단할 수 없어요.'
        if housing_score is not None and transport_score is None and lead:
            nearby_housing = [row for row in housing_component.get('inputs', [])
                              if row.get('distanceMeters') is not None and row['distanceMeters'] <= 800]
            selected_is_nearby = any(row.get('projectId') == housing_component.get('selectedProjectId')
                                     for row in nearby_housing)
            project_phrase = (f'{lead_name} 등 가까운 정비사업'
                              if selected_is_nearby and len(nearby_housing) > 1 else f'{lead_name} 계획')
            if housing_score >= 4.0:
                decision = f'{named_subject} {project_phrase}으로 주변 주거환경이 크게 바뀔 수 있어요. 새 철도 수혜는 아직 확인되지 않았어요.'
            elif housing_score >= 3.0:
                decision = f'{named_subject} {project_phrase}으로 주거환경이 달라질 수 있어요. 교통 개선은 아직 평가하지 못했어요.'
            else:
                decision = f'{named_subject} 확인된 주거환경 변화의 가점은 작아요. 교통 개선은 아직 평가하지 못했어요.'
            partial_headline = decision
        elif transport_score is not None and housing_score is None and rail_name:
            if transport_score >= 3.5:
                decision = f'{subject}의 {rail_name} 계획에 따른 교통 가점은 눈여겨볼 만해요. 주거환경 변화는 아직 평가하지 못했어요.'
            elif transport_score >= 3.0:
                decision = f'{subject}의 {rail_name} 계획에 따른 교통 가점은 보통이에요. 주거환경 변화는 아직 평가하지 못했어요.'
            else:
                decision = f'{subject}의 {rail_name} 계획에 따른 교통 가점은 작아요. 주거환경 변화는 아직 평가하지 못했어요.'
            partial_headline = decision
        elif lead and (rail_input or route):
            decision = f'{named_subject} 주변 사업은 보이지만 생활권 전체를 평가할 자료는 부족해요.'
        elif lead:
            decision = f'{named_subject} {lead_name}{_topic(lead_name)} 확인됐지만 교통 변화는 아직 평가할 수 없어요.'
        elif rail_input or route:
            decision = f'{named_subject} 새 철도 계획은 있지만 이용할 역의 위치가 확인되지 않았어요.'
        else:
            decision = f'{named_subject} 주변의 확인된 변화 자료가 부족해요.'
    elif direct and score >= 3.5:
        verdict = '좋아요.'
        decision = f'{named_subject} {lead_name}까지 가는 길이 확인됐어요. 완공 시점을 따져 보세요.'
    elif strong_plans:
        verdict = '좋아요.'
        decision = f'{subject}의 매수 비교에서는 {lead_name}{_with(lead_name)} {rail_name} 계획이 모두 가점이에요.'
    elif score < 3.0:
        verdict = '아쉬워요.'
        if contrast_decision:
            decision = contrast_decision
        elif rail_name and lead:
            decision = f'{named_subject} {lead_name}{_with(lead_name)} {rail_name} 계획이 있어도 현재 확인된 가점은 작아요.'
        elif rail_name:
            decision = f'{named_subject} {rail_name} 계획에서 확인된 교통 가점은 작아요.'
        elif lead:
            decision = f'{named_subject} {lead_name} 계획에서 확인된 주거 변화 가점은 작아요.'
        else:
            decision = f'{named_subject} 현재 확인된 주변 계획의 가점은 작아요.'
    else:
        verdict = '보통이에요.'
        if contrast_decision:
            decision = contrast_decision
        elif planned_move_in:
            decision = f'{named_subject} 입주할 때 {lead_name}{_with(lead_name)} {rail_name} 계획이 어디까지 진행됐는지 확인하세요.' if lead and rail_name else f'{named_subject} 입주할 때 주변 사업의 진행 상황을 확인하세요.'
        elif lead and rail_name:
            decision = f'{named_subject} {lead_name}{_with(lead_name)} {rail_name} 계획이 있지만 실제 이용 변화는 더 확인해야 해요.'
        elif lead:
            decision = f'{named_subject} {lead_name} 계획이 있지만 실제 생활 변화는 더 확인해야 해요.'
        elif rail_name:
            decision = f'{named_subject} {rail_name} 계획이 있지만 이용할 역은 더 확인해야 해요.'
        else:
            decision = f'{named_subject} 확인된 계획의 실제 이용 변화는 더 확인해야 해요.'

    facts = []
    if lead:
        _, housing_intro = housing_judgment(identity, lead)
        facts.append(housing_intro)
    if rail_input:
        station = rail_input.get('name') or rail_name
        meters = rail_input.get('distanceMeters')
        if meters is not None:
            facts.append(f'{station}의 참고 위치는 직선 {meters:,.0f}m예요. 새 노선 출입구와 걸어가는 시간은 확인되지 않았어요.')
        else:
            facts.append(f'{station} 계획은 확인했지만 이 단지에서 이용할 역의 위치는 확인되지 않았어요.')
    elif route:
        facts.append(f'{route["name"]} 노선 자료는 확인했지만 이 단지에서 이용할 새 역의 위치는 확인되지 않았어요.')
    if strong_plans and not direct:
        facts.append('계획 점수는 실제로 누릴 이점이나 집값 상승을 뜻하지 않아요.')
    if score is not None and score < 3.0:
        facts.append('낮은 계획 점수는 지금 살기 나쁘거나 집값이 내려간다는 뜻이 아니에요.')
    if not facts:
        facts.append('사업 위치와 새 역 자료가 확인되면 다시 평가할 수 있어요.')
    headline = partial_headline or f'생활권 변화는 {verdict} {decision}'
    intro = ' '.join(facts)
    result['headline'] = headline
    result['intro'] = intro
    result.setdefault('judgment', {}).update(headline=headline, shortTerm=decision, longTerm=intro,
                                             policyVersion=VERDICT_POLICY_VERSION)
    if result.get('snapshotId'):
        result['snapshotId'] = sources.digest({'planSnapshot':result['snapshotId'],
                                               'judgmentVersion':VERDICT_POLICY_VERSION,
                                               'headline':headline, 'intro':intro})
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
