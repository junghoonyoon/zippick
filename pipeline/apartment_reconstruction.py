"""Shared building-register facts and evidence-gated reconstruction conditions.

Ratios describe the whole registered site, never one apartment's floor plan.
No network requests, scores, probabilities, or assumed zoning ceilings here.
"""
import datetime as dt
import json
import math
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import apartment_identity
import apartment_development
import config
import reconstruction_project_plans
import regional_reconstruction_plans
import shared_data

VERSION = "reconstruction-conditions-v1"
FEASIBILITY_VERSION = "reconstruction-feasibility-v1"
FACT_FILE = "building_register_records.json"
PLANNING_FILE = "reconstruction_planning_records.json"
CONTEXT_PATH = config.ROOT / "data/apartment_reconstruction_context.json"
ORDINANCES_PATH = config.ROOT / "data/reconstruction_ordinances.json"
ORDINANCE_CHECK_FILE = "reconstruction_ordinance_verification.json"
MAX_SOURCE_AGE_DAYS = 180
# Display convention only, not a legal or financial threshold: a difference
# within 10% of a verified ceiling is described as limited, without a score.
LIMITED_HEADROOM_RATIO = 0.10

_SOURCE_CONFIRMATIONS = {}
_CONFIRMATION_LOCK = threading.RLock()


def _confirmation_key(entity):
    return tuple(str(entity.get(k) or '') for k in ('apartmentId', 'province', 'district', 'legalDong', 'jibun'))


def _confirmation_revision():
    return json.dumps([shared_data.data_revision(), revision()], sort_keys=True)


def forget_primary_confirmation(entity):
    with _CONFIRMATION_LOCK:
        _SOURCE_CONFIRMATIONS.pop(_confirmation_key(entity), None)


def _current_confirmation(entity):
    with _CONFIRMATION_LOCK:
        proof = _SOURCE_CONFIRMATIONS.get(_confirmation_key(entity))
        if proof and proof['expires'] > time.monotonic() and proof['revision'] == _confirmation_revision():
            return proof
        _SOURCE_CONFIRMATIONS.pop(_confirmation_key(entity), None)
    return None


def confirm_primary_snapshot(entity, remote):
    """Confirm only an identical local snapshot against the verified primary API.

    Do not import remote values or clear the global SSH failure. All consumers
    still calculate from cache_path(); only that complex's freshness is proven.
    """
    forget_primary_confirmation(entity)
    if not shared_data.read_only() or remote.get('status') in ('loading', 'stale', 'connection_error', 'invalid_source', 'identity_unverified', 'access_denied'):
        return False
    token = _confirmation_revision()
    local = analyze(entity, _source_confirmed=True)
    comparable = lambda model: {k: v for k, v in model.items() if k not in ('sourceRevision', 'sourceVerification')}
    if comparable(local) != comparable(remote) or token != _confirmation_revision():
        return False
    with _CONFIRMATION_LOCK:
        if len(_SOURCE_CONFIRMATIONS) >= 1000:
            _SOURCE_CONFIRMATIONS.clear()
        _SOURCE_CONFIRMATIONS[_confirmation_key(entity)] = {
            'revision': token, 'expires': time.monotonic() + shared_data.REFRESH_SECONDS,
            'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    return True


def number(value):
    try:
        result = float(str(value).replace(",", ""))
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def parcel(entity):
    if entity.get("aggregate") or entity.get("sectionIdentity"):
        return None
    code = str(entity.get("cortarNo") or "")
    lot = apartment_identity.entity_parcel(entity)
    match = re.fullmatch(r"(산?)(\d{1,4})(?:-(\d{1,4}))?", lot)
    if not re.fullmatch(r"\d{10}", code) or not match:
        return None
    return {"sigunguCd": code[:5], "bjdongCd": code[5:],
            "platGbCd": "1" if match[1] else "0", "bun": match[2].zfill(4),
            "ji": (match[3] or "0").zfill(4)}


def parcel_key(entity):
    p = parcel(entity)
    return "".join(p[k] for k in ("sigunguCd", "bjdongCd", "platGbCd", "bun", "ji")) if p else ""


def parcel_pnu(entity):
    """PNU uses 1/2 for normal/mountain; building HUB keys use 0/1."""
    p = parcel(entity)
    return (p["sigunguCd"] + p["bjdongCd"] + str(int(p["platGbCd"]) + 1)
            + p["bun"] + p["ji"]) if p else ""


def _stamp(path):
    try:
        s = path.stat()
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return None


def revision():
    return [VERSION, FEASIBILITY_VERSION, _stamp(shared_data.cache_path(FACT_FILE)),
            _stamp(shared_data.cache_path(PLANNING_FILE)), _stamp(CONTEXT_PATH),
            _stamp(ORDINANCES_PATH), _stamp(shared_data.cache_path(reconstruction_project_plans.FILE)),
            _stamp(shared_data.cache_path(ORDINANCE_CHECK_FILE)), regional_reconstruction_plans.stamp()]


@lru_cache(maxsize=4)
def _read(path, stamp):
    if stamp is None:
        return {"records": {}}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("records"), dict) or any(not isinstance(v, dict) for v in value["records"].values()):
        raise ValueError("invalid building register store")
    return value


