#!/usr/bin/env python3
"""집픽 지역 커버리지 스캔.

`후보 0곳`은 리포트가 아니라 환불 사유다. 주문을 받기 전에 어느 지역이
어느 예산부터 후보를 내놓는지 미리 알아야 상품 페이지에서 걸러낼 수 있다.

    python3 수익화/coverage_scan.py            # 이어서 실행 (완료된 건 건너뜀)
    python3 수익화/coverage_scan.py --limit 20 # 이번 실행에서 20건만
    python3 수익화/coverage_scan.py --report   # 호출 없이 결과만 다시 출력

결과: 수익화/coverage.json (원본) · 수익화/coverage.md (요약표)
"""

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import generate_report as gr  # noqa: E402

RAW_PATH = ROOT / "coverage.json"
MD_PATH = ROOT / "coverage.md"

# 실제로 주문이 들어올 만한 곳만 본다. 전국을 다 도는 건 의미가 없다.
REGIONS = [
    # 서울 25구
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구",
    "금천구", "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구",
    "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구",
    "은평구", "종로구", "중구", "중랑구",
    # 경기 · 인천 주요
    "고양덕양구", "고양일산동구", "고양일산서구", "광명시", "구리시",
    "김포시", "남양주시", "부천시", "성남분당구", "성남수정구", "수원영통구",
    "수원장안구", "안양동안구", "용인수지구", "의정부시", "하남시", "화성시",
    "인천연수구", "인천서구", "인천남동구", "인천부평구", "인천미추홀구",
]

# 주의: /api/budget-candidates 의 budget 파라미터만 바꿔서는 결과가 바뀌지 않는다.
# 서버가 프로필(자기자금·소득)로 매수 상한을 다시 계산하기 때문이다.
# 그래서 스캔 축은 예산이 아니라 `자기자금`이어야 한다.
PROFILES = [
    ("소액", 3, 7000),      # 자기자금 3억 · 연 7,000만원
    ("중간", 7, 12000),     # 자기자금 7억 · 연 1.2억
    ("고액", 12, 20000),    # 자기자금 12억 · 연 2억
]

# 스캔용 표준 프로필. 실제 주문서와 같은 파라미터 형태를 쓴다.
BASE_ORDER = {
    "보유주택": "no_home",
    "생애최초": True,
    "자기자금_억": 3,
    "연소득_만원": 7000,
    "월대출상환_만원": 0,
    "배우자합산": False,
    "예상금리": 4.2,
    "대출기간": 30,
    "부대비용률": 3,
    "매수목적": "live",
    "가격전략": "stretch",
    "희망평형": 59,
}


def order_for(cash, income):
    order = dict(BASE_ORDER)
    order["자기자금_억"] = cash
    order["연소득_만원"] = income
    return order


def load():
    if RAW_PATH.exists():
        return json.loads(RAW_PATH.read_text(encoding="utf-8"))
    return {}


def save(data):
    """임시 파일에 쓰고 교체한다. 중간에 죽어도 원본이 깨지지 않는다."""
    tmp = RAW_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RAW_PATH)


_BUDGET_CACHE = {}


def budget_for(tier, cash, income):
    """프로필별 매수 가능 상한. 지역과 무관하므로 한 번만 계산한다."""
    if tier not in _BUDGET_CACHE:
        power = gr.fetch_purchase_power(order_for(cash, income))
        _BUDGET_CACHE[tier] = power.get("budgetEok")
    return _BUDGET_CACHE[tier]


def probe(region, tier, cash, income, attempts=4):
    """429는 실패가 아니라 대기 신호다. 실패로 기록하면 `데이터 없음`으로 오독된다."""
    order = order_for(cash, income)
    budget = budget_for(tier, cash, income)
    last = None
    for attempt in range(attempts):
        try:
            payload = gr.fetch_candidates(order, region, budget)
            break
        except Exception as exc:
            last = exc
            if "429" not in str(exc) or attempt == attempts - 1:
                return {
                    "region": region,
                    "tier": tier,
                    "cash": cash,
                    "count": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            time.sleep(2 ** attempt + random.random() * 2)
    else:
        return {
            "region": region,
            "tier": tier,
            "cash": cash,
            "count": None,
            "error": f"{type(last).__name__}: {last}",
        }
    try:
        candidates = payload.get("candidates") or []
        return {
            "region": region,
            "tier": tier,
            "cash": cash,
            "budget": budget,
            "count": len(candidates),
            "seed": payload.get("liveSeedCount"),
            "filter": payload.get("filterSummary") or {},
            "top": (candidates[0].get("displayName") if candidates else None),
        }
    except Exception as exc:  # 한 지역이 죽어도 스캔 전체를 멈추지 않는다
        return {
            "region": region,
            "tier": tier,
            "cash": cash,
            "count": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def scan(limit=None, workers=8):
    data = load()
    for tier, cash, income in PROFILES:
        budget_for(tier, cash, income)
    # 실패로 남은 건은 결과가 아니다. 지우고 다시 돈다.
    for key in [k for k, v in list(data.items()) if v.get("error")]:
        data.pop(key)
    todo = [
        (region, tier, cash, income)
        for region in REGIONS
        for tier, cash, income in PROFILES
        if f"{region}|{tier}" not in data
    ]
    if limit:
        todo = todo[:limit]
    print(f"남은 {len(todo)}건 · 동시 {workers}개로 스캔", flush=True)
    if not todo:
        return data

    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe, r, t, c, i): (r, t) for r, t, c, i in todo
        }
        for future in as_completed(futures):
            region, tier = futures[future]
            row = future.result()
            data[f"{region}|{tier}"] = row
            done += 1
            save(data)  # 중간에 끊겨도 다음 실행에서 이어서 돈다
            mark = "x" if row.get("count") in (0, None) else "o"
            print(
                f"  [{done}/{len(todo)}] {mark} {region} {tier} "
                f"→ {row.get('count')}곳",
                flush=True,
            )
    print(f"{done}건 완료 ({time.time() - started:.0f}s)", flush=True)
    return data


