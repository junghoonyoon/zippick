"use client";

import { useEffect, useMemo, useState } from "react";
import { HeatDefinitionCard } from "@/components/heatmap/HeatDefinitionCard";
import { HeatmapHeader } from "@/components/heatmap/HeatmapHeader";
import { HeatmapTabs } from "@/components/heatmap/HeatmapTabs";
import { PeriodSelector } from "@/components/heatmap/PeriodSelector";
import { RegionDetailPanel } from "@/components/heatmap/RegionDetailPanel";
import { SeoulMap } from "@/components/heatmap/SeoulMap";
import { SpreadLegend } from "@/components/heatmap/SpreadLegend";
import type {
  HeatmapTab,
  HeatComparisonPeriod,
  HeatRegion,
  RegionSnapshot,
  RegionMapShape,
  SpreadRoute,
  TimelineWeek
} from "@/lib/heatmap/types";
import {
  formatRate,
  getIncomingSpreadRoutes,
  getPeriodSpreadRoutes,
  getRateChangeForWeeks,
  getRegionSnapshot,
  getRegionsForWeek
} from "@/lib/heatmap/utils";

const comparisonPeriods: HeatComparisonPeriod[] = [
  { label: "1개월", shortLabel: "1개월 전", weeks: 4 },
  { label: "3개월", shortLabel: "3개월 전", weeks: 12 },
  { label: "6개월", shortLabel: "6개월 전", weeks: 24 },
  { label: "2년", shortLabel: "2년 전", weeks: 104 }
];

type HeatmapPageData = {
  heatmapWeeks: TimelineWeek[];
  heatRegions: HeatRegion[];
  regionMapShapes: RegionMapShape[];
  spreadRoutes: SpreadRoute[];
  sourceLabel: string;
};

type HeatmapPageProps = {
  initialData: HeatmapPageData;
};

const tabGuides: Record<
  HeatmapTab,
  {
    title: string;
    body: (period: HeatComparisonPeriod) => string;
    metric: (period: HeatComparisonPeriod) => string;
  }
> = {
  current: {
    title: "현재 상승 흐름 순위",
    body: () =>
      "지도 숫자는 2년 시작 대비 많이 오른 순서예요. 색이 진할수록 상승 흐름이 강해요.",
    metric: () => "지도 숫자 = 순위"
  },
  change: {
    title: "최근 상승 흐름 순위",
    body: (period) =>
      `${period.shortLabel}보다 더 오른 순서예요. 짧은 기간에 새로 강해진 곳을 봐요.`,
    metric: (period) => `지도 숫자 = ${period.label} 순위`
  },
  spread: {
    title: "가격 상승 흐름",
    body: () =>
      "㎡당 중간 거래가가 먼저 오른 구와 뒤따라 오른 구를 화살표로 함께 봐요.",
    metric: () => "지도 표시: 화살표 방향"
  },
  candidate: {
    title: "다음 관심 지역",
    body: (period) =>
      `앞 지역의 가격 흐름과 ${period.label} 변화를 함께 볼 만한 지역을 정리했어요.`,
    metric: () => "순위 + 연결된 흐름"
  }
};

function getRankByRate(
  regions: RegionSnapshot[],
  rateGetter: (region: RegionSnapshot) => number
) {
  return new Map(
    [...regions]
      .sort((a, b) => rateGetter(b) - rateGetter(a))
      .map((region, index) => [region.id, index + 1])
  );
}

