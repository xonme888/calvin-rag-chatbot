"use client";

import { ArrowRight } from "lucide-react";

interface Props {
  questions: string[];
  onPick: (question: string) => void;
  disabled?: boolean;
}

/**
 * 답변 직후 후속 질문 chip 그리드.
 * 클릭 시 즉시 새 질문으로 전송 (articulation barrier 제거).
 */
export function FollowupChips({ questions, onPick, disabled }: Props) {
  if (questions.length === 0) return null;
  return (
    <div className="mt-3 pt-3 border-t border-slate-100">
      <p className="text-[11px] font-medium text-slate-500 mb-2">
        이어서 물어볼 만한 질문
      </p>
      <div className="flex flex-col gap-1.5">
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="group flex items-center justify-between gap-2 text-left rounded-md border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-700 hover:border-primary hover:bg-primary/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="leading-snug">{q}</span>
            <ArrowRight
              size={14}
              className="text-slate-300 group-hover:text-primary shrink-0"
            />
          </button>
        ))}
      </div>
    </div>
  );
}
