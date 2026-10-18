"""Run an advisory Jev review. Never mutate the approved map exclusion registry."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from typesafe_jev import review_occupancy_evidence


def main():
    registry = json.loads((ROOT / "data/redevelopment_occupancy_overrides.json").read_text())
    # Duplicate boundary records share the same physical complex and evidence.
    unique = {row["kaptCode"]: row for row in registry["entries"]}
    records = list(unique.values()) + registry["retainedForReview"]
    result = review_occupancy_evidence(records, registry["asOfDate"])
    result["asOfDate"] = registry["asOfDate"]
    result["scope"] = "Provided evidence summaries only; not independent source verification or removal authorization."
    output = ROOT / "docs/redevelopment-occupancy-jev-audit.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "reviewed": len(result["reviews"]),
                      "needsReview": [r["zoneName"] for r in result["reviews"] if r["choice"] != "supported"]}, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
