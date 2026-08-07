#!/usr/bin/env python3
"""인천광역시 아파트 단지 목록 CSV 생성.

인천은 서울·경기와 달리 단지 목록 CSV가 없어서 검색 시드가 0이었다.
그 결과 인천 연수·서·부평·미추홀구는 어떤 조건으로도 후보가 나오지 않았다.

새로 내려받지 않고 이미 있는 전국 원본에서 뽑는다. 서울·경기 파일과
원천·기준일(한국부동산원 20250918)이 같아야 세 지역을 한 표에서 비교할 수
있기 때문이다. 다른 날짜 파일을 섞으면 단지고유번호 체계가 어긋난다.

    python3 pipeline/build_incheon_complex_list.py

만들어지는 파일: data/인천광역시_아파트_단지_목록_한국부동산원_20250918.csv
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "korea_housing_complex_basic_20250918.csv"
OUTPUT = ROOT / "data" / "인천광역시_아파트_단지_목록_한국부동산원_20250918.csv"

PROVINCE = "인천광역시"
SOURCE_LABEL = "한국부동산원_공동주택 단지 식별정보_기본정보_20250918"

# 전국 원본은 단지종류를 코드로만 준다. 서울·경기 파일의 매핑과 같아야 한다.
COMPLEX_KINDS = {"1": "아파트", "2": "연립", "3": "다세대"}
APARTMENT_CODE = "1"

# 경기도 파일과 동일한 컬럼 순서. 로더가 `시군구 or 자치구`로 읽으므로
# 군 지역(강화·옹진)까지 담을 수 있는 경기도 스키마를 따른다.
FIELDS = [
    "단지고유번호", "필지고유번호", "시도", "시군구", "일반구", "읍면동", "지번",
    "주소", "대표단지명", "단지명_공시가격", "단지명_건축물대장", "단지명_도로명주소",
    "단지종류코드", "단지종류명", "동수", "세대수", "사용승인일", "원천데이터",
]


def split_address(address):
    """`인천광역시 연수구 동춘동 926` → (연수구, 동춘동, 926).

    강화군처럼 읍·리가 끼는 주소는 `강화읍` + `관청리 123`으로 나눈다.
    경기도 파일이 쓰는 방식과 같게 맞춘다.
    """
    tokens = str(address or "").split()
    if len(tokens) < 3 or tokens[0] != PROVINCE:
        return None
    district = tokens[1]
    dong = tokens[2]
    jibun = " ".join(tokens[3:])
    return district, dong, jibun


def representative_name(row):
    """대표단지명. 경기도 파일은 건축물대장 이름을 대표로 쓴다."""
    for key in ("단지명_건축물대장", "단지명_도로명주소", "단지명_공시가격"):
        name = str(row.get(key) or "").strip()
        if name:
            return name
    return ""


def build():
    if not SOURCE.exists():
        raise SystemExit(f"전국 원본이 없습니다: {SOURCE}")

    written = 0
    skipped_address = 0
    by_district = {}

    with SOURCE.open(newline="", encoding="utf-8-sig") as src, OUTPUT.open(
        "w", newline="", encoding="utf-8-sig"
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=FIELDS)
        writer.writeheader()

        for row in reader:
            address = str(row.get("주소") or "")
            if not address.startswith(PROVINCE):
                continue
            if str(row.get("단지종류") or "").strip() != APARTMENT_CODE:
                continue
            parts = split_address(address)
            if not parts:
                skipped_address += 1
                continue
            district, dong, jibun = parts
            writer.writerow({
                "단지고유번호": row.get("단지고유번호", ""),
                "필지고유번호": row.get("필지고유번호", ""),
                "시도": PROVINCE,
                "시군구": district,
                "일반구": "",  # 인천은 일반구가 없다
                "읍면동": dong,
                "지번": jibun,
                "주소": address,
                "대표단지명": representative_name(row),
                "단지명_공시가격": row.get("단지명_공시가격", ""),
                "단지명_건축물대장": row.get("단지명_건축물대장", ""),
                "단지명_도로명주소": row.get("단지명_도로명주소", ""),
                "단지종류코드": APARTMENT_CODE,
                "단지종류명": COMPLEX_KINDS[APARTMENT_CODE],
                "동수": row.get("동수", ""),
                "세대수": row.get("세대수", ""),
                "사용승인일": row.get("사용승인일", ""),
                "원천데이터": SOURCE_LABEL,
            })
            written += 1
            by_district[district] = by_district.get(district, 0) + 1

    print(f"생성: {OUTPUT}")
    print(f"아파트 단지 {written:,}곳")
    if skipped_address:
        print(f"주소 형식이 달라 건너뜀: {skipped_address:,}건")
    for district, count in sorted(by_district.items(), key=lambda x: -x[1]):
        print(f"  {district:<10} {count:>6,}곳")
    return written


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
