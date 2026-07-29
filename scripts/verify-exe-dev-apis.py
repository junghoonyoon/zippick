#!/usr/bin/env python3
"""Verify the deployed ZipPick APIs after exe.dev deployment."""

import json
import sys
import time
from urllib import parse, request
from urllib.error import HTTPError, URLError


BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "https://maesuhalkkayo.exe.xyz").rstrip("/")


def _open(path, *, method="GET", payload=None, timeout=45):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return body.decode("utf-8", "replace")
    return json.loads(body.decode("utf-8"))


def _query(path, params):
    return path + "?" + parse.urlencode(params)


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _retry(label, fn, attempts=3):
    last_error = None
    for index in range(attempts):
        try:
            return fn()
        except (AssertionError, HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            if index < attempts - 1:
                time.sleep(2 + index * 2)
    raise AssertionError(f"{label} 확인 실패: {last_error}") from last_error


def verify():
    home = _retry("홈", lambda: _open("/"))
    _assert("real-estate-search" in home or "집픽" in home, "홈 HTML이 예상과 달라요.")

    status = _retry("상태", lambda: _open("/api/status"))
    _assert(status.get("ready") is True, "/api/status ready 값이 false예요.")
    _assert(status.get("molitConfigured") is True, "국토부 API 설정이 꺼져 있어요.")
    _assert(status.get("molitAvailable") is True, "국토부 API가 사용 가능 상태가 아니에요.")

    map_config = _retry("지도 설정", lambda: _open("/api/map-config"))
    _assert(map_config.get("configured") is True, "지도 API 설정이 꺼져 있어요.")

    analytics = _retry("행동데이터 설정", lambda: _open("/api/analytics-config"))
    _assert(analytics.get("enabled") is True, "PostHog 행동데이터가 꺼져 있어요.")

    leader_regions = _retry("지역별 대장 지역", lambda: _open("/api/apartment-leader-regions"))
    _assert(len(leader_regions.get("regions") or []) > 0, "지역별 대장 지역 목록이 비어 있어요.")
    _assert(len(leader_regions.get("areaBuckets") or []) > 0, "면적 목록이 비어 있어요.")

    common_profile = {
        "home_ownership": "no_home",
        "first_time": "true",
        "cash_eok": "5",
        "annual_income": "10000",
        "monthly_debt_payment": "0",
        "mortgage_rate": "4",
        "loan_term_years": "30",
        "region": "서울특별시 성동구",
        "purpose": "실거주",
    }
    purchase_power = _retry("구매력 계산", lambda: _open(_query("/api/purchase-power", common_profile)))
    _assert(purchase_power.get("budgetEok") or purchase_power.get("snapshot"), "구매력 계산 응답이 비어 있어요.")

    candidates = _retry(
        "예산 후보",
        lambda: _open(_query("/api/budget-candidates", {**common_profile, "limit": "3"})),
        attempts=2,
    )
    _assert(len(candidates.get("candidates") or []) > 0, "예산 후보가 비어 있어요.")

    apartment_suggest = _retry(
        "단지 추천",
        lambda: _open(_query("/api/apartment-suggest", {"q": "길음뉴타운4단지"})),
    )
    _assert(len(apartment_suggest.get("suggestions") or []) > 0, "단지 추천 결과가 비어 있어요.")

    areas = _retry(
        "단지 면적",
        lambda: _open(_query("/api/apartment-areas", {"name": "길음뉴타운4단지(e편한세상)", "region": "성북구"})),
    )
    _assert(len(areas.get("areas") or []) > 0, "단지 면적 결과가 비어 있어요.")

    location_score = _retry(
        "전세가율 점수표",
        lambda: _open(
            "/api/apartment-location-score",
            method="POST",
            payload={
                "name": "길음뉴타운4단지(e편한세상)",
                "region": "성북구",
                "areaLabel": "전용 59㎡",
                "currentEstimateMidPriceEok": 9.4,
                "transactionCount": 6,
                "signals": {"status": "insufficient"},
            },
        ),
    )
    candidate = location_score.get("candidate") or {}
    _assert(float(candidate.get("jeonseRatioPct") or 0) > 0, "전세가율이 비어 있어요.")
    _assert(float(candidate.get("latestJeonseDepositEok") or 0) > 0, "전세 또는 추정 전세가 비어 있어요.")
    parts = {
        part.get("key"): part
        for part in ((candidate.get("locationScore") or {}).get("parts") or [])
        if isinstance(part, dict)
    }
    jeonse = parts.get("jeonse") or {}
    _assert(jeonse.get("status") == "ok", "전세가율·입주물량·투자금 점수가 판단불가예요.")
    details = {
        detail.get("key"): detail
        for detail in (jeonse.get("details") or [])
        if isinstance(detail, dict)
    }
    _assert((details.get("jeonse_ratio") or {}).get("status") == "ok", "전세가율 세부 점수가 비어 있어요.")
    _assert((details.get("investment_gap") or {}).get("status") == "ok", "필요 투자금 세부 점수가 비어 있어요.")

    estimate = _retry(
        "R-ONE 시세",
        lambda: _open(_query("/api/rone-estimate", {
            "name": "길음뉴타운4단지(e편한세상)",
            "region": "성북구",
            "area": "59",
        })),
    )
    _assert(bool(estimate.get("estimate")), "R-ONE 시세 추정 응답이 비어 있어요.")


if __name__ == "__main__":
    verify()
    print(f"운영 API 확인 완료: {BASE_URL}")
