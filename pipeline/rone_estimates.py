"""Client and short-lived cache for the deployed R-ONE price estimate API."""
import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config


API_BASE_URL = os.environ.get(
    "RONE_ESTIMATE_API_BASE_URL",
    "https://stockzip.exe.xyz/maesu",
).rstrip("/")
CACHE_DIR = config.CACHE_DIR / "rone_estimates"
CACHE_TTL_SECONDS = int(os.environ.get("RONE_ESTIMATE_CACHE_TTL_SECONDS", str(60 * 60 * 6)))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("RONE_ESTIMATE_TIMEOUT_SECONDS", "12"))


def _cache_path(apartment, region, area, months, include_details=False):
    material = json.dumps(
        {
            "apartment": apartment,
            "region": region,
            "area": area,
            "months": months,
            "includeDetails": bool(include_details),
            "api": API_BASE_URL,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return CACHE_DIR / f"{hashlib.sha256(material).hexdigest()}.json"


def _read_cache(path):
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(cached.get("savedAt") or 0) > CACHE_TTL_SECONDS:
        return None
    payload = cached.get("payload")
    return payload if isinstance(payload, dict) else None


def _write_cache(path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{time.monotonic_ns()}.tmp")
        temporary.write_text(
            json.dumps({"savedAt": time.time(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        # A cache write must never make the estimate unavailable.
        pass


def estimate(apartment, region, area="", months=12, include_details=False):
    """Return ``(payload, status)`` from the R-ONE service, using a 6-hour cache."""
    apartment = str(apartment or "").strip()
    region = str(region or "").strip()
    area = str(area or "").strip()
    try:
        months = max(1, min(int(months), 60))
    except (TypeError, ValueError):
        months = 12

    if len(apartment) < 2 or len(region) < 2:
        return {"error": "단지명과 지역을 확인해 주세요."}, 400

    path = _cache_path(apartment, region, area, months, include_details=include_details)
    cached = _read_cache(path)
    if cached:
        return {**cached, "cacheHit": True}, 200

    query = {"apt": apartment, "region": region, "months": months}
    if area:
        query["area"] = area
    if include_details:
        query["include_details"] = "true"
    request = Request(
        f"{API_BASE_URL}/estimate?{urlencode(query)}",
        headers={"Accept": "application/json", "User-Agent": "zippick-rone-client/1.0"},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = int(response.status)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            payload = {"error": "현재가 추정 자료를 찾지 못했어요."}
        return payload, int(exc.code)
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        return {"error": "현재가 추정 서비스에 잠시 연결할 수 없어요.", "detail": str(exc)}, 502

    if status == 200 and isinstance(payload, dict):
        _write_cache(path, payload)
    return payload, status
