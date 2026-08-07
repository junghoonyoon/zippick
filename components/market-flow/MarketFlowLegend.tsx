import { statusCopy } from "@/lib/market-flow/utils";
import type { MarketStatus } from "@/lib/market-flow/types";
import { cn } from "@/lib/utils";

const legendItems: MarketStatus[] = ["leader", "spreading", "early"];

export function MarketFlowLegend() {
  return (
    <div className="absolute left-5 top-5 z-10 rounded-lg border border-zippick-line bg-white/95 p-4 shadow-sm backdrop-blur">
      <ul className="space-y-3 text-[14px] font-bold text-zippick-body">
        {legendItems.map((status) => (
          <li className="flex items-center gap-3" key={status}>
            <span
              className={cn(
                "h-4 w-4 rounded-full ring-4",
                statusCopy[status].className,
                statusCopy[status].ringClassName
              )}
            />
            <span>{statusCopy[status].label}</span>
          </li>
        ))}
        <li className="flex items-center gap-3">
          <span className="relative h-[3px] w-7 rounded-full bg-orange-500">
            <span className="absolute -right-1 -top-[3px] h-0 w-0 border-y-[5px] border-l-[7px] border-y-transparent border-l-orange-500" />
          </span>
          <span>확산 방향</span>
        </li>
      </ul>
    </div>
  );
}
