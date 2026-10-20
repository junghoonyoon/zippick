import copy
import datetime as dt
import json
from pathlib import Path

import pytest
import import_rail_station_mapping as importer
import rail_station_mapping as registry
import living_area_plan_rating as rating

DAY = dt.date(2026, 10, 19)
LINE = dict(id='test', name='시험선', stageCode='construction', stage='공사 중',
            sourceDate='2026-01-01', sourceUrl='https://example.gov/plan',
            stationsSourceUrl='https://example.gov/stations', stationListComplete=True)
STATION = dict(stationId='test:1', name='시험', sido='경기도', sigungu='성남시',
               membershipVerified=True, serviceStatus='planned')
PLACE = dict(id='1', place_name='시험역(예정)', address_name='경기 성남시 수정구 고등동',
             category_name='교통,수송 > 지하철,전철', x='127.10', y='37.42',
             place_url='https://place.map.kakao.com/1')


def resolve(station, documents):
    return importer.resolve(LINE, station, lambda *_: {'documents': documents}, DAY.isoformat())


def test_future_station_does_not_need_operating_station_category_code():
    assert importer.place_matches(PLACE, STATION)
    for changed in [dict(address_name='경기 하남시 망월동'), dict(category_name='음식점'),
                    dict(place_name='시험역주차장'), dict(place_name='시험역')]:
        assert not importer.place_matches(PLACE | changed, STATION)
    assert resolve(STATION, [PLACE])['scoringEligible'] is True


def test_complex_coverage_checks_all_lines_without_nearby_route_shapes(monkeypatch):
    center = {'latitude':37.42, 'longitude':127.1}
    stations = [dict(id='planned', name='새 노선 예정역', lineId='new-line',
                     locationStatus='located', serviceStatus='planned', scoringEligible=True, **center),
                dict(id='operating', name='기존역', lineId='old-line',
                     locationStatus='located', serviceStatus='operating', scoringEligible=False, **center),
                dict(id='reference', name='역 주변 시설', lineId='unverified-line',
                     locationStatus='located', serviceStatus='planned', scoringEligible=False, **center)]
    lines = [dict(id='new-line', mappingComplete=True), dict(id='unknown-line', mappingComplete=False)]
    monkeypatch.setattr(registry, 'load', lambda:dict(integrityValid=True,checkedAt=DAY.isoformat(),
                        lines=lines,stations=stations,coverage={}))
    result = registry.complex_coverage(center, DAY)
    assert [s['id'] for s in result['nearbyPlannedStations']] == ['planned']
    assert [s['id'] for s in result['nearbyOperatingStations']] == ['operating']
    assert [s['id'] for s in result['nearbyReferenceStations']] == ['reference']
    assert result['scopeComplete'] is False
    assert result['incompleteLines'][0]['id'] == 'unknown-line'


def test_miseong_retains_operating_gtx_a_and_incomplete_other_plans():
    coverage = registry.complex_coverage({'latitude':37.6148205101596,'longitude':126.928054602465}, DAY)
    yeonsinnae = next(s for s in coverage['nearbyOperatingStations'] if s['id']=='gtx-a:004')
    assert yeonsinnae['distanceMeters'] == 798
    assert yeonsinnae['name'] == '연신내역 · GTX-A'
    assert coverage['lineCount'] == len(registry.load()['lines'])
    assert not coverage['scopeComplete']
    assert any(line['id']=='goyang-eunpyeong' for line in coverage['incompleteLines'])


def test_far_apart_same_name_places_are_ambiguous():
    row = resolve(STATION, [PLACE, PLACE | dict(id='2', y='37.44')])
    assert row['locationStatus'] == 'ambiguous'
    assert 'latitude' not in row
    assert row['scoringEligible'] is False


def test_official_parcel_must_match_exactly():
    station = STATION | dict(address='경기도 성남시 수정구 고등동 1')
    doc = dict(address={'address_name':'경기 성남시 수정구 고등동 2'}, x='127.1', y='37.42')
    assert resolve(station, [doc])['locationStatus'] == 'unresolved'
    doc['address']['address_name'] = '경기 성남시 수정구 고등동 1'
    assert resolve(station, [doc])['coordinateBasis'] == 'official_station_parcel_geocode'
    assert importer.exact_address({'address':{'address_name':'경기 화성시 동탄구 오산동 123'}}, '경기도 화성시 오산동 123')
    assert not importer.exact_address({'address':{'address_name':'경기 성남시 수정구 고등동 산1'}}, station['address'])


