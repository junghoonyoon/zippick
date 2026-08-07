import type { FlowEdge, RegionNode } from "@/lib/market-flow/types";
import {
  getCandidateNodes,
  getStrongestIncomingEdge
} from "@/lib/market-flow/utils";
import { cn } from "@/lib/utils";

type PropagationRankingCardProps = {
  edges: FlowEdge[];
  nodes: RegionNode[];
  selectedNodeId: string | null;
  onCandidateSelect: (nodeId: string, edgeId: string | null) => void;
};

export function PropagationRankingCard({
  edges,
  nodes,
  selectedNodeId,
  onCandidateSelect
}: PropagationRankingCardProps) {
  const candidates = getCandidateNodes(nodes);

  return (
    <section className="rounded-lg border border-zippick-line bg-white p-5 shadow-panel">
      <div className="flex items-center gap-2">
        <h2 className="text-[18px] font-black text-zippick-ink">
          다음 확산 후보
        </h2>
        <span
          aria-label="직전 기간보다 확산 가능성 점수가 얼마나 변했는지 보여줘요."
          className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-zippick-line text-[12px] font-black text-zippick-muted"
          title="증감은 가격 상승률이 아니라 확산 가능성 점수 변화예요."
        >
          ?
        </span>
      </div>

      <div className="mt-4 divide-y divide-zippick-line">
        {candidates.map((node, index) => {
          const incomingEdge = getStrongestIncomingEdge(edges, node.id);
          const isSelected = selectedNodeId === node.id;

          return (
            <button
              aria-pressed={isSelected}
              className={cn(
                "flex w-full items-center gap-3 py-3 text-left transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-300",
                isSelected && "rounded-md bg-blue-50 px-2"
              )}
              key={node.id}
              onClick={() => onCandidateSelect(node.id, incomingEdge?.id ?? null)}
              type="button"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zippick-ink text-[14px] font-black text-white">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[15px] font-bold text-zippick-ink">
                  {node.name}
                </span>
                <span className="mt-1 block text-[13px] text-zippick-muted">
                  확산 가능성 점수 변화예요
                </span>
              </span>
              <span className="text-right">
                <strong className="block text-[22px] leading-none text-zippick-ink">
                  {node.propagationScore}
                </strong>
                <span className="mt-1 block text-[13px] font-bold text-green-600">
                  ▲ {node.propagationDelta}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
