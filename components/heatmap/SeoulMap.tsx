"use client";

import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { TimelinePlayer } from "@/components/heatmap/TimelinePlayer";
import type {
  HeatmapTab,
  HeatComparisonPeriod,
  RegionMapShape,
  RegionSnapshot,
  SpreadRoute,
  TimelineWeek
} from "@/lib/heatmap/types";
import {
  getHeatFillClass,
  getHeatTextClass
} from "@/lib/heatmap/utils";
import { cn } from "@/lib/utils";

type SeoulMapProps = {
  activeTab: HeatmapTab;
  candidateRegionIds: string[];
  comparisonPeriod: HeatComparisonPeriod;
  currentWeekIndex: number;
  isPlaying: boolean;
  regions: RegionSnapshot[];
  selectedRegionId: string;
  shapes: RegionMapShape[];
  routes: SpreadRoute[];
  weeks: TimelineWeek[];
  onRegionSelect: (regionId: string) => void;
  onPlayToggle: () => void;
  onWeekChange: (weekIndex: number) => void;
  periodRankById: Map<string, number>;
  rankById: Map<string, number>;
};

type ViewBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const initialViewBox: ViewBox = {
  x: 0,
  y: 0,
  width: 940,
  height: 610
};

function getMapCopy(activeTab: HeatmapTab, period: HeatComparisonPeriod) {
  if (activeTab === "change") {
    return {
      title: `${period.label} 상승 순위 지도`,
      description: `지도 숫자 = ${period.shortLabel}보다 많이 오른 순서예요.`
    };
  }

  if (activeTab === "spread") {
    return {
      title: "번지는 흐름 지도",
      description: "화살표는 먼저 오른 구에서 뒤따라 오른 구로 이어져요. 굵을수록 흐름이 강해요."
    };
  }

  if (activeTab === "candidate") {
    return {
      title: "다음 관심 지역 지도",
      description: "숫자는 현재 상승 흐름 순위예요. 화살표는 후보로 들어오는 흐름이에요."
    };
  }

  return {
    title: "현재 상승 흐름 지도",
    description: "지도 숫자 = 2년 시작 대비 많이 오른 순서예요."
  };
}

function viewBoxToString(viewBox: ViewBox) {
  return `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`;
}

function getRouteLine(
  shapeById: Map<string, RegionMapShape>,
  fromRegionId: string,
  toRegionId: string
) {
  const from = shapeById.get(fromRegionId);
  const to = shapeById.get(toRegionId);
  const fromX = from?.labelX ?? 0;
  const fromY = from?.labelY ?? 0;
  const toX = to?.labelX ?? 0;
  const toY = to?.labelY ?? 0;
  const dx = toX - fromX;
  const dy = toY - fromY;
  const length = Math.hypot(dx, dy);

  if (length < 1) {
    return { x1: fromX, y1: fromY, x2: toX, y2: toY };
  }

  const unitX = dx / length;
  const unitY = dy / length;

  return {
    x1: fromX + unitX * 14,
    y1: fromY + unitY * 14,
    x2: toX - unitX * 24,
    y2: toY - unitY * 24
  };
}

function getArrowHead(
  line: ReturnType<typeof getRouteLine>,
  scale = 1
) {
  const dx = line.x2 - line.x1;
  const dy = line.y2 - line.y1;
  const length = Math.hypot(dx, dy);

  if (length < 1) {
    return "";
  }

  const unitX = dx / length;
  const unitY = dy / length;
  const normalX = -unitY;
  const normalY = unitX;
  const headLength = 11 * scale;
  const headWidth = 7 * scale;
  const baseX = line.x2 - unitX * headLength;
  const baseY = line.y2 - unitY * headLength;

  return [
    `${line.x2},${line.y2}`,
    `${baseX + normalX * headWidth},${baseY + normalY * headWidth}`,
    `${baseX - normalX * headWidth},${baseY - normalY * headWidth}`
  ].join(" ");
}

function getRouteVisual(strength: number, isCandidateView: boolean) {
  const normalized = Math.max(0, Math.min(1, (strength - 25) / 65));
  const width = (isCandidateView ? 3.6 : 2.2) + normalized * (isCandidateView ? 7.2 : 6.2);
  const opacity = 0.3 + normalized * 0.62;
  const headScale = (isCandidateView ? 1.05 : 0.8) + normalized * 1.15;

  return {
    headScale,
    innerWidth: Math.max(1.1, width * 0.32),
    opacity,
    width
  };
}

