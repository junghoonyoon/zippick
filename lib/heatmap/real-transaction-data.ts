import "server-only";

import fs from "node:fs";
import path from "node:path";
import {
  heatRegions as fallbackHeatRegions,
  regionMapShapes,
  spreadRoutes
} from "@/lib/heatmap/mock-data";
import type { HeatRegion, TimelineWeek } from "@/lib/heatmap/types";
import type { SpreadRoute } from "@/lib/heatmap/types";
import { calculateHeatScore, clampScore, getHeatState } from "@/lib/heatmap/utils";

type PriceBandRow = {
  name: string;
  region: string;
  midPrice: number;
  averagePrice: number;
  maxPrice: number;
  transactionCount: number;
  latestDealDate: string;
  latestDealPrice: number;
};

type RegionAggregate = {
  id: string;
  name: string;
  rows: PriceBandRow[];
  transactionCount: number;
  latestDealDate: string;
};

type RawTransaction = {
  apartment?: string;
  cancellationDate?: string;
  dealAmountEok?: number;
  dealDate?: string;
  dealType?: string;
  exclusiveArea?: number;
};

type RegionPriceFlow = {
  id: string;
  name: string;
  baselinePpsm: number;
  currentChangeRate: number;
  currentPpsm: number;
  firstRiseWeek: number | null;
  sampleCount: number;
  weeklyChangeRates: number[];
  weeklyPpsm: number[];
};

const PRICE_BANDS_PATH = path.join(
  process.cwd(),
  "data",
  "seoul_small_apartment_price_bands.csv"
);

const MOLIT_CACHE_DIR = path.join(process.cwd(), "pipeline", "cache", "molit_transactions");
const FLOW_START_DATE = "2024-08-05";
const FLOW_END_DATE = "2026-08-03";

const districtCodeById = new Map([
  ["gangnam", "11680"],
  ["seocho", "11650"],
  ["songpa", "11710"],
  ["gangdong", "11740"],
  ["mapo", "11440"],
  ["yongsan", "11170"],
  ["seongdong", "11200"],
  ["gwangjin", "11215"],
  ["yeongdeungpo", "11560"],
  ["dongjak", "11590"],
  ["yangcheon", "11470"],
  ["gangseo", "11500"],
  ["guro", "11530"],
  ["geumcheon", "11545"],
  ["gwanak", "11620"],
  ["jongno", "11110"],
  ["jung", "11140"],
  ["seodaemun", "11410"],
  ["eunpyeong", "11380"],
  ["dongdaemun", "11230"],
  ["jungnang", "11260"],
  ["seongbuk", "11290"],
  ["gangbuk", "11305"],
  ["dobong", "11320"],
  ["nowon", "11350"]
]);

const routeCandidatePairs = [
  ["gangnam", "seocho"],
  ["gangnam", "songpa"],
  ["songpa", "gangdong"],
  ["songpa", "gwangjin"],
  ["seocho", "dongjak"],
  ["yongsan", "seongdong"],
  ["seongdong", "gwangjin"],
  ["seongdong", "dongdaemun"],
  ["mapo", "seodaemun"],
  ["mapo", "eunpyeong"],
  ["yeongdeungpo", "mapo"],
  ["yeongdeungpo", "dongjak"],
  ["yangcheon", "gangseo"],
  ["yangcheon", "guro"],
  ["guro", "geumcheon"],
  ["dongjak", "gwanak"],
  ["jongno", "jung"],
  ["jongno", "seongbuk"],
  ["seongbuk", "gangbuk"],
  ["nowon", "dobong"],
  ["nowon", "jungnang"],
  ["nowon", "gangbuk"]
] as const;

function getWeekOfMonth(date: Date) {
  return Math.ceil(date.getUTCDate() / 7);
}

function buildHeatmapWeeks() {
  const weeks: TimelineWeek[] = [];
  const end = weekStart(new Date(`${FLOW_END_DATE}T00:00:00Z`));
  const current = weekStart(new Date(`${FLOW_START_DATE}T00:00:00Z`));

  while (current <= end) {
    const index = weeks.length;
    const month = current.getUTCMonth() + 1;
    const week = getWeekOfMonth(current);
    weeks.push({
      index,
      label: `${current.getUTCFullYear()}년 ${month}월 ${week}주`,
      shortLabel: `${month}월 ${week}주`
    });
    current.setUTCDate(current.getUTCDate() + 7);
  }

  return weeks;
}