def _date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _official(url):
    p = urlsplit(str(url or ""))
    host = p.hostname or ""
    # 노원구청은 .kr 도메인을 사용한다. 임의의 .kr은 허용하지 않는다.
    return p.scheme == "https" and (host.endswith(".go.kr") or host in {"nowon.kr", "www.nowon.kr"})


def _reference(entity, context, day, *, allow_expired=False):
    """A parcel ordinance is a reference, never a verified site-wide limit."""
    context = context or {}
    identity = context.get("identity") or {}
    ref = context.get("ordinanceReference") or {}
    if not isinstance(identity, dict) or not isinstance(ref, dict):
        return None
    checked = _date(ref.get("checkedAt"))
    area = number(ref.get("parcelAreaSqm"))
    zone_area = number(ref.get("zoneAreaSqm"))
    far = number(ref.get("floorAreaRatio"))
    coverage = number(ref.get("buildingCoverageRatio"))
    source = urlsplit(str(ref.get("sourceUrl") or ""))
    if not (all(identity.get(k) and str(identity[k]) == str(entity.get(k))
                for k in ("apartmentId", "district", "legalDong", "jibun"))
            and ref.get("kind") == "ordinance_reference" and ref.get("pnu") == parcel_pnu(entity)
            and source.scheme == "https" and source.hostname in ("eum.go.kr", "www.eum.go.kr")
            and checked and (day - checked).days >= 0
            and (allow_expired or (day - checked).days <= MAX_SOURCE_AGE_DAYS)
            and far and coverage and coverage <= 100 and ref.get("zoneName")
            and area and zone_area and abs(area - zone_area) <= 0.01):
        return None
    # A district-unit plan describes land-use planning, not an approved rebuilding project.
    result = {k: ref.get(k) for k in ("kind", "pnu", "parcelAreaSqm", "zoneAreaSqm", "zoneName",
              "floorAreaRatio", "buildingCoverageRatio", "sourceUrl", "checkedAt", "lawAsOf", "landAsOf")}
    if ref.get("districtPlanName") and _official(ref.get("districtPlanUrl")):
        result.update(districtPlanName=ref["districtPlanName"], districtPlanUrl=ref["districtPlanUrl"])
    return result


