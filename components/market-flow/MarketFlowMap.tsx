"use client";

import type { KeyboardEvent } from "react";
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { MarketFlowLegend } from "@/components/market-flow/MarketFlowLegend";
import { seoulRegionMapShapes } from "@/lib/heatmap/seoul-map-shapes";
import type { FlowEdge, RegionNode } from "@/lib/market-flow/types";
import {
  formatFlowTitle,
  getNodeById,
  getNodeRadius,
  isEdgeConnectedToNode,
  statusCopy
} from "@/lib/market-flow/utils";
import { cn } from "@/lib/utils";

type MarketFlowMapProps = {
  edges: FlowEdge[];
  nodes: RegionNode[];
  selectedEdgeId: string | null;
  selectedNodeId: string | null;
  onClearSelection: () => void;
  onEdgeSelect: (edgeId: string) => void;
  onNodeSelect: (nodeId: string) => void;
};

type ViewBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type FlowPath = {
  d: string;
  selectX: number;
  selectY: number;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
};

const initialViewBox: ViewBox = {
  x: 125,
  y: 25,
  width: 715,
  height: 560
};

const seoulRegionNameById = new Map([
  ["dobong", "도봉구"],
  ["dongdaemun", "동대문구"],
  ["dongjak", "동작구"],
  ["eunpyeong", "은평구"],
  ["gangbuk", "강북구"],
  ["gangdong", "강동구"],
  ["gangnam", "강남구"],
  ["gangseo", "강서구"],
  ["geumcheon", "금천구"],
  ["guro", "구로구"],
  ["gwanak", "관악구"],
  ["gwangjin", "광진구"],
  ["jongno", "종로구"],
  ["jung", "중구"],
  ["jungnang", "중랑구"],
  ["mapo", "마포구"],
  ["nowon", "노원구"],
  ["seocho", "서초구"],
  ["seodaemun", "서대문구"],
  ["seongbuk", "성북구"],
  ["seongdong", "성동구"],
  ["songpa", "송파구"],
  ["yangcheon", "양천구"],
  ["yeongdeungpo", "영등포구"],
  ["yongsan", "용산구"]
]);

function viewBoxToString(viewBox: ViewBox) {
  return `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`;
}

function getFlowPath(
  edge: FlowEdge,
  nodeById: Map<string, RegionNode>
): FlowPath | null {
  const source = nodeById.get(edge.sourceRegionId);
  const target = nodeById.get(edge.targetRegionId);

  if (!source || !target) return null;

  const sourceRadius = getNodeRadius(source);
  const targetRadius = getNodeRadius(target);
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy);

  if (length < 1) return null;

  const unitX = dx / length;
  const unitY = dy / length;
  const sourceOffset = Math.min(sourceRadius + 8, length * 0.28);
  const targetOffset = Math.min(targetRadius + 14, length * 0.28);
  const startX = source.x + unitX * sourceOffset;
  const startY = source.y + unitY * sourceOffset;
  const endX = target.x - unitX * targetOffset;
  const endY = target.y - unitY * targetOffset;
  const curveDirection = edge.id.length % 2 === 0 ? 1 : -1;
  const curve = Math.min(44, Math.max(18, length * 0.12)) * curveDirection;
  const controlX = (startX + endX) / 2 - unitY * curve;
  const controlY = (startY + endY) / 2 + unitX * curve;
  const selectX = startX * 0.25 + controlX * 0.5 + endX * 0.25;
  const selectY = startY * 0.25 + controlY * 0.5 + endY * 0.25;

  return {
    d: `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`,
    selectX,
    selectY,
    startX,
    startY,
    endX,
    endY
  };
}

function getStrokeWidth(edge: FlowEdge) {
  if (edge.strength >= 86) return 3.2;
  if (edge.strength >= 70) return 2.6;
  return 2;
}

function getRegionFill(node: RegionNode | undefined, isSelected: boolean) {
  if (!node) return isSelected ? "#ffffff" : "#f8fafc";
  if (node.status === "leader") return isSelected ? "#f87171" : "#fca5a5";
  if (node.status === "spreading") return isSelected ? "#fb923c" : "#fdba74";
  return isSelected ? "#60a5fa" : "#bfdbfe";
}

function getRegionStroke(node: RegionNode | undefined, isSelected: boolean) {
  if (isSelected) return "#2563eb";
  if (node?.status === "leader") return "#fee2e2";
  if (node?.status === "spreading") return "#ffedd5";
  if (node?.status === "early") return "#dbeafe";
  return "#dbeafe";
}

