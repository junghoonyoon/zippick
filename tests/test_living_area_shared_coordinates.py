"""Shared coordinates must retain physical identity and source freshness."""
import copy
import datetime as dt

import pytest

import kakao_station_distances as stations
import living_area as living
import living_area_metro as metro
import living_area_sources as sources
import shared_data


DAY = dt.date(2026, 11, 2)
IDENTITY = {'apartmentId': '41131120411567', 'name': '산성역 포레스티아',
            'province': '경기도', 'district': '성남수정구', 'legalDong': '신흥동', 'jibun': '6951'}
RECORD = {'status': 'ok', 'source': 'kakao-local-v2', 'apartmentName': '산성역 포레스티아',
          'address': '경기도 성남수정구 신흥동 6951', 'matchedAddress': '경기 성남시 수정구 수정로 319',
          'latitude': 37.4530754180382, 'longitude': 127.146997243895,
          'fetchedAt': '2026-09-29T04:49:07.619117+00:00'}


@pytest.fixture
def shared_location(monkeypatch):
    record = copy.deepcopy(RECORD)
    monkeypatch.setattr(stations, 'cached_record', lambda _: record)
    monkeypatch.setattr(metro, 'audited_center', lambda *args: None)
    monkeypatch.setattr(shared_data, 'read_only', lambda: True)

    def unexpected_lookup(*args):
        raise AssertionError('Replica must not collect apartment coordinates')

    monkeypatch.setattr(metro, '_center', unexpected_lookup)
    return record


def test_replica_reuses_shared_address_coordinates_for_real_report(tmp_path, shared_location):
    point = metro.center_for(IDENTITY, DAY)
    assert point['latitude'] == RECORD['latitude']
    assert point['coordinateBasis'] == 'address_geocode'
    assert point['checkedAt'] == '2026-09-29'
    report = living.analyze(IDENTITY, path=tmp_path / 'empty.db', day=DAY)
    assert report['metroCoverage']['locationStatus'] != 'unresolved'
    assert report['planRating']['subScores']['housing'] is not None
    assert report['planRating']['subScores']['transport'] is not None


@pytest.mark.parametrize('change', [
    {'status': 'error'}, {'source': 'other'}, {'apartmentName': '다른 단지'},
    {'address': '경기도 성남수정구 신흥동 6952'},
    {'matchedAddress': '서울 성남시 수정구 수정로 319'},
    {'matchedAddress': '경기 성남시 중원구 수정로 319'},
    {'matchedAddress': '경기 남양주시 수정구 수정로 319'},
    {'matchedAddress': ''}, {'coordinateMatchType': 'apartment_keyword'},
    {'coordinateMatchType': 'entity'}, {'fetchedAt': '2026-11-03T00:00:00+00:00'},
    {'fetchedAt': '2026-01-01T00:00:00+00:00'}, {'fetchedAt': 'invalid'},
    {'latitude': None}, {'longitude': float('nan')}, {'latitude': 0},
])
def test_unverified_shared_coordinate_is_withheld_without_local_lookup(shared_location, change):
    shared_location.update(change)
    assert metro.center_for(IDENTITY, DAY) is None


def test_missing_shared_record_does_not_collect_on_replica(monkeypatch, shared_location):
    monkeypatch.setattr(stations, 'cached_record', lambda _: None)
    assert metro.center_for(IDENTITY, DAY) is None


def test_primary_can_collect_missing_address(monkeypatch, shared_location):
    monkeypatch.setattr(stations, 'cached_record', lambda _: None)
    monkeypatch.setattr(shared_data, 'read_only', lambda: False)
    point = {'latitude': 37.45, 'longitude': 127.14}
    monkeypatch.setattr(metro, '_center', lambda *args: point)
    assert metro.center_for(IDENTITY, DAY) == point


def test_audited_coordinates_keep_priority(monkeypatch, shared_location):
    point = {'latitude': 37.45, 'longitude': 127.14}
    monkeypatch.setattr(metro, 'audited_center', lambda *args: point)
    shared_location['latitude'] = None
    assert metro.center_for(IDENTITY, DAY) == point


def test_station_not_found_still_has_usable_address_coordinates(shared_location):
    shared_location.update(status='station_not_found', coordinateMatchType='address_cache')
    assert metro.center_for(IDENTITY, DAY) is not None


def test_living_area_revision_changes_when_shared_coordinates_change(monkeypatch):
    monkeypatch.setattr(stations, 'cache_revision', lambda: 'first')
    before = sources.revision()
    monkeypatch.setattr(stations, 'cache_revision', lambda: 'second')
    assert sources.revision() != before
