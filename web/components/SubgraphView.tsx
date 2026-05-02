"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

// react-force-graph-2d 는 canvas 사용 — SSR 비활성
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="h-[280px] flex items-center justify-center text-xs text-slate-400">
      그래프 로딩 중…
    </div>
  ),
});

interface GraphNode {
  id: string;
  label: string;
  type?: string;
  properties?: Record<string, unknown>;
}

interface GraphEdge {
  source: string;
  target: string;
  label?: string;
  properties?: Record<string, unknown>;
}

export interface SubgraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface Props {
  subgraph: SubgraphData;
  height?: number;
}

// 시각적으로 구분되며 차분한 톤. 등장 순서대로 매핑된다.
const PALETTE = [
  "#6366f1", // indigo
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // rose
  "#0ea5e9", // sky
  "#8b5cf6", // violet
  "#14b8a6", // teal
  "#f43f5e", // pink
  "#64748b", // slate (fallback)
];

/**
 * KG 모드 답변에 동봉되는 부분 그래프(`metadata.subgraph`)를 force-directed 로 렌더.
 * - 노드 색상: type 별 직접 매핑 (등장 순서) — 헤더에 범례 노출
 * - 엣지 라벨: 호버 시 툴팁
 * - 화살표: source → target 방향
 *
 * 백엔드 추가 호출 0 — KG 답변 응답에 이미 포함된 데이터만 사용.
 */
export function SubgraphView({ subgraph, height = 280 }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(320);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(() => {
      setWidth(el.clientWidth);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // type 별 색상 매핑 (등장 순서 보존, palette 순환)
  const typeColor = useMemo(() => {
    const order: string[] = [];
    for (const n of subgraph.nodes) {
      const t = n.type ?? "Entity";
      if (!order.includes(t)) order.push(t);
    }
    const map = new Map<string, string>();
    order.forEach((t, i) => map.set(t, PALETTE[i % PALETTE.length]));
    return { order, get: (t: string) => map.get(t) ?? PALETTE[PALETTE.length - 1] };
  }, [subgraph.nodes]);

  // react-force-graph 형식으로 변환 (edges → links)
  const data = useMemo(
    () => ({
      nodes: subgraph.nodes.map((n) => ({
        id: n.id,
        name: n.label,
        type: n.type ?? "Entity",
        color: typeColor.get(n.type ?? "Entity"),
      })),
      links: subgraph.edges.map((e) => ({
        source: e.source,
        target: e.target,
        label: e.label ?? "",
      })),
    }),
    [subgraph, typeColor],
  );

  if (!subgraph.nodes.length) return null;

  return (
    <div
      ref={wrapRef}
      className="my-3 rounded-md border border-slate-200 bg-slate-50/50 overflow-hidden"
    >
      <div className="px-3 py-2 text-xs text-slate-500 border-b border-slate-200 flex items-center justify-between">
        <span>
          지식 그래프 — 노드 {subgraph.nodes.length} · 관계{" "}
          {subgraph.edges.length}
        </span>
        <span className="text-[10px] text-slate-400">드래그/스크롤로 탐색</span>
      </div>

      {/* type 별 색상 범례 */}
      <div className="px-3 py-2 border-b border-slate-200 flex flex-wrap gap-x-3 gap-y-1">
        {typeColor.order.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-1 text-[11px] text-slate-600"
          >
            <span
              aria-hidden
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: typeColor.get(t) }}
            />
            {t}
          </span>
        ))}
      </div>

      <ForceGraph2D
        graphData={data}
        width={width}
        height={height}
        nodeRelSize={5}
        nodeLabel="name"
        linkLabel="label"
        nodeCanvasObject={(node, ctx, globalScale) => {
          const n = node as {
            x?: number;
            y?: number;
            name?: string;
            color?: string;
          };
          if (n.x == null || n.y == null) return;
          const label = n.name ?? "";
          const fontSize = 11 / globalScale;
          ctx.font = `${fontSize}px sans-serif`;
          ctx.fillStyle = n.color ?? "#64748b";
          ctx.beginPath();
          ctx.arc(n.x, n.y, 5, 0, 2 * Math.PI, false);
          ctx.fill();
          ctx.fillStyle = "#0f172a";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, n.x, n.y + 10);
        }}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkColor={() => "#cbd5e1"}
        cooldownTicks={120}
      />
    </div>
  );
}