def test_opened_unverified_and_landmark_points_are_never_scored():
    for changed in [dict(serviceStatus='operating'), dict(membershipVerified=False), dict(referenceOnly=True)]:
        assert resolve(STATION | changed, [PLACE])['scoringEligible'] is False
    station = STATION | dict(referenceOnly=True, referenceQuery='시험학교')
    landmark = PLACE | dict(place_name='시험학교')
    result = importer.build({'scope':'test','lines':[LINE | {'stations':[station]}]},
                            lambda *_: {'documents':[landmark]}, DAY.isoformat())
    assert result['coverage']['landmarkReferences'] == 1
    assert result['coverage']['stationLocationCount'] == 0
    assert result['lines'][0]['mappingComplete'] is False


def test_station_stage_overrides_line_stage():
    station = importer.resolve(LINE | dict(id='myeonmok'),
        STATION | dict(stageCode='planning', stageLabel='기본계획안 의견 수렴'),
        lambda *_: {'documents': [PLACE]}, DAY.isoformat())
    station['distanceMeters'] = 100
    project = dict(id='metro-rail:myeonmok', projectType='transport', stage='construction')
    result = rating.calculate([project], {'stations':[station]}, DAY)
    assert result['components']['transport']['inputs'][0]['stage'] == 'planning'
    station['serviceStatus'] = 'operating'
    assert rating.calculate([project], {'stations':[station]}, DAY)['subScores']['transport'] is None


def test_stale_or_changed_registry_fails_closed_and_history_uses_fallback(monkeypatch):
    bundle = registry.load()
    assert registry.current(bundle, DAY)
    assert not registry.current(bundle, DAY + dt.timedelta(days=121))
    monkeypatch.setattr(registry, 'load', lambda: bundle | {'integrityValid':False})
    assert registry.stations(DAY, ['fallback']) == []
    assert registry.stations(DAY - dt.timedelta(days=1), ['fallback']) == ['fallback']


def test_shipped_registry_integrity_and_major_station_lists():
    b = registry.load()
    assert b['integrityValid']
    lines = {l['id']:l for l in b['lines']}
    assert len(lines) == len(b['lines'])
    ids = [s['id'] for s in b['stations']]
    assert len(ids) == len(set(ids))
    routes = [r for l in b['lines'] for r in l.get('routeIds',[])]
    inventories = [r for l in b['lines'] for r in l.get('inventoryKeys',[])]
    assert len(routes) == len(set(routes)) == 24
    assert len(inventories) == len(set(inventories)) == 29
    for line, count in {'gtx-a':11, 'gtx-b':14, 'gtx-c':14, 'dongbuk':16, 'wirye':12,
                        'indeogwon-dongtan':18, 'okjeong-pocheon':4}.items():
        assert lines[line]['listedStations'] == count
    assert not any(s['lineId']=='gtx-b' and s['stationName'] in ('구리','갈매') for s in b['stations'])
    for s in b['stations']:
        if s.get('locationStatus') == 'located':
            assert 33 <= s['latitude'] <= 39 and 124 <= s['longitude'] <= 132
            assert s['coordinateSourceUrl'].startswith(('https://','http://'))
            assert s['stationEntranceVerified'] is False
        if s.get('serviceStatus')=='operating' or s.get('referenceOnly'):
            assert s['scoringEligible'] is False
    assert b['coverage']['scopeComplete'] is False


def test_pangyo_gtx_a_has_known_stations_but_no_new_station_within_2km():
    b = registry.load()
    line = next(l for l in b['lines'] if l['id']=='gtx-a')
    c = registry.route_coverage(line['routeIds'][0],
        {'latitude':37.4273553189971,'longitude':127.101274022377}, DAY)
    assert c['mappingComplete']
    assert c['nearestKnownStation']['serviceStatus']=='operating'
    assert c['nearestPlannedStation']['distanceMeters'] > 2000
    assert c['nearestPlannedStation']['name'].startswith('삼성')
