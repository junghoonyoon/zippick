import copy
import datetime as dt
import json

import future_transformation as future
import living_area as living
import living_area_context as context
import living_area_reference_points as refs
import living_area_sources as sources

DAY = dt.date(2026, 10, 16)
ID = '484457631ccb1633'


def subject():
    return {**future.registry_entity(ID), 'apartmentId':ID}


def test_heristone_has_nearby_plans_without_invented_direct_benefits():
    x = subject()
    report = living.analyze(x, day=DAY)
    projects = {p['id']:p for p in report['displayProjects']}
    assert len(projects) > 4
    sanseong = projects['seongnam-sanseong-living-zone']
    assert sanseong['jibun'] == '74' and x['jibun'] == '1336'
    assert sanseong['plannedHouseholds'] == 1884
    assert sanseong['distanceMeters'] == 407
    assert projects['seongnam-dandae-living-zone']['distanceMeters'] == 713
    assert all(p['benefitClass'] == 'unverified' and p.get('walkingMeters') is None for p in projects.values())
    assert not report['projects'] and 'center' not in report
    assert report['mapCenter']['coordinateBasis'] == 'address_geocode'
    assert report['score'] is None
    assert all(m['value'] is None for m in report['metrics'])
    rating = report['planRating']
    assert rating['subScores']['housing'] >= 3.4
    assert rating['subScores']['transport'] is None
    assert rating['score'] is None
    assert rating['transportCoverage']['status'] == 'no_verified_station_within_2km'
    assert set(rating['subScores']) == {'housing', 'transport'}
    assert 'competitiveness' not in rating['components']
    assert report['briefing']['verdict'] == 'pending'
    assert x['name'] in ' '.join(report['briefing']['advice'])
    assert report['briefing']['keyProjects']
    assert all(card['impact'] and card['timing'] and card['check']
               for card in report['briefing']['keyProjects'])
    assert not any(p.get('jibun') == x['jibun'] and p.get('legalDong') == x['legalDong'] for p in projects.values())


def test_points_require_exact_id_lot_provider_response_and_freshness():
    records = context.read(refs.PATH)['points']
    x = subject()
    assert refs.point_for(x, records, DAY, subject=True)
    for key,value in [('apartmentId','other'),('district','강남구'),('legalDong','신흥동'),('jibun','74')]:
        assert refs.point_for({**x,key:value},records,DAY,subject=True) is None
    assert refs.point_for(x,records,DAY+dt.timedelta(days=121),subject=True) is None
    for key,value in [('latitude',37.5),('provider','unknown'),('coordinateBasis','official_point')]:
        changed = copy.deepcopy(records)
        changed[0][key] = value
        assert refs.point_for(x,changed,DAY,subject=True) is None
    assert refs.point_for(x,records+[records[0]],DAY,subject=True) is None


def test_tampered_bundle_fails_closed_and_does_not_leak_to_other_complex(tmp_path, monkeypatch):
    path = tmp_path/'points.json'
    bundle = context.read(refs.PATH)
    bundle['points'][0]['latitude'] += .1
    path.write_text(json.dumps(bundle))
    monkeypatch.setattr(refs,'PATH',path)
    assert living.analyze(subject(),day=DAY)['status'] == 'error'


def test_fact_only_source_is_limited_to_reviewed_metadata(monkeypatch):
    source = copy.deepcopy(sources.REGISTRY['seongnam-living-20260831'])
    assert sources.allowed('seongnam-living-20260831', day=DAY)
    source['scope'] = 'images_and_full_article'
    monkeypatch.setitem(sources.REGISTRY,'seongnam-living-20260831',source)
    assert not sources.allowed('seongnam-living-20260831', day=DAY)
