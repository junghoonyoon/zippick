import type {
  HeatComparisonPeriod,
  HeatRegion,
  HeatState,
  RegionHeatMetrics,
  RegionSnapshot,
  SpreadRoute
} from "@/lib/heatmap/types";

export function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function calculateHeatScore(metrics: RegionHeatMetrics) {
  return clampScore(
    metrics.volumeStrength * 0.4 +
      metrics.priceRiseRatio * 0.35 +
      metrics.risingComplexRatio * 0.25
  );
}

export function getHeatState(score: number): HeatState {
  if (score <= 34) return "냉각";
  if (score <= 49) return "관망";
  if (score <= 64) return "회복";
  if (score <= 79) return "확산";
  return "과열 주의";
}

export function getHeatFillClass(score: number) {
  if (score <= 34) return "fill-slate-200";
  if (score <= 49) return "fill-slate-300";
  if (score <= 64) return "fill-amber-200";
  if (score <= 79) return "fill-orange-300";
  return "fill-red-400";
}

export function getHeatTextClass(score: number) {
  if (score <= 34) return "text-slate-500";
  if (score <= 49) return "text-slate-600";
  if (score <= 64) return "text-amber-700";
  if (score <= 79) return "text-orange-700";
  return "text-red-700";
}

export function getHeatBadgeClass(score: number) {
  if (score <= 34) return "border-slate-200 bg-slate-100 text-slate-600";
  if (score <= 49) return "border-slate-300 bg-white text-slate-600";
  if (score <= 64) return "border-amber-200 bg-amber-50 text-amber-700";
  if (score <= 79) return "border-orange-200 bg-orange-50 text-orange-700";
  return "border-red-200 bg-red-50 text-red-700";
}

export function getRegionSnapshot(
  region: HeatRegion,
  weekIndex: number
): RegionSnapshot {
  const safeWeekIndex = Math.max(
    0,
    Math.min(region.weeklyHistory.length - 1, weekIndex)
  );
  const score = clampScore(region.weeklyHistory[safeWeekIndex]);
  const changeRate = Number(region.weeklyChangeRates?.[safeWeekIndex] ?? 0);
  const previousIndex = Math.max(0, safeWeekIndex - 4);
  const score4wAgo = clampScore(region.weeklyHistory[previousIndex]);
  const score12wAgo = clampScore(region.weeklyHistory[0]);
  const weekChange4w = score - score4wAgo;
  const weekChange12w = score - score12wAgo;
  const scoreDelta = score - region.currentScore;
  const historyRange = region.currentScore - score12wAgo;
  const historyProgress =
    historyRange === 0
      ? 1
      : Math.max(0, Math.min(1, (score - score12wAgo) / historyRange));
  const candidateScore = clampScore(
    score + (region.nextHeatCandidateScore - region.currentScore) * historyProgress
  );

  return {
    ...region,
    score,
    candidateScore,
    changeRate,
    state: getHeatState(score),
    weekIndex: safeWeekIndex,
    score4wAgo,
    score12wAgo,
    weekChange4w,
    weekChange12w,
    metrics: {
      volumeStrength: clampScore(region.volumeStrength + scoreDelta * 0.45),
      priceRiseRatio: clampScore(region.priceRiseRatio + scoreDelta * 0.35),
      risingComplexRatio: clampScore(
        region.risingComplexRatio + scoreDelta * 0.25
      )
    }
  };
}

export function getRegionsForWeek(regions: HeatRegion[], weekIndex: number) {
  return regions.map((region) => getRegionSnapshot(region, weekIndex));
}

export function formatChange(value: number) {
  if (value > 0) return `+${value}점`;
  if (value < 0) return `${value}점`;
  return "변화 없음";
}

export function formatRate(value: number) {
  if (Math.abs(value) < 0.05) return "0.0%";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function getRateWeeksAgo(region: RegionSnapshot, weeks: number) {
  const previousIndex = Math.max(0, region.weekIndex - weeks);

  return Number(region.weeklyChangeRates?.[previousIndex] ?? 0);
}

export function getRateChangeForWeeks(region: RegionSnapshot, weeks: number) {
  return region.changeRate - getRateWeeksAgo(region, weeks);
}

export function getScoreWeeksAgo(region: RegionSnapshot, weeks: number) {
  const previousIndex = Math.max(0, region.weekIndex - weeks);

  return clampScore(region.weeklyHistory[previousIndex]);
}

export function getChangeForWeeks(region: RegionSnapshot, weeks: number) {
  return region.score - getScoreWeeksAgo(region, weeks);
}

export function getTopNextCandidates(regions: HeatRegion[], limit = 5) {
  return [...regions]
    .sort((a, b) => b.nextHeatCandidateScore - a.nextHeatCandidateScore)
    .slice(0, limit);
}

export function getIncomingSpreadRoutes(
  routes: SpreadRoute[],
  regionId: string
) {
  return routes
    .filter((route) => route.to === regionId)
    .sort((a, b) => b.strength - a.strength);
}

export function getOutgoingSpreadRoutes(
  routes: SpreadRoute[],
  regionId: string
) {
  return routes
    .filter((route) => route.from === regionId)
    .sort((a, b) => b.strength - a.strength);
}

export function getPeriodSpreadRoutes(
  routes: SpreadRoute[],
  regions: RegionSnapshot[],
  period: HeatComparisonPeriod
) {
  const regionById = new Map(regions.map((region) => [region.id, region]));
  const periodRoutes: SpreadRoute[] = [];

  for (const route of routes) {
      const fromRegion = regionById.get(route.from);
      const toRegion = regionById.get(route.to);
      if (!fromRegion || !toRegion) continue;

      const lagWeeks = route.lagWeeks ?? 4;
      const startIndex = Math.max(0, toRegion.weekIndex - period.weeks);
      const leadIndex = Math.max(startIndex, toRegion.weekIndex - lagWeeks);
      const fromStartRate = Number(fromRegion.weeklyChangeRates?.[startIndex] ?? 0);
      const fromLeadRate = Number(fromRegion.weeklyChangeRates?.[leadIndex] ?? 0);
      const toStartRate = Number(toRegion.weeklyChangeRates?.[startIndex] ?? 0);
      const toCurrentRate = Number(toRegion.weeklyChangeRates?.[toRegion.weekIndex] ?? 0);
      const fromGain = fromLeadRate - fromStartRate;
      const toGain = toCurrentRate - toStartRate;
      const gainGap = Math.abs(fromGain - toGain);
      const gainBase = Math.max(1, Math.abs(fromGain), Math.abs(toGain));
      const similarityScore = Math.max(0, 1 - gainGap / gainBase) * 30;
      const momentumScore = Math.max(0, fromGain) * 2.2 + Math.max(0, toGain) * 5.2;
      const leadScore = fromLeadRate > toStartRate ? 12 : 0;
      const strength = clampScore(20 + similarityScore + momentumScore + leadScore);

      if (strength < 28 || (fromGain <= 0 && toGain <= 0)) continue;

      periodRoutes.push({
        ...route,
        strength,
        confidence: strength,
        description: `${fromRegion.name}가 먼저 ${formatRate(fromGain)} 움직이고, ${lagWeeks}주 뒤 ${toRegion.name}가 ${formatRate(toGain)} 움직였어요.`
      });
  }

  return periodRoutes.sort((a, b) => b.strength - a.strength);
}