const heatmapWeeks = buildHeatmapWeeks();
const flowStartLabel = heatmapWeeks[0]?.label ?? "시작 시점";

const regionNameToId = new Map(
  regionMapShapes.map((shape) => [fallbackHeatRegions.find((region) => region.id === shape.id)?.name, shape.id])
);

function parseCsvLine(line: string) {
  const values: string[] = [];
  let current = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];

    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      quoted = !quoted;
      continue;
    }

    if (char === "," && !quoted) {
      values.push(current);
      current = "";
      continue;
    }

    current += char;
  }

  values.push(current);
  return values;
}

function toNumber(value: string | undefined) {
  const parsed = Number(String(value ?? "").replace(/,/g, "").trim());
  return Number.isFinite(parsed) ? parsed : 0;
}

function median(values: number[]) {
  const sorted = values.filter((value) => value > 0).sort((a, b) => a - b);
  if (sorted.length === 0) return 0;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function weekStart(date: Date) {
  const next = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const day = next.getUTCDay() || 7;
  next.setUTCDate(next.getUTCDate() - day + 1);
  return next;
}

function weekIndexForDate(dateText: string) {
  const date = new Date(`${dateText}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return -1;
  const start = weekStart(new Date(`${FLOW_START_DATE}T00:00:00Z`));
  const current = weekStart(date);
  return Math.floor((current.getTime() - start.getTime()) / (7 * 24 * 60 * 60 * 1000));
}

function buildMonthKeys() {
  const keys: string[] = [];
  const current = new Date(`${FLOW_START_DATE}T00:00:00Z`);
  const end = new Date(`${FLOW_END_DATE}T00:00:00Z`);
  current.setUTCDate(1);

  while (current <= end) {
    keys.push(`${current.getUTCFullYear()}${String(current.getUTCMonth() + 1).padStart(2, "0")}`);
    current.setUTCMonth(current.getUTCMonth() + 1);
  }

  return keys;
}

function readTransactionsForRegion(regionId: string) {
  const lawdCode = districtCodeById.get(regionId);
  if (!lawdCode || !fs.existsSync(MOLIT_CACHE_DIR)) return [];

  const rows: RawTransaction[] = [];
  for (const month of buildMonthKeys()) {
    const cachePath = path.join(MOLIT_CACHE_DIR, `${lawdCode}_${month}.json`);
    if (!fs.existsSync(cachePath)) continue;

    try {
      const payload = JSON.parse(fs.readFileSync(cachePath, "utf8")) as {
        items?: RawTransaction[];
      };
      rows.push(...(payload.items ?? []));
    } catch {
      continue;
    }
  }

  return rows.filter((row) => {
    const area = Number(row.exclusiveArea ?? 0);
    const price = Number(row.dealAmountEok ?? 0);
    return (
      area > 0 &&
      price > 0 &&
      row.dealDate &&
      !row.cancellationDate &&
      String(row.dealType ?? "").replace(/\s/g, "") !== "직거래"
    );
  });
}

function buildPriceFlows() {
  const fallbackNameById = new Map(fallbackHeatRegions.map((region) => [region.id, region.name]));

  return regionMapShapes.map((shape): RegionPriceFlow => {
    const transactions = readTransactionsForRegion(shape.id);
    const weeklyValues = Array.from({ length: heatmapWeeks.length }, () => [] as number[]);

    for (const row of transactions) {
      const index = weekIndexForDate(String(row.dealDate));
      if (index < 0 || index >= weeklyValues.length) continue;
      weeklyValues[index].push(Number(row.dealAmountEok) / Number(row.exclusiveArea));
    }

    let lastKnown = 0;
    const smoothedWeekly = weeklyValues.map((_, index) => {
      const fourWeekValues = weeklyValues
        .slice(Math.max(0, index - 3), index + 1)
        .flat();
      const eightWeekValues = weeklyValues
        .slice(Math.max(0, index - 7), index + 1)
        .flat();
      const usableValues =
        fourWeekValues.length >= 8
          ? fourWeekValues
          : eightWeekValues.length >= 8
            ? eightWeekValues
            : [];
      const value = median(usableValues);

      if (value > 0) {
        lastKnown = value;
        return value;
      }

      return lastKnown;
    });
    const baseline = median(smoothedWeekly.slice(0, 4)) || smoothedWeekly[0] || 0;
    const weeklyChangeRates = smoothedWeekly.map((value) =>
      baseline > 0 ? ((value - baseline) / baseline) * 100 : 0
    );
    const firstRiseWeek = weeklyChangeRates.findIndex(
      (value, index) =>
        index >= 2 && value >= 1.5 && value >= (weeklyChangeRates[index - 2] || value) + 0.4
    );

    return {
      id: shape.id,
      name: fallbackNameById.get(shape.id) ?? shape.id,
      baselinePpsm: baseline,
      currentChangeRate: weeklyChangeRates[weeklyChangeRates.length - 1] ?? 0,
      currentPpsm: smoothedWeekly[smoothedWeekly.length - 1] ?? 0,
      firstRiseWeek: firstRiseWeek >= 0 ? firstRiseWeek : null,
      sampleCount: transactions.length,
      weeklyChangeRates,
      weeklyPpsm: smoothedWeekly
    };
  });
}

function buildPriceSpreadRoutes(flows: RegionPriceFlow[]): SpreadRoute[] {
  const flowById = new Map(flows.map((flow) => [flow.id, flow]));
  const routes: SpreadRoute[] = [];

  for (const [from, to] of routeCandidatePairs) {
      const fromFlow = flowById.get(from);
      const toFlow = flowById.get(to);
      if (
        !fromFlow ||
        !toFlow ||
        fromFlow.firstRiseWeek == null ||
        toFlow.firstRiseWeek == null
      ) {
        continue;
      }

      const lagWeeks = toFlow.firstRiseWeek - fromFlow.firstRiseWeek;
      if (lagWeeks < 1 || lagWeeks > 10) continue;

      const sampleScore = Math.min(30, Math.floor((fromFlow.sampleCount + toFlow.sampleCount) / 25));
      const lagScore = Math.max(0, 40 - Math.abs(lagWeeks - 4) * 5);
      const strength = clampScore(35 + sampleScore + lagScore);

      routes.push({
        id: `${from}-${to}-price-flow`,
        from,
        to,
        strength,
        lagWeeks,
        confidence: strength,
        description: `${fromFlow.name}의 ㎡당 중간 거래가가 먼저 오르고, ${lagWeeks}주 뒤 ${toFlow.name}도 비슷한 상승 흐름을 보였어요.`
      });
  }

  const sortedRoutes = routes.sort((a, b) => b.strength - a.strength).slice(0, 12);

  return sortedRoutes.length > 0 ? sortedRoutes : spreadRoutes;
}

function applyPriceFlowToRegions(regions: HeatRegion[], flows: RegionPriceFlow[]) {
  const validFlows = flows.filter((flow) => flow.currentPpsm > 0 && flow.baselinePpsm > 0);
  if (validFlows.length === 0) return regions;

  const allChangeRates = validFlows.flatMap((flow) => flow.weeklyChangeRates);
  const minChangeRate = Math.min(...allChangeRates);
  const maxChangeRate = Math.max(...allChangeRates);
  const flowById = new Map(flows.map((flow) => [flow.id, flow]));

  return regions.map((region) => {
    const flow = flowById.get(region.id);
    if (!flow || flow.currentPpsm <= 0 || flow.baselinePpsm <= 0) return region;

    const weeklyHistory = flow.weeklyChangeRates.map((value) =>
      normalize(value, minChangeRate, maxChangeRate, 35)
    );
    const currentScore = weeklyHistory[weeklyHistory.length - 1] ?? region.currentScore;
    const score12wAgo = weeklyHistory[Math.max(0, weeklyHistory.length - 13)] ?? currentScore;
    const score24wAgo = weeklyHistory[0] ?? currentScore;
    const sixMonthChange = currentScore - score24wAgo;
    const threeMonthChange = currentScore - score12wAgo;
    const threeMonthRate =
      flow.weeklyChangeRates[flow.weeklyChangeRates.length - 1] -
      (flow.weeklyChangeRates[Math.max(0, flow.weeklyChangeRates.length - 13)] ?? 0);

    return {
      ...region,
      weeklyHistory,
      weeklyChangeRates: flow.weeklyChangeRates,
      currentScore,
      currentState: getHeatState(currentScore),
      volumeStrength: currentScore,
      priceRiseRatio: clampScore(50 + threeMonthChange),
      risingComplexRatio: clampScore(50 + sixMonthChange),
      change4w: currentScore - (weeklyHistory[Math.max(0, weeklyHistory.length - 5)] ?? currentScore),
      reasons: [
        `${flowStartLabel}부터 최근까지 실거래 ${flow.sampleCount.toLocaleString("ko-KR")}건을 봤어요.`,
        `구별 평균 대신 ㎡당 중간 거래가 상승률로 가격 흐름을 계산했어요.`,
        `${flowStartLabel} 대비 ${flow.currentChangeRate >= 0 ? "+" : ""}${flow.currentChangeRate.toFixed(1)}% · 최근 3개월 ${threeMonthRate >= 0 ? "+" : ""}${threeMonthRate.toFixed(1)}%예요.`
      ],
      nextHeatCandidateScore: clampScore(currentScore + Math.max(0, threeMonthChange) * 0.8),
      dataSource: {
        label: "집픽 국토부 실거래 원본",
        basisDate: "2026-07",
        sampleCount: flow.sampleCount,
        complexCount: region.dataSource?.complexCount ?? 0
      }
    };
  });
}

function readPriceBands(): PriceBandRow[] {
  if (!fs.existsSync(PRICE_BANDS_PATH)) return [];

  const lines = fs
    .readFileSync(PRICE_BANDS_PATH, "utf8")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter(Boolean);

  const header = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const columns = parseCsvLine(line);
    const row = new Map(header.map((key, index) => [key, columns[index] ?? ""]));

    return {
      name: row.get("name") ?? "",
      region: row.get("region") ?? "",
      midPrice: toNumber(row.get("mid_price_억")),
      averagePrice: toNumber(row.get("average_price_억")),
      maxPrice: toNumber(row.get("max_price_억")),
      transactionCount: toNumber(row.get("transaction_count")),
      latestDealDate: row.get("latest_deal_date") ?? "",
      latestDealPrice: toNumber(row.get("latest_deal_price_억"))
    };
  });
}

function normalize(value: number, min: number, max: number, floor = 35) {
  if (max <= min) return floor;
  return clampScore(floor + ((value - min) / (max - min)) * (100 - floor));
}

function buildWeeklyHistory(score: number, change4w: number, latestIntensity: number) {
  const start = clampScore(score - Math.max(8, change4w + latestIntensity * 0.12));
  return Array.from({ length: heatmapWeeks.length }, (_, index) => {
    const progress = index / Math.max(1, heatmapWeeks.length - 1);
    const curve = Math.pow(progress, 1.15);
    return clampScore(start + (score - start) * curve);
  });
}

function extendFallbackHistory(region: HeatRegion): HeatRegion {
  if (region.weeklyHistory.length >= heatmapWeeks.length) return region;

  const firstScore = region.weeklyHistory[0];
  const earlyStart = clampScore(firstScore - 10);
  const missingWeeks = heatmapWeeks.length - region.weeklyHistory.length;
  const prefix = Array.from({ length: missingWeeks }, (_, index) => {
    const progress = index / Math.max(1, missingWeeks);
    return clampScore(earlyStart + (firstScore - earlyStart) * progress);
  });

  return {
    ...region,
    weeklyHistory: [...prefix, ...region.weeklyHistory]
  };
}

function buildRegionsFromAggregates(aggregates: RegionAggregate[]): HeatRegion[] {
  const counts = aggregates.map((item) => item.transactionCount);
  const perComplexCounts = aggregates.map(
    (item) => item.transactionCount / Math.max(1, item.rows.length)
  );
  const minCount = Math.min(...counts);
  const maxCount = Math.max(...counts);
  const minPerComplex = Math.min(...perComplexCounts);
  const maxPerComplex = Math.max(...perComplexCounts);

  return aggregates.map((aggregate) => {
    const complexCount = aggregate.rows.length;
    const perComplex = aggregate.transactionCount / Math.max(1, complexCount);
    const activeComplexes = aggregate.rows.filter(
      (row) => row.latestDealPrice >= row.midPrice
    ).length;
    const strongComplexes = aggregate.rows.filter(
      (row) => row.latestDealPrice >= row.averagePrice
    ).length;
    const hotComplexes = aggregate.rows.filter(
      (row) => row.latestDealPrice >= row.maxPrice * 0.96
    ).length;
    const volumeStrength = normalize(
      perComplex * 0.7 + aggregate.transactionCount * 0.3,
      minPerComplex * 0.7 + minCount * 0.3,
      maxPerComplex * 0.7 + maxCount * 0.3
    );
    const priceRiseRatio = clampScore((activeComplexes / Math.max(1, complexCount)) * 100);
    const risingComplexRatio = clampScore((strongComplexes / Math.max(1, complexCount)) * 100);
    const currentScore = calculateHeatScore({
      volumeStrength,
      priceRiseRatio,
      risingComplexRatio
    });
    const change4w = clampScore(
      hotComplexes * 1.4 + (aggregate.transactionCount / Math.max(1, maxCount)) * 12
    );
    const weeklyHistory = buildWeeklyHistory(currentScore, change4w, volumeStrength);
    const linkedRegions = spreadRoutes
      .filter((route) => route.from === aggregate.id || route.to === aggregate.id)
      .map((route) => {
        const linkedId = route.from === aggregate.id ? route.to : route.from;
        return fallbackHeatRegions.find((region) => region.id === linkedId)?.name;
      })
      .filter((name): name is string => Boolean(name))
      .slice(0, 4);

    return {
      id: aggregate.id,
      name: aggregate.name,
      weeklyHistory,
      currentScore,
      currentState: getHeatState(currentScore),
      volumeStrength,
      priceRiseRatio,
      risingComplexRatio,
      change4w:
        weeklyHistory[weeklyHistory.length - 1] -
        weeklyHistory[weeklyHistory.length - 5],
      reasons: [
        `최근 실거래 요약 ${aggregate.transactionCount.toLocaleString("ko-KR")}건을 구 단위로 묶었어요.`,
        `${complexCount.toLocaleString("ko-KR")}개 단지 중 ${activeComplexes.toLocaleString("ko-KR")}개가 중간값보다 높은 최근 거래를 보였어요.`,
        `가장 최근 거래일은 ${aggregate.latestDealDate || "확인 전"}예요.`
      ],
      linkedRegions,
      nextHeatCandidateScore: clampScore(
        currentScore + change4w * 0.8 + hotComplexes * 0.6
      ),
      dataSource: {
        label: "집픽 국토부 실거래 요약",
        basisDate: aggregate.latestDealDate,
        sampleCount: aggregate.transactionCount,
        complexCount
      }
    };
  });
}

export function getRealTransactionHeatmapData() {
  const rows = readPriceBands();
  if (rows.length === 0) {
    return {
      heatRegions: fallbackHeatRegions.map(extendFallbackHistory),
      heatmapWeeks,
      regionMapShapes,
      spreadRoutes,
      sourceLabel: "MVP 샘플 데이터"
    };
  }

  const aggregateByRegion = new Map<string, RegionAggregate>();

  for (const row of rows) {
    const id = regionNameToId.get(row.region);
    if (!id) continue;

    const current = aggregateByRegion.get(id) ?? {
      id,
      name: row.region,
      rows: [],
      transactionCount: 0,
      latestDealDate: ""
    };

    current.rows.push(row);
    current.transactionCount += row.transactionCount;
    if (row.latestDealDate > current.latestDealDate) {
      current.latestDealDate = row.latestDealDate;
    }
    aggregateByRegion.set(id, current);
  }

  const realRegions = buildRegionsFromAggregates([...aggregateByRegion.values()]);
  const priceFlows = buildPriceFlows();
  const fallbackById = new Map(
    fallbackHeatRegions.map((region) => [region.id, extendFallbackHistory(region)])
  );
  const realById = new Map(realRegions.map((region) => [region.id, region]));
  const mergedRegions = applyPriceFlowToRegions(
    regionMapShapes.map((shape) => realById.get(shape.id) ?? fallbackById.get(shape.id)!),
    priceFlows
  );
  const priceSpreadRoutes = buildPriceSpreadRoutes(priceFlows);
  const latestDate = realRegions.reduce(
    (latest, region) =>
      region.dataSource?.basisDate && region.dataSource.basisDate > latest
        ? region.dataSource.basisDate
        : latest,
    ""
  );

  return {
    heatRegions: mergedRegions,
    heatmapWeeks,
    regionMapShapes,
    spreadRoutes: priceSpreadRoutes,
    sourceLabel: latestDate
      ? `집픽 실거래 원본 · ${latestDate} 기준`
      : "집픽 실거래 원본"
  };
}
