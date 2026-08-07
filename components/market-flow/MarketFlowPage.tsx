"use client";

import { useEffect, useMemo, useState } from "react";
import { MarketFlowFilters } from "@/components/market-flow/MarketFlowFilters";
import { MarketFlowHeader } from "@/components/market-flow/MarketFlowHeader";
import { MarketFlowMap } from "@/components/market-flow/MarketFlowMap";
import { MarketFlowNotice } from "@/components/market-flow/MarketFlowNotice";
import { MarketFlowSummaryCard } from "@/components/market-flow/MarketFlowSummaryCard";
import { PropagationRankingCard } from "@/components/market-flow/PropagationRankingCard";
import { SelectedFlowCard } from "@/components/market-flow/SelectedFlowCard";
import type {
  FlowEdge,
  MarketFlowSnapshot,
  MarketPeriod,
  RegionScope
} from "@/lib/market-flow/types";
import {
  getEdgeById,
  getInitialEdge,
  getSnapshot,
  getStrongestIncomingEdge,
  isEdgeConnectedToNode
} from "@/lib/market-flow/utils";
import { cn } from "@/lib/utils";

type MarketFlowPageProps = {
  snapshots: MarketFlowSnapshot[];
};

function isMarketPeriod(value: string | null): value is MarketPeriod {
  return value === "3m" || value === "6m" || value === "1y";
}

function isRegionScope(value: string | null): value is RegionScope {
  return value === "seoul" || value === "capital";
}

function getSelectedEdge(
  edges: FlowEdge[],
  selectedEdgeId: string | null,
  selectedNodeId: string | null
) {
  if (selectedEdgeId) {
    return getEdgeById(edges, selectedEdgeId);
  }

  if (selectedNodeId) {
    return getStrongestIncomingEdge(edges, selectedNodeId);
  }

  return getInitialEdge(edges);
}

export function MarketFlowPage({ snapshots }: MarketFlowPageProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<MarketPeriod>("3m");
  const [selectedScope, setSelectedScope] = useState<RegionScope>("seoul");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(
    "gangnam-seongdong"
  );

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const period = search.get("period");
    const scope = search.get("scope");
    const edge = search.get("edge");

    if (isMarketPeriod(period)) setSelectedPeriod(period);
    if (isRegionScope(scope)) setSelectedScope(scope);
    if (edge) setSelectedEdgeId(edge);
  }, []);

  const snapshot = useMemo(
    () => getSnapshot(snapshots, selectedPeriod, selectedScope),
    [selectedPeriod, selectedScope, snapshots]
  );
  const selectedEdge = getSelectedEdge(
    snapshot.edges,
    selectedEdgeId,
    selectedNodeId
  );

  useEffect(() => {
    if (selectedEdgeId && !snapshot.edges.some((edge) => edge.id === selectedEdgeId)) {
      const nextEdge = getInitialEdge(snapshot.edges);
      setSelectedEdgeId(nextEdge?.id ?? null);
      setSelectedNodeId(null);
    }
  }, [selectedEdgeId, snapshot.edges]);

  useEffect(() => {
    const search = new URLSearchParams();
    search.set("period", selectedPeriod);
    search.set("scope", selectedScope);
    if (selectedEdge?.id) search.set("edge", selectedEdge.id);
    window.history.replaceState(null, "", `/flow?${search.toString()}`);
  }, [selectedEdge?.id, selectedPeriod, selectedScope]);

  const handleNodeSelect = (nodeId: string) => {
    const connectedSelectedEdge =
      selectedEdge && isEdgeConnectedToNode(selectedEdge, nodeId)
        ? selectedEdge
        : getStrongestIncomingEdge(snapshot.edges, nodeId);

    setSelectedNodeId(nodeId);
    setSelectedEdgeId(connectedSelectedEdge?.id ?? null);
  };

  const handleClearSelection = () => {
    setSelectedNodeId(null);
    setSelectedEdgeId(getInitialEdge(snapshot.edges)?.id ?? null);
  };

  return (
    <main className="min-h-screen bg-zippick-canvas">
      <div className="grid min-h-screen lg:grid-cols-[196px_minmax(0,1fr)]">
        <aside className="hidden border-r border-zippick-line bg-white px-4 py-7 lg:block">
          <div className="text-[34px] font-black text-zippick-blue">집픽</div>
          <nav className="mt-10 space-y-2 text-[15px] font-bold">
            {[
              ["대시보드", "/"],
              ["온기 흐름", "/flow"],
              ["지역 분석", "/heatmap"],
              ["단지 검색", "/"],
              ["관심 지역", "/"]
            ].map(([label, href]) => (
              <a
                className={cn(
                  "block rounded-lg px-4 py-3 transition",
                  href === "/flow"
                    ? "bg-blue-50 text-zippick-blue"
                    : "text-zippick-body hover:bg-slate-50"
                )}
                href={href}
                key={label}
              >
                {label}
              </a>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 px-5 py-7 lg:px-8 lg:py-9">
          <div className="mx-auto flex max-w-[1500px] flex-col gap-6">
            <MarketFlowHeader baseDate={snapshot.baseDate} />

            <div className="xl:hidden">
              <MarketFlowSummaryCard nodes={snapshot.nodes} />
            </div>

            <MarketFlowFilters
              onPeriodChange={(period) => {
                setSelectedPeriod(period);
                setSelectedNodeId(null);
                setSelectedEdgeId("gangnam-seongdong");
              }}
              onScopeChange={(scope) => {
                setSelectedScope(scope);
                setSelectedNodeId(null);
                setSelectedEdgeId("gangnam-seongdong");
              }}
              selectedPeriod={selectedPeriod}
              selectedScope={selectedScope}
            />

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_412px]">
              <section className="order-1 flex min-w-0 flex-col gap-4">
                <MarketFlowMap
                  edges={snapshot.edges}
                  nodes={snapshot.nodes}
                  onClearSelection={handleClearSelection}
                  onEdgeSelect={(edgeId) => {
                    setSelectedEdgeId(edgeId);
                    setSelectedNodeId(null);
                  }}
                  onNodeSelect={handleNodeSelect}
                  selectedEdgeId={selectedEdge?.id ?? null}
                  selectedNodeId={selectedNodeId}
                />
              </section>

              <aside className="order-2 flex flex-col gap-4 xl:sticky xl:top-6 xl:self-start">
                <div className="hidden xl:block">
                  <MarketFlowSummaryCard nodes={snapshot.nodes} />
                </div>
                <PropagationRankingCard
                  edges={snapshot.edges}
                  nodes={snapshot.nodes}
                  onCandidateSelect={(nodeId, edgeId) => {
                    setSelectedNodeId(nodeId);
                    setSelectedEdgeId(edgeId);
                  }}
                  selectedNodeId={selectedNodeId}
                />
                <SelectedFlowCard edge={selectedEdge} nodes={snapshot.nodes} />
                <MarketFlowNotice />
              </aside>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
