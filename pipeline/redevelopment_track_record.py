#!/usr/bin/env python3
"""재개발 이주가 시작된 뒤 옆 단지들이 실제로 어떻게 됐는지 세어서 보여준다.

"오를 거예요"라고 말하지 않는다. 대신 과거에 같은 일이 몇 번 있었는지 센다.
숫자는 오프라인 분석이 만들어 둔 파일에서 읽는다. 요청마다 계산하지 않는다.

읽는 파일: data/redevelopment_track_record.json
이 파일을 만들려면 구역별 이주 시작 시점이 먼저 필요하다. 아직 수집 전이라
지금은 항상 status='missing'을 돌려주고, 화면에서는 블록이 통째로 숨는다.
자세한 절차는 docs/redevelopment-price-impact-analysis.md에 있다.
"""

import json
from pathlib import Path

import redevelopment_analysis as ra


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "redevelopment_track_record.json"

# 사례가 이보다 적으면 화면에 보여주지 않는다.
# 적은 표본으로 만든 비율은 우연에 가깝다.
MIN_SAMPLE = 30

# 이 거리 안에 있는 구역만 '옆 단지'로 본다.
# 화면의 '이주를 앞두고 있어요' 알림과 같은 기준을 쓴다.
NEARBY_METERS = ra.MOVE_OUT_NEARBY_METERS

_CACHE = {"mtime": None, "payload": None}


def _load():
    try:
        mtime = DATA_PATH.stat().st_mtime
    except OSError:
        return None
    if _CACHE["mtime"] == mtime:
        return _CACHE["payload"]
    try:
        with DATA_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        payload = None
    _CACHE.update({"mtime": mtime, "payload": payload})
    return payload


def _missing(reason, message):
    return {"status": "missing", "reason": reason, "message": message}


def _nearby_move_out(row, entity):
    """이주가 임박했거나 시작된 구역이 가까이 있는지 본다."""
    projects, status = ra.nearby_projects(row, entity, radius_meters=NEARBY_METERS)
    if status != "ok":
        return []
    return [
        project
        for project in projects
        if project["stage"] in ra.IMMINENT_MOVE_OUT_STAGES
    ]


def summary(row, entity, years=3):
    """이 단지에 붙일 트랙레코드 한 줄을 만든다.

    데이터가 없거나 사례가 적으면 status를 missing으로 돌려준다.
    화면에서는 그럴 때 이 블록을 통째로 감춘다.
    """
    nearby = _nearby_move_out(row, entity)
    if not nearby:
        return _missing(
            "no_move_out_nearby",
            f"{NEARBY_METERS}m 안에 이주를 앞둔 재개발 구역이 없어요",
        )

    payload = _load()
    if not payload:
        return _missing(
            "track_record_missing",
            "이주 시점 자료를 아직 모으는 중이에요",
        )

    buckets = payload.get("buckets") or {}
    bucket = buckets.get(str(years))
    if not bucket:
        return _missing("years_missing", f"{years}년 기준 자료가 아직 없어요")

    total = bucket.get("total")
    outperformed = bucket.get("outperformed")
    if not isinstance(total, int) or not isinstance(outperformed, int):
        return _missing("malformed", "이주 시점 자료를 아직 모으는 중이에요")
    if total < MIN_SAMPLE:
        return _missing(
            "sample_too_small",
            f"비교할 사례가 {total}곳뿐이라 아직 보여드리지 않아요",
        )

    closest = min(nearby, key=lambda project: project["distanceMeters"])
    worst_drop = bucket.get("worstDropPercent")

    return {
        "status": "ok",
        "years": years,
        "total": total,
        "outperformed": outperformed,
        # 비율은 화면에 크게 쓰지 않는다. 확률로 오해하기 쉽다.
        "headline": f"{total}곳 중 {outperformed}곳이 동네 평균보다 더 올랐어요",
        "description": (
            f"근처에서 재개발 이주가 시작되고 {years}년이 지난 구축 아파트를 "
            "실거래로 세어봤어요"
        ),
        "worstDropPercent": worst_drop,
        "worstDropNote": (
            f"가장 나빴던 곳은 {worst_drop}% 떨어졌어요" if worst_drop else None
        ),
        "trigger": {
            "name": closest["name"],
            "stage": closest["stage"],
            "distanceMeters": closest["distanceMeters"],
        },
        "basis": payload.get("basis"),
        "calculatedAt": payload.get("calculatedAt"),
        # 인과를 주장하지 않는다. 같은 동네 평균과 비교한 결과일 뿐이다.
        "disclaimer": "같은 동네 평균과 비교한 결과예요. 앞으로 오른다는 뜻은 아니에요.",
    }
