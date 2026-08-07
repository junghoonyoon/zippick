export type MarketPeriod = "3m" | "6m" | "1y";

export type RegionScope = "seoul" | "capital";

export type MarketStatus = "leader" | "spreading" | "early";

export type FlowConfidence = "high" | "medium" | "low";

export type FlowEvidenceType =
  | "source_price_momentum"
  | "source_transaction_growth"
  | "target_transaction_growth"
  | "rising_complex_ratio"
  | "price_gap";

export type FlowRiskType =
  | "reporting_delay"
  | "small_sample"
  | "single_complex_bias"
  | "supply_risk";

export type RegionNode = {
  id: string;
  name: string;
  shortName?: string;
  x: number;
  y: number;
  status: MarketStatus;
  heatScore: number;
  propagationScore: number;
  propagationDelta: number;
  transactionChange: number;
  priceMomentum: number;
};

export type FlowEvidence = {
  id: string;
  type: FlowEvidenceType;
  label: string;
  value?: number;
  unit?: string;
};

export type FlowRisk = {
  id: string;
  type: FlowRiskType;
  label: string;
};

export type FlowEdge = {
  id: string;
  sourceRegionId: string;
  targetRegionId: string;
  lagMinMonths: number;
  lagMaxMonths: number;
  propagationScore: number;
  confidence: FlowConfidence;
  strength: number;
  active: boolean;
  evidence: FlowEvidence[];
  risks: FlowRisk[];
};

export type MarketFlowSnapshot = {
  period: MarketPeriod;
  regionScope: RegionScope;
  baseDate: string;
  nodes: RegionNode[];
  edges: FlowEdge[];
};
