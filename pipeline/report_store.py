"""기기 소유자와 공유 링크로 접근하는 매물 검증 리포트 저장소."""

import datetime
import hashlib
import json
import re
import secrets
from pathlib import Path

import config


STORE_DIR = config.CACHE_DIR / "listing_reports"
REPORT_ID_PATTERN = re.compile(r"^[a-f0-9-]{16,64}$")


def _hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _report_path(report_id, store_dir=None):
    if not REPORT_ID_PATTERN.fullmatch(str(report_id or "")):
        raise ValueError("리포트 주소를 확인해 주세요.")
    return Path(store_dir or STORE_DIR) / f"{report_id}.json"


def _read(report_id, store_dir=None):
    path = _report_path(report_id, store_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def save(report, owner_token, store_dir=None):
    """서버가 만든 리포트를 저장하고 최초 1회 공유 토큰을 반환한다."""
    if not isinstance(report, dict):
        raise ValueError("저장할 리포트를 확인해 주세요.")
    owner_token = str(owner_token or "").strip()
    if len(owner_token) < 16:
        raise ValueError("리포트 소유 기기를 확인해 주세요.")
    report_id = str(report.get("id") or "").strip()
    path = _report_path(report_id, store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read(report_id, store_dir)
    share_token = secrets.token_urlsafe(24)
    saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    wrapper = {
        "schemaVersion": 1,
        "report": report,
        "ownerTokenHash": _hash(owner_token),
        "shareTokenHash": _hash(share_token),
        "createdAt": (
            existing.get("createdAt")
            if isinstance(existing, dict) and existing.get("createdAt")
            else saved_at
        ),
        "updatedAt": saved_at,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(wrapper, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return {
        "reportId": report_id,
        "shareToken": share_token,
        "savedAt": saved_at,
    }


def get(report_id, owner_token="", share_token="", store_dir=None):
    """소유 기기 또는 공유 토큰이 일치할 때만 저장 리포트를 반환한다."""
    wrapper = _read(report_id, store_dir)
    if not wrapper:
        return None
    owner_allowed = bool(owner_token) and secrets.compare_digest(
        _hash(owner_token),
        str(wrapper.get("ownerTokenHash") or ""),
    )
    share_allowed = bool(share_token) and secrets.compare_digest(
        _hash(share_token),
        str(wrapper.get("shareTokenHash") or ""),
    )
    if not (owner_allowed or share_allowed):
        raise PermissionError("이 리포트를 열 권한이 없어요.")
    report = wrapper.get("report")
    return report if isinstance(report, dict) else None


def create_share(report_id, owner_token, store_dir=None):
    """소유 기기가 다시 공유할 수 있도록 공유 토큰을 새로 발급한다."""
    wrapper = _read(report_id, store_dir)
    if not wrapper:
        return None
    if not owner_token or not secrets.compare_digest(
        _hash(owner_token),
        str(wrapper.get("ownerTokenHash") or ""),
    ):
        raise PermissionError("이 리포트를 공유할 권한이 없어요.")
    share_token = secrets.token_urlsafe(24)
    wrapper["shareTokenHash"] = _hash(share_token)
    wrapper["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = _report_path(report_id, store_dir)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(wrapper, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return {
        "reportId": report_id,
        "shareToken": share_token,
        "savedAt": wrapper["updatedAt"],
    }


def list_owned(owner_token, store_dir=None):
    """현재 기기에서 만든 리포트의 최소 요약 목록을 반환한다."""
    owner_token = str(owner_token or "").strip()
    if len(owner_token) < 16:
        return []
    rows = []
    directory = Path(store_dir or STORE_DIR)
    if not directory.exists():
        return rows
    expected_hash = _hash(owner_token)
    for path in directory.glob("*.json"):
        wrapper = _read(path.stem, directory)
        if not wrapper or not secrets.compare_digest(
            expected_hash,
            str(wrapper.get("ownerTokenHash") or ""),
        ):
            continue
        report = wrapper.get("report") or {}
        rows.append({
            "id": report.get("id"),
            "name": (report.get("apartment") or {}).get("name"),
            "region": (report.get("apartment") or {}).get("region"),
            "askingPriceEok": (report.get("pricing") or {}).get("askingPriceEok"),
            "verdict": (report.get("verdict") or {}).get("label"),
            "asOf": report.get("asOf"),
            "updatedAt": wrapper.get("updatedAt"),
        })
    rows.sort(key=lambda row: str(row.get("updatedAt") or ""), reverse=True)
    return rows
