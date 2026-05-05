"use client";

import { useState } from "react";
import type { MatchedTerm } from "@/lib/api";

interface Props {
  term: MatchedTerm;
  /** 답변 본문 안 실제 등장 단어 (alias 일 수 있음). */
  display: string;
}

/**
 * 답변 본문 안 글로서리 매칭 단어를 dotted underline 으로 wrap.
 * 호버/포커스 시 popover — 정의 + 출처 페이지.
 *
 * 글로서리는 정적 데이터라 LLM 환각 위험 0.
 */
export function TermTooltip({ term, display }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="border-b border-dotted border-slate-400 hover:border-primary hover:text-primary cursor-help"
        aria-label={`용어 설명: ${term.term}`}
      >
        {display}
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute bottom-full left-1/2 z-20 mb-1 w-80 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-700 shadow-lg"
        >
          <span className="block text-[11px] font-semibold text-primary mb-1">
            {term.term}
            {term.aliases.length > 0 && (
              <span className="ml-1 font-normal text-slate-400">
                ({term.aliases.slice(0, 2).join(", ")})
              </span>
            )}
          </span>
          <span className="block leading-relaxed">{term.definition}</span>
          {term.sources.length > 0 && (
            <span className="mt-2 pt-2 border-t border-slate-100 block text-[10px] text-slate-500">
              {term.sources.map((s) => s.label).join(" · ")}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
