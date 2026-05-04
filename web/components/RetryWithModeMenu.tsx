"use client";

import { useState } from "react";
import { ChevronDown, RotateCw } from "lucide-react";
import type { RagMode } from "@/lib/api";

interface Props {
  /** 직전 답변에서 실제 호출된 모드 (라우팅 결과 포함). 메뉴에서 제외. */
  currentMode: RagMode | null;
  /** 클릭 시 호출 — 같은 질문을 새 모드로 재실행 */
  onRetry: (mode: RagMode) => void;
  disabled?: boolean;
}

const ALL_MODES: { name: RagMode; label: string }[] = [
  { name: "hybrid", label: "Hybrid" },
  { name: "agentic", label: "Agentic" },
  { name: "kg", label: "Knowledge Graph" },
];

/**
 * 답변 카드 푸터의 '다른 모드로 재시도' 드롭다운.
 * 사용자가 라우터 실수를 자기교정 + audit_log 의 user_overrode 시그널로 누적 →
 * 라우터 진화 (PRD-3 §C5/C6) 학습 데이터.
 */
export function RetryWithModeMenu({ currentMode, onRetry, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const choices = ALL_MODES.filter((m) => m.name !== currentMode);

  return (
    <div className="relative inline-block mt-3 pt-3 border-t border-slate-100">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-primary disabled:opacity-50"
      >
        <RotateCw size={11} />
        다른 모드로 재시도
        <ChevronDown size={11} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full mt-1 z-10 rounded-md border border-slate-200 bg-white shadow-md py-1 min-w-[140px]"
          onMouseLeave={() => setOpen(false)}
        >
          {choices.map((m) => (
            <button
              key={m.name}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onRetry(m.name);
              }}
              className="block w-full text-left px-3 py-1.5 text-[12px] text-slate-700 hover:bg-primary/5 hover:text-primary"
            >
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
