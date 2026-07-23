"""Build a deployable ZipPick-to-Naver complex mapping file.

Production can be slow or blocked when it calls Naver's unofficial endpoints
directly. This script runs in a local/network-friendly environment, matches the
candidate apartment universe by legal-dong complex lists, and writes a static
mapping that the app can use before making any live request.
"""
import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path

import requests

import budget_candidates
import config
import naver_complex
import real_estate_search

DEFAULT_OUTPUT = config.ROOT / "data" / "naver_complex_overrides.json"
COMPLEX_URL_RE = re.compile(r"/complexes/(\d+)")
_CORTAR_CACHE = {}


def _compact(value):
    return real_estate_search.compact(value)


def _dedupe_values(values):
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        key = _compact(text)
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _source_complex_no(row):
    match = COMPLEX_URL_RE.search(str(row.get("sourceUrl") or ""))
    return match.group(1) if match else ""


def _entry_by_complex_no(entries, complex_no):
    for entry in entries or []:
        if naver_complex._entry_complex_no(entry) == str(complex_no):
            return {
                "complexNo": str(complex_no),
                "complexName": naver_complex._entry_name(entry),
            }
    return {"complexNo": str(complex_no), "complexName": ""}


def _cache_file_stems(name, legal_dong, jibun):
    identity = "{name}_{dong}_{jibun}".format(
        name=_compact(name),
        dong=_compact(legal_dong),
        jibun=_compact(jibun),
    )
    for version in ("v6", "v5", "v4", "v3", ""):
        stem = f"{version}_{identity}" if version else identity
        yield re.sub(r"[^0-9a-zA-Z가-힣_-]", "", stem)[:120]


def _cached_resolved_complex(candidate):
    for name in candidate["aliases"] or [candidate["name"]]:
        for stem in _cache_file_stems(
            name,
            candidate["legalDong"],
            candidate["jibun"],
        ):
            path = naver_complex.CACHE_DIR / f"{stem}.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            complex_no = str(payload.get("complexNo") or "").strip()
            if complex_no.isdigit():
                return {
                    "complexNo": complex_no,
                    "complexName": str(payload.get("complexName") or "").strip(),
                }
    return None


