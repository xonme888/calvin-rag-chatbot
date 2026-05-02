"use client";

import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { chatStream, chatSync, fetchModes } from "@/lib/api";
import type {
  CitationLabel,
  ChatStreamMeta,
  ChatSyncResponse,
  Mode,
  ModeInfo,
} from "@/lib/api";
import { AboutModal } from "./AboutModal";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { MessageHeader } from "./MessageHeader";
import { ModeSelector } from "./ModeSelector";
import { SourceCarousel } from "./SourceCarousel";
import { SuggestedPrompts } from "./SuggestedPrompts";

interface UIMessage {
  role: "user" | "assistant";
  content: string;
  meta?: ChatSyncResponse;
  streamMeta?: ChatStreamMeta; // Hybrid 모드 stream 종료 후 도착
  streaming?: boolean;
}

// sync 응답 또는 stream meta 에서 출처 정보 통합 추출
function extractSources(msg: UIMessage): {
  sources: string[];
  labels: Array<CitationLabel | null>;
} {
  if (msg.streamMeta) {
    return {
      sources: msg.streamMeta.source_documents,
      labels: msg.streamMeta.source_pages_label,
    };
  }
  if (msg.meta) {
    const labels =
      (msg.meta.metadata.source_pages_label as Array<CitationLabel | null>) ??
      [];
    return { sources: msg.meta.source_documents, labels };
  }
  return { sources: [], labels: [] };
}

export function ChatPanel() {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [mode, setMode] = useState<Mode>("hybrid");
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
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
    await sendQuestion(question);
  }

  async function sendQuestion(question: string) {
    if (busy) return;
    setError(null);
    setBusy(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true },
    ]);

    try {
      if (mode === "hybrid") {
        // Hybrid 는 SSE 스트리밍 (UX 임팩트). delta + 종료 직전 meta 1회 도착.
        let acc = "";
        let chunkCount = 0;
        let receivedMeta: ChatStreamMeta | undefined;
        for await (const chunk of chatStream({ question, mode })) {
          if (chunk.type === "meta") {
            receivedMeta = chunk.meta;
            if (process.env.NODE_ENV !== "production") {
              // eslint-disable-next-line no-console
              console.debug("[chat] meta 도착", receivedMeta);
            }
            continue;
          }
          // delta
          acc += chunk.text;
          chunkCount += 1;
          if (process.env.NODE_ENV !== "production") {
            // eslint-disable-next-line no-console
            console.debug(`[chat] chunk#${chunkCount} len=${acc.length}`);
          }
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
        if (acc === "" && process.env.NODE_ENV !== "production") {
          // eslint-disable-next-line no-console
          console.warn("[chat] stream 종료됐으나 누적 chunk가 비어 있음");
        }
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: "assistant",
            content: acc || "(빈 응답 — 백엔드 SSE 파싱 점검 필요)",
            streamMeta: receivedMeta,
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
      {/* 헤더 — 미니멀: 타이틀 + 정보 아이콘만 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white">
        <h1 className="text-lg font-semibold">칼빈 신학 챗봇</h1>
        <button
          type="button"
          onClick={() => setAboutOpen(true)}
          className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-700"
          aria-label="소개 열기"
          title="소개"
        >
          <Info size={18} />
        </button>
      </div>

      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />

      {/* 대화 영역 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <SuggestedPrompts onPick={sendQuestion} disabled={busy} />
        )}
        {messages.map((m, i) => {
          const { sources, labels } = extractSources(m);
          const isAssistant = m.role === "assistant";
          return (
            <div
              key={i}
              className={[
                "rounded-lg px-4 py-3 text-sm",
                m.role === "user"
                  ? "bg-primary text-white ml-12"
                  : "bg-white border border-slate-200 mr-12",
              ].join(" ")}
            >
              {/* 답변 헤더 meta 행 (응답시간 · 모드 · 토큰 · 신뢰도) */}
              {isAssistant && (m.meta || m.streamMeta) && (
                <MessageHeader
                  mode={mode}
                  syncMeta={m.meta}
                  streamMeta={m.streamMeta}
                />
              )}
              {/* 답변 위 출처 carousel (Perplexity 스타일) */}
              {isAssistant && sources.length > 0 && (
                <SourceCarousel sources={sources} labels={labels} />
              )}
              {/* 답변 본문 — assistant 면 markdown + 인라인 [p.N] 치환 */}
              {isAssistant ? (
                <MarkdownAnswer
                  content={m.content}
                  sources={sources}
                  labels={labels}
                />
              ) : (
                <div className="whitespace-pre-wrap leading-relaxed">
                  {m.content}
                </div>
              )}
              {isAssistant && m.streaming && (
                <span className="inline-block ml-1 animate-pulse text-slate-400">
                  ▍
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* 입력 영역 — 모드 토글이 입력창 위 */}
      {error && (
        <div className="px-4 py-2 bg-red-50 border-t border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="border-t border-slate-200 bg-white px-4 pt-3 pb-3">
        <div className="mb-2">
          <ModeSelector modes={modes} current={mode} onChange={setMode} />
        </div>
        <form onSubmit={handleSubmit} className="flex gap-2">
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
    </div>
  );
}
