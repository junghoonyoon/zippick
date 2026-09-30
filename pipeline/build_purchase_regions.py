#!/usr/bin/env python3
"""구매 희망지역 선택용 시·도 / 시·군·구 목록을 만든다.

전국 공동주택 단지 기본정보의 필지고유번호 앞 5자리(시군구 코드)와 주소를
묶어 `data/purchase_regions.json`을 만든다. 규제지역 여부는 이 파일에 넣지 않고
정책 설정(`housing_policy_snapshot.json`)에서 계산한다.
"""
import collections
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "korea_housing_complex_basic_20250918.csv"
OUTPUT = ROOT / "data" / "purchase_regions.json"

# 집픽 서비스 지역: 서울·경기·인천. 지역을 넓히면 이 목록에 시·도를 더한다.
PROVINCE_ORDER = ["서울특별시", "경기도", "인천광역시"]

# 원본 자료(2025.09) 이후 새로 생긴 일반구. 규제지역 판단에 필요한 곳만 보강한다.
# 코드는 상위 시 코드 뒤에 구 이름을 붙여 구분한다.
EXTRA_DISTRICTS = [
    ("경기도", "화성시 동탄구", "41590-동탄구"),
    ("경기도", "화성시 만세구", "41590-만세구"),
    ("경기도", "화성시 효행구", "41590-효행구"),
    ("경기도", "화성시 병점구", "41590-병점구"),
]
REPLACED_BY_EXTRA = {"41590"}


def build():
    counts = collections.defaultdict(collections.Counter)
    with SOURCE.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            pnu = re.sub(r"\D", "", row.get("필지고유번호") or "")
            tokens = (row.get("주소") or "").split()
            if len(pnu) < 5 or len(tokens) < 2:
                continue
            province = tokens[0]
            district = tokens[1]
            if province == "세종특별자치시":
                district = "세종시"
            elif len(tokens) > 2 and district.endswith("시") and tokens[2].endswith("구"):
                district = f"{district} {tokens[2]}"
            elif province.endswith("도") and district.endswith("구") and len(district) > 3:
                # 원본 주소의 '성남분당구'처럼 붙은 표기를 '성남시 분당구'로 나눈다.
                # 일반구가 있는 도 소속 시는 모두 두 글자 이름이다.
                district = f"{district[:2]}시 {district[2:]}"
            counts[pnu[:5]][(province, district)] += 1

    regions = []
    for code, counter in counts.items():
        if code in REPLACED_BY_EXTRA:
            continue
        province, district = counter.most_common(1)[0][0]
        if province not in PROVINCE_ORDER:
            continue
        regions.append({"code": code, "province": province, "district": district})
    for province, district, code in EXTRA_DISTRICTS:
        regions.append({"code": code, "province": province, "district": district})

    order = {name: index for index, name in enumerate(PROVINCE_ORDER)}
    regions.sort(key=lambda item: (order.get(item["province"], 99), item["district"]))
    return {
        "source": SOURCE.name,
        "note": "시군구 코드는 필지고유번호 앞 5자리예요. 새 일반구는 상위 시 코드에 구 이름을 붙였어요.",
        "regions": regions,
    }


def main():
    data = build()
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(data['regions'])}개 지역 저장: {OUTPUT}")


if __name__ == "__main__":
    main()
