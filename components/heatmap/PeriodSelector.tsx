import type { HeatComparisonPeriod } from "@/lib/heatmap/types";
import { cn } from "@/lib/utils";

type PeriodSelectorProps = {
  periods: HeatComparisonPeriod[];
  selectedWeeks: number;
  onChange: (weeks: number) => void;
};

export function PeriodSelector({
  periods,
  selectedWeeks,
  onChange
}: PeriodSelectorProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zippick-line bg-white px-5 py-4 shadow-sm md:flex-row md:items-center md:justify-between">
      <div>
        <h2 className="text-[17px] font-bold text-zippick-ink">
          비교 기간
        </h2>
        <p className="mt-1 text-[14px] leading-6 text-zippick-body">
          현재 흐름을 언제와 비교할지 골라요.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {periods.map((period) => {
          const selected = selectedWeeks === period.weeks;

          return (
            <button
              className={cn(
                "rounded-md border px-4 py-3 text-[14px] font-bold transition",
                selected
                  ? "border-zippick-ink bg-zippick-ink text-white"
                  : "border-zippick-line bg-white text-zippick-body hover:border-orange-300"
              )}
              key={period.weeks}
              onClick={() => onChange(period.weeks)}
              type="button"
            >
              {period.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
