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
  /**
   * 백그라운드 답변용 — 시작 시점의 sessionId 로 commit 한다.
   * 이걸 써야 사용자가 다른 세션 둘러봐도 원래 세션에 답변이 도착한다.
   */
  onUpdateById: (
    id: string,
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
  /** 현재 active session 이 응답 진행 중인지. */
  isPending: boolean;
  /** 진행 시작/종료 표시용 — 사이드바 dot 인디케이터 갱신. */
  markPending: (id: string, pending: boolean) => void;
}

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

function extractSubgraph(msg: SessionMessage): SubgraphData | null {
  const sg = msg.meta?.metadata.subgraph as SubgraphData | undefined;
  if (!sg || !Array.isArray(sg.nodes) || sg.nodes.length === 0) return null;
  return sg;
}

export function ChatPanel({
  session,
  onUpdate,
  onUpdateById,
  isPending,
  markPending,
}: ChatPanelProps) {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  // session.messages 가 단일 진실 소스 — local mirror 두지 않음
  const messages = session.messages;
  const [mode, setModeLocal] = useState<Mode>(session.mode);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null); // mode 로딩 등 oneshot 에러
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

  // 세션 전환 시 입력/draft/drawer 만 reset (진행 중 답변은 abort 하지 않음)
  useEffect(() => {
    setModeLocal(session.mode);
    setInput("");
    setError(null);
    setDrawer(null);
  }, [session.id, session.mode]);

  // messages 변화 시 자동 스크롤
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  function handleModeChange(m: Mode) {
    if (isPending) return;
    setModeLocal(m);
    onUpdate({ mode: m });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || isPending) return;
    const question = input.trim();
    setInput("");
    await sendQuestion(question);
  }

  async function sendQuestion(question: string) {
    if (isPending) return;
    setError(null);

    // 시작 시점의 sessionId 캡처 — 도중에 active 가 바뀌어도 이 값으로 commit
    const startedSessionId = session.id;
    const startMode = mode;
    markPending(startedSessionId, true);

    let next: SessionMessage[] = [
      ...session.messages,
      { role: "user", content: question },
      { role: "assistant", content: "", streaming: true },
    ];
    onUpdateById(startedSessionId, {
      messages: next,
      title: deriveTitle(next),
      mode: startMode,
    });

    try {
      if (startMode === "hybrid") {
        let text = "";
        let receivedMeta: ChatStreamMeta | undefined;
        for await (const chunk of chatStream({ question, mode: startMode })) {
          if (chunk.type === "meta") {
            receivedMeta = chunk.meta;
            continue;
          }
          text += chunk.text;
          next = [
            ...next.slice(0, -1),
            { role: "assistant", content: text, streaming: true },
          ];
          onUpdateById(startedSessionId, { messages: next });
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
        onUpdateById(startedSessionId, {
          messages: next,
          title: deriveTitle(next),
        });
      } else {
        const resp = await chatSync({ question, mode: startMode });
        next = [
          ...next.slice(0, -1),
          {
            role: "assistant",
            content: resp.answer,
            meta: resp,
            streaming: false,
          },
        ];
        onUpdateById(startedSessionId, {
          messages: next,
          title: deriveTitle(next),
        });
      }
    } catch (err: unknown) {
      // AbortError 는 거의 일어나지 않지만 안전 차원에서 처리
      if (err instanceof DOMException && err.name === "AbortError") return;
      const errMsg = err instanceof Error ? err.message : String(err);
      next = [
        ...next.slice(0, -1),
        {
          role: "assistant",
          content: `오류: ${errMsg}`,
          streaming: false,
        },
      ];
      onUpdateById(startedSessionId, {
        messages: next,
        title: deriveTitle(next),
      });
    } finally {
      markPending(startedSessionId, false);
    }
  }

  return (
    <div className="flex flex-col h-full flex-1 max-w-3xl w-full mx-auto">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white">
        <h1 className="text-lg font-semibold truncate flex items-center gap-2">
          {isPending && (
            <span
              aria-label="응답 진행 중"
              className="inline-block w-2 h-2 rounded-full bg-primary animate-pulse shrink-0"
            />
          )}
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

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <SuggestedPrompts onPick={sendQuestion} disabled={isPending} />
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
                  disabled={isPending}
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
            disabled={isPending}
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-primary disabled:bg-slate-100"
          />
          <button
            type="submit"
            disabled={isPending || !input.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {isPending ? "전송 중…" : "전송"}
          </button>
        </form>
      </div>
    </div>
  );
}
