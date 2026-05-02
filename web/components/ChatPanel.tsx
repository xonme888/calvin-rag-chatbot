"use client";

import { useEffect, useRef, useState } from "react";
import { chatStream, chatSync, fetchModes } from "@/lib/api";
import type { ChatSyncResponse, Mode, ModeInfo } from "@/lib/api";
import { ModeSelector } from "./ModeSelector";
import { SourceCard } from "./SourceCard";

interface UIMessage {
  role: "user" | "assistant";
  content: string;
  meta?: ChatSyncResponse;
  streaming?: boolean;
}

export function ChatPanel() {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [mode, setMode] = useState<Mode>("hybrid");
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 모드 목록 로드
  useEffect(() => {
    fetchModes()
      .then(setModes)
      .catch((e) => setError(`/modes 로드 실패: ${e.message}`));
  }, []);

  // 새 메시지 도착 시 스크롤
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy) return;
    const question = input.trim();
    setInput("");
    setError(null);
    setBusy(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true },
    ]);

    try {
      if (mode === "hybrid") {
        // Hybrid 는 SSE 스트리밍 (UX 임팩트)
        let acc = "";
        for await (const chunk of chatStream({ question, mode })) {
          acc += chunk;
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              role: "assistant",
              content: acc,
              streaming: true,
            };
            return next;
          });
        }
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: "assistant",
            content: acc,
            streaming: false,
          };
          return next;
        });
      } else {
        // Agentic / KG 는 sync (응답 완성 후 가드 풀 패스 + 메타 전체)
        const resp = await chatSync({ question, mode });
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: "assistant",
            content: resp.answer,
            meta: resp,
            streaming: false,
          };
          return next;
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          content: `오류: ${msg}`,
          streaming: false,
        };
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto">
      {/* 헤더 — 모드 셀렉터 */}
      <div className="px-4 py-3 border-b border-slate-200 bg-white">
        <h1 className="text-lg font-semibold mb-2">칼빈 신학 챗봇</h1>
        <p className="text-xs text-slate-500 mb-2">
          Hybrid (BM25+Dense+RRF) / Agentic (create_agent) / Knowledge Graph (Neo4j)
        </p>
        <ModeSelector modes={modes} current={mode} onChange={setMode} />
      </div>

      {/* 대화 영역 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-slate-400 py-12">
            <p className="text-sm">예: 칼빈은 예정론을 어떻게 정의하는가?</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={[
              "rounded-lg px-4 py-3 text-sm",
              m.role === "user"
                ? "bg-primary text-white ml-12"
                : "bg-white border border-slate-200 mr-12",
            ].join(" ")}
          >
            <div className="whitespace-pre-wrap leading-relaxed">
              {m.content}
              {m.streaming && <span className="ml-1 animate-pulse">▍</span>}
            </div>
            {m.meta && (
              <>
                <div className="mt-2 text-xs text-slate-400">
                  응답 시간 {m.meta.elapsed_seconds.toFixed(2)}초
                </div>
                <SourceCard sources={m.meta.source_documents} metadata={m.meta.metadata} />
              </>
            )}
          </div>
        ))}
      </div>

      {/* 입력 */}
      {error && (
        <div className="px-4 py-2 bg-red-50 border-t border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}
      <form
        onSubmit={handleSubmit}
        className="border-t border-slate-200 bg-white px-4 py-3 flex gap-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="질문을 입력하세요…"
          disabled={busy}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-primary disabled:bg-slate-100"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {busy ? "전송 중…" : "전송"}
        </button>
      </form>
    </div>
  );
}