function formatMomentumPercent(node: RegionNode | undefined) {
  if (!node) return "관찰중";
  return `${(node.priceMomentum / 40).toFixed(1).replace(".0", "")}%`;
}

function isKeyboardSelect(
  event: KeyboardEvent<SVGGElement | SVGPathElement | SVGCircleElement>
) {
  return event.key === "Enter" || event.key === " ";
}

export function MarketFlowMap({
  edges,
  nodes,
  selectedEdgeId,
  selectedNodeId,
  onClearSelection,
  onEdgeSelect,
  onNodeSelect
}: MarketFlowMapProps) {
  const [viewBox, setViewBox] = useState<ViewBox>(initialViewBox);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const dragStartRef = useRef<{ x: number; y: number; viewBox: ViewBox } | null>(
    null
  );
  const dragDistanceRef = useRef(0);
  const pendingMapActionRef = useRef<
    { type: "edge" | "node"; id: string } | null
  >(null);
  const suppressNextMapClearRef = useRef(false);

  const shapeById = useMemo(
    () => new Map(seoulRegionMapShapes.map((shape) => [shape.id, shape])),
    []
  );
  const displayNodes = useMemo(
    () =>
      nodes.map((node) => {
        const shape = shapeById.get(node.id);
        if (!shape) return node;

        return {
          ...node,
          x: shape.labelX,
          y: shape.labelY
        };
      }),
    [nodes, shapeById]
  );
  const nodeById = useMemo(
    () => new Map(displayNodes.map((node) => [node.id, node])),
    [displayNodes]
  );
  const regionNameById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node.name])),
    [nodes]
  );
  const selectedEdge = edges.find((edge) => edge.id === selectedEdgeId);
  const selectedNode =
    getNodeById(displayNodes, selectedNodeId) ??
    (selectedEdge
      ? getNodeById(displayNodes, selectedEdge.targetRegionId)
      : undefined);
  const tooltipNode = hoveredNodeId
    ? getNodeById(displayNodes, hoveredNodeId)
    : selectedNode;

  const zoom = (factor: number) => {
    setViewBox((current) => {
      const nextWidth = Math.max(390, Math.min(760, current.width * factor));
      const nextHeight = Math.max(305, Math.min(600, current.height * factor));
      const centerX = current.x + current.width / 2;
      const centerY = current.y + current.height / 2;

      return {
        x: Math.max(105, Math.min(835 - nextWidth, centerX - nextWidth / 2)),
        y: Math.max(25, Math.min(590 - nextHeight, centerY - nextHeight / 2)),
        width: nextWidth,
        height: nextHeight
      };
    });
  };

  return (
    <section className="rounded-lg border border-zippick-line bg-white p-4 shadow-panel">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-[18px] font-black text-zippick-ink">
            온기 확산 지도
          </h2>
          <p className="mt-1 text-[14px] leading-6 text-zippick-body">
            화살표는 먼저 움직인 지역에서 뒤따라 볼 지역으로 이어져요.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => zoom(0.82)} size="sm" variant="secondary">
            확대
          </Button>
          <Button onClick={() => zoom(1.18)} size="sm" variant="secondary">
            축소
          </Button>
          <Button
            onClick={() => {
              setViewBox(initialViewBox);
              onClearSelection();
            }}
            size="sm"
            variant="ghost"
          >
            초기화
          </Button>
        </div>
      </div>

      <div className="relative overflow-hidden rounded-lg border border-zippick-line bg-slate-50">
        <MarketFlowLegend />
        <svg
          aria-label="서울과 수도권 온기 흐름 지도"
          className="h-[520px] w-full touch-none select-none md:h-[640px]"
          onClick={(event) => {
            if (suppressNextMapClearRef.current) {
              suppressNextMapClearRef.current = false;
              return;
            }
            if (event.target === event.currentTarget && dragDistanceRef.current < 8) {
              onClearSelection();
            }
          }}
          onPointerDown={(event) => {
            const target = event.target as Element;
            const edgeTarget = target.closest("[data-edge-id]") as
              | HTMLElement
              | SVGElement
              | null;
            const nodeTarget = target.closest("[data-node-id]") as
              | HTMLElement
              | SVGElement
              | null;

            if (edgeTarget instanceof SVGElement || edgeTarget instanceof HTMLElement) {
              const edgeId = edgeTarget.dataset.edgeId;
              pendingMapActionRef.current = edgeId
                ? { type: "edge", id: edgeId }
                : null;
            } else if (
              nodeTarget instanceof SVGElement ||
              nodeTarget instanceof HTMLElement
            ) {
              const nodeId = nodeTarget.dataset.nodeId;
              pendingMapActionRef.current = nodeId
                ? { type: "node", id: nodeId }
                : null;
            } else {
              pendingMapActionRef.current = null;
            }

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
                105,
                Math.min(
                  835 - dragStart.viewBox.width,
                  dragStart.viewBox.x - dx * (dragStart.viewBox.width / 835)
                )
              ),
              y: Math.max(
                25,
                Math.min(
                  590 - dragStart.viewBox.height,
                  dragStart.viewBox.y - dy * (dragStart.viewBox.height / 590)
                )
              ),
              width: dragStart.viewBox.width,
              height: dragStart.viewBox.height
            });
          }}
          onPointerUp={(event) => {
            const pendingAction = pendingMapActionRef.current;
            if (pendingAction && dragDistanceRef.current < 8) {
              suppressNextMapClearRef.current = true;
              if (pendingAction.type === "edge") {
                onEdgeSelect(pendingAction.id);
              } else {
                onNodeSelect(pendingAction.id);
                setHoveredNodeId(pendingAction.id);
              }
            }
            pendingMapActionRef.current = null;
            dragStartRef.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onWheel={(event) => {
            event.preventDefault();
            zoom(event.deltaY < 0 ? 0.9 : 1.1);
          }}
          role="img"
          viewBox={viewBoxToString(viewBox)}
        >
          <defs>
            <marker
              id="flow-arrow"
              markerHeight="7"
              markerUnits="userSpaceOnUse"
              markerWidth="8"
              orient="auto"
              refX="7"
              refY="3.5"
            >
              <path d="M 0 0 L 7 3.5 L 0 7 z" fill="#ea580c" />
            </marker>
            <marker
              id="flow-arrow-selected"
              markerHeight="8"
              markerUnits="userSpaceOnUse"
              markerWidth="9"
              orient="auto"
              refX="8"
              refY="4"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" fill="#dc2626" />
            </marker>
            <filter
              height="150%"
              id="node-shadow"
              width="150%"
              x="-25%"
              y="-25%"
            >
              <feDropShadow
                dx="0"
                dy="8"
                floodColor="#0f172a"
                floodOpacity="0.24"
                stdDeviation="7"
              />
            </filter>
          </defs>

          <rect
            fill="#f8fafc"
            height="640"
            onClick={() => onClearSelection()}
            rx="22"
            width="900"
            x="80"
            y="0"
          />
          <path
            d="M 205 374 C 300 330 390 348 482 360 C 590 374 705 330 873 270 C 930 250 993 254 1050 276"
            fill="none"
            opacity="0.48"
            pointerEvents="none"
            stroke="#bfdbfe"
            strokeLinecap="round"
            strokeWidth="12"
          />

          {seoulRegionMapShapes.map((shape) => {
            const node = nodeById.get(shape.id);
            const isSelected =
              selectedNodeId === shape.id ||
              selectedEdge?.sourceRegionId === shape.id ||
              selectedEdge?.targetRegionId === shape.id;
            const shouldDim =
              Boolean(selectedEdgeId || selectedNodeId) && !isSelected;

            return (
              <path
                aria-label={`${seoulRegionNameById.get(shape.id) ?? shape.id}, ${
                  node ? statusCopy[node.status].label : "관찰 지역"
                }, 현재 온기 ${node?.heatScore ?? 0}점, 확산 가능성 ${
                  node?.propagationScore ?? 0
                }점`}
                className="cursor-pointer outline-none transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-300"
                d={shape.svgPath}
                data-node-id={node?.id}
                fill={getRegionFill(node, isSelected)}
                key={shape.id}
                onBlur={() => setHoveredNodeId(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  if (node && dragDistanceRef.current < 8) onNodeSelect(node.id);
                  if (node) setHoveredNodeId(node.id);
                }}
                onFocus={() => {
                  if (node) setHoveredNodeId(node.id);
                }}
                onKeyDown={(event) => {
                  if (!node || !isKeyboardSelect(event)) return;
                  event.preventDefault();
                  onNodeSelect(node.id);
                  setHoveredNodeId(node.id);
                }}
                onPointerEnter={() => {
                  if (node) setHoveredNodeId(node.id);
                }}
                onPointerLeave={() => setHoveredNodeId(null)}
                opacity={shouldDim ? 0.72 : 1}
                role={node ? "button" : "img"}
                stroke={getRegionStroke(node, isSelected)}
                strokeLinejoin="round"
                strokeWidth={isSelected ? 5 : 4}
                tabIndex={node ? 0 : -1}
              />
            );
          })}

          {edges.map((edge) => {
            const flowPath = getFlowPath(edge, nodeById);
            if (!flowPath) return null;

            const isSelected = selectedEdgeId === edge.id;
            const isConnected =
              selectedNodeId != null && isEdgeConnectedToNode(edge, selectedNodeId);
            const shouldDim = Boolean(selectedEdgeId || selectedNodeId) && !isSelected && !isConnected;
            const strokeWidth = getStrokeWidth(edge);
            const edgeLabel = `${formatFlowTitle(edge, regionNameById)}로 확산되는 흐름, 확산 가능성 ${edge.propagationScore}점, 평균 시차 ${edge.lagMinMonths}개월에서 ${edge.lagMaxMonths}개월`;

            return (
              <g key={edge.id}>
                <path
                  aria-hidden="true"
                  className="cursor-pointer"
                  data-edge-id={edge.id}
                  d={flowPath.d}
                  fill="none"
                  onClick={(event) => {
                    event.stopPropagation();
                    if (dragDistanceRef.current < 8) onEdgeSelect(edge.id);
                  }}
                  pointerEvents="stroke"
                  stroke="#111827"
                  strokeOpacity="0.01"
                  strokeLinecap="round"
                  strokeWidth={strokeWidth + 18}
                />
                <path
                  className={cn(isSelected && "market-flow-selected")}
                  data-flow-line={isSelected ? "selected" : undefined}
                  d={flowPath.d}
                  fill="none"
                  markerEnd={
                    isSelected ? "url(#flow-arrow-selected)" : "url(#flow-arrow)"
                  }
                  opacity={shouldDim ? 0.24 : isSelected ? 0.92 : 0.44}
                  pointerEvents="none"
                  stroke={isSelected ? "#dc2626" : "#ea580c"}
                  strokeLinecap="round"
                  strokeWidth={isSelected ? strokeWidth + 0.9 : strokeWidth}
                />
                {isSelected && (
                  <circle
                    className="market-flow-dot"
                    fill="#dc2626"
                    pointerEvents="none"
                    r="4.2"
                  >
                    <animateMotion
                      dur="2.6s"
                      path={flowPath.d}
                      repeatCount="indefinite"
                    />
                  </circle>
                )}
                <circle
                  aria-label={edgeLabel}
                  className="cursor-pointer outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-300"
                  cx={flowPath.selectX}
                  cy={flowPath.selectY}
                  data-edge-id={edge.id}
                  fill="#111827"
                  fillOpacity="0.01"
                  onClick={(event) => {
                    event.stopPropagation();
                    if (dragDistanceRef.current < 8) onEdgeSelect(edge.id);
                  }}
                  onKeyDown={(event) => {
                    if (!isKeyboardSelect(event)) return;
                    event.preventDefault();
                    onEdgeSelect(edge.id);
                  }}
                  r="16"
                  role="button"
                  tabIndex={0}
                >
                  <title>{formatFlowTitle(edge, regionNameById)}</title>
                </circle>
              </g>
            );
          })}

          {seoulRegionMapShapes.map((shape) => {
            const node = nodeById.get(shape.id);
            const regionName = seoulRegionNameById.get(shape.id) ?? shape.id;
            const isSelected =
              selectedNodeId === shape.id ||
              selectedEdge?.sourceRegionId === shape.id ||
              selectedEdge?.targetRegionId === shape.id;
            const shouldDim =
              Boolean(selectedEdgeId || selectedNodeId) && !isSelected;

            return (
              <g
                aria-hidden="true"
                key={`${shape.id}-label`}
                opacity={shouldDim ? 0.76 : 1}
                pointerEvents="none"
              >
                <text
                  className="select-none fill-slate-800 text-[15px] font-black"
                  paintOrder="stroke"
                  stroke="white"
                  strokeWidth="4"
                  textAnchor="middle"
                  x={shape.labelX}
                  y={shape.labelY - 4}
                >
                  {regionName}
                </text>
                <text
                  className="select-none fill-slate-700 text-[14px] font-bold"
                  paintOrder="stroke"
                  stroke="white"
                  strokeWidth="4"
                  textAnchor="middle"
                  x={shape.labelX}
                  y={shape.labelY + 15}
                >
                  {formatMomentumPercent(node)}
                </text>
              </g>
            );
          })}

          {displayNodes.filter((node) => !shapeById.has(node.id)).map((node) => {
            const isSelected =
              selectedNodeId === node.id ||
              selectedEdge?.sourceRegionId === node.id ||
              selectedEdge?.targetRegionId === node.id;
            const shouldDim = Boolean(selectedEdgeId || selectedNodeId) && !isSelected;
            const radius = getNodeRadius(node);
            const label = node.shortName ?? node.name;

            return (
              <g
                aria-label={`${node.name}, ${statusCopy[node.status].label}, 현재 온기 ${node.heatScore}점, 확산 가능성 ${node.propagationScore}점`}
                className="cursor-pointer outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-300"
                data-node-id={node.id}
                key={node.id}
                onBlur={() => setHoveredNodeId(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  if (dragDistanceRef.current < 8) onNodeSelect(node.id);
                  setHoveredNodeId(node.id);
                }}
                onFocus={() => setHoveredNodeId(node.id)}
                onKeyDown={(event) => {
                  if (!isKeyboardSelect(event)) return;
                  event.preventDefault();
                  onNodeSelect(node.id);
                  setHoveredNodeId(node.id);
                }}
                onPointerEnter={() => setHoveredNodeId(node.id)}
                onPointerLeave={() => setHoveredNodeId(null)}
                role="button"
                tabIndex={0}
              >
                <circle
                  className={cn(
                    "transition",
                    statusCopy[node.status].className,
                    shouldDim && "opacity-35"
                  )}
                  cx={node.x}
                  cy={node.y}
                  filter={isSelected ? "url(#node-shadow)" : undefined}
                  r={radius}
                  stroke={isSelected ? "#ffffff" : "#ffffff"}
                  strokeWidth={isSelected ? 6 : 4}
                />
                <circle
                  cx={node.x}
                  cy={node.y}
                  fill="none"
                  opacity={isSelected ? 0.85 : 0.22}
                  r={radius + 8}
                  stroke={
                    node.status === "leader"
                      ? "#fecaca"
                      : node.status === "spreading"
                        ? "#fed7aa"
                        : "#bfdbfe"
                  }
                  strokeWidth="5"
                />
                <text
                  className="pointer-events-none select-none fill-white text-[16px] font-black"
                  dominantBaseline="middle"
                  textAnchor="middle"
                  x={node.x}
                  y={node.y - 2}
                >
                  {label}
                </text>
                <text
                  className="pointer-events-none select-none fill-white/90 text-[11px] font-bold"
                  dominantBaseline="middle"
                  textAnchor="middle"
                  x={node.x}
                  y={node.y + 17}
                >
                  {statusCopy[node.status].label}
                </text>
              </g>
            );
          })}

          {tooltipNode && (
            <g className="pointer-events-none">
              <rect
                fill="white"
                height="94"
                rx="10"
                stroke="#e5e8eb"
                width="180"
                x={Math.min(tooltipNode.x + 22, 875)}
                y={Math.max(tooltipNode.y - 108, 70)}
              />
              <text
                className="fill-zippick-ink text-[15px] font-black"
                x={Math.min(tooltipNode.x + 38, 891)}
                y={Math.max(tooltipNode.y - 78, 100)}
              >
                {tooltipNode.name}
              </text>
              <text
                className="fill-zippick-body text-[13px] font-semibold"
                x={Math.min(tooltipNode.x + 38, 891)}
                y={Math.max(tooltipNode.y - 52, 126)}
              >
                상태: {statusCopy[tooltipNode.status].label}
              </text>
              <text
                className="fill-zippick-body text-[13px] font-semibold"
                x={Math.min(tooltipNode.x + 38, 891)}
                y={Math.max(tooltipNode.y - 30, 148)}
              >
                현재 온기: {tooltipNode.heatScore}점
              </text>
              <text
                className="fill-zippick-body text-[13px] font-semibold"
                x={Math.min(tooltipNode.x + 38, 891)}
                y={Math.max(tooltipNode.y - 8, 170)}
              >
                확산 가능성: {tooltipNode.propagationScore}점
              </text>
            </g>
          )}
        </svg>
      </div>
    </section>
  );
}
