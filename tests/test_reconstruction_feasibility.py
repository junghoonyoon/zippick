"""Business-condition conclusions use shared facts without inventing returns."""
import pytest

import apartment_reconstruction as r
from test_apartment_reconstruction import DAY, ENTITY, context, entry, ordinance_context
from test_reconstruction_report import HARNESS, NAMES
from test_report_loading import run_js
from test_report_renewal_titles import renewal_run


@pytest.fixture(autouse=True)
def plan_source(monkeypatch, tmp_path):
    monkeypatch.setattr(r.shared_data, 'cache_path', lambda name: tmp_path / name)
    monkeypatch.setattr(r.reconstruction_project_plans, 'for_apartment', lambda *a, **k: {'status': 'not_found'})


def analyze(**kwargs):
    return r.analyze(ENTITY, kwargs.pop('entry', entry()), kwargs.pop('context', context()), day=DAY, **kwargs)


@pytest.mark.parametrize('ceiling,direction', [(250, 'favorable'), (175, 'limited'), (160, 'unfavorable'), (150, 'unfavorable')])
def test_good_small_and_no_capacity_are_explained_without_financial_score(ceiling, direction):
    model = analyze(context=context(floorAreaRatio=ceiling))
    f = model['feasibility']
    assert f['direction'] == direction
    assert f['status'] == 'assessed'
    assert f['comparison']['differencePp'] == ceiling - 160
    assert f['financialStatus'] == 'not_assessed'
    assert '사업성' in f['headline']
    assert '공사비' in f['financialLimitation']
    assert not {'score', 'probability', 'profit', 'generalSaleHouseholds'}.intersection(f)
    assert '불가능' not in f['headline'] + f['reason']


def test_exact_plan_is_a_conditional_direction_even_with_different_boundary(monkeypatch):
    plan = {'status': 'ready', 'apartmentId': ENTITY['apartmentId'],
            'identityMatch': 'district_dong_parcel_and_name', 'plannedFloorAreaRatio': 249.99,
            'plannedHouseholds': 1126, 'projectAreaSqm': 63257}
    monkeypatch.setattr(r.reconstruction_project_plans, 'for_apartment', lambda *a, **k: plan)
    f = analyze(context={})['feasibility']
    assert f['direction'] == 'favorable'
    assert f['status'] == 'conditional'
    assert f['headline'].startswith('계획 기준으로는')
    assert f['comparison']['differencePp'] is None
    assert f['comparison']['siteScopeVerified'] is False
    assert '범위가 다를 수 있어' in f['scopeNote']
    assert not {'householdIncrease', 'additionalFloorAreaSqm', 'generalSaleHouseholds'}.intersection(f)
    # No new designation or profit is invented from an exact-name plan.
    assert 'stage' not in f


@pytest.mark.parametrize('patch', [{'status': 'stale'}, {'status': 'ambiguous'},
                                  {'apartmentId': 'another'}, {'identityMatch': 'name_only'},
                                  {'plannedFloorAreaRatio': 0}])
def test_bad_plan_cannot_create_a_favorable_verdict(monkeypatch, patch):
    plan = {'status': 'ready', 'apartmentId': ENTITY['apartmentId'],
            'identityMatch': 'district_dong_parcel_and_name', 'plannedFloorAreaRatio': 250, **patch}
    monkeypatch.setattr(r.reconstruction_project_plans, 'for_apartment', lambda *a, **k: plan)
    assert analyze(context={})['feasibility']['direction'] == 'unknown'


def test_parcel_is_explicitly_conditional_and_plan_takes_precedence(monkeypatch):
    f = analyze(context=ordinance_context())['feasibility']
    assert f['headline'].startswith('조례 기준이 적용된다면')
    assert f['status'] == 'conditional'
    assert f['comparison']['differencePp'] is None
    assert '단지 전체' in f['scopeNote']
    monkeypatch.setattr(r.reconstruction_project_plans, 'for_apartment', lambda *a, **k: {
        'status': 'ready', 'apartmentId': ENTITY['apartmentId'],
        'identityMatch': 'district_dong_parcel_and_name', 'plannedFloorAreaRatio': 160})
    f = analyze(context=ordinance_context())['feasibility']
    assert f['basisKind'] == 'project_plan'
    assert f['direction'] == 'unfavorable'


def test_zero_stale_or_failed_building_source_does_not_become_a_bad_or_good_verdict():
    for value in [None, 0, -1, 'NaN', 'Infinity']:
        assert analyze(entry=entry(vlRat=value))['feasibility']['direction'] == 'unknown'
    for change in ['old', 'failed']:
        e = entry()
        if change == 'old':
            e['snapshot']['fetchedAt'] = '2020-01-01'
        else:
            e['lastError'] = {'status': 'connection_error'}
        f = analyze(entry=e)['feasibility']
        assert f['direction'] == 'unknown'
        assert f['status'] == 'unavailable'


