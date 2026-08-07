import type { FlowEdge, RegionNode } from "@/lib/market-flow/types";
import {
  confidenceCopy,
  formatFlowTitle,
  getRegionNameMap
} from "@/lib/market-flow/utils";

type SelectedFlowCardProps = {
  edge: FlowEdge | undefined;
  nodes: RegionNode[];
};

export function SelectedFlowCard({ edge, nodes }: SelectedFlowCardProps) {
  const regionNameById = getRegionNameMap(nodes);

  if (!edge) {
    return (
      <section className="rounded-lg border border-zippick-line bg-white p-5 shadow-panel">
        <h2 className="text-[18px] font-black text-zippick-ink">선택한 흐름</h2>
        <p className="mt-3 text-[15px] leading-6 text-zippick-body">
          지역이나 화살표를 누르면 흐름 근거를 볼 수 있어요.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-zippick-line bg-white p-5 shadow-panel">
      <h2 className="text-[18px] font-black text-zippick-ink">선택한 흐름</h2>
      <div className="mt-4">
        <p className="text-[24px] font-black text-red-600">
          {formatFlowTitle(edge, regionNameById)}
        </p>
        <dl className="mt-4 divide-y divide-zippick-line text-[15px]">
          <div className="flex items-center justify-between py-2">
            <dt className="text-zippick-body">평균 시차</dt>
            <dd className="font-black text-zippick-ink">
              {edge.lagMinMonths}~{edge.lagMaxMonths}개월
            </dd>
          </div>
          <div className="flex items-center justify-between py-2">
            <dt className="text-zippick-body">확산 가능성</dt>
            <dd className="font-black text-red-600">
              {edge.propagationScore}점
            </dd>
          </div>
          <div className="flex items-center justify-between py-2">
            <dt className="text-zippick-body">신뢰도</dt>
            <dd
              className={`rounded-md px-3 py-1 text-[13px] font-black ${confidenceCopy[edge.confidence].className}`}
            >
              {confidenceCopy[edge.confidence].label}
            </dd>
          </div>
        </dl>
      </div>

      <div className="mt-5">
        <h3 className="text-[15px] font-black text-zippick-ink">흐름 근거</h3>
        <ul className="mt-3 space-y-2">
          {edge.evidence.map((item) => (
            <li
              className="flex gap-2 text-[14px] leading-6 text-zippick-body"
              key={item.id}
            >
              <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full bg-zippick-blue" />
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-5">
        <h3 className="text-[15px] font-black text-zippick-ink">확인할 점</h3>
        <ul className="mt-3 space-y-2">
          {edge.risks.map((item) => (
            <li
              className="flex gap-2 text-[14px] leading-6 text-zippick-body"
              key={item.id}
            >
              <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full bg-amber-400" />
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
