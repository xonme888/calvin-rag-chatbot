"use client";

import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { chatStream, chatSync, fetchModes } from "@/lib/api";
import type { ChatStreamMeta, Mode, ModeInfo, RagMode } from "@/lib/api";
import { messageToBlocks } from "@/lib/blocks";
import {
  deriveTitle,
  type ChatSession,
  type SessionMessage,
} from "@/lib/sessionStore";
import { AboutModal } from "./AboutModal";
import { renderBlock, type BlockContext } from "./blockRenderers";
import { ModeSelector } from "./ModeSelector";
import { SourcePreviewDrawer } from "./SourcePreviewDrawer";
import type { SourceItem } from "./SourcePreviewDrawer";

interface ChatPanelProps {
  session: ChatSession;
  onUpdate: (
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
  onUpdateById: (
    id: string,
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
  isPending: boolean;
  markPending: (id: string, pending: boolean) => void;
}

// 메시지 sources/labels 를 한 번 추출 (drawer + Block context 공용)
function getSourcesFromMessage(msg: SessionMessage) {
  if (msg.streamMeta) {
    return {
      sources: msg.streamMeta.source_documents,
      labels: msg.streamMeta.source_pages_label,
    };
  }
  if (msg.meta) {
    const labels =
      (msg.meta.metadata.source_pages_label as
        | BlockContext["labels"]
        | undefined) ?? [];
    return { sources: msg.meta.source_documents, labels };
  }
  return { sources: [] as string[], labels: [] as BlockContext["labels"] };
}

export function ChatPanel({
  session,
  onUpdate,
  onUpdateById,
  isPending,
  markPending,
}: ChatPanelProps) {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const messages = session.messages; // session 이 단일 진실 소스
  const [mode, setModeLocal] = useState<Mode>(session.mode);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [drawer, setDrawer] = useState<{
    items: SourceItem[];
    highlightedIndex?: number;
  } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchModes()
      .then(setModes)
      .catch((e) => setError(`/modes 로드 실패: ${e.message}`));
  }, []);

  useEffect(() => {
    setModeLocal(session.mode);
    setInput("");
    setError(null);
    setDrawer(null);
  }, [session.id, session.mode]);

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

  async function sendQuestion(
    question: string,
    opts?: { mode?: Mode; previousMode?: RagMode | null },
  ) {
    if (isPending) return;
    setError(null);

    const startedSessionId = session.id;
    const startMode: Mode = opts?.mode ?? mode;
    const previousMode = opts?.previousMode ?? null;
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
      if (startMode === "hybrid" || startMode === "auto") {
        // auto/hybrid 는 SSE 스트리밍 시도. 백엔드 라우터가 다른 모드로
        // 결정하면 sync replay 로 자연스럽게 처리됨.
        let text = "";
        let receivedMeta: ChatStreamMeta | undefined;
        for await (const chunk of chatStream({
          question,
          mode: startMode,
          previous_mode: previousMode ?? undefined,
        })) {
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
        const resp = await chatSync({
          question,
          mode: startMode,
          previous_mode: previousMode ?? undefined,
        });
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
          <SuggestedPromptsLazy onPick={sendQuestion} disabled={isPending} />
        )}
        {messages.map((m, i) => {
          const isAssistantMsg = m.role === "assistant";
          const isLastAssistant =
            isAssistantMsg && i === messages.length - 1 && !m.streaming;
          const { sources, labels } = getSourcesFromMessage(m);
          // assistant 메시지의 직전 user 메시지를 retry_menu 에 전달
          const previousUserQuestion =
            isAssistantMsg && i > 0 && messages[i - 1]?.role === "user"
              ? messages[i - 1].content
              : undefined;

          const buildItems = (): SourceItem[] =>
            sources.map((content, idx) => ({
              index: idx + 1,
              label: labels[idx] ?? null,
              content,
            }));

          const ctx: BlockContext = {
            sources,
            labels,
            onCardClick: (index1Based) =>
              setDrawer({ items: buildItems(), highlightedIndex: index1Based }),
            onCitationClick: (page) => {
              let hi: number | undefined;
              for (let k = 0; k < labels.length; k++) {
                if (labels[k]?.page === page) {
                  hi = k + 1;
                  break;
                }
              }
              setDrawer({ items: buildItems(), highlightedIndex: hi });
            },
            onFollowupPick: (q) => sendQuestion(q),
            pendingFollowup: isPending,
            onRetry: (q, retryMode, prevMode) =>
              sendQuestion(q, { mode: retryMode, previousMode: prevMode }),
            pendingRetry: isPending,
          };

          const blocks = messageToBlocks(m, {
            isLastAssistant,
            previousUserQuestion,
          });

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
              {blocks.map((b, bi) => (
                <div key={bi}>{renderBlock(b, ctx)}</div>
              ))}
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

// SuggestedPrompts 는 빈 상태에서만 노출 — 별도 import (default lazy 불필요, alias)
import { SuggestedPrompts as SuggestedPromptsLazy } from "./SuggestedPrompts";
