"use client";

import { Plus, Trash2 } from "lucide-react";
import type { ChatSession } from "@/lib/sessionStore";

interface Props {
  sessions: ChatSession[];
  activeId: string | null;
  pendingIds?: ReadonlySet<string>;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  busy?: boolean;
}

const MODE_LABEL: Record<string, string> = {
  hybrid: "Hybrid",
  agentic: "Agentic",
  kg: "Knowledge Graph",
};

/**
 * 좌측 사이드바 — 멀티 세션 목록 + 새 대화 + 삭제.
 * 미니멀 톤 유지: w-60, slate-50 배경, 텍스트 위주.
 */
export function SessionSidebar({
  sessions,
  activeId,
  pendingIds,
  onSelect,
  onNew,
  onDelete,
  busy,
}: Props) {
  // updatedAt desc 정렬 (최근 활동 위)
  const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <aside className="hidden md:flex flex-col w-60 shrink-0 border-r border-slate-200 bg-slate-50">
      <button
        type="button"
        onClick={onNew}
        disabled={busy}
        className="m-2 flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:border-primary hover:bg-primary/5 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Plus size={15} />새 대화
      </button>
      <div className="flex-1 overflow-y-auto px-1 pb-2">
        {sorted.length === 0 && (
          <p className="text-xs text-slate-400 px-2 py-3">대화가 없습니다.</p>
        )}
        {sorted.map((s) => {
          const isActive = s.id === activeId;
          const isPending = pendingIds?.has(s.id) ?? false;
          return (
            <div
              key={s.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(s.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(s.id);
                }
              }}
              className={[
                "group relative rounded-md px-2 py-2 mb-0.5 cursor-pointer transition-colors text-sm border",
                isActive
                  ? "bg-white border-primary text-ink"
                  : "border-transparent hover:bg-white hover:border-slate-200 text-slate-700",
              ].join(" ")}
            >
              <div className="truncate pr-6 leading-tight flex items-center gap-1.5">
                {isPending && (
                  <span
                    aria-label="응답 진행 중"
                    title="응답 진행 중"
                    className="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-pulse shrink-0"
                  />
                )}
                <span className="truncate">{s.title || "새 대화"}</span>
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5 truncate">
                {MODE_LABEL[s.mode] ?? s.mode} · {s.messages.length} 메시지
                {isPending ? " · 응답 중" : ""}
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (isPending) {
                    alert("응답 중인 대화는 삭제할 수 없습니다.");
                    return;
                  }
                  if (confirm("이 대화를 삭제할까요?")) onDelete(s.id);
                }}
                className="absolute right-1.5 top-1.5 p-1 rounded hover:bg-rose-50 text-slate-300 hover:text-rose-500 opacity-0 group-hover:opacity-100 focus:opacity-100"
                aria-label="대화 삭제"
                title="삭제"
              >
                <Trash2 size={12} />
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