def report(data):
    """지역별로 후보가 열리는 최소 자기자금을 뽑는다."""
    by_region = {}
    for row in data.values():
        by_region.setdefault(row["region"], {})[row.get("tier")] = row

    tiers = [t for t, _, _ in PROFILES]
    supported, conditional, no_data, too_pricey, failed = [], [], [], [], []
    header = " | ".join(
        f"{t}(자기자금 {c}억)" for t, c, _ in PROFILES
    )
    lines = [f"| 지역 | {header} | 판정 |", "|---|" + "---|" * (len(tiers) + 1)]

    for region in REGIONS:
        rows = by_region.get(region)
        if not rows:
            continue
        counts = [rows.get(t, {}).get("count") for t in tiers]
        seed = next(
            (rows[t].get("seed") for t in tiers if rows.get(t, {}).get("seed") is not None),
            None,
        )
        cells = " | ".join("-" if c is None else f"{c}곳" for c in counts)
        opened = [t for t, c in zip(tiers, counts) if c]
        # 호출이 실패한 건은 `후보 0곳`이 아니다. 섞으면 없는 지역을 만들어낸다.
        errored = [t for t in tiers if rows.get(t, {}).get("error")]
        if errored and not opened:
            verdict = "측정 실패(재스캔 필요)"
            failed.append(region)
        elif not opened and not seed:
            verdict = "**데이터 없음**"
            no_data.append(region)
        elif not opened:
            verdict = "**전 구간 0곳**"
            too_pricey.append(region)
        elif opened[0] == tiers[0]:
            verdict = "지원"
            supported.append(region)
        else:
            cash = dict((t, c) for t, c, _ in PROFILES)[opened[0]]
            verdict = f"자기자금 {cash}억~"
            conditional.append((region, cash))
        lines.append(f"| {region} | {cells} | {verdict} |")

    budgets = ", ".join(
        f"{t} {_BUDGET_CACHE.get(t) or by_region and '?'}억" for t in tiers
    )
    summary = [
        "# 집픽 지역 커버리지",
        "",
        f"스캔 기준: 무주택·생애최초·전용 59㎡ · 총 {len(data)}건 호출",
        "",
        "> 주의: `/api/budget-candidates`의 budget 파라미터만 바꾸면 결과가 바뀌지 않는다.",
        "> 서버가 프로필(자기자금·소득)로 매수 상한을 다시 계산하기 때문이다.",
        "> 그래서 이 스캔의 축은 예산이 아니라 자기자금이다.",
        "",
        f"- 전 구간 지원: {len(supported)}곳",
        f"- 자기자금 조건부: {len(conditional)}곳",
        f"- **단지 데이터 자체가 없음: {len(no_data)}곳**",
        f"- **자기자금 12억에도 후보 0곳: {len(too_pricey)}곳**",
        f"- 측정 실패(재스캔 필요): {len(failed)}곳",
        "",
    ]
    if no_data:
        summary += [
            "## 데이터가 없어 주문을 받으면 안 되는 지역",
            "",
            ", ".join(no_data),
            "",
            "단지 목록 CSV에 해당 지역이 없습니다. 상품 페이지에서 빼세요.",
            "",
        ]
    if too_pricey:
        summary += [
            "## 전용 59㎡ 기준 후보가 열리지 않는 지역",
            "",
            ", ".join(too_pricey),
            "",
            "데이터는 있으나 시세가 스캔한 최고 구간을 넘습니다. "
            "더 넓은 평형이나 더 높은 자기자금에서는 열릴 수 있습니다.",
            "",
        ]
    if conditional:
        summary += [
            "## 최소 자기자금 조건을 표기해야 할 지역",
            "",
            ", ".join(f"{r}(자기자금 {c}억~)" for r, c in conditional),
            "",
        ]
    summary += ["## 전체", ""] + lines + [""]
    MD_PATH.write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary[:16]))
    print(f"\n저장: {MD_PATH}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    data = load() if args.report else scan(args.limit, args.workers)
    if data:
        report(data)


if __name__ == "__main__":
    main()
