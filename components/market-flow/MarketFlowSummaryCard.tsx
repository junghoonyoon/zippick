import type { RegionNode } from "@/lib/market-flow/types";
import { getSummary } from "@/lib/market-flow/utils";

type MarketFlowSummaryCardProps = {
  nodes: RegionNode[];
};

export function MarketFlowSummaryCard({ nodes }: MarketFlowSummaryCardProps) {
  const summary = getSummary(nodes);

  return (
    <section className="rounded-lg border border-zippick-line bg-white p-5 shadow-panel">
      <h2 className="text-[18px] font-black text-zippick-ink">핵심 요약</h2>
      <div className="mt-5 grid grid-cols-3 divide-x divide-zippick-line text-center">
        <div>
          <p className="text-[14px] font-bold text-red-600">선도 지역</p>
          <strong className="mt-2 block text-[34px] leading-none text-red-600">
            {summary.leader}
          </strong>
        </div>
        <div>
          <p className="text-[14px] font-bold text-orange-600">확산 진행</p>
          <strong className="mt-2 block text-[34px] leading-none text-orange-600">
            {summary.spreading}
          </strong>
        </div>
        <div>
          <p className="text-[14px] font-bold text-blue-600">초기 후보</p>
          <strong className="mt-2 block text-[34px] leading-none text-blue-600">
            {summary.early}
          </strong>
        </div>
      </div>
    </section>
  );
}
