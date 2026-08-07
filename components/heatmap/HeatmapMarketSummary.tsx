import type { RegionSnapshot } from "@/lib/heatmap/types";
import { formatChange, getHeatBadgeClass } from "@/lib/heatmap/utils";
import { cn } from "@/lib/utils";

type HeatmapMarketSummaryProps = {
  hottestRegion: RegionSnapshot;
  fastestRegion: RegionSnapshot;
  nextCandidate: RegionSnapshot;
};

export function HeatmapMarketSummary({
  hottestRegion,
  fastestRegion,
  nextCandidate
}: HeatmapMarketSummaryProps) {
  return (
    <section className="grid gap-3 lg:grid-cols-[1.2fr_1fr_1fr]">
      <article className="rounded-lg border border-zippick-line bg-white p-5 shadow-sm">
        <p className="text-[13px] font-bold text-orange-700">먼저 볼 곳</p>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <h2 className="text-[24px] font-bold text-zippick-ink">
              {hottestRegion.name}
            </h2>
            <p className="mt-2 text-[14px] leading-6 text-zippick-body">
              현재 {hottestRegion.score}점이에요. 4주 전{" "}
              {hottestRegion.score4wAgo}점보다{" "}
              {formatChange(hottestRegion.weekChange4w)} 움직였어요.
            </p>
          </div>
          <span
            className={cn(
              "rounded-md border px-3 py-2 text-[15px] font-bold",
              getHeatBadgeClass(hottestRegion.score)
            )}
          >
            {hottestRegion.score}점
          </span>
        </div>
      </article>

      <article className="rounded-lg border border-zippick-line bg-white p-5 shadow-sm">
        <p className="text-[13px] font-bold text-orange-700">최근 오른 곳</p>
        <h2 className="mt-2 text-[22px] font-bold text-zippick-ink">
          {fastestRegion.name}
        </h2>
        <p className="mt-2 text-[14px] leading-6 text-zippick-body">
          4주 전 {fastestRegion.score4wAgo}점에서 현재{" "}
          {fastestRegion.score}점으로 움직였어요.
        </p>
      </article>

      <article className="rounded-lg border border-zippick-line bg-white p-5 shadow-sm">
        <p className="text-[13px] font-bold text-orange-700">다음에 볼 곳</p>
        <h2 className="mt-2 text-[22px] font-bold text-zippick-ink">
          {nextCandidate.name}
        </h2>
        <p className="mt-2 text-[14px] leading-6 text-zippick-body">
          후보 점수 {nextCandidate.nextHeatCandidateScore}점이에요.
          현재 {nextCandidate.score}점, 4주 변화는{" "}
          {formatChange(nextCandidate.weekChange4w)}예요.
        </p>
      </article>
    </section>
  );
}
