#!/usr/bin/env python3
"""Build the remodeling evidence snapshot from the audited collection exports."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import remodeling_assessment as remodeling

REGISTER_URL = "https://www.hub.go.kr/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do"
REB_URL = "https://www.data.go.kr/data/15106866/fileData.do"


def read_json(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("register_inventory", type=Path)
    parser.add_argument("ratios", type=Path)
    parser.add_argument("gis", type=Path)
    parser.add_argument("--output", type=Path, default=remodeling.PATH)
    args = parser.parse_args()

    inventory = read_json(args.inventory)["records"]
    registers = read_json(args.register_inventory)["records"]
    ratios = read_json(args.ratios)
    gis_rows = read_json(args.gis)["records"].values()
    gis = {remodeling.identity_key(row["identity"]): row["values"].get("buildingCoverage") for row in gis_rows}
    records = {}
    for row_id, row in inventory.items():
        key = remodeling.identity_key(row["identity"])
        if key is None:
            if row.get("highestResidentialFloors"):
                raise ValueError(f"Floor evidence without an exact identity: {row_id}")
            continue
        if key in records:
            raise ValueError(f"Duplicate identity: {row_id}")
        approved_at = row.get("approvalDate") or row.get("approvalYear")
        if row.get("approvalPrecision") == "month":
            approved_at = str(approved_at)[:7]
        elif row.get("approvalPrecision") == "year":
            approved_at = str(approved_at)[:4]
        record = {"approvedAt": approved_at}
        floors = row.get("highestResidentialFloors")
        if floors is not None:
            if floors <= 0 or int(floors) != floors:
                raise ValueError(f"Invalid floor count: {row_id}")
            source_file = row["floorEvidenceFile"]
            proof = registers.get(row_id, {}).get("registerProof") or {}
            from_register = source_file == args.register_inventory.name
            if not from_register and source_file not in {
                "최고층수-한국부동산원-동별대조.json", "최고층수-잔여512곳-추가대조.json"
            }:
                raise ValueError(f"Unknown floor evidence source: {source_file}")
            record["floor"] = {"value": int(floors), "method": "건축물대장 주거동 대조" if from_register else "한국부동산원 주거동 대조",
                               "sourceUrl": (proof.get("floorSourceUrl") or proof.get("url") or REGISTER_URL) if from_register else REB_URL}
        coverage = ratios["records"].get(key, {}).get("buildingCoverageRatio")
        site_estimate = gis.get(key) or {}
        if (site_estimate.get("estimated") is True and remodeling.coverage_value(site_estimate.get("value"))
                and site_estimate.get("sourceUrls") and (not coverage or
                    coverage["estimated"] and not coverage["sourceUrls"])):
            coverage = {"value": site_estimate["value"], "estimated": True, "method": site_estimate["basis"],
                        "sourceUrls": site_estimate["sourceUrls"], "checkedAt": ratios["asOf"]}
        if coverage and remodeling.coverage_value(coverage["value"]):
            record["coverage"] = coverage
        records[key] = record

    snapshot = {"version": remodeling.VERSION, "asOf": ratios["asOf"], "records": records}
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    args.output.write_bytes(gzip.compress(raw, mtime=0))
    print(f'{len(records):,} identities, {sum("floor" in row for row in records.values()):,} floor counts, '
          f'{sum("coverage" in row for row in records.values()):,} coverage ratios')


if __name__ == "__main__":
    main()
