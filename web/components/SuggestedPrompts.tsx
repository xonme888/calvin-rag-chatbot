"use client";

import { BookOpen, GitBranch, Scale, Search, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";

interface Prompt {
  category: "정의" | "요약" | "관계" | "비교" | "조회";
  expectedMode: "hybrid" | "agentic" | "kg"; // 자동 라우팅이 보낼 모드 — 시연용 가시화
  question: string;
  icon: ReactNode;
}

/**
 * 빈 첫 화면용 도메인 예시.
 *
 * 자동 라우팅이 잘 동작하는지 사용자가 바로 체감할 수 있도록 3 모드를 균등하게
 * 노출 (각 2개). 카드 라벨에 "자동 → Hybrid" 식 미리보기는 일부러 숨겨, 답변
 * 도착 후 헤더에서 라우팅 결과를 확인하는 흐름을 유도한다.
 */
const PROMPTS: Prompt[] = [
  // Hybrid (정의/요약 — 본문 인용 위주)
  {
    category: "정의",
    expectedMode: "hybrid",
    question: "예정론을 칼빈은 어떻게 정의하는가?",
    icon: <Sparkles size={14} />,
  },
  {
    category: "요약",
    expectedMode: "hybrid",
    question: "기독교 강요 1권의 핵심 주제는 무엇인가?",
    icon: <BookOpen size={14} />,
  },
  // KG (인물/개념 관계)
  {
    category: "관계",
    expectedMode: "kg",
    question: "어거스틴이 칼빈에게 미친 영향은?",
    icon: <GitBranch size={14} />,
  },
  {
    category: "관계",
    expectedMode: "kg",
    question: "칼빈의 신학에 영향을 준 인물들은 누가 있는가?",
    icon: <Users size={14} />,
  },
  // Agentic (비교/조회)
  {
    category: "비교",
    expectedMode: "agentic",
    question: "칼빈의 성례론은 루터와 어떻게 다른가?",
    icon: <Scale size={14} />,
  },
  {
    category: "조회",
    expectedMode: "agentic",
    question: "칼빈주의 5대 강령에 대한 최신 논의를 찾아줘",
    icon: <Search size={14} />,
  },
];

interface Props {
  onPick: (question: string) => void;
  disabled?: boolean;
}

export function SuggestedPrompts({ onPick, disabled }: Props) {
  return (
    <div className="py-12">
      <div className="text-center mb-6">
        <p className="text-sm text-slate-500">
          질문을 직접 입력하거나, 아래 예시를 골라 시작해 보세요.
        </p>
        <p className="text-[11px] text-slate-400 mt-1">
          자동 모드가 질문에 따라 적합한 검색 전략을 고릅니다.
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