def _parcel_reference(entity, context, day, *, allow_expired=False):
    """Public parcel zoning is useful, but does not establish site-wide coverage."""
    context = context or {}
    identity, ref = context.get('identity') or {}, context.get('parcelReference') or {}
    if not isinstance(identity, dict) or not isinstance(ref, dict):
        return None
    checked = _date(ref.get('checkedAt'))
    source = urlsplit(str(ref.get('sourceUrl') or ''))
    zones, plans = ref.get('zoneNames'), ref.get('districtPlans')
    if not (all(identity.get(k) and str(identity[k]) == str(entity.get(k))
                for k in ('apartmentId', 'district', 'legalDong', 'jibun'))
            and all(not identity.get(k) or str(identity[k]) == str(entity.get(k)) for k in ('province', 'cortarNo'))
            and ref.get('pnu') == parcel_pnu(entity) and ref.get('scope') == 'representative_parcel'
            and ref.get('zoneCoverageVerified') is False and ref.get('license') == '공공누리 출처표시'
            and source.scheme == 'https' and source.hostname in ('eum.go.kr', 'www.eum.go.kr')
            and checked and (day - checked).days >= 0 and (allow_expired or (day - checked).days <= MAX_SOURCE_AGE_DAYS)
            and number(ref.get('parcelAreaSqm')) and isinstance(zones, list) and zones
            and all(isinstance(zone, str) and zone for zone in zones)
            and isinstance(plans, list) and all(isinstance(plan, str) for plan in plans)):
        return None
    result = {'kind': 'parcel_zoning', 'pnu': ref['pnu'], 'zoneName': ', '.join(zones),
              'zoneNames': zones, 'parcelAreaSqm': ref['parcelAreaSqm'], 'sourceUrl': ref['sourceUrl'],
              'checkedAt': ref['checkedAt'], 'zoneCoverageVerified': False}
    if len(plans) == 1:
        match = re.fullmatch(r'(?:제[0-9]+종)?지구단위계획구역\((.+)\)', plans[0])
        result.update(districtPlanName=match.group(1) if match else plans[0], districtPlanUrl=ref['sourceUrl'])
    if len(zones) == 1:
        try:
            rules = _read(str(ORDINANCES_PATH), _stamp(ORDINANCES_PATH))['records'].get(entity.get('province')) or {}
            verified = _date(rules.get('checkedAt'))
            check_path = shared_data.cache_path(ORDINANCE_CHECK_FILE)
            checks = _read(str(check_path), _stamp(check_path))['records']
            check = checks.get(entity.get('province'))
            if check:
                if (check.get('status') == 'verified' and not check.get('lastError')
                        and check.get('effectiveAt') == rules.get('effectiveAt')
                        and check.get('sourceUrl') == 'https://www.law.go.kr/ordinInfoP.do?ordinId=2000719'):
                    verified = _date(check.get('checkedAt'))
                else:
                    verified = None
                    result['ordinanceStatus'] = 'stale' if check.get('lastError') else check.get('status') or 'connection_error'
                    if check.get('sourceUrl') == 'https://www.law.go.kr/ordinInfoP.do?ordinId=2000719':
                        result['ordinanceSourceUrl'] = check['sourceUrl']
            values = (rules.get('zones') or {}).get(zones[0]) or {}
            if (verified and 0 <= (day - verified).days <= MAX_SOURCE_AGE_DAYS and _official(rules.get('sourceUrl'))
                    and number(values.get('floorAreaRatio')) and number(values.get('buildingCoverageRatio'))
                    and number(values.get('buildingCoverageRatio')) <= 100):
                result.update(floorAreaRatio=number(values['floorAreaRatio']),
                              buildingCoverageRatio=number(values['buildingCoverageRatio']),
                              ordinanceSourceUrl=rules['sourceUrl'], lawAsOf=rules.get('effectiveAt'))
            elif values and not result.get('ordinanceStatus'):
                result['ordinanceStatus'] = 'stale'
        except (OSError, ValueError, TypeError):
            result['ordinanceStatus'] = 'connection_error'
    return result


def _planning_reference(entity, context, day, *, allow_expired=False):
    """Do not present an older manually verified ordinance as current after a change."""
    reference = _reference(entity, context, day, allow_expired=allow_expired)
    if not reference:
        return _parcel_reference(entity, context, day, allow_expired=allow_expired)
    try:
        path = shared_data.cache_path(ORDINANCE_CHECK_FILE)
        check = _read(str(path), _stamp(path))['records'].get(entity.get('province')) or {}
        checked = _date(check.get('checkedAt'))
        problem = (check and (check.get('status') != 'verified' or check.get('lastError')
                   or not checked or not 0 <= (day - checked).days <= MAX_SOURCE_AGE_DAYS
                   or check.get('sourceUrl') != 'https://www.law.go.kr/ordinInfoP.do?ordinId=2000719'
                   or check.get('effectiveAt') != reference.get('lawAsOf')))
        status = 'changed' if check.get('status') == 'changed' else 'connection_error'
    except (OSError, ValueError, TypeError):
        problem, status = True, 'connection_error'
    if problem:
        reference = {**reference, 'kind': 'parcel_zoning', 'ordinanceStatus': status}
        reference.pop('floorAreaRatio', None)
        reference.pop('buildingCoverageRatio', None)
    return reference


