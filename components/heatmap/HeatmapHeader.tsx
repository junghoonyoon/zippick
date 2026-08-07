type HeatmapHeaderProps = {
  periodLabel: string;
  sourceLabel: string;
  weekLabel: string;
};

export function HeatmapHeader({
  periodLabel,
  sourceLabel,
  weekLabel
}: HeatmapHeaderProps) {
  return (
    <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-3xl">
        <p className="mb-3 text-[15px] font-semibold text-orange-700">
          지역 흐름 보기
        </p>
        <h1 className="text-[38px] font-bold leading-tight text-zippick-ink">
          서울 아파트 가격 흐름
        </h1>
        <p className="mt-4 max-w-2xl text-[17px] leading-7 text-zippick-body">
          집픽에 저장된 실거래 원본으로 구별 가격이 먼저 오른 흐름을 보여줘요.
          관심 지역을 고른 뒤 지역 상세와 단지 상세로 이어갈 수 있어요.
        </p>
      </div>
      <div className="rounded-lg border border-zippick-line bg-white px-4 py-3 text-right shadow-sm">
        <p className="text-[13px] font-medium text-zippick-muted">기준 시점</p>
        <p className="mt-1 text-[15px] font-semibold text-zippick-ink">
          {weekLabel} · 최근 {periodLabel} 기준
        </p>
        <p className="mt-1 text-[13px] font-medium text-zippick-muted">
          {sourceLabel}
        </p>
      </div>
    </header>
  );
}
