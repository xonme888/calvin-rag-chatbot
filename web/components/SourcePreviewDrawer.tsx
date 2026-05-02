"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import type { CitationLabel } from "@/lib/api";

interface SourceItem {
  index: number; // 1-indexed (carousel 번호)
  label: CitationLabel | null;
  content: string;
}

interface Props {
  open: boolean;
  items: SourceItem[]; // drawer 안에 같이 보여줄 청크들 (보통 1~N)
  highlightedIndex?: number; // [N] 인라인 클릭 시 스크롤 타깃
  onClose: () => void;
}

/**
 * 인라인 [N] 또는 carousel 카드 클릭 시 우측에서 슬라이드 인 되는 출처 발췌 패널.
 * 백엔드 추가 호출 없음 — 답변 응답에 이미 포함된 source_documents 전문을 노출한다.
 *
 * - ESC / backdrop 클릭으로 닫기
 * - highlightedIndex 항목으로 자동 스크롤
 */
export function SourcePreviewDrawer({
  open,
  items,
  highlightedIndex,
  onClose,
}: Props) {
  // ESC 닫기
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // highlight 항목으로 스크롤
  useEffect(() => {
    if (!open || highlightedIndex == null) return;
    const el = document.getElementById(`src-item-${highlightedIndex}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [open, highlightedIndex, items]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40">
      {/* backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/30"
        onClick={onClose}
        aria-hidden
      />
      {/* drawer */}
      <aside
        className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-xl border-l border-slate-200 flex flex-col"
        role="dialog"
        aria-label="출처 발췌"
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <div>
            <h2 className="text-sm font-semibold text-ink">출처 발췌</h2>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {items.length}개 청크 · ESC 또는 바깥 영역 클릭으로 닫기
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100"
            aria-label="닫기"
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {items.length === 0 && (
            <p className="text-sm text-slate-400">
              표시할 출처 청크가 없습니다.
            </p>
          )}
          {items.map((item) => {
            const display = item.label?.display ?? `[${item.index}]`;
            const isHighlighted = highlightedIndex === item.index;
            return (
              <article
                key={item.index}
                id={`src-item-${item.index}`}
                className={[
                  "rounded-lg border p-3",
                  isHighlighted
                    ? "border-primary ring-2 ring-primary/30 bg-primary/5"
                    : "border-slate-200 bg-white",
                ].join(" ")}
              >
                <header className="flex items-center justify-between mb-2">
                  <span
                    className={[
                      "font-mono text-[11px] font-semibold",
                      isHighlighted ? "text-primary" : "text-slate-600",
                    ].join(" ")}
                  >
                    {display}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    [{item.index}]
                  </span>
                </header>
                <p className="text-[13px] text-slate-700 leading-relaxed whitespace-pre-wrap">
                  {item.content}
                </p>
              </article>
            );
          })}
        </div>
      </aside>
    </div>
  );
}

export type { SourceItem };