export function SeoulMap({
  activeTab,
  candidateRegionIds,
  comparisonPeriod,
  currentWeekIndex,
  isPlaying,
  regions,
  selectedRegionId,
  shapes,
  routes,
  weeks,
  onPlayToggle,
  onRegionSelect,
  onWeekChange,
  periodRankById,
  rankById
}: SeoulMapProps) {
  const [viewBox, setViewBox] = useState<ViewBox>(initialViewBox);
  const dragStartRef = useRef<{ x: number; y: number; viewBox: ViewBox } | null>(
    null
  );
  const dragDistanceRef = useRef(0);

  const regionById = useMemo(
    () => new Map(regions.map((region) => [region.id, region])),
    [regions]
  );
  const shapeById = useMemo(
    () => new Map(shapes.map((shape) => [shape.id, shape])),
    [shapes]
  );
  const candidateRegionIdSet = useMemo(
    () => new Set(candidateRegionIds),
    [candidateRegionIds]
  );
  const visibleRoutes =
    activeTab === "spread"
      ? routes
      : activeTab === "candidate"
        ? routes.filter((route) => candidateRegionIdSet.has(route.to))
        : [];

  const zoom = (factor: number) => {
    setViewBox((current) => {
      const nextWidth = Math.max(520, Math.min(940, current.width * factor));
      const nextHeight = Math.max(340, Math.min(610, current.height * factor));
      const centerX = current.x + current.width / 2;
      const centerY = current.y + current.height / 2;

      return {
        x: Math.max(0, Math.min(940 - nextWidth, centerX - nextWidth / 2)),
        y: Math.max(0, Math.min(610 - nextHeight, centerY - nextHeight / 2)),
        width: nextWidth,
        height: nextHeight
      };
    });
  };

  return (
    <div className="rounded-lg border border-zippick-line bg-white p-4 shadow-panel">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-[18px] font-bold text-zippick-ink">
            {getMapCopy(activeTab, comparisonPeriod).title}
          </h2>
          <p className="mt-1 text-[14px] leading-6 text-zippick-body">
            {getMapCopy(activeTab, comparisonPeriod).description}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => zoom(0.82)} size="sm" variant="secondary">
            확대
          </Button>
          <Button onClick={() => zoom(1.18)} size="sm" variant="secondary">
            축소
          </Button>
          <Button
            onClick={() => setViewBox(initialViewBox)}
            size="sm"
            variant="ghost"
          >
            초기화
          </Button>
        </div>
      </div>

      <div className="relative overflow-hidden rounded-lg bg-slate-50">
        <svg
          aria-label="서울 부동산 온기 지도"
          className="h-[580px] w-full touch-none select-none"
          onPointerDown={(event) => {
            dragStartRef.current = {
              x: event.clientX,
              y: event.clientY,
              viewBox
            };
            dragDistanceRef.current = 0;
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            const dragStart = dragStartRef.current;
            if (!dragStart) return;

            const dx = event.clientX - dragStart.x;
            const dy = event.clientY - dragStart.y;
            dragDistanceRef.current = Math.max(
              dragDistanceRef.current,
              Math.abs(dx) + Math.abs(dy)
            );

            setViewBox({
              x: Math.max(
                0,
                Math.min(
                  940 - dragStart.viewBox.width,
                  dragStart.viewBox.x - dx * (dragStart.viewBox.width / 940)
                )
              ),
              y: Math.max(
                0,
                Math.min(
                  610 - dragStart.viewBox.height,
                  dragStart.viewBox.y - dy * (dragStart.viewBox.height / 610)
                )
              ),
              width: dragStart.viewBox.width,
              height: dragStart.viewBox.height
            });
          }}
          onPointerUp={(event) => {
            dragStartRef.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          role="img"
          viewBox={viewBoxToString(viewBox)}
        >
          <rect fill="#f8fafc" height="610" rx="18" width="940" />
          {shapes.map((shape) => {
            const region = regionById.get(shape.id);
            if (!region) return null;

            const isSelected = selectedRegionId === shape.id;
            const score =
              activeTab === "candidate"
                ? region.candidateScore
                : region.score;

            return (
              <path
                className={cn(
                  "cursor-pointer stroke-white stroke-[3] transition duration-150 hover:brightness-95",
                  getHeatFillClass(score),
                  isSelected && "stroke-zippick-ink stroke-[5]"
                )}
                d={shape.svgPath}
                filter={isSelected ? "url(#selectedShadow)" : undefined}
                key={shape.id}
                onClick={() => {
                  if (dragDistanceRef.current < 8) {
                    onRegionSelect(shape.id);
                  }
                }}
                role="button"
                tabIndex={0}
              />
            );
          })}

          {visibleRoutes.map((route) => {
            const line = getRouteLine(shapeById, route.from, route.to);
            const isCandidateView = activeTab === "candidate";
            const routeVisual = getRouteVisual(route.strength, isCandidateView);
            const arrowHead = getArrowHead(line, routeVisual.headScale);

            return (
              <g className="pointer-events-none" key={route.id}>
                <line
                  stroke="#ea580c"
                  strokeLinecap="round"
                  strokeOpacity={routeVisual.opacity}
                  strokeWidth={routeVisual.width}
                  x1={line.x1}
                  x2={line.x2}
                  y1={line.y1}
                  y2={line.y2}
                />
                <line
                  stroke="#fed7aa"
                  strokeLinecap="round"
                  strokeOpacity="0.9"
                  strokeWidth={routeVisual.innerWidth}
                  x1={line.x1}
                  x2={line.x2}
                  y1={line.y1}
                  y2={line.y2}
                />
                {arrowHead && (
                  <polygon
                    fill="#ea580c"
                    fillOpacity={Math.min(0.95, routeVisual.opacity + 0.14)}
                    points={arrowHead}
                    stroke="#fff7ed"
                    strokeLinejoin="round"
                    strokeWidth="1.1"
                  />
                )}
              </g>
            );
          })}

          {shapes.map((shape) => {
            const region = regionById.get(shape.id);
            if (!region) return null;

            const score =
              activeTab === "candidate"
                ? region.candidateScore
                : region.score;
            const label =
              activeTab === "change"
                ? `${periodRankById.get(region.id) ?? "-"}위`
                : `${rankById.get(region.id) ?? "-"}위`;

            return (
              <g key={`${shape.id}-label`}>
                <text
                  className="pointer-events-none select-none text-[15px] font-black fill-zippick-ink"
                  paintOrder="stroke"
                  stroke="white"
                  strokeWidth="4"
                  textAnchor="middle"
                  x={shape.labelX}
                  y={shape.labelY - 8}
                >
                  {region.name.replace("구", "")}
                </text>
                <text
                  className={cn(
                    "pointer-events-none select-none text-[13px] font-black",
                    getHeatTextClass(score)
                  )}
                  paintOrder="stroke"
                  stroke="white"
                  strokeWidth="4"
                  textAnchor="middle"
                  x={shape.labelX}
                  y={shape.labelY + 12}
                >
                  {label}
                </text>
              </g>
            );
          })}

          <defs>
            <filter
              height="140%"
              id="selectedShadow"
              width="140%"
              x="-20%"
              y="-20%"
            >
              <feDropShadow
                dx="0"
                dy="8"
                floodColor="#0f172a"
                floodOpacity="0.25"
                stdDeviation="6"
              />
            </filter>
          </defs>
        </svg>
      </div>

      {activeTab === "spread" && (
        <TimelinePlayer
          currentWeekIndex={currentWeekIndex}
          embedded
          isPlaying={isPlaying}
          onPlayToggle={onPlayToggle}
          onWeekChange={onWeekChange}
          weeks={weeks}
        />
      )}

      <div className="mt-4 grid grid-cols-5 gap-2 text-[12px] font-semibold text-zippick-body">
        {[
          ["bg-heat-cold", "냉각"],
          ["bg-heat-watch", "관망"],
          ["bg-heat-recover", "회복"],
          ["bg-heat-spread", "확산"],
          ["bg-heat-hot", "과열 주의"]
        ].map(([colorClass, label]) => (
          <div className="flex items-center gap-2" key={label}>
            <span className={cn("h-3 w-3 rounded-full", colorClass)} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
