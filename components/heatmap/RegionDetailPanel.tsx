"use client";

import type {
  HeatComparisonPeriod,
  RegionSnapshot
} from "@/lib/heatmap/types";
import type { SpreadRoute } from "@/lib/heatmap/types";
import {
  formatRate,
  getIncomingSpreadRoutes,
  getOutgoingSpreadRoutes,
  getRateChangeForWeeks,
  getRateWeeksAgo,
  getHeatBadgeClass,
  getHeatTextClass
} from "@/lib/heatmap/utils";
import { cn } from "@/lib/utils";

type RegionDetailPanelProps = {
  region: RegionSnapshot;
  routes: SpreadRoute[];
  regionNameById: Map<string, string>;
  selectedPeriod: HeatComparisonPeriod;
  rank: number;
  periodRank: number;
  totalRegions: number;
  onViewSpread: () => void;
};

const metricLabels = [
  {
    key: "volumeStrength",
    label: "2년 상승 강도",
    weight: "장기",
    description: "시작 시점보다 흐름이 얼마나 강해졌는지 봐요."
  },
  {
    key: "priceRiseRatio",
    label: "최근 변화 강도",
    weight: "선택 기간",
    description: "선택한 기간 안에서 새로 강해진 정도예요."
  },
  {
    key: "risingComplexRatio",
    label: "흐름 지속성",
    weight: "안정성",
    description: "한 번 오른 뒤 흐름이 이어졌는지 봐요."
  }
] as const;

function getPriceIndex(changeRate: number) {
  return Math.max(0, 100 + changeRate);
}

function getSampleStability(sampleCount?: number) {
  if (!sampleCount) {
    return {
      label: "확인 필요",
      body: "표본 수를 확인한 뒤 봐야 해요.",
      className: "text-slate-600"
    };
  }

  if (sampleCount >= 300) {
    return {
      label: "안정",
      body: "거래 표본이 충분한 편이에요.",
      className: "text-emerald-700"
    };
  }

  if (sampleCount >= 100) {
    return {
      label: "보통",
      body: "큰 흐름은 볼 수 있어요.",
      className: "text-orange-700"
    };
  }

  return {
    label: "주의",
    body: "거래가 적어 해석에 주의해야 해요.",
    className: "text-red-700"
  };
}

