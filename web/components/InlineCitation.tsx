"use client";

import { useState } from "react";
import type { CitationLabel } from "@/lib/api";

interface Props {
  page: number;
  carouselIndex: number; // 1-indexed (사용자에게 보이는 [N])
  label: CitationLabel | null;
  preview: string;
  onActivate?: (page: number) => void;
}

/**
 * 답변 본문 안의 [p.N] 마커를 <sup> + hover popover 로 렌더.
 * 클릭 시 SourceCarousel 의 해당 카드 highlight (onActivate 콜백).
 */
export function InlineCitation({
  page,
  carouselIndex,
  label,
  preview,
  onActivate,
}: Props) {
  const [open, setOpen] = useState(false);
  const display = label?.display ?? `p.${page}`;

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => onActivate?.(page)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="mx-0.5 rounded bg-primary/10 px-1 text-[10px] font-semibold text-primary hover:bg-primary/20 align-super leading-none"
        aria-label={`출처 ${display}`}
      >
        [{carouselIndex}]
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute bottom-full left-1/2 z-10 mb-1 w-72 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-2 text-xs text-slate-600 shadow-lg"
        >
          <span className="block font-mono text-[11px] font-semibold text-primary">
            {display}
          </span>
          <span className="mt-1 block leading-relaxed line-clamp-4">
            {preview}
          </span>
        </span>
      )}
    </span>
  );
}
