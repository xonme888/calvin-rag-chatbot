"use client";

import { BookOpen, GitBranch, Scale, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

interface Prompt {
  category: "정의" | "요약" | "관계" | "비교";
  question: string;
  icon: ReactNode;
}

const PROMPTS: Prompt[] = [
  {
    category: "정의",
    question: "칼빈은 예정론을 어떻게 정의하는가?",
    icon: <Sparkles size={14} />,
  },
  {
    category: "요약",
    question: "기독교 강요 1권의 핵심 주제는 무엇인가?",
    icon: <BookOpen size={14} />,
  },
  {
    category: "관계",
    question: "어거스틴이 칼빈에게 미친 영향은?",
    icon: <GitBranch size={14} />,
  },
  {
    category: "비교",
    question: "칼빈의 성례론은 루터와 어떻게 다른가?",
    icon: <Scale size={14} />,
  },
  {
    category: "정의",
    question: "이신칭의는 무엇이며 칼빈은 어떻게 설명하는가?",
    icon: <Sparkles size={14} />,
  },
  {
    category: "요약",
    question: "칼빈은 교회의 직제를 어떻게 보았는가?",
    icon: <BookOpen size={14} />,
  },
];

interface Props {
  onPick: (question: string) => void;
  disabled?: boolean;
}

/**
 * 빈 채팅 첫 화면용 도메인 예시 질문 카드 그리드.
 * 클릭 시 곧바로 해당 질문을 전송한다.
 */
export function SuggestedPrompts({ onPick, disabled }: Props) {
  return (
    <div className="py-12">
      <div className="text-center mb-6">
        <p className="text-sm text-slate-500">
          질문을 직접 입력하거나, 아래 예시를 골라 시작해 보세요.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PROMPTS.map((p) => (
          <button
            key={p.question}
            type="button"
            disabled={disabled}
            onClick={() => onPick(p.question)}
            className="text-left rounded-lg border border-slate-200 bg-white px-3 py-3 hover:border-primary hover:bg-primary/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500 mb-1">
              {p.icon}
              {p.category}
            </span>
            <span className="text-sm text-slate-700 leading-snug block">
              {p.question}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
