"""Reviewed occupancy corrections; never infer completion from a nearby apartment."""

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "data" / "redevelopment_occupancy_overrides.json"


def revision():
    """Invalidate derived map caches when evidence changes or its date becomes valid."""
    try:
        modified = OVERRIDES_PATH.stat().st_mtime_ns
    except OSError:
        modified = None
    return modified, date.today().isoformat()


@lru_cache(maxsize=4)
def _read_overrides(path, mtime):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []


def reviewed_entries():
    try:
        rows = _read_overrides(str(OVERRIDES_PATH), OVERRIDES_PATH.stat().st_mtime_ns)
    except OSError:
        return []
    valid = []
    for row in rows:
        if row.get("status") not in {"occupied", "completed"} or not all(row.get(key) for key in (
            "kaptCode", "legalDong", "useApprovalDate", "sourceUrl", "verifiedAt", "evidence"
        )) or not (row.get("roadAddress") or row.get("legalAddress")):
            continue
        try:
            if not (date.fromisoformat(row["useApprovalDate"]) <= date.fromisoformat(row["verifiedAt"]) <= date.today()):
                continue
        except (TypeError, ValueError):
            continue
        valid.append(row)
    return valid


def occupancy_evidence(zone):
    for row in reviewed_entries():
        # A reused ID or a same-name project in another district must stay visible.
        if all(str(zone.get(key) or "") == str(row.get(source) or "") for key, source in (
            ("id", "zoneId"), ("name", "zoneName"),
            ("districtCode", "districtCode"), ("projectType", "projectType"),
        )):
            return row
    return None


def project_evidence(project):
    """Apply the same reviewed retirement to catalogue/list/score identities."""
    for row in reviewed_entries():
        for identity in row.get("projectIdentities", []):
            if all(str(project.get(k) or "") == str(identity.get(k) or "")
                   for k in ("id", "name", "region", "legalDong", "jibun")):
                return row
    return None


def completed_stage(stage):
    text = re.sub(r"\s+", "", str(stage or ""))
    # Actual move-in starts retire a zone; no need to wait for every household.
    if re.search(r"예정|계획|부분|일부|임시|미준공|미완료|미승인|신청|심사|모집", text):
        return False
    return text in {"입주", "입주완료", "입주중", "입주진행중", "입주개시", "입주시작", "준공", "준공인가", "준공완료", "사용승인", "사용승인완료", "사업완료", "해제", "폐지"}
