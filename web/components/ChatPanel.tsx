"use client";

import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { chatStream, chatSync, fetchModes } from "@/lib/api";
import type {
  CitationLabel,
  ChatStreamMeta,
  Mode,
  ModeInfo,
} from "@/lib/api";
import {
  deriveTitle,
  type ChatSession,
  type SessionMessage,
} from "@/lib/sessionStore";
import { AboutModal } from "./AboutModal";
import { FollowupChips } from "./FollowupChips";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { MessageHeader } from "./MessageHeader";
import { ModeSelector } from "./ModeSelector";
import { SourceCarousel } from "./SourceCarousel";
import { SourcePreviewDrawer } from "./SourcePreviewDrawer";
import type { SourceItem } from "./SourcePreviewDrawer";
import { SubgraphView } from "./SubgraphView";
import type { SubgraphData } from "./SubgraphView";
import { SuggestedPrompts } from "./SuggestedPrompts";

interface ChatPanelProps {
  session: ChatSession;
  onUpdate: (
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
}

// sync 응답 또는 stream meta 에서 출처 정보 통합 추출
function extractSources(msg: SessionMessage): {
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

// sync metadata 또는 stream meta 에서 후속 질문 추출
function extractFollowups(msg: SessionMessage): string[] {
  const candidate =
    msg.streamMeta?.suggested_followups ??
    (msg.meta?.metadata.suggested_followups as string[] | undefined);
  return Array.isArray(candidate)
    ? candidate.filter((q) => typeof q === "string")
    : [];
}

function isAssistant(msg: SessionMessage): boolean {
  return msg.role === "assistant";
}

// KG 모드 응답에서 부분 그래프 추출 (sync 응답에만 존재)
function extractSubgraph(msg: SessionMessage): SubgraphData | null {
  const sg = msg.meta?.metadata.subgraph as SubgraphData | undefined;
  if (!sg || !Array.isArray(sg.nodes) || sg.nodes.length === 0) return null;
  return sg;
}

export function ChatPanel({ session, onUpdate }: ChatPanelProps) {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [messages, setMessages] = useState<SessionMessage[]>(session.messages);
  const [mode, setMode] = useState<Mode>(session.mode);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [drawer, setDrawer] = useState<{
    items: SourceItem[];
    highlightedIndex?: number;
  } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 모드 목록 로드 (1회)
  useEffect(() => {
    fetchModes()
      .then(setModes)
      .catch((e) => setError(`/modes 로드 실패: ${e.message}`));
  }, []);

  // 세션 전환 시 local 상태 동기화
  useEffect(() => {
    setMessages(session.messages);
    setMode(session.mode);
    setInput("");
    setError(null);
    setDrawer(null);
  }, [session.id]);

  // 새 메시지 도착 시 스크롤
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  function commit(nextMessages: SessionMessage[], nextMode?: Mode) {
    onUpdate({
      messages: nextMessages,
      title: deriveTitle(nextMessages),
      mode: nextMode ?? mode,
    });
  }

  function handleModeChange(m: Mode) {
    if (busy) return;
    setMode(m);
    onUpdate({ mode: m });
  }

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

    let next: SessionMessage[] = [
      ...messages,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true },
    ];
    setMessages(next);

    try {
      if (mode === "hybrid") {
        let text = "";
        let receivedMeta: ChatStreamMeta | undefined;
        for await (const chunk of chatStream({ question, mode })) {
          if (chunk.type === "meta") {
            receivedMeta = chunk.meta;
            continue;
          }
          text += chunk.text;
          next = [
            ...next.slice(0, -1),
            { role: "assistant", content: text, streaming: true },
          ];
          setMessages(next);
        }
        next = [
          ...next.slice(0, -1),
          {
            role: "assistant",
            content: text || "(빈 응답 — 백엔드 SSE 파싱 점검 필요)",
            streamMeta: receivedMeta,
            streaming: false,
          },
        ];
        setMessages(next);
      } else {
        const resp = await chatSync({ question, mode });
        next = [
          ...next.slice(0, -1),
          {
            role: "assistant",
            content: resp.answer,
            meta: resp,
            streaming: false,
          },
        ];
        setMessages(next);
      }
      commit(next);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setError(errMsg);
      next = [
        ...next.slice(0, -1),
        {
          role: "assistant",
          content: `오류: ${errMsg}`,
          streaming: false,
        },
      ];
      setMessages(next);
      commit(next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-full flex-1 max-w-3xl w-full mx-auto">
      {/* 헤더 — 미니멀: 타이틀 + 정보 아이콘만 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white">
        <h1 className="text-lg font-semibold truncate">
          {session.title || "칼빈 신학 챗봇"}
        </h1>
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
      <SourcePreviewDrawer
        open={drawer !== null}
        items={drawer?.items ?? []}
        highlightedIndex={drawer?.highlightedIndex}
        onClose={() => setDrawer(null)}
      />

      {/* 대화 영역 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <SuggestedPrompts onPick={sendQuestion} disabled={busy} />
        )}
        {messages.map((m, i) => {
          const { sources, labels } = extractSources(m);
          const followups = isAssistant(m) ? extractFollowups(m) : [];
          const isLastAssistant =
            m.role === "assistant" && i === messages.length - 1 && !m.streaming;
          const isAssistantMsg = m.role === "assistant";

          const buildItems = (): SourceItem[] =>
            sources.map((content, idx) => ({
              index: idx + 1,
              label: labels[idx] ?? null,
              content,
            }));

          const handleCitationClick = (page: number) => {
            let hi: number | undefined;
            for (let k = 0; k < labels.length; k++) {
              if (labels[k]?.page === page) {
                hi = k + 1;
                break;
              }
            }
            setDrawer({ items: buildItems(), highlightedIndex: hi });
          };

          const handleCardClick = (index1Based: number) => {
            setDrawer({ items: buildItems(), highlightedIndex: index1Based });
          };

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
              {isAssistantMsg && (m.meta || m.streamMeta) && (
                <MessageHeader
                  mode={mode}
                  syncMeta={m.meta}
                  streamMeta={m.streamMeta}
                />
              )}
              {isAssistantMsg && sources.length > 0 && (
                <SourceCarousel
                  sources={sources}
                  labels={labels}
                  onCardClick={handleCardClick}
                />
              )}
              {isAssistantMsg &&
                (() => {
                  const sg = extractSubgraph(m);
                  return sg ? <SubgraphView subgraph={sg} /> : null;
                })()}
              {isAssistantMsg ? (
                <MarkdownAnswer
                  content={m.content}
                  sources={sources}
                  labels={labels}
                  onCitationClick={handleCitationClick}
                />
              ) : (
                <div className="whitespace-pre-wrap leading-relaxed">
                  {m.content}
                </div>
              )}
              {isAssistantMsg && m.streaming && (
                <span className="inline-block ml-1 animate-pulse text-slate-400">
                  ▍
                </span>
              )}
              {isLastAssistant && followups.length > 0 && (
                <FollowupChips
                  questions={followups}
                  onPick={sendQuestion}
                  disabled={busy}
                />
              )}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="px-4 py-2 bg-red-50 border-t border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="border-t border-slate-200 bg-white px-4 pt-3 pb-3">
        <div className="mb-2">
          <ModeSelector modes={modes} current={mode} onChange={handleModeChange} />
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
