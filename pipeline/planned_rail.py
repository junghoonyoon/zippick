"""공식 발표된 수도권 예정 역을 시·구 단위로 보수적으로 연결한다."""

import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "planned_rail_metro.json"
_DATA = None
_REVISION = None


def _load():
    global _DATA, _REVISION
    revision=DATA_PATH.stat().st_mtime_ns
    if _DATA is None or _REVISION != revision:
        _DATA = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        _REVISION=revision
    return _DATA


def planned_rail_for_candidate(row):
    """주소로 확인한 계획역 또는 별도 검수된 지역 참고 사업만 반환한다."""
    if not isinstance(row, dict):
        return []
    addresses = (row.get("mapAddress"), row.get("address"), row.get("displayRegion"))
    sido = str(row.get("province") or "").strip()
    city = str(row.get("city") or "").strip()
    district = str(row.get("district") or "").strip()
    address_district = ""
    for address in addresses:
        tokens = str(address or "").strip().split()
        if tokens and tokens[0] in {"서울특별시", "경기도", "인천광역시"}:
            sido = tokens[0]
            if len(tokens) >= 2:
                if sido == "경기도":
                    city = tokens[1]
                    if len(tokens) >= 3 and tokens[2].endswith("구"):
                        address_district = city.removesuffix("시") + tokens[2]
                else:
                    district = tokens[1]
            break
    if sido not in {"서울특별시", "경기도", "인천광역시"}:
        return []
    if sido == "경기도" and not city and district:
        # Some report entry points only carry the city+district code.
        # Resolve it through reviewed scopes, and reject ambiguous names.
        cities = {parts[1] for line in _load()["lines"]
                  for scope in line.get("regionalScopes", [])
                  if len(parts := scope.split(":")) == 3 and parts[0] == sido
                  and (parts[2] == district or parts[2].endswith(district))}
        if len(cities) == 1:
            city = cities.pop()
    sigungu = city if sido == "경기도" else district
    if not sigungu or not sigungu.endswith(("시", "구")):
        return []
    full_district = address_district or district
    if sido == "경기도" and full_district and not full_district.startswith(city.removesuffix("시")):
        full_district = city.removesuffix("시") + full_district
    regional_scope = f"{sido}:{sigungu}:{full_district}" if sido == "경기도" else f"{sido}:{sigungu}"
    result = []
    for line in _load()["lines"]:
        stations = [station["name"] for station in line["stations"]
                    if station["sido"] == sido and station["sigungu"] == sigungu]
        regional_reference = regional_scope in line.get("regionalScopes", [])
        if stations or regional_reference:
            result.append({key: line[key] for key in (
                "id", "name", "stage", "targetOpening", "source", "sourceUrl", "stationsSourceUrl"
            )} | {"stations": stations, "province": sido, "region": sigungu,
                 "stageCode": line.get("stageCode"),
                 "relation": "같은 시·구의 계획역" if stations else "공식 발표를 검수한 지역 참고 사업 · 역 위치 미확인",
                 "regionalReference": regional_reference and not stations,
                 "planningNote": line.get("planningNote"),
                 "sourceDate": line.get("sourceDate"),
                 "verifiedAt": line.get("verifiedAt") or _load().get("checkedAt")})
    return result
