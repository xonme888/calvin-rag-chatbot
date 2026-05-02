"use client";

import type { CitationLabel } from "@/lib/api";

interface Props {
  sources: string[];
  labels: Array<CitationLabel | null>;
  highlightedPage?: number | null; // 인라인 [p.N] 클릭 시 활성 카드 표시 (C5)
}

/**
 * 답변 *위*에 가로 스크롤 출처 카드 N개. Perplexity 스타일.
 * - 라벨: "p.780 (3권 21장)" 또는 "p.50" (5단원 외)
 * - 카드 클릭 영역: 미리보기 240자
 * - highlightedPage: 인라인 [p.N] 클릭 시 해당 카드 강조 (C5에서 활성)
 */
export function SourceCarousel({ sources, labels, highlightedPage }: Props) {
  if (sources.length === 0) return null;

  return (
    <div className="mt-2 mb-3">
      <div className="text-xs text-slate-500 mb-1">
        출처 ({sources.length}개)
      </div>
      <div
        className="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1"
        style={{ scrollbarWidth: "thin" }}
      >
        {sources.map((src, i) => {
          const label = labels[i] ?? null;
          const display = label?.display ?? `[${i + 1}]`;
          const isHighlighted =
            highlightedPage != null && label?.page === highlightedPage;
          const preview = src.replace(/\n/g, " ").slice(0, 200);

          return (
            <div
              key={i}
              className={[
                "shrink-0 w-64 rounded-md border bg-white p-3 text-xs transition-colors",
                isHighlighted
                  ? "border-primary ring-2 ring-primary/30"
                  : "border-slate-200",
              ].join(" ")}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className={[
                    "font-mono text-[11px] font-semibold",
                    isHighlighted ? "text-primary" : "text-slate-600",
                  ].join(" ")}
                >
                  {display}
                </span>
                <span className="text-[10px] text-slate-400">[{i + 1}]</span>
              </div>
              <p className="text-slate-600 leading-relaxed line-clamp-4">
                {preview}
                {src.length > 200 ? "…" : ""}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
