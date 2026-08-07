import { Button } from "@/components/ui/button";
import type { TimelineWeek } from "@/lib/heatmap/types";
import { cn } from "@/lib/utils";

type TimelinePlayerProps = {
  weeks: TimelineWeek[];
  currentWeekIndex: number;
  isPlaying: boolean;
  embedded?: boolean;
  onPlayToggle: () => void;
  onWeekChange: (weekIndex: number) => void;
};

export function TimelinePlayer({
  weeks,
  currentWeekIndex,
  embedded = false,
  isPlaying,
  onPlayToggle,
  onWeekChange
}: TimelinePlayerProps) {
  const currentWeek = weeks[currentWeekIndex];

  return (
    <section
      className={cn(
        embedded
          ? "mt-4 border-t border-zippick-line pt-4"
          : "rounded-lg border border-zippick-line bg-white p-5 shadow-panel"
      )}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-[18px] font-bold text-zippick-ink">
            가격 흐름 시간 이동
          </h2>
          <p className="mt-1 text-[14px] leading-6 text-zippick-body">
            2년 동안 구별 상승률이 어떻게 달라졌는지 재생해봐요.
          </p>
        </div>
        <Button
          className="min-w-24"
          onClick={onPlayToggle}
          variant={isPlaying ? "secondary" : "default"}
        >
          {isPlaying ? "멈춤" : "재생"}
        </Button>
      </div>

      <div className="mt-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="text-[14px] font-semibold text-zippick-muted">
            시작
          </span>
          <strong className="text-[16px] text-zippick-ink">
            {currentWeek.label}
          </strong>
          <span className="text-[14px] font-semibold text-zippick-muted">
            현재
          </span>
        </div>
        <input
          aria-label="2년 가격 흐름 주차"
          className="heatmap-range h-3 w-full"
          max={weeks.length - 1}
          min={0}
          onChange={(event) => onWeekChange(Number(event.target.value))}
          step={1}
          type="range"
          value={currentWeekIndex}
        />
        <div
          className="mt-3 grid text-center text-[12px] font-semibold text-zippick-muted"
          style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}
        >
          {weeks.map((week) => (
            <span key={`${week.index}-${week.shortLabel}`}>
              {week.index % 4 === 0 || week.index === weeks.length - 1
                ? week.shortLabel
                : ""}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
