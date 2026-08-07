export type HeatState = "냉각" | "관망" | "회복" | "확산" | "과열 주의";

export type HeatmapTab = "current" | "change" | "spread" | "candidate";

export type HeatComparisonPeriod = {
  label: string;
  shortLabel: string;
  weeks: number;
};

export type RegionHeatMetrics = {
  volumeStrength: number;
  priceRiseRatio: number;
  risingComplexRatio: number;
};

export type HeatRegion = RegionHeatMetrics & {
  id: string;
  name: string;
  weeklyHistory: number[];
  weeklyChangeRates?: number[];
  currentScore: number;
  currentState: HeatState;
  change4w: number;
  reasons: string[];
  linkedRegions: string[];
  nextHeatCandidateScore: number;
  dataSource?: {
    label: string;
    basisDate: string;
    sampleCount: number;
    complexCount: number;
  };
};

export type RegionSnapshot = HeatRegion & {
  score: number;
  candidateScore: number;
  changeRate: number;
  state: HeatState;
  weekIndex: number;
  score4wAgo: number;
  score12wAgo: number;
  weekChange4w: number;
  weekChange12w: number;
  metrics: RegionHeatMetrics;
};

export type RegionMapShape = {
  id: string;
  svgPath: string;
  labelX: number;
  labelY: number;
};

export type SpreadRoute = {
  id: string;
  from: string;
  to: string;
  strength: number;
  description: string;
  lagWeeks?: number;
  confidence?: number;
};

export type TimelineWeek = {
  index: number;
  label: string;
  shortLabel: string;
};