def profile(entity, entry):
    """Select one exact whole-site register; a parcel alone is insufficient."""
    p = parcel(entity)
    snapshot = entry.get("snapshot") or {}
    if not isinstance(snapshot, dict) or not _official(snapshot.get("sourceUrl")):
        return {"status": "invalid_source", "reason": "공식 건축물대장 원본을 확인하지 못했어요."}
    if not p or snapshot.get("parcel") != p or snapshot.get("recordType") != "recap":
        return {"status": "identity_unverified", "reason": "단지 전체의 건축물대장을 연결하지 못했어요."}
    rows = snapshot.get("records", [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or len(rows) != snapshot.get("totalCount"):
        return {"status": "invalid_source", "reason": "건축물대장 자료가 온전하지 않아 판단할 수 없어요."}
    matches = []
    for r in rows:
        if any(str(r.get(k, "")).zfill(len(v)) != v for k, v in p.items()):
            continue
        if str(r.get("regstrKindCd")) != "1" or not r.get("mgmBldrgstPk"):
            continue
        if "공동주택" not in str(r.get("mainPurpsCdNm", "")):
            continue
        if apartment_identity.phase_conflicts(entity.get("name"), r.get("bldNm")):
            continue
        expected, households = number(entity.get("households")), number(r.get("hhldCnt"))
        if expected and households and expected != households:
            continue
        named = bool(apartment_development.entity_keys(entity) & apartment_development.name_keys(r.get("bldNm"), entity.get("legalDong")))
        if not named and not (expected and households == expected):
            continue
        matches.append(r)
    if len(matches) != 1:
        return {"status": "identity_unverified" if rows else "no_records",
                "reason": "단지 전체의 건축물대장을 하나로 확인하지 못했어요." if rows else "이 주소의 단지 전체 건축물대장 조회 결과가 없어요."}
    r = matches[0]
    far, coverage = number(r.get("vlRat")), number(r.get("bcRat"))
    land, area = number(r.get("platArea")), number(r.get("vlRatEstmTotArea"))
    build_area = number(r.get("archArea"))
    # Invalid or placeholder zero is unknown, never a favorable low ratio.
    if far and land and area and abs(far - area / land * 100) > 1:
        far = None
    if coverage and (coverage > 100 or (land and build_area and abs(coverage - build_area / land * 100) > 1)):
        coverage = None
    return {"status": "ready" if far and coverage else "partial",
            "floorAreaRatio": far, "buildingCoverageRatio": coverage, "landAreaSqm": land,
            "floorAreaForRatioSqm": area, "households": number(r.get("hhldCnt")),
            "registerId": str(r["mgmBldrgstPk"]), "registerName": r.get("bldNm", ""),
            "approvedAt": r.get("useAprDay"), "recordCreatedAt": r.get("crtnDay"),
            "scope": "whole_registered_site", "source": snapshot.get("source"),
            "sourceUrl": snapshot.get("sourceUrl"), "fetchedAt": snapshot.get("fetchedAt"),
            "reason": "" if far and coverage else "공식 자료에서 일부 값이 비어 있거나 면적과 맞지 않아요."}


def _load_context(entity, result, *, source_confirmed=False):
    try:
        context = _read(str(CONTEXT_PATH), _stamp(CONTEXT_PATH))['records'].get(result['apartmentId'])
    except (OSError, ValueError, TypeError):
        context = None
    try:
        planning_path = shared_data.cache_path(PLANNING_FILE)
        shared_context = _read(str(planning_path), _stamp(planning_path))['records'].get(result['apartmentId'])
        if shared_context:
            context = {**shared_context, **(context or {})}
            shared_identity = shared_context.get('identity') or {}
            if (not isinstance(shared_identity, dict) or
                    any(str(shared_identity.get(k) or '') != str(entity.get(k) or '')
                        for k in ('apartmentId', 'district', 'legalDong', 'jibun'))):
                result['planningSourceStatus'] = 'identity_unverified'
            elif shared_context.get('lastError'):
                result['planningSourceStatus'] = ('stale' if shared_context.get('ordinanceReference')
                                                   or shared_context.get('parcelReference')
                                                   else shared_context['lastError'].get('status', 'connection_error'))
            elif not source_confirmed and shared_data.read_only() and shared_data.status().get('status') == 'stale':
                result['planningSourceStatus'] = 'stale'
    except (OSError, ValueError, TypeError):
        result['planningSourceStatus'] = 'connection_error'
    return context


def _conditions(entity, entry=None, context=None, *, day=None, source_confirmed=False):
    day = day or dt.date.today()
    result = {"version": VERSION, "apartmentId": str(entity.get("apartmentId") or ""),
              "identity": {k: entity.get(k, "") for k in ("apartmentId", "province", "district", "legalDong", "jibun")},
              "status": "not_collected", "grade": "unknown", "summary": "", "profile": {},
              "heading": "재건축 여건은 자료가 부족해 판단할 수 없어요",
              "reason": "단지 전체의 용적률·건폐율 자료가 아직 수집되지 않았어요.",
              "limitation": "현재 건물의 조건과 실제 사업 추진 상황은 따로 확인해요.",
              "basis": None, "planningReference": None, "projectPlan": None, "sourceRevision": revision()}
    if not parcel(entity) or not result["apartmentId"]:
        result.update(status="identity_unverified", reason="단지 고유번호와 법정동·지번을 확인해야 해요.")
        return result
    result['projectPlan'] = reconstruction_project_plans.for_apartment(entity, day=day, _source_confirmed=source_confirmed)
    if context is None:
        context = _load_context(entity, result, source_confirmed=source_confirmed)
    if result.get('planningSourceStatus') != 'identity_unverified':
        reference = _planning_reference(entity, context, day)
        if reference:
            result['planningReference'] = reference
            if result.get('planningSourceStatus') == 'stale':
                result['planningReferenceStatus'] = 'stale'
            result['limitation'] = '대표 지번의 조례 기준은 참고값이에요. 단지 전체에 실제 적용되는 기준은 따로 확인해야 해요.'
    if entry is None:
        try:
            path = shared_data.cache_path(FACT_FILE)
            entry = _read(str(path), _stamp(path))["records"].get(parcel_key(entity))
        except (OSError, ValueError, TypeError):
            result.update(status="connection_error", reason="건축물대장 원본을 읽지 못했어요. 리포트를 다시 열어 주세요.")
            return result
    if not entry:
        if shared_data.read_only() and shared_data.status().get("status") in ("stale", "unavailable"):
            result.update(status="connection_error", reason="운영 원본 연결을 마치지 못해 건축물대장 자료를 가져오지 못했어요. 다시 불러오기를 눌러 주세요.")
        return result
    result["status"] = entry.get("status", "not_collected")
    if not entry.get("snapshot"):
        result["reason"] = {"connection_error": "건축물대장 연결에 실패했어요. 잠시 뒤 리포트를 다시 열어 주세요.",
                            "no_records": "이 주소의 단지 전체 건축물대장 조회 결과가 없어요.",
                            "access_denied": "공식 자료 제공처에서 조회를 허용하지 않아 자료를 받지 못했어요. 연결이 복구되면 다시 확인할 수 있어요."}.get(result["status"], result["reason"])
        result["errorCode"] = entry.get("errorCode")
        return result
    facts = profile(entity, entry)
    result.update(profile=facts, status=facts["status"])
    if facts["status"] not in ("ready", "partial"):
        result["reason"] = facts["reason"]
        return result
    collected = _date(facts.get("fetchedAt"))
    if entry.get("lastError") or not collected or (day - collected).days not in range(MAX_SOURCE_AGE_DAYS + 1):
        result.update(status="stale", reason="최신 건축물대장을 확인하지 못해 마지막 정상 자료를 보여드려요. 리포트를 다시 열어 주세요.")
        return result
    far = facts.get("floorAreaRatio")
    if far is None:
        result.update(heading="현재 용적률을 알 수 없어 건축 규모를 비교할 수 없어요",
                      reason="건축물대장에 용적률이 비어 있거나 면적과 맞지 않아요.")
        return result
    age = apartment_development._age(entity, day)
    plan = result.get('projectPlan') or {}
    confirmed_plan = (plan.get('status') == 'ready' and plan.get('apartmentId') == result['apartmentId']
                      and plan.get('identityMatch') == 'district_dong_parcel_and_name')
    young = (age is None or age < 30) and not confirmed_plan
    if young:
        reference = _planning_reference(entity, context, day)
        stale = result.get('planningSourceStatus') == 'stale'
        result.update(grade='not_assessed', heading='현재 용적률과 건폐율을 확인했어요',
                      reason='이 자료는 단지 전체의 건축 규모를 나타내요. 재건축 추진 여부나 자격을 뜻하지 않아요.')
        if reference:
            result.update(status='stale' if stale else 'reference_partial', planningReference=reference,
                          heading='현재 건축 규모와 대표 지번 기준을 확인했어요',
                          limitation='대표 지번의 조례 기준은 참고값이에요. 재건축 계획이나 실제 적용 기준을 뜻하지 않아요.')
        return result
    result.update(status="basis_missing", heading="현재 용적률은 확인됐지만 늘릴 수 있는 규모는 아직 판단할 수 없어요",
                  reason="이 단지에 적용되는 건축 기준이나 공식 정비계획이 아직 확인되지 않았어요.",
                  limitation="용적률이 낮다는 사실만으로 재건축 사업성이나 분담금을 확정할 수는 없어요.")
    basis = (context or {}).get("basis") or {}
    checked = _date(basis.get("checkedAt"))
    identity = (context or {}).get("identity") or {}
    complete_identity = all(identity.get(k) and identity[k] == entity.get(k) for k in ("apartmentId", "district", "legalDong", "jibun"))
    ceiling = number(basis.get("floorAreaRatio"))
    if not (complete_identity and _official(basis.get("sourceUrl")) and checked
            and 0 <= (day - checked).days <= MAX_SOURCE_AGE_DAYS and ceiling
            and basis.get("kind") in ("current_limit", "approved_plan") and basis.get("siteScopeVerified") is True
            and number(basis.get("landAreaSqm")) == facts.get("landAreaSqm")):
        reference = _planning_reference(entity, context, day)
        stale_reference = _planning_reference(entity, context, day, allow_expired=True)
        if stale_reference and (not reference or result.get("planningSourceStatus") == "stale"):
            result.update(status="stale", grade="unknown", planningReference=stale_reference,
                          heading="마지막으로 확인한 조례 기준을 보여드려요",
                          reason="건축 기준의 최신 자료를 확인하지 못했어요. 마지막 정상 자료를 표시해요.",
                          limitation="현재도 같은 기준인지 확인하지 못했어요. 지구단위계획과 정비계획에 따라 실제 기준이 달라질 수 있어요.")
            if stale_reference.get('kind') == 'ordinance_reference':
                result['differencePp'] = round(number(stale_reference['floorAreaRatio']) - far, 2)
            return result
        if reference:
            if reference.get('kind') == 'parcel_zoning':
                result.update(status='reference_partial', grade='reference', planningReference=reference,
                              heading='대표 지번의 용도지역과 조례 기준을 확인했어요' if reference.get('floorAreaRatio') else '대표 지번의 용도지역을 확인했어요',
                              reason=f"대표 지번은 단지 주소로 쓰는 땅이에요. 이 땅의 용도지역(건축 기준을 정하는 땅의 종류)은 {reference['zoneName']}이에요.",
                              limitation='단지 전체 땅이 같은 기준에 해당하는지 아직 확인하지 못해 차이는 계산하지 않았어요. 지구단위계획과 정비계획, 공공기여에 따라 실제 기준은 달라질 수 있어요.')
                if reference.get('ordinanceStatus') == 'changed':
                    result['limitation'] = '조례가 바뀌어 새 건축 기준 확인이 필요해요. 단지 전체 땅의 적용 기준도 따로 확인해야 해요.'
                elif reference.get('ordinanceStatus'):
                    result['limitation'] = '최신 조례를 불러오지 못했어요. 단지 전체 땅의 적용 기준도 따로 확인해야 해요.'
                return result
            gap = round(number(reference["floorAreaRatio"]) - far, 2)
            comparison = "낮아요" if gap > 0 else "같아요" if gap == 0 else "높아요"
            result.update(status="reference", grade="reference", planningReference=reference,
                          differencePp=gap,
                          heading=f"현재 용적률은 대표 지번의 조례 기준보다 {comparison}",
                          summary=f"연식은 오래됐고, 현재 용적률은 대표 지번의 조례 기준보다 {comparison}.",
                          reason=f"대표 지번은 단지 주소로 쓰는 땅이에요. 이 땅의 용도지역(건축 기준을 정하는 땅의 종류)은 {reference['zoneName']}이에요. 조례 기준은 모든 조건을 반영한 값은 아니에요.",
                          limitation="실제 건축 기준은 단지 전체 땅의 범위, 지구단위계획(동네 건축 계획), 정비계획(재건축 계획), 공공기여(공공을 위한 시설·비용) 등에 따라 달라질 수 있어요. 세대수나 수익은 아직 알 수 없어요.")
        elif result.get("planningSourceStatus") == "connection_error":
            result.update(status="connection_error", heading="건축 기준을 불러오지 못해 규모를 비교할 수 없어요",
                          reason="건축 기준 원본 연결에 문제가 생겼어요. 잠시 뒤 리포트를 다시 열어 주세요.")
        elif result.get('planningSourceStatus') in ('access_denied', 'license_unverified', 'identity_unverified', 'no_records', 'invalid_source'):
            reasons = {'access_denied':'공식 자료 제공처에서 조회를 허용하지 않았어요. 잠시 뒤 다시 열어 주세요.',
                       'license_unverified':'공식 자료의 이용 조건을 확인하지 못했어요.',
                       'identity_unverified':'공식 자료의 지번이 단지 주소와 일치하지 않아요.',
                       'no_records':'대표 지번의 용도지역 자료를 찾지 못했어요.',
                       'invalid_source':'공식 자료 형식을 확인하지 못했어요. 잠시 뒤 다시 열어 주세요.'}
            status = result['planningSourceStatus']
            result.update(status=status, heading='건축 기준을 확인하지 못해 규모를 비교할 수 없어요', reason=reasons[status])
        return result
    result["planningReference"] = None
    result.pop('planningReferenceStatus', None)
    result["basis"] = basis
    gap = round(ceiling - far, 2)
    result["differencePp"] = gap
    limited = gap / ceiling <= LIMITED_HEADROOM_RATIO
    result.update(status="ready", grade="limited" if limited else "potential")
    if basis["kind"] == "approved_plan":
        result.update(grade="planned", heading="공식 정비계획에서 새로 지을 규모를 확인했어요",
                      summary="연식은 오래됐지만, 공식 정비계획에서 새로 지을 규모가 확인됐어요.",
                      reason="현재와 계획의 대지 범위가 같은 자료로 용적률을 비교했어요.")
    elif not limited:
        result.update(heading="현재 용적률이 확인된 건축 기준보다 낮아요",
                      summary="연식은 약점이지만, 건축 기준보다 낮은 용적률은 재건축 검토의 강점이에요.",
                      reason="현재 기준보다 적게 지어져 있어 규모를 늘릴 여지를 검토할 수 있어요. 실제로 늘어날 세대수는 아직 정해지지 않았어요.")
    else:
        result.update(heading="현재 기준에서는 건축 규모를 늘릴 여지가 작아요" if gap > 0 else "현재 기준에서는 용적률을 더 늘릴 여지가 확인되지 않아요",
                      summary="연식은 오래됐고, 현재 확인된 기준에서는 규모를 늘릴 여지가 작아요." if gap > 0 else "연식은 오래됐고, 현재 확인된 기준에서는 용적률을 더 늘릴 여지가 확인되지 않아요.",
                      reason="현재 용적률과 건축 한도의 차이가 한도의 10% 이내예요. 집픽의 설명 기준이며 사업 가능 여부를 정하는 법적 기준은 아니에요." if gap > 0 else "현재 용적률이 확인된 건축 한도에 도달했어요. 별도 완화나 새 정비계획이 확인되면 다시 판단해요.")
    result["limitation"] = "용적률 차이가 그대로 일반분양 물량이나 수익이 되지는 않아요. 기존 세대수·사업비·추가분담금을 함께 봐야 해요."
    return result


def feasibility(model):
    """A directional construction assessment, not a profitability calculation.

    A matched project's FAR describes its own density even when its boundary
    differs. Compare that direction provisionally; never turn it into saleable
    area, extra units, or profit. Parcel ordinances are explicitly conditional.
    Missing costs and revenue never become a negative score or a zero value.
    """
    facts, basis = model.get('profile') or {}, model.get('basis') or {}
    plan, reference = model.get('projectPlan') or {}, model.get('planningReference') or {}
    result = {'version': FEASIBILITY_VERSION, 'scope': 'construction_conditions',
              'status': 'unknown', 'direction': 'unknown', 'basisKind': None,
              'headline': '사업성은 자료가 부족해 판단할 수 없어요',
              'reason': model.get('reason') or '현재 건축 규모와 적용 기준을 함께 확인하지 못했어요.',
              'financialStatus': 'not_assessed',
              'financialLimitation': '공사비·일반분양 수입·공공기여 비용이 없어 실제 수익성과 추가분담금은 아직 판단할 수 없어요.',
              'missingFinancialInputs': ['construction_cost', 'general_sale_revenue', 'public_contribution_cost'],
              'comparison': None}
    if model.get('status') in ('stale', 'connection_error', 'invalid_source', 'identity_unverified', 'access_denied'):
        result.update(status='unavailable', headline='최신 자료를 확인하지 못해 사업성 판단을 보류했어요')
        return result
    if model.get('grade') == 'not_assessed':
        result.update(status='not_assessed', headline='현재 건축 규모만으로 재건축 사업성을 판단하지 않아요')
        return result
    current = number(facts.get('floorAreaRatio'))
    # Some older apartment sites have no recap register. The same official
    # quarterly record can supply both before/after densities, but only when
    # the physical address/name AND the existing household count agree.
    # This remains a dated project-density comparison, never a site-wide limit.
    inventory_current = (not current and plan.get('status') == 'ready'
                         and plan.get('apartmentId') == model.get('apartmentId')
                         and plan.get('identityMatch') == 'district_dong_parcel_and_name'
                         and plan.get('subjectHouseholdsMatch') is True
                         and number(plan.get('existingFloorAreaRatio'))
                         and number(plan.get('plannedFloorAreaRatio')))
    if inventory_current:
        current = number(plan['existingFloorAreaRatio'])
    if not current or not inventory_current and facts.get('scope') != 'whole_registered_site':
        result['reason'] = '현재 용적률을 확인하지 못해 계획대로 얼마나 더 지을 수 있는지 비교하지 못했어요.'
        return result

    target, kind = number(basis.get('floorAreaRatio')), basis.get('kind')
    if target:
        scope_verified = True
    elif (plan.get('status') == 'ready' and plan.get('apartmentId') == model.get('apartmentId')
          and plan.get('identityMatch') == 'district_dong_parcel_and_name'
          and number(plan.get('plannedFloorAreaRatio'))):
        target, kind, scope_verified = number(plan['plannedFloorAreaRatio']), 'project_plan', False
    elif (model.get('planningReferenceStatus') != 'stale'
          and model.get('planningSourceStatus') not in ('stale', 'connection_error', 'identity_unverified')
          and not reference.get('ordinanceStatus') and number(reference.get('floorAreaRatio'))):
        target, kind, scope_verified = number(reference['floorAreaRatio']), 'parcel_ordinance', False
    else:
        result['reason'] = '현재 용적률은 확인됐지만 비교할 계획 용적률이나 건축 기준이 없어 유리·불리를 판단하지 못했어요.'
        return result

    # Retain the existing 10%-of-ceiling description convention, not a new
    # legal eligibility threshold or a score estimating financial returns.
    gap = target - current
    direction = 'unfavorable' if gap <= 0 else 'limited' if gap / target <= LIMITED_HEADROOM_RATIO else 'favorable'
    qualifier = ('계획 기준으로는 ' if kind in ('approved_plan', 'project_plan') else
                 '조례 기준이 적용된다면 ' if kind == 'parcel_ordinance' else '확인된 기준에서는 ')
    headlines = {'favorable': '사업성에 유리한 건축 조건이에요',
                 'limited': '사업성을 높일 건축 여지가 크지 않아요',
                 'unfavorable': '사업성에 불리한 건축 조건이에요'}
    evidence = {'favorable': '현재보다 높은 용적률로 지을 수 있는 기준이 있어요',
                'limited': '현재 용적률과 비교 기준의 차이가 작아요',
                'unfavorable': '현재 용적률이 비교 기준에 이미 도달했어요'}
    if kind in ('approved_plan', 'project_plan') and direction == 'favorable':
        evidence['favorable'] = '현재보다 높은 용적률로 짓는 계획이에요'
    reasons = {'favorable': '주택을 더 지을 여지를 검토할 수 있어요. 일반분양 물량이 확보되면 사업비를 충당하는 데 도움이 될 수 있어요.',
               'limited': '용적률 차이가 비교 기준의 10% 이내여서, 건축 규모를 늘려 사업비를 충당할 여지는 크지 않다고 봤어요.',
               'unfavorable': '현재 확인한 용적률 기준만으로는 건축 규모를 더 늘리기 어려워요. 별도 완화나 새 계획이 생기면 판단이 달라질 수 있어요.'}
    scope_note = ('용적률 차이가 일반분양 물량을 뜻하지는 않아요.' if scope_verified else
                  '정비사업과 기존 단지의 땅 범위가 다를 수 있어 계획의 방향만 판단했어요. 늘어날 면적·일반분양 물량은 계산하지 않았어요.'
                  if kind == 'project_plan' else
                  '대표 지번의 조례 기준을 단지 전체에 적용할 수 있는지는 아직 확인되지 않았어요. 정비계획에 따라 달라질 수 있어요.')
    result.update(status='assessed' if scope_verified else 'conditional', direction=direction, basisKind=kind,
                  headline=qualifier + headlines[direction], evidenceHeading=evidence[direction],
                  reason=reasons[direction], scopeNote=scope_note,
                  comparison={'currentFloorAreaRatio': current, 'referenceFloorAreaRatio': target,
                              'siteScopeVerified': scope_verified,
                              'differencePp': round(gap, 2) if scope_verified else None},
                  classificationNote='차이가 비교 기준의 10% 이내면 여지가 작다고 보는 집픽의 설명 기준이에요. 법적 기준이나 수익률 점수는 아니에요.')
    if inventory_current:
        result['comparison'].update(currentSource='official_project_inventory', currentSourceDate=plan.get('sourceDate'))
        result['scopeNote'] = ('건축물대장 총괄자료가 없어 공식 통계에 실린 기존·신축 용적률을 비교했어요. '
                               '단지 주소·이름·기존 세대수를 대조했어요. 통계 기준일 이후 바뀌었을 수 있고, 일반분양 물량이나 수익은 계산하지 않았어요.')
    return result


def analyze(entity, entry=None, context=None, *, day=None, _source_confirmed=False):
    proof = _current_confirmation(entity) if entry is None and context is None else None
    result = _conditions(entity, entry, context, day=day, source_confirmed=_source_confirmed or bool(proof))
    result['feasibility'] = feasibility(result)
    if proof and proof['revision'] != _confirmation_revision():
        forget_primary_confirmation(entity)
        return analyze(entity, entry, context, day=day)
    if proof:
        result['sourceVerification'] = {'method': 'primary_api_same_snapshot', 'checkedAt': proof['checkedAt']}
    return result


def attach(row, entity=None):
    row["reconstructionConditions"] = analyze(entity or row)
    return row
