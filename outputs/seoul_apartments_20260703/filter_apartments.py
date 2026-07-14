import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "서울시_공동주택_단지_목록_한국부동산원_20250918.csv"
OUTPUT = Path(__file__).resolve().parent / "서울시_아파트_단지_목록_한국부동산원_20250918.csv"
JSON_OUTPUT = Path(__file__).resolve().parent / "서울시_아파트_단지_목록_한국부동산원_20250918.json"


with SOURCE.open(newline="", encoding="utf-8-sig") as src, OUTPUT.open(
    "w", newline="", encoding="utf-8-sig"
) as dst:
    reader = csv.DictReader(src)
    writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
    writer.writeheader()
    count = 0
    rows = []
    for row in reader:
        if row.get("단지종류명") == "아파트":
            writer.writerow(row)
            rows.append(row)
            count += 1

JSON_OUTPUT.write_text(
    json.dumps({"headers": reader.fieldnames, "rows": rows}, ensure_ascii=False),
    encoding="utf-8",
)
print(OUTPUT)
print(count)
