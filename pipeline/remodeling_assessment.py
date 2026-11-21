"""Preliminary remodeling assessment from identity-matched current buildings."""

import calendar
import datetime as dt
from functools import lru_cache
import gzip
import json
import math

import config

VERSION = "remodeling-site-v1"
PATH = config.ROOT / "data" / "remodeling_site_evidence.json.gz"
ADDRESS_FIELDS = ("province", "district", "legalDong", "jibun")
LAW_URL = "https://law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1030956351"
FLOOR_RULE_URL = "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0013&lsiSeq=289499&urlMode=lsScJoRltInfoR"
VERIFIED_15_YEAR_REGIONS = {"서울특별시", "인천광역시", "경기도"}


def identity_key(entity):
    address = tuple(str(entity.get(field) or "").strip() for field in ADDRESS_FIELDS)
    apt_id = str(entity.get("apartmentId") or "").strip()
    name = str(entity.get("name") or "").strip()
    if entity.get("aggregate") or not all(address[:3]):
        return None
    if apt_id:
        return "\x1f".join(("id", apt_id, *address))
    if name and address[-1]:
        return "\x1f".join(("address", name, *address))
    return None


def revision():
    try:
        stamp = PATH.stat()
        return VERSION, stamp.st_mtime_ns, stamp.st_size
    except OSError:
        return VERSION, None, None


@lru_cache(maxsize=1)
def _read(token):
    if token[1] is None:
        return {}
    try:
        with gzip.open(PATH, "rt", encoding="utf-8") as stream:
            snapshot = json.load(stream)
    except (OSError, ValueError):
        return {}
    if not isinstance(snapshot, dict) or snapshot.get("version") != VERSION:
        return {}
    return snapshot.get("records") or {}


def _approval_bounds(value):
    value = str(value or "").strip()
    if len(value) == 8 and value.isdecimal():
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    try:
        if len(value) == 4 and value.isdecimal():
            year = int(value)
            return dt.date(year, 1, 1), dt.date(year, 12, 31)
        if len(value) == 7:
            first = dt.date.fromisoformat(f"{value}-01")
            return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
        date = dt.date.fromisoformat(value)
        return date, date
    except ValueError:
        return None


def coverage_value(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 < value <= 100)


def evaluate(entity, profile, *, day=None):
    key = identity_key(entity)
    if not key:
        return None
    evidence = _read(revision()).get(key, {})
    if not entity.get("apartmentId") and not evidence.get("floor"):
        return None
    registered = profile if profile.get("scope") == "whole_registered_site" else {}
    coverage = evidence.get("coverage")
    official = registered.get("buildingCoverageRatio")
    if coverage_value(official):
        coverage = {"value": official, "estimated": False, "method": "건축물대장",
                    "sourceUrls": [registered["sourceUrl"]] if registered.get("sourceUrl") else [],
                    "checkedAt": registered.get("fetchedAt")}
    floor = evidence.get("floor")
    day = day or dt.date.today()
    bounds = _approval_bounds(evidence.get("approvedAt") or entity.get("approvedAt") or registered.get("approvedAt"))
    result = {"version": VERSION, "status": "missing", "stars": None, "highestResidentialFloors": floor,
              "buildingCoverage": coverage, "legalSourceUrl": FLOOR_RULE_URL, "ageSourceUrl": LAW_URL,
              "title": "리모델링은 증축 여건을 평가할 자료가 부족해요."}
    if not entity.get("apartmentId"):
        result["addressIdentity"] = {field: entity[field] for field in ("name", *ADDRESS_FIELDS)}
    if not bounds or bounds[0] > day:
        return {**result, "reason": "사용승인일을 확인해야 증축형 리모델링 연한을 판단할 수 있어요."}

    ages = [day.year - date.year - ((day.month, day.day) < (date.month, date.day)) for date in bounds[::-1]]
    if ages[1] < 15:
        return {**result, "status": "under_age", "title": "증축형 리모델링을 검토할 연한 전이에요.",
                "reason": "사용승인 후 15년이 아직 지나지 않았어요."}
    threshold = 15 if entity.get("province") in VERIFIED_15_YEAR_REGIONS else 20
    if ages[0] < threshold:
        return {**result, "reason": "사용승인일과 이 지역에 적용하는 증축형 리모델링 연한을 더 확인해야 해요."}

    missing = []
    if not floor:
        missing.append("주거동 최고 층수")
    if not coverage:
        missing.append("단지 전체 건폐율")
    if missing:
        return {**result, "reason": " 및 ".join(missing) + " 자료를 확인해야 해요."}

    floors = floor["value"]
    limit = 2 if floors < 15 else 3
    share = 100 * limit / floors
    ratio = coverage["value"]
    footprint_vote = 1 if ratio <= 19 else -1 if ratio >= 49 else 0
    height_vote = 1 if share >= 20 else -1 if share <= 10 else 0
    stars = 3 + footprint_vote + height_vote
    grade = "좋은 편이에요" if stars >= 4 else "불리한 편이에요" if stars <= 2 else "보통이에요"
    return {**result, "status": "rated", "stars": stars, "maxAddedFloors": limit,
            "title": f"리모델링은 증축 여건이 {grade}.",
            "reason": f"가장 높은 주거동은 {floors}층으로, 법령상 최대 {limit}층을 더 올리는 방안을 검토할 수 있어요. 실제 증축 가능 여부와 규모는 안전진단과 설계로 확인해야 해요."}
