"""청약홈 APT 분양정보를 오픈API로 받아 전국 입주 예정 물량표를 만든다.

왜 오픈API인가. 기존 `build_presale_supplement.py`는 공공데이터포털의
파일 다운로드를 긁어 오고, 서울·경기로 제한한다. 그 결과 서울 38건,
경기 206건만 모였다. 이 편차 때문에 입주물량을 종합 점수에 넣을 수 없다.
수집이 잘 된 지역만 공급 벌점을 받는 구조가 되어 순위가 뒤집히기 때문이다.

그래서 전국을 같은 기준으로 한 번에 받는 경로가 필요하다.

사전 준비:
    공공데이터포털에서 `한국부동산원_청약홈 분양정보 조회 서비스` 활용신청
    https://www.data.go.kr/data/15098547/openapi.do
    승인 후 `설정.txt`에 `청약홈키` 또는 `공공데이터키`를 넣는다.

사용법:
    python3 pipeline/applyhome_supply.py --dry-run     # 키·응답만 확인
    python3 pipeline/applyhome_supply.py               # 전국 수집 후 CSV 저장
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "입주예정_전국.csv"

ENDPOINT = (
    "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
)
DATA_PORTAL_URL = "https://www.data.go.kr/data/15098547/openapi.do"
PAGE_SIZE = 1000
MAX_PAGES = 60
TIMEOUT = 30

OUTPUT_COLUMNS = [
    "공고번호",
    "시도",
    "자치구",
    "시군구",
    "법정동",
    "대표단지명",
    "세대수",
    "상태",
    "입주예정월",
    "출처",
]

# odcloud 자동변환 API는 영문 코드명으로 오지만, 파일데이터를 그대로
# 노출할 때는 한글 컬럼명으로 온다. 둘 다 받는다.
FIELD_ALIASES = {
    "name": ("HOUSE_NM", "주택명"),
    "area": ("SUBSCRPT_AREA_CODE_NM", "공급지역명"),
    "address": ("HSSPLY_ADRES", "공급위치"),
    "households": ("TOT_SUPLY_HSHLDCO", "공급규모"),
    "moveIn": ("MVN_PREARNGE_YM", "입주예정월"),
    "noticeDate": ("RCRIT_PBLANC_DE", "모집공고일"),
    "houseType": ("HOUSE_SECD_NM", "주택구분코드명"),
    # 같은 이름·지역·입주월인 별개 공고가 실제로 존재한다(블록 분할, 차수 분할).
    # 공고번호가 없으면 그 둘이 한 건으로 뭉개져 세대수가 사라진다.
    "noticeNo": ("PBLANC_NO", "HOUSE_MANAGE_NO", "공고번호"),
}

# 경기 특례시는 앱에서 `수원영통구`처럼 시와 구를 붙여 쓴다.
MERGED_CITY_DISTRICTS = {
    "수원시", "성남시", "안양시", "안산시", "고양시", "용인시", "부천시",
    "창원시", "청주시", "천안시", "전주시", "포항시",
}
METRO_SHORT = {
    "서울특별시": "",  # 서울 자치구는 접두 없이 `노원구`로 쓴다
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
}


def service_key():
    for name in ("APPLYHOME_API_KEY", "PUBLIC_DATA_API_KEY", "MOLIT_APARTMENT_TRADE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import config

        for attr in ("APPLYHOME_API_KEY", "PUBLIC_DATA_API_KEY", "MOLIT_APARTMENT_TRADE_API_KEY"):
            value = str(getattr(config, attr, "") or "").strip()
            if value:
                return value
    except Exception:
        pass
    return ""


def _pick(row, field):
    for key in FIELD_ALIASES[field]:
        if key in row and str(row[key]).strip():
            return str(row[key]).strip()
    return ""


def normalize_region(address, area_name=""):
    """공급위치 주소에서 앱이 쓰는 시군구 이름을 만든다.

    `경기도 수원시 영통구 ...` → `수원영통구`
    `서울특별시 노원구 ...`     → `노원구`
    `경기도 평택시 ...`        → `평택시`
    """
    text = re.sub(r"\s+", " ", str(address or "").strip())
    if not text:
        return "", ""
    tokens = text.split(" ")
    sido = tokens[0] if tokens else ""
    if not re.search(r"(특별시|광역시|특별자치시|특별자치도|도)$", sido):
        sido = str(area_name or "").strip()
        rest = tokens
    else:
        rest = tokens[1:]

    # 실재하는 시·군·구 이름은 가장 긴 것도 4자다(영등포구, 미추홀구, 부산진구).
    # 이 제한이 없으면 `고덕강일 공공주택지구` 같은 사업지구명이 자치구로 잡힌다.
    def _pick_token(suffix):
        return next(
            (t for t in rest if t.endswith(suffix) and 2 <= len(t) <= 4),
            "",
        )

    city = _pick_token("시")
    district = _pick_token("구")
    county = _pick_token("군")

    if sido == "서울특별시":
        return sido, district or county
    if sido.startswith("세종"):
        # 세종은 시군구 없이 동으로 바로 내려간다. 시 전체를 한 단위로 본다.
        return sido, "세종시"
    if city and city in MERGED_CITY_DISTRICTS and district:
        return sido, f"{city[:-1]}{district}"
    if city:
        return sido, city
    if district or county:
        prefix = METRO_SHORT.get(sido, "")
        return sido, f"{prefix}{district or county}"
    return sido, ""


def _legal_dong(address):
    for token in re.sub(r"\s+", " ", str(address or "")).split(" "):
        if token.endswith(("동", "읍", "면")) and len(token) >= 2:
            return token
    return ""


def _month(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 6:
        year, month = digits[:4], digits[4:6]
        if "1" <= month <= "12" or month in {"01", "02", "03", "04", "05", "06",
                                             "07", "08", "09", "10", "11", "12"}:
            return f"{year}-{month}"
    return ""


def fetch_page(key, page, page_size=PAGE_SIZE):
    url = f"{ENDPOINT}?" + urllib.parse.urlencode(
        {"page": page, "perPage": page_size, "serviceKey": key}
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all(key, page_size=PAGE_SIZE, max_pages=MAX_PAGES, verbose=True, budget=None):
    """전체 수집. budget을 주면 그 레코드 수에서 멈춘다.

    공공데이터포털 개발계정은 하루 1,000건이다. 여기서 세는 단위는 호출 수가
    아니라 레코드 수라서, 2,800건을 한 번에 받으면 그날 한도가 끝난다.
    한도를 넘기면 오류가 아니라 `totalCount: 0`에 빈 배열이 돌아온다.
    그래서 응답이 비었을 때 `데이터 없음`으로 오해하지 않도록 따로 알린다.
    """
    rows = []
    for page in range(1, max_pages + 1):
        if budget is not None and len(rows) >= budget:
            if verbose:
                print(f"  일일 한도({budget}건)에 맞춰 중단했습니다.")
            break
        size = page_size
        if budget is not None:
            size = max(1, min(page_size, budget - len(rows)))
        payload = fetch_page(key, page, size)
        chunk = payload.get("data") or []
        total = payload.get("totalCount")
        if page == 1 and not chunk and not total:
            raise QuotaExhausted(
                "totalCount 0 · 빈 응답입니다. 데이터가 없는 게 아니라 "
                "개발계정 일일 트래픽(1,000건)을 소진했을 가능성이 큽니다."
            )
        rows.extend(chunk)
        if verbose:
            print(f"  page {page}: {len(chunk)}건 (누적 {len(rows)}/{total})")
        if not chunk or (total and len(rows) >= total):
            break
    return rows


class QuotaExhausted(RuntimeError):
    """일일 트래픽 소진. 빈 응답을 '물량 없음'으로 오해하면 안 된다."""


def merge_with_existing(records, path=None):
    """기존 CSV와 합친다. 같은 단지·지역·입주월은 새 값으로 덮어쓴다.

    한도 때문에 나눠 받을 때 이전 수집분이 사라지면 안 된다.
    """
    path = Path(path or OUTPUT_PATH)
    existing = []
    if path.exists():
        with path.open(encoding="utf-8-sig") as handle:
            existing = list(csv.DictReader(handle))

    def key_of(row):
        notice = str(row.get("공고번호") or "").strip()
        if notice:
            return ("notice", notice)
        # 공고번호가 없던 예전 수집분은 세대수까지 넣어 충돌을 줄인다.
        name = re.sub(r"[^0-9A-Za-z가-힣]", "", str(row.get("대표단지명") or ""))
        region = row.get("자치구") or row.get("시군구") or ""
        return ("fallback", name, region, row.get("입주예정월"), str(row.get("세대수") or ""))

    merged = {key_of(row): row for row in existing}
    added = 0
    for row in records:
        if key_of(row) not in merged:
            added += 1
        merged[key_of(row)] = row
    return list(merged.values()), added, len(existing)


def to_records(raw_rows):
    """API 원본을 supply_forecast 가 읽는 형태로 바꾼다."""
    records = []
    skipped = {"no_month": 0, "no_households": 0, "no_region": 0}
    for row in raw_rows:
        month = _month(_pick(row, "moveIn"))
        households = re.sub(r"\D", "", _pick(row, "households"))
        address = _pick(row, "address")
        sido, region = normalize_region(address, _pick(row, "area"))
        if not month:
            skipped["no_month"] += 1
            continue
        if not households or households == "0":
            skipped["no_households"] += 1
            continue
        if not region:
            skipped["no_region"] += 1
            continue
        is_seoul = sido == "서울특별시"
        records.append(
            {
                "공고번호": _pick(row, "noticeNo"),
                "시도": sido,
                "자치구": region if is_seoul else "",
                "시군구": "" if is_seoul else region,
                "법정동": _legal_dong(address),
                "대표단지명": _pick(row, "name"),
                "세대수": households,
                "상태": "입주예정",
                "입주예정월": month,
                "출처": "청약홈 분양정보 오픈API",
            }
        )
    return records, skipped


def write_csv(records, path=None):
    path = Path(path or OUTPUT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    return path


def main():
    parser = argparse.ArgumentParser(description="청약홈 전국 입주 예정 물량 수집")
    parser.add_argument("--dry-run", action="store_true", help="첫 페이지만 받아 응답 확인")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument(
        "--budget",
        type=int,
        default=900,
        help="이번 실행에서 받을 최대 레코드 수. 개발계정 일일 한도(1000)보다 낮게 잡는다. "
             "0을 주면 제한 없이 받는다.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="기존 CSV를 합치지 않고 통째로 갈아엎는다.",
    )
    args = parser.parse_args()

    key = service_key()
    if not key:
        print("청약홈 API 키가 없습니다.")
        print(f"  1) {DATA_PORTAL_URL} 에서 활용신청")
        print("  2) 설정.txt 에 `청약홈키` 또는 `공공데이터키` 추가")
        return 1

    try:
        first = fetch_page(key, 1, 5 if args.dry_run else args.page_size)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            print("401 Unauthorized — 키는 있지만 이 API에 활용신청이 안 되어 있습니다.")
            print(f"  {DATA_PORTAL_URL} 에서 활용신청하세요. 보통 자동승인이고 1~2시간 뒤 사용 가능합니다.")
        else:
            print(f"HTTP {error.code}: {error.reason}")
        return 1

    if args.dry_run:
        print(f"응답 OK · totalCount = {first.get('totalCount')}")
        sample = (first.get("data") or [{}])[0]
        print(f"필드 {len(sample)}개:")
        for key_name, value in list(sample.items())[:30]:
            print(f"  {key_name:28} {str(value)[:40]}")
        records, skipped = to_records(first.get("data") or [])
        print(f"\n변환 결과 {len(records)}건, 제외 {skipped}")
        for record in records[:3]:
            print(f"  {record['시도']} {record['자치구'] or record['시군구']} "
                  f"{record['대표단지명']} {record['입주예정월']} {record['세대수']}세대")
        return 0

    print("전국 청약홈 분양정보 수집 중...")
    try:
        raw = fetch_all(
            key,
            args.page_size,
            args.max_pages,
            budget=args.budget or None,
        )
    except QuotaExhausted as error:
        print(f"\n{error}")
        print("  · 마이페이지 > 데이터활용 > Open API > 활용신청 현황에서 트래픽을 확인하세요.")
        print("  · 한도는 매일 자정에 초기화됩니다. 내일 다시 실행하면 됩니다.")
        print("  · 기존 CSV는 그대로 두었습니다. 리포트와 점수는 계속 동작합니다.")
        return 1

    records, skipped = to_records(raw)
    if args.replace:
        final, added, before = records, len(records), 0
    else:
        final, added, before = merge_with_existing(records, args.output)
    path = write_csv(final, args.output)

    regions = {r["자치구"] or r["시군구"] for r in final}
    total = sum(int(r["세대수"]) for r in final if str(r["세대수"]).isdigit())
    print(f"\n이번 수신 {len(raw)}건 → 사용 {len(records)}건 (신규 {added}건)")
    print(f"제외: 입주예정월 없음 {skipped['no_month']}, "
          f"세대수 없음 {skipped['no_households']}, 지역 파싱 실패 {skipped['no_region']}")
    print(f"누적 {before}건 → {len(final)}건 · 시군구 {len(regions)}곳 · 총 {total:,}세대")
    print(f"저장 → {path}")
    if args.budget and len(raw) >= args.budget:
        print("\n한도에 걸려 일부만 받았을 수 있습니다. 내일 같은 명령을 다시 실행하면")
        print("기존 데이터에 이어서 합쳐집니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