export function RegionDetailPanel({
  onViewSpread,
  periodRank,
  rank,
  region,
  regionNameById,
  routes,
  selectedPeriod,
  totalRegions
}: RegionDetailPanelProps) {
  const periodRateAgo = getRateWeeksAgo(region, selectedPeriod.weeks);
  const periodRateChange = getRateChangeForWeeks(region, selectedPeriod.weeks);
  const changeIsUp = periodRateChange > 0;
  const incomingRoutes = getIncomingSpreadRoutes(routes, region.id);
  const outgoingRoutes = getOutgoingSpreadRoutes(routes, region.id);
  const priceIndex = getPriceIndex(region.changeRate);
  const stability = getSampleStability(region.dataSource?.sampleCount);

  return (
    <aside className="rounded-lg border border-zippick-line bg-white p-6 shadow-panel">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[14px] font-semibold text-zippick-muted">
            선택 지역
          </p>
          <h2 className="mt-1 text-[28px] font-bold text-zippick-ink">
            {region.name}
          </h2>
        </div>
        <span
          className={cn(
            "rounded-md border px-3 py-2 text-[14px] font-bold",
            getHeatBadgeClass(region.score)
          )}
        >
          {region.state}
        </span>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-slate-50 p-4">
          <p className="text-[13px] font-semibold text-zippick-muted">
            현재 상승 흐름
          </p>
          <p
            className={cn(
              "mt-2 text-[38px] font-bold leading-none",
              getHeatTextClass(region.score)
            )}
          >
            {rank || "-"}위
          </p>
          <p className="mt-2 text-[13px] font-medium text-zippick-muted">
            전체 {totalRegions}개 구 중 · 근거 {formatRate(region.changeRate)}
          </p>
        </div>
        <div className="rounded-lg bg-slate-50 p-4">
          <p className="text-[13px] font-semibold text-zippick-muted">
            최근 {selectedPeriod.label} 흐름
          </p>
          <p
            className={cn(
              "mt-2 text-[28px] font-bold",
              changeIsUp ? "text-orange-700" : "text-slate-600"
            )}
          >
            {periodRank || "-"}위
          </p>
          <p className="mt-2 text-[13px] font-medium text-zippick-muted">
            근거 {formatRate(periodRateChange)} · 이전 {formatRate(periodRateAgo)}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-zippick-line bg-white p-4">
        <h3 className="text-[16px] font-bold text-zippick-ink">
          숫자는 이렇게 봐요
        </h3>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md bg-slate-50 px-3 py-3">
            <p className="text-[13px] font-semibold text-zippick-muted">
              2년 지수
            </p>
            <p className="mt-1 text-[18px] font-bold text-zippick-ink">
              {priceIndex.toFixed(1)}
            </p>
            <p className="mt-1 text-[12px] text-zippick-muted">시작 100</p>
          </div>
          <div className="rounded-md bg-slate-50 px-3 py-3">
            <p className="text-[13px] font-semibold text-zippick-muted">
              선택 기간
            </p>
            <p className="mt-1 text-[18px] font-bold text-zippick-ink">
              {formatRate(periodRateChange)}
            </p>
            <p className="mt-1 text-[12px] text-zippick-muted">
              {selectedPeriod.label}
            </p>
          </div>
          <div className="rounded-md bg-orange-50 px-3 py-3">
            <p className="text-[13px] font-semibold text-orange-700">
              표본 안정성
            </p>
            <p className={cn("mt-1 text-[18px] font-bold", stability.className)}>
              {stability.label}
            </p>
            <p className="mt-1 text-[12px] text-zippick-muted">
              {region.dataSource?.sampleCount.toLocaleString("ko-KR") ?? "-"}건
            </p>
          </div>
        </div>
        <p className="mt-3 text-[13px] leading-5 text-zippick-muted">
          지도 순위는 보기 쉽게 만든 비교값이에요. 실제 판단은 지수, 최근 변화,
          거래 표본을 같이 봐야 해요.
        </p>
      </div>

      <div className="mt-6">
        <h3 className="text-[17px] font-bold text-zippick-ink">
          가격 흐름은 이렇게 봐요
        </h3>
        <div className="mt-4 grid gap-4">
          {metricLabels.map((metric) => {
            const value = region.metrics[metric.key];

            return (
              <div key={metric.key}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[14px] font-semibold text-zippick-body">
                      {metric.label}
                      <span className="ml-2 text-[13px] text-zippick-muted">
                        {metric.weight}
                      </span>
                    </p>
                    <p className="mt-1 text-[13px] leading-5 text-zippick-muted">
                      {metric.description}
                    </p>
                  </div>
                  <strong className="text-[15px] text-zippick-ink">
                    {value}
                  </strong>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-orange-500"
                    style={{ width: `${value}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-7 rounded-lg border border-slate-200 bg-slate-50 p-4">
        <h3 className="text-[17px] font-bold text-zippick-ink">
          이 지역에서 보이는 신호
        </h3>
        <ul className="mt-3 grid gap-2 text-[14px] leading-6 text-zippick-body">
          {region.reasons.map((reason) => (
            <li className="flex gap-2" key={reason}>
              <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-orange-500" />
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      </div>

      {region.dataSource && (
        <div className="mt-4 rounded-lg border border-zippick-line bg-white p-4">
          <h3 className="text-[16px] font-bold text-zippick-ink">
            데이터 기준
          </h3>
          <p className="mt-2 text-[14px] leading-6 text-zippick-body">
            {region.dataSource.label}을 구 단위로 묶었어요.
          </p>
          <p className="mt-2 text-[13px] leading-5 text-zippick-muted">
            표본 {region.dataSource.sampleCount.toLocaleString("ko-KR")}건 · 단지{" "}
            {region.dataSource.complexCount.toLocaleString("ko-KR")}개 · 최근 거래일{" "}
            {region.dataSource.basisDate || "확인 전"}
          </p>
          <p className="mt-1 text-[13px] leading-5 text-zippick-muted">
            {stability.body}
          </p>
        </div>
      )}

      {(incomingRoutes.length > 0 || outgoingRoutes.length > 0) && (
        <div className="mt-6 rounded-lg border border-orange-200 bg-orange-50 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-[17px] font-bold text-zippick-ink">
                번지는 흐름과 연결
              </h3>
              <p className="mt-1 text-[13px] leading-5 text-zippick-body">
                이 지역을 중심으로 앞뒤 흐름을 같이 봐요.
              </p>
            </div>
            <button
              className="shrink-0 text-[12px] font-bold text-orange-700 underline decoration-orange-200 underline-offset-4"
              onClick={onViewSpread}
              type="button"
            >
              지도에서 보기
            </button>
          </div>
          <div className="mt-3 grid gap-2">
            {incomingRoutes.slice(0, 2).map((route) => (
              <div
                className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2"
                key={route.id}
              >
                <span className="text-[13px] font-bold text-zippick-ink">
                  {regionNameById.get(route.from)} → {region.name}
                </span>
                <span className="text-[12px] font-semibold text-orange-700">
                  이어짐
                </span>
              </div>
            ))}
            {outgoingRoutes.slice(0, 2).map((route) => (
              <div
                className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2"
                key={route.id}
              >
                <span className="text-[13px] font-bold text-zippick-ink">
                  {region.name} → {regionNameById.get(route.to)}
                </span>
                <span className="text-[12px] font-semibold text-slate-500">
                  다음 흐름
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-6">
        <h3 className="text-[17px] font-bold text-zippick-ink">
          다음에 같이 볼 지역
        </h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {region.linkedRegions.map((name) => (
            <span
              className="rounded-md border border-zippick-line bg-white px-3 py-2 text-[14px] font-semibold text-zippick-body"
              key={name}
            >
              {name}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
        <h3 className="text-[16px] font-bold text-zippick-ink">
          다음 확인
        </h3>
        <p className="mt-2 text-[14px] leading-6 text-zippick-body">
          이 화면은 탐색용이에요. 실제 매수 판단은 지역 상세, 단지 거래,
          대출 조건을 같이 확인해야 해요.
        </p>
      </div>
    </aside>
  );
}
