import type { HeatRegion, SpreadRoute } from "@/lib/heatmap/types";

type SpreadLegendProps = {
  routes: SpreadRoute[];
  regions: HeatRegion[];
};

export function SpreadLegend({ routes, regions }: SpreadLegendProps) {
  const regionNameById = new Map(
    regions.map((region) => [region.id, region.name])
  );
  const getRouteStrengthLabel = (strength: number) => {
    if (strength >= 80) return "강함";
    if (strength >= 65) return "보통";
    return "약함";
  };

  return (
    <aside className="rounded-lg border border-orange-100 bg-orange-50 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[17px] font-bold text-zippick-ink">
            가격 상승 흐름
          </h2>
          <p className="mt-1 text-[14px] leading-6 text-zippick-body">
            ㎡당 중간 거래가가 먼저 오른 구와 뒤따라 오른 구를 연결했어요.
          </p>
        </div>
        <span className="rounded-md bg-white px-3 py-2 text-[13px] font-bold text-orange-700">
          {routes.length}개
        </span>
      </div>
      <div className="mt-4 grid max-h-72 gap-2 overflow-y-auto pr-1 md:grid-cols-2">
        {routes.length === 0 && (
          <p className="rounded-md bg-white px-3 py-3 text-[14px] leading-6 text-zippick-body md:col-span-2">
            선택한 기간에는 뚜렷하게 이어진 가격 상승 흐름이 없어요.
          </p>
        )}
        {routes.map((route) => (
          <div
            className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-[14px]"
            key={route.id}
          >
            <span className="font-semibold text-zippick-ink">
              {regionNameById.get(route.from)} → {regionNameById.get(route.to)}
            </span>
            <span className="text-[13px] font-semibold text-orange-700">
              {route.lagWeeks ? `${route.lagWeeks}주 뒤` : "시차 확인"}
              {" · "}
              {getRouteStrengthLabel(route.strength)}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
