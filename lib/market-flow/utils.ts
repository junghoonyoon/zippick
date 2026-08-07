import type {
  FlowConfidence,
  FlowEdge,
  MarketFlowSnapshot,
  MarketPeriod,
  MarketStatus,
  RegionNode,
  RegionScope
} from "@/lib/market-flow/types";

export const periodOptions: Array<{ label: string; value: MarketPeriod }> = [
  { label: "최근 3개월", value: "3m" },
  { label: "6개월", value: "6m" },
  { label: "1년", value: "1y" }
];

export const scopeOptions: Array<{ label: string; value: RegionScope }> = [
  { label: "서울", value: "seoul" },
  { label: "수도권", value: "capital" }
];

export const statusCopy: Record<
  MarketStatus,
  { label: string; className: string; ringClassName: string }
> = {
  leader: {
    label: "선도 지역",
    className: "bg-red-600 text-white",
    ringClassName: "ring-red-100"
  },
  spreading: {
    label: "확산 중",
    className: "bg-orange-500 text-white",
    ringClassName: "ring-orange-100"
  },
  early: {
    label: "초기 후보",
    className: "bg-blue-500 text-white",
    ringClassName: "ring-blue-100"
  }
};

export const confidenceCopy: Record<
  FlowConfidence,
  { label: string; className: string }
> = {
  high: { label: "높음", className: "bg-green-100 text-green-700" },
  medium: { label: "보통", className: "bg-slate-100 text-zippick-body" },
  low: { label: "낮음", className: "bg-amber-100 text-amber-700" }
};

export function getSnapshot(
  snapshots: MarketFlowSnapshot[],
  period: MarketPeriod,
  scope: RegionScope
) {
  return (
    snapshots.find(
      (snapshot) => snapshot.period === period && snapshot.regionScope === scope
    ) ?? snapshots[0]
  );
}

export function getSummary(nodes: RegionNode[]) {
  return {
    leader: nodes.filter((node) => node.status === "leader").length,
    spreading: nodes.filter((node) => node.status === "spreading").length,
    early: nodes.filter((node) => node.status === "early").length
  };
}

export function getNodeById(nodes: RegionNode[], nodeId?: string | null) {
  return nodes.find((node) => node.id === nodeId);
}

export function getEdgeById(edges: FlowEdge[], edgeId?: string | null) {
  return edges.find((edge) => edge.id === edgeId);
}

export function getInitialEdge(edges: FlowEdge[]) {
  return getEdgeById(edges, "gangnam-seongdong") ?? edges[0];
}

export function getStrongestIncomingEdge(
  edges: FlowEdge[],
  nodeId: string
) {
  return edges
    .filter((edge) => edge.targetRegionId === nodeId)
    .sort((a, b) => b.strength - a.strength)[0];
}

export function getCandidateNodes(nodes: RegionNode[]) {
  return [...nodes]
    .filter((node) => node.status !== "leader")
    .sort(
      (a, b) =>
        b.propagationScore +
        b.propagationDelta * 2 -
        (a.propagationScore + a.propagationDelta * 2)
    )
    .slice(0, 3);
}

export function getNodeRadius(node: RegionNode) {
  if (node.heatScore >= 78) return 34;
  if (node.heatScore >= 62) return 26;
  return 22;
}

export function getRegionNameMap(nodes: RegionNode[]) {
  return new Map(nodes.map((node) => [node.id, node.name]));
}

export function isEdgeConnectedToNode(edge: FlowEdge, nodeId: string) {
  return edge.sourceRegionId === nodeId || edge.targetRegionId === nodeId;
}

export function formatFlowTitle(
  edge: FlowEdge | undefined,
  regionNameById: Map<string, string>
) {
  if (!edge) return "선택한 흐름 없음";

  return `${regionNameById.get(edge.sourceRegionId) ?? ""} → ${
    regionNameById.get(edge.targetRegionId) ?? ""
  }`;
}
