import { periodOptions, scopeOptions } from "@/lib/market-flow/utils";
import type { MarketPeriod, RegionScope } from "@/lib/market-flow/types";
import { cn } from "@/lib/utils";

type MarketFlowFiltersProps = {
  selectedPeriod: MarketPeriod;
  selectedScope: RegionScope;
  onPeriodChange: (period: MarketPeriod) => void;
  onScopeChange: (scope: RegionScope) => void;
};

export function MarketFlowFilters({
  selectedPeriod,
  selectedScope,
  onPeriodChange,
  onScopeChange
}: MarketFlowFiltersProps) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-wrap gap-2" aria-label="기간 선택">
        {periodOptions.map((option) => (
          <button
            aria-pressed={selectedPeriod === option.value}
            className={cn(
              "h-11 rounded-md border px-5 text-[15px] font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-300",
              selectedPeriod === option.value
                ? "border-zippick-blue bg-zippick-blue text-white shadow-sm"
                : "border-zippick-line bg-white text-zippick-body hover:bg-slate-50"
            )}
            key={option.value}
            onClick={() => onPeriodChange(option.value)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2" aria-label="지역 선택">
        {scopeOptions.map((option) => (
          <button
            aria-pressed={selectedScope === option.value}
            className={cn(
              "h-11 rounded-md border px-5 text-[15px] font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-300",
              selectedScope === option.value
                ? "border-zippick-blue bg-blue-50 text-zippick-blue"
                : "border-zippick-line bg-white text-zippick-body hover:bg-slate-50"
            )}
            key={option.value}
            onClick={() => onScopeChange(option.value)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
