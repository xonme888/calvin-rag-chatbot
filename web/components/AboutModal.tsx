"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * 데이터 / 기술 스택 / 모드 비교 팁 모달.
 * HTML <dialog> 사용 — backdrop 자동 처리, ESC 닫기 기본 동작.
 */
export function AboutModal({ open, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    if (!open && dlg.open) dlg.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        // backdrop 클릭 시 닫기
        if (e.target === ref.current) onClose();
      }}
      className="rounded-lg p-0 backdrop:bg-slate-900/50 max-w-lg w-full"
    >
      <div className="bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-semibold">소개</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100"
            aria-label="닫기"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm text-slate-700 max-h-[70vh] overflow-y-auto">
          <section>
            <h3 className="font-semibold text-ink mb-1">데이터</h3>
            <p>
              칼빈, <em>기독교 강요</em> 한국어 번역본 (1,251p). 개인 학습 ·
              포트폴리오 용도에 한정. 출판사 저작권은 원 저작권자에게 귀속.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-ink mb-1">기술 스택</h3>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Python 3.11 · FastAPI · LangChain 1.x / LangGraph 1.x</li>
              <li>Hybrid 검색 = BM25 + FAISS Dense + RRF</li>
              <li>Knowledge Graph: Neo4j + LLMGraphTransformer</li>
              <li>Next.js 15 · React 19 · Tailwind 3 · TypeScript 5</li>
            </ul>
          </section>

          <section>
            <h3 className="font-semibold text-ink mb-1">모드 비교 팁</h3>
            <ul className="space-y-1">
              <li>
                <span className="font-medium">Hybrid</span> — 일반 질문, 빠른
                응답이 필요할 때 (SSE 스트리밍).
              </li>
              <li>
                <span className="font-medium">Agentic</span> — 다단계 추론이
                필요한 복합 질문 (web 검색 도구 동원).
              </li>
              <li>
                <span className="font-medium">Knowledge Graph</span> — 인물 ·
                개념 관계를 그래프로 보고 싶을 때.
              </li>
            </ul>
          </section>

          <section className="text-xs text-slate-500 pt-2 border-t border-slate-200">
            <p className="mb-2">
              출처는 답변 위 카드와 본문 안 [N] 마커로 함께 제공됩니다.
            </p>
            <nav className="flex gap-3 text-[11px]">
              <a href="/terms" target="_blank" rel="noreferrer" className="hover:text-primary">
                서비스 약관
              </a>
              <a href="/privacy" target="_blank" rel="noreferrer" className="hover:text-primary">
                개인정보 처리방침
              </a>
              <a href="/license" target="_blank" rel="noreferrer" className="hover:text-primary">
                데이터 출처
              </a>
            </nav>
          </section>
        </div>
      </div>
    </dialog>
  );
}
