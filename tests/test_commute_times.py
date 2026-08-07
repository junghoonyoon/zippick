"""업무지구 소요시간 추정이 실제와 얼마나 벌어지는지 고정해 둔다.

기준값은 카카오맵·네이버지도의 평일 출근시간대 지하철 승차시간(도보 제외)이다.
추정 방식이 바뀌어도 이 오차 범위를 넘으면 실패하게 만들어, 화면에 나가는
숫자가 조용히 나빠지는 것을 막는다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

import commute_times  # noqa: E402


# (출발역 표기, 업무지구, 실제 승차시간 분)
REFERENCE_RIDES = [
    ("개봉역 1호선", "여의도", 20),
    ("개봉역 1호선", "광화문", 24),
    ("신도림역 1호선", "여의도", 10),
    ("신도림역 1호선", "광화문", 20),
    ("잠실역 2호선", "강남", 13),
    ("판교역 신분당선", "강남", 14),
    ("사당역 2호선", "강남", 7),
    ("목동역 5호선", "광화문", 26),
    ("부천역 1호선", "여의도", 27),
    ("노원역 4호선", "강남", 45),
    ("상계역 4호선", "광화문", 40),
    ("수원역 1호선", "광화문", 60),
    ("서울숲역 수인분당선", "강남", 18),
    ("가산디지털단지역 7호선", "여의도", 20),
    ("일산역 경의중앙선", "광화문", 45),
]

TOLERANCE_MINUTES = 12


@pytest.fixture(scope="module", autouse=True)
def matrix_built():
    commute_times.reset_cache()
    if not os.path.exists(commute_times.MATRIX_PATH):
        commute_times.save_matrix()


@pytest.mark.parametrize("station,hub,expected", REFERENCE_RIDES)
def test_ride_minutes_close_to_reality(station, hub, expected):
    profile = commute_times.commute_profile(station)
    assert profile, f"{station} 소요시간 데이터가 없습니다"
    ride = profile["hubs"][hub]["rideMinutes"]
    assert abs(ride - expected) <= TOLERANCE_MINUTES, (
        f"{station}→{hub} 추정 {ride}분 / 실제 {expected}분"
    )


def test_mean_absolute_error_stays_small():
    """개별 오차보다 전체 편향이 더 중요하다. 평균 오차를 함께 묶어둔다."""
    errors = []
    for station, hub, expected in REFERENCE_RIDES:
        profile = commute_times.commute_profile(station)
        errors.append(abs(profile["hubs"][hub]["rideMinutes"] - expected))
    assert sum(errors) / len(errors) <= 7


def test_walk_time_is_added_to_ride_time():
    profile = commute_times.commute_profile("개봉역 1호선", 536)
    hub = profile["hubs"]["여의도"]
    assert profile["walkMinutes"] == 8
    assert hub["totalMinutes"] == hub["rideMinutes"] + 8


def test_line_classification_fixes_previous_bugs():
    # 마천지선이 1호선으로 잡히던 버그
    assert commute_times.line_for_code("P552") == "5호선"
    # 경부선 구간은 1호선으로 유지되어야 한다
    assert commute_times.line_for_code("P142") == "1호선"
    assert commute_times.line_for_code("D11") == "신분당선"


def test_station_name_only_fallback():
    """캐시의 노선 표기가 달라도(안산선→수인분당선) 찾을 수 있어야 한다."""
    assert commute_times.commute_profile("정왕역 수인분당선")
    assert commute_times.commute_profile("서울역 4호선")


def test_score_bands_are_monotonic():
    fast = commute_times.commute_profile("신도림역 1호선", 300)
    slow = commute_times.commute_profile("수원역 1호선", 300)
    fast_score, _ = commute_times.commute_access_score(fast)
    slow_score, _ = commute_times.commute_access_score(slow)
    assert fast_score > slow_score