export function HeatmapPage({ initialData }: HeatmapPageProps) {
  const { heatmapWeeks, heatRegions, regionMapShapes, sourceLabel, spreadRoutes } =
    initialData;
  const [selectedRegionId, setSelectedRegionId] = useState("gangnam");
  const [activeTab, setActiveTab] = useState<HeatmapTab>("current");
  const [weekIndex, setWeekIndex] = useState(heatmapWeeks.length - 1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [comparisonWeeks, setComparisonWeeks] = useState(4);

  useEffect(() => {
    if (!isPlaying || activeTab !== "spread") return;

    const timer = window.setInterval(() => {
      setWeekIndex((current) =>
        current >= heatmapWeeks.length - 1 ? 0 : current + 1
      );
    }, 1100);

    return () => window.clearInterval(timer);
  }, [activeTab, heatmapWeeks.length, isPlaying]);

  const handleTabChange = (nextTab: HeatmapTab) => {
    setActiveTab(nextTab);
    if (nextTab !== "spread") {
      setIsPlaying(false);
    }
  };

  const regionSnapshots = useMemo(
    () => getRegionsForWeek(heatRegions, weekIndex),
    [weekIndex]
  );

  const selectedRegion = useMemo(() => {
    const baseRegion =
      heatRegions.find((region) => region.id === selectedRegionId) ??
      heatRegions[0];
    return getRegionSnapshot(baseRegion, weekIndex);
  }, [selectedRegionId, weekIndex]);

  const regionNameById = useMemo(
    () => new Map(heatRegions.map((region) => [region.id, region.name])),
    []
  );
  const selectedPeriod =
    comparisonPeriods.find((period) => period.weeks === comparisonWeeks) ??
    comparisonPeriods[0];
  const rankById = useMemo(
    () => getRankByRate(regionSnapshots, (region) => region.changeRate),
    [regionSnapshots]
  );
  const periodRankById = useMemo(
    () =>
      getRankByRate(regionSnapshots, (region) =>
        getRateChangeForWeeks(region, comparisonWeeks)
      ),
    [comparisonWeeks, regionSnapshots]
  );
  const periodSpreadRoutes = useMemo(
    () => getPeriodSpreadRoutes(spreadRoutes, regionSnapshots, selectedPeriod),
    [regionSnapshots, selectedPeriod, spreadRoutes]
  );
  const nextCandidateSnapshots = useMemo(
    () =>
      [...regionSnapshots]
        .sort((a, b) => {
          const incomingA = getIncomingSpreadRoutes(periodSpreadRoutes, a.id)[0];
          const incomingB = getIncomingSpreadRoutes(periodSpreadRoutes, b.id)[0];
          const strengthA = incomingA?.strength ?? 0;
          const strengthB = incomingB?.strength ?? 0;

          return (
            strengthB +
            getRateChangeForWeeks(b, comparisonWeeks) -
            (strengthA + getRateChangeForWeeks(a, comparisonWeeks))
          );
        })
        .slice(0, 5)
        .map((snapshot) => ({
          candidate: snapshot,
          snapshot
        })),
    [comparisonWeeks, periodSpreadRoutes, regionSnapshots]
  );
  const candidateRegionIds = useMemo(
    () => nextCandidateSnapshots.map(({ candidate }) => candidate.id),
    [nextCandidateSnapshots]
  );

  return (
    <main className="min-h-screen bg-zippick-canvas px-5 py-8 lg:px-8 lg:py-10">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-7">
        <HeatmapHeader
          periodLabel={selectedPeriod.label}
          sourceLabel={sourceLabel}
          weekLabel={heatmapWeeks[weekIndex].label}
        />
        <HeatDefinitionCard />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <section className="flex min-w-0 flex-col gap-4">
            <HeatmapTabs activeTab={activeTab} onChange={handleTabChange} />
            <PeriodSelector
              onChange={setComparisonWeeks}
              periods={comparisonPeriods}
              selectedWeeks={comparisonWeeks}
            />
            <div className="flex flex-col gap-3 rounded-lg border border-zippick-line bg-white px-5 py-4 shadow-sm md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-[18px] font-bold text-zippick-ink">
                  {tabGuides[activeTab].title}
                </h2>
                <p className="mt-1 text-[14px] leading-6 text-zippick-body">
                  {tabGuides[activeTab].body(selectedPeriod)}
                </p>
              </div>
              <span className="w-fit rounded-md bg-orange-50 px-3 py-2 text-[13px] font-bold text-orange-700">
                {tabGuides[activeTab].metric(selectedPeriod)}
              </span>
            </div>
            <SeoulMap
              activeTab={activeTab}
              candidateRegionIds={candidateRegionIds}
              comparisonPeriod={selectedPeriod}
              currentWeekIndex={weekIndex}
              isPlaying={isPlaying}
              onRegionSelect={setSelectedRegionId}
              onPlayToggle={() => setIsPlaying((current) => !current)}
              onWeekChange={(nextWeekIndex) => {
                setWeekIndex(nextWeekIndex);
                setIsPlaying(false);
              }}
              periodRankById={periodRankById}
              rankById={rankById}
              regions={regionSnapshots}
              routes={periodSpreadRoutes}
              selectedRegionId={selectedRegionId}
              shapes={regionMapShapes}
              weeks={heatmapWeeks}
            />
            {activeTab === "spread" && (
              <SpreadLegend routes={periodSpreadRoutes} regions={heatRegions} />
            )}

            {activeTab === "candidate" && (
              <section className="rounded-lg border border-zippick-line bg-white p-5 shadow-panel">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-[18px] font-bold text-zippick-ink">
                      다음 관심 지역
                    </h2>
                    <p className="mt-1 text-[14px] leading-6 text-zippick-body">
                      번지는 흐름과 실제 상승률을 함께 보고 먼저 볼 지역을 골라요.
                    </p>
                  </div>
                  <span className="rounded-md bg-slate-100 px-3 py-2 text-[13px] font-bold text-zippick-body">
                    흐름 연결 상위 5곳
                  </span>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-5">
                  {nextCandidateSnapshots.map(({ candidate, snapshot }, index) => (
                    <article
                      className="rounded-lg border border-zippick-line bg-slate-50 p-4 transition hover:border-orange-300 hover:bg-orange-50"
                      key={candidate.id}
                    >
                      <button
                        className="block w-full text-left"
                        onClick={() => setSelectedRegionId(candidate.id)}
                        type="button"
                      >
                        <span className="text-[13px] font-bold text-orange-700">
                          관심 {index + 1}순위
                        </span>
                        <strong className="mt-2 block text-[18px] text-zippick-ink">
                          {candidate.name}
                        </strong>
                        <span className="mt-2 block text-[14px] font-semibold text-zippick-body">
                          현재 상승 흐름 {rankById.get(candidate.id) ?? "-"}위
                        </span>
                        <span className="mt-1 block text-[13px] text-zippick-muted">
                          근거: {selectedPeriod.shortLabel}보다{" "}
                          {formatRate(getRateChangeForWeeks(snapshot, comparisonWeeks))}
                        </span>
                      </button>
                      {(() => {
                        const incomingRoute = getIncomingSpreadRoutes(
                          periodSpreadRoutes,
                          candidate.id
                        )[0];

                        if (!incomingRoute) {
                          return (
                            <p className="mt-4 border-t border-zippick-line pt-3 text-[13px] leading-5 text-zippick-muted">
                              아직 연결된 번짐 흐름이 없어요.
                            </p>
                          );
                        }

                        return (
                          <div className="mt-4 border-t border-orange-200 pt-3">
                            <p className="text-[12px] font-bold text-orange-700">
                              번지는 흐름과 연결
                            </p>
                            <p className="mt-1 text-[13px] font-bold text-zippick-ink">
                              {regionNameById.get(incomingRoute.from)} →{" "}
                              {candidate.name}
                            </p>
                            <button
                              className="mt-2 text-[12px] font-bold text-orange-700 underline decoration-orange-200 underline-offset-4"
                              onClick={() => {
                                setSelectedRegionId(candidate.id);
                                setActiveTab("spread");
                              }}
                              type="button"
                            >
                              지도에서 흐름 보기
                            </button>
                          </div>
                        );
                      })()}
                    </article>
                  ))}
                </div>
              </section>
            )}
          </section>

          <RegionDetailPanel
            onViewSpread={() => setActiveTab("spread")}
            periodRank={periodRankById.get(selectedRegion.id) ?? 0}
            rank={rankById.get(selectedRegion.id) ?? 0}
            region={selectedRegion}
            regionNameById={regionNameById}
            routes={periodSpreadRoutes}
            selectedPeriod={selectedPeriod}
            totalRegions={regionSnapshots.length}
          />
        </div>
      </div>
    </main>
  );
}
