"""Business-condition conclusions use shared facts without inventing returns."""
import pytest

import apartment_reconstruction as r
from test_apartment_reconstruction import DAY, ENTITY, context, entry, ordinance_context
from test_reconstruction_frontend import HARNESS, NAMES, run_js


@pytest.fixture(autouse=True)
def plan_source(monkeypatch):
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
assert.match(html,/건폐율은 현재 건물 배치/);
for(const status of ['stale','connection_error','loading']) {
 item.reconstructionConditions.status=status;
 assert.ok(!zippickReconstructionHtml(item).includes(f.headline));
}
''')

