import type { HeatmapTab } from "@/lib/heatmap/types";
import { cn } from "@/lib/utils";

const tabs: Array<{ id: HeatmapTab; label: string; description: string }> = [
  { id: "current", label: "현재 순위", description: "2년 흐름" },
  {
    id: "change",
    label: "최근 순위",
    description: "선택 기간"
  },
  { id: "spread", label: "번지는 흐름", description: "방향과 강도" },
  { id: "candidate", label: "다음 관심", description: "흐름 연결" }
];

type HeatmapTabsProps = {
  activeTab: HeatmapTab;
  onChange: (tab: HeatmapTab) => void;
};

export function HeatmapTabs({ activeTab, onChange }: HeatmapTabsProps) {
  return (
    <div className="grid grid-cols-4 gap-1 rounded-lg border border-zippick-line bg-white p-1 shadow-sm">
      {tabs.map((tab) => (
        <button
          className={cn(
            "flex min-h-16 flex-col items-center justify-center gap-1 rounded-md px-2 text-center transition hover:bg-slate-50",
            activeTab === tab.id && "bg-zippick-ink text-white hover:bg-zippick-ink"
          )}
          key={tab.id}
          onClick={() => onChange(tab.id)}
          type="button"
        >
          <span className="text-[14px] font-bold leading-5 md:text-[15px]">
            {tab.label}
          </span>
          <span
            className={cn(
              "text-[12px] font-semibold text-zippick-muted",
              activeTab === tab.id && "text-white/75"
            )}
          >
            {tab.description}
          </span>
        </button>
      ))}
    </div>
  );
}