def _fetch_cortar_complexes(cortar_no, timeout=8.0):
    cortar_no = re.sub(r"\D", "", str(cortar_no or ""))[:10]
    if len(cortar_no) != 10:
        return None
    if cortar_no in _CORTAR_CACHE:
        return _CORTAR_CACHE[cortar_no]
    try:
        response = requests.get(
            naver_complex.MOBILE_COMPLEX_LIST_ENDPOINT,
            params={"cortarNo": cortar_no},
            headers={**naver_complex.HEADERS, "Referer": "https://m.land.naver.com/"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        _CORTAR_CACHE[cortar_no] = None
        return None
    complexes = data.get("result") if isinstance(data, dict) else None
    if not isinstance(complexes, list):
        complexes = None
    _CORTAR_CACHE[cortar_no] = complexes
    return complexes


def _price_candidate_entities():
    for row in budget_candidates._load_price_bands():
        matches = budget_candidates._find_entities(
            row.get("name", ""),
            row.get("region", ""),
            row.get("legalDong", ""),
            row.get("jibun", ""),
        )
        if len(matches) != 1:
            continue
        entity = matches[0]
        if entity.get("aggregate") or budget_candidates._is_rental_apartment(row, entity):
            continue
        legal_dong = str(entity.get("legalDong") or row.get("legalDong") or "").strip()
        jibun = str(
            entity.get("jibun")
            or budget_candidates._entity_jibun(entity)
            or row.get("jibun")
            or ""
        ).strip()
        if not legal_dong or not jibun:
            continue
        aliases = _dedupe_values([
            row.get("name"),
            entity.get("name"),
            budget_candidates._candidate_display_name(row, entity),
            *(
                []
                if entity.get("aggregate")
                else entity.get("aliases") or []
            ),
        ])
        yield {
            "row": row,
            "entity": entity,
            "name": str(row.get("name") or entity.get("name") or "").strip(),
            "region": str(row.get("region") or entity.get("district") or "").strip(),
            "legalDong": legal_dong,
            "jibun": jibun,
            "cortarNo": str(entity.get("cortarNo") or "").strip(),
            "aliases": aliases,
            "cacheOnly": False,
        }


def _master_cache_entities():
    for entity in real_estate_search.APARTMENT_MASTER:
        if entity.get("aggregate"):
            continue
        legal_dong = str(entity.get("legalDong") or "").strip()
        jibun = str(
            entity.get("jibun")
            or budget_candidates._entity_jibun(entity)
            or ""
        ).strip()
        if not legal_dong or not jibun:
            continue
        aliases = _dedupe_values([
            entity.get("name"),
            *(entity.get("aliases") or []),
        ])
        if not aliases:
            continue
        yield {
            "row": {},
            "entity": entity,
            "name": str(entity.get("name") or "").strip(),
            "region": str(entity.get("district") or entity.get("city") or "").strip(),
            "legalDong": legal_dong,
            "jibun": jibun,
            "cortarNo": str(entity.get("cortarNo") or "").strip(),
            "aliases": aliases,
            "cacheOnly": True,
        }


def _candidate_identity(candidate):
    return (
        _compact(candidate.get("name")),
        _compact(candidate.get("legalDong")),
        _compact(candidate.get("jibun")),
    )


def build_overrides(limit=0, sleep_seconds=0.08, include_master_cache=True):
    candidates_by_key = {}
    for candidate in _price_candidate_entities():
        candidates_by_key[_candidate_identity(candidate)] = candidate
    if include_master_cache:
        for candidate in _master_cache_entities():
            candidates_by_key.setdefault(_candidate_identity(candidate), candidate)
    candidates = list(candidates_by_key.values())
    if limit:
        candidates = candidates[:limit]
    entries_by_key = {}
    stats = {
        "candidates": len(candidates),
        "resolved": 0,
        "unresolved": 0,
        "missingCortarNo": 0,
    }
    for index, candidate in enumerate(candidates, 1):
        row = candidate["row"]
        cortar_no = re.sub(r"\D", "", candidate.get("cortarNo", ""))[:10]
        resolved = None
        source = "local_cache"
        resolved = _cached_resolved_complex(candidate)
        if candidate.get("cacheOnly") and not resolved:
            stats["unresolved"] += 1
            continue
        if cortar_no:
            complexes = None if resolved else _fetch_cortar_complexes(cortar_no)
            source_no = _source_complex_no(row)
            if complexes is not None and source_no and not resolved:
                resolved = _entry_by_complex_no(complexes, source_no)
                source = "source_url"
            if complexes is not None and not resolved:
                primary, *alternates = candidate["aliases"] or [candidate["name"]]
                resolved = naver_complex._pick(
                    complexes,
                    primary,
                    candidate["legalDong"],
                    alternate_names=alternates,
                )
                source = "cortar_list"
        else:
            stats["missingCortarNo"] += 1
        if not resolved or not resolved.get("complexNo"):
            stats["unresolved"] += 1
            continue
        stats["resolved"] += 1
        for name in candidate["aliases"] or [candidate["name"]]:
            key = (
                _compact(name),
                _compact(candidate["legalDong"]),
                _compact(candidate["jibun"]),
            )
            if key in entries_by_key:
                continue
            entries_by_key[key] = {
                "name": name,
                "legalDong": candidate["legalDong"],
                "jibun": candidate["jibun"],
                "region": candidate["region"],
                "complexNo": str(resolved["complexNo"]),
                "complexName": str(resolved.get("complexName") or "").strip(),
                "source": source,
            }
        if sleep_seconds and index % 8 == 0:
            time.sleep(sleep_seconds)
    payload = {
        "version": 1,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": "pipeline/build_naver_complex_overrides.py",
        "stats": {
            **stats,
            "entries": len(entries_by_key),
        },
        "entries": sorted(
            entries_by_key.values(),
            key=lambda item: (
                _compact(item.get("region")),
                _compact(item.get("legalDong")),
                _compact(item.get("jibun")),
                _compact(item.get("name")),
            ),
        ),
    }
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument(
        "--price-only",
        action="store_true",
        help="skip successful local cache mappings from the full apartment master",
    )
    args = parser.parse_args(argv)

    # The generated file is an offline artifact, so prefer completeness over the
    # production request timeout.
    naver_complex.TIMEOUT_SECONDS = max(float(naver_complex.TIMEOUT_SECONDS), 8.0)
    payload = build_overrides(
        limit=args.limit,
        sleep_seconds=args.sleep,
        include_master_cache=not args.price_only,
    )
    output_arg = Path(args.output)
    output = output_arg if output_arg.is_absolute() else config.ROOT / output_arg
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "wrote {entries} entries from {resolved}/{candidates} resolved candidates to {path}".format(
            entries=payload["stats"]["entries"],
            resolved=payload["stats"]["resolved"],
            candidates=payload["stats"]["candidates"],
            path=output,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1:])