def test_building_coverage_age_and_household_counts_do_not_manufacture_profitability():
    low = analyze(entry=entry(bcRat=5, archArea=2000))['feasibility']
    high = analyze(entry=entry(bcRat=50, archArea=20000))['feasibility']
    assert low == high
    assert analyze(context={})['feasibility']['direction'] == 'unknown'
    young = r.analyze({**ENTITY, 'approvedAt': '2020-01-01'}, entry(), context(), day=DAY)
    assert young['feasibility']['status'] == 'not_assessed'


def test_verified_active_plan_is_not_hidden_just_because_the_master_is_under_thirty(monkeypatch):
    monkeypatch.setattr(r.reconstruction_project_plans,'for_apartment',lambda *a,**k:{
        'status':'ready','apartmentId':ENTITY['apartmentId'],'identityMatch':'district_dong_parcel_and_name',
        'plannedFloorAreaRatio':250,'stageLabel':'조합설립인가'})
    model=r.analyze({**ENTITY,'approvedAt':'1999-01-01'},entry(),{},day=DAY)
    assert model['grade'] != 'not_assessed'
    assert model['feasibility']['direction'] == 'favorable'


@pytest.mark.parametrize('households_match,direction',[(True,'favorable'),(False,'unknown')])
def test_missing_recap_can_only_use_published_before_after_density_with_matching_households(monkeypatch, households_match, direction):
    monkeypatch.setattr(r.reconstruction_project_plans,'for_apartment',lambda *a,**k:{
        'status':'ready','apartmentId':ENTITY['apartmentId'],'identityMatch':'district_dong_parcel_and_name',
        'plannedFloorAreaRatio':250,'existingFloorAreaRatio':160,'subjectHouseholdsMatch':households_match,
        'sourceDate':'2026-09-30','stageLabel':'추진위원회승인'})
    model=r.analyze(ENTITY,{'status':'no_records'}, {},day=DAY)
    f=model['feasibility']
    assert f['direction'] == direction
    if households_match:
        assert f['status'] == 'conditional'
        assert f['comparison']['currentSource'] == 'official_project_inventory'
        assert f['comparison']['differencePp'] is None
        assert '통계' in f['scopeNote']
        assert model['profile'] == {}  # the inventory never becomes a building-register fact


def test_all_existing_attach_consumers_receive_identical_analysis_for_each_area():
    # analyze() is the one path reused by candidate, location, report, and refresh APIs.
    model = analyze()
    for area in [59, 84, 59.87]:
        other = r.analyze({**ENTITY, 'areaLabel': str(area)}, entry(), context(), day=DAY)
        assert other == model


def test_actual_render_and_failed_refresh_never_keep_a_positive_conclusion():
    import json
    f = analyze()['feasibility']
    run_js(NAMES, HARNESS + 'const f=' + json.dumps(f, ensure_ascii=False) + ';' + r'''
item.reconstructionConditions=model({status:'ready', feasibility:f});
const html=zippickReconstructionHtml(item);
assert.ok(html.includes(f.headline));assert.ok(html.includes(f.financialLimitation));
assert.ok(html.indexOf(f.headline)<html.indexOf('160%'));
assert.match(html,/그 밖의 땅이 모두 녹지나 더 지을 수 있는 땅은 아니/);
for(const status of ['stale','connection_error','loading']) {
 item.reconstructionConditions.status=status;
 assert.ok(!zippickReconstructionHtml(item).includes(f.headline));
}
''')


def test_stage_and_feasibility_share_a_heading_while_scores_and_order_are_preserved():
    import json
    f = analyze()['feasibility']
    renewal_run('const f=' + json.dumps(f, ensure_ascii=False) + ';' + r'''
const item=attach(oldApartment());const original=verdict(item), before=zippickDevelopmentHtml(item);
item.reconstructionConditions={version:'reconstruction-conditions-v1',apartmentId:item.apartmentId,
 identity:{legalDong:item.legalDong,jibun:item.jibun},status:'ready',profile:{},feasibility:f};
const after=verdict(item), html=zippickDevelopmentHtml(item);
for(const key of ['tone','stars','scores','priceTitle','price','reason']) assert.deepEqual(after[key],original[key]);
assert.ok(after.reviewHeadline.includes(`재건축은 초기지만, ${f.headline}`));
assert.ok(after.summary.includes(f.headline));assert.equal(after.propertyHeading,original.propertyHeading);
assert.ok(!after.summary.includes(f.financialLimitation));
assert.match(html,/<h5>재건축은 초기지만.*사업성에 유리한 건축 조건/);assert.ok(html.includes(f.reason));
assert.equal((html.match(/<h5>/g)||[]).length,1);
assert.equal(html.split('단지 변화 별점 기준').length, before.split('단지 변화 별점 기준').length);
assert.ok(html.indexOf('단지 변화 별점 기준')<html.indexOf('재건축 여건'));
// Remodeling and terminal projects cannot inherit a reconstruction business conclusion.
item.futureTransformation.ownDevelopment.rating.projectType='remodeling';
assert.equal(zippickReconstructionFeasibility(item),null);
item.futureTransformation.ownDevelopment.rating.projectType='reconstruction';
item.futureTransformation.ownDevelopment.status='completed_or_cancelled';
assert.equal(zippickReconstructionFeasibility(item),null);
''')
