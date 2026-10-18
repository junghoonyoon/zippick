"""Reviewed occupancy corrections; never infer completion from a nearby apartment."""

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "data" / "redevelopment_occupancy_overrides.json"


@lru_cache(maxsize=4)
def _read_overrides(path, mtime):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []


def occupancy_evidence(zone):
    try:
        rows = _read_overrides(str(OVERRIDES_PATH), OVERRIDES_PATH.stat().st_mtime_ns)
    except OSError:
        return None
    for row in rows:
        if str(zone.get("id") or "") != row.get("zoneId"):
            continue
        if row.get("status") != "occupied" or not all(row.get(key) for key in (
            "kaptCode", "legalDong", "roadAddress", "useApprovalDate", "sourceUrl", "verifiedAt", "evidence"
        )):
            continue
        try:
            if not (date.fromisoformat(row["useApprovalDate"]) <= date.fromisoformat(row["verifiedAt"]) <= date.today()):
                continue
        except (TypeError, ValueError):
            continue
        # A reused ID or a same-name project in another district must stay visible.
        if all(str(zone.get(key) or "") == str(row.get(source) or "") for key, source in (
            ("id", "zoneId"), ("name", "zoneName"),
            ("districtCode", "districtCode"), ("projectType", "projectType"),
        )):
            return row
    return None


def completed_stage(stage):
    text = re.sub(r"\s+", "", str(stage or ""))
    # Recruitment, forecasts, partial approval and ongoing occupancy are not completion.
    if re.search(r"예정|계획|부분|일부|임시|미준공|미완료|미승인|신청|심사|모집|입주중|입주시작|입주개시|입주진행", text):
        return False
    return text in {"입주", "입주완료", "준공", "준공인가", "준공완료", "사용승인", "사용승인완료", "사업완료", "해제", "폐지"}
