"use client";

/**
 * Block 타입별 Renderer.
 *
 * 새 결과 타입 (이미지 / tool_call_trace / chart / MCP 결과) 추가 = blocks.ts 에
 * 타입 한 줄, 여기 RENDERERS 에 entry 한 줄. ChatPanel 무수정.
 */

import { type ReactNode } from "react";
import type { Block } from "@/lib/blocks";
import type { CitationLabel, RagMode } from "@/lib/api";
import { FollowupChips } from "./FollowupChips";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { MessageHeader } from "./MessageHeader";
import { RetryWithModeMenu } from "./RetryWithModeMenu";
import { SourceCarousel } from "./SourceCarousel";
import { SubgraphView } from "./SubgraphView";
import type { SubgraphData } from "./SubgraphView";
import { ToolTraceView } from "./ToolTraceView";

// 렌더 시점에 메시지 단위로 주입되는 컨텍스트 (이벤트 콜백 + 공유 state)
export interface BlockContext {
  // citation/source 클릭 → drawer 열기
  onCitationClick: (page: number) => void;
  onCardClick: (index1Based: number) => void;
  // followups 클릭 → 새 질문 전송
  onFollowupPick: (question: string) => void;
  pendingFollowup: boolean;
  // citations block 이 본문 markdown 에서도 사용하도록 공유
  sources: string[];
  labels: Array<CitationLabel | null>;
  // retry_menu 클릭 → 같은 질문 다른 모드로 재전송
  onRetry: (question: string, mode: RagMode, previousMode: RagMode | null) => void;
  pendingRetry: boolean;
}

type BlockRenderer<T extends Block["type"]> = (
  block: Extract<Block, { type: T }>,
  ctx: BlockContext,
) => ReactNode;

const RENDERERS: { [K in Block["type"]]: BlockRenderer<K> } = {
  user_text: (block) => (
    <div className="whitespace-pre-wrap leading-relaxed">{block.content}</div>
  ),

  user_images: (block) => (
    <div className="flex flex-wrap gap-2 mb-2">
      {block.attachments.map((a, i) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={i}
          src={a.data_url}
          alt={a.name ?? `image-${i}`}
          className="max-w-[200px] max-h-[200px] rounded border border-white/30 object-cover"
        />
      ))}
    </div>
  ),

  header: (block) => {
    // MessageHeader 는 syncMeta/streamMeta 를 받지만, block 시점엔 이미 분해된
    // routed_mode 만 남아있어서 가짜 meta 객체로 어댑팅한다.
    const fakeSync = {
      answer: "",
      source_documents: [],
      metadata: {
        pattern: block.mode ?? undefined,
        routed_mode: block.routedMode ?? undefined,
        auto_routed: block.autoRouted,
      },
      elapsed_seconds: 0,
    };
    return <MessageHeader mode={null} syncMeta={fakeSync} />;
  },

  citations: (block, ctx) => (
    <SourceCarousel
      sources={block.sources}
      labels={block.labels}
      onCardClick={ctx.onCardClick}
    />
  ),

  subgraph: (block) => (
    <SubgraphView subgraph={block.data as SubgraphData} />
  ),

  tool_trace: (block) => <ToolTraceView calls={block.calls} />,

  text: (block, ctx) => (
    <>
      <MarkdownAnswer
        content={block.content}
        sources={ctx.sources}
        labels={ctx.labels}
        onCitationClick={ctx.onCitationClick}
      />
      {block.streaming && (
        <span className="inline-block ml-1 animate-pulse text-slate-400">▍</span>
      )}
    </>
  ),

  followups: (block, ctx) => (
    <FollowupChips
      questions={block.questions}
      onPick={ctx.onFollowupPick}
      disabled={ctx.pendingFollowup}
    />
  ),

  retry_menu: (block, ctx) => (
    <RetryWithModeMenu
      currentMode={block.currentMode}
      disabled={ctx.pendingRetry}
      onRetry={(mode) =>
        ctx.onRetry(block.previousQuestion, mode, block.currentMode)
      }
    />
  ),

  // ---- Skeletons ----
  skeleton_header: () => (
    <div className="mb-2 flex gap-2" aria-hidden>
      <div className="h-3 w-16 rounded bg-slate-100 animate-pulse" />
      <div className="h-3 w-24 rounded bg-slate-100 animate-pulse" />
      <div className="h-3 w-20 rounded bg-slate-100 animate-pulse" />
    </div>
  ),

  skeleton_citations: () => (
    <div className="mt-2 mb-3" aria-hidden>
      <div className="h-3 w-12 rounded bg-slate-100 animate-pulse mb-2" />
      <div className="flex gap-2 overflow-hidden">
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="shrink-0 w-64 h-[88px] rounded-md border border-slate-200 bg-slate-50/60"
          >
            <div className="p-3 flex flex-col gap-1.5">
              <div className="h-2.5 w-2/3 rounded bg-slate-200/70 animate-pulse" />
              <div className="h-2 w-full rounded bg-slate-100 animate-pulse" />
              <div className="h-2 w-full rounded bg-slate-100 animate-pulse" />
              <div className="h-2 w-3/4 rounded bg-slate-100 animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </div>
  ),

  skeleton_followups: () => (
    <div
      className="mt-3 pt-3 border-t border-slate-100 flex flex-col gap-1.5"
      aria-hidden
    >
      <div className="h-3 w-32 rounded bg-slate-100 animate-pulse mb-1" />
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-9 rounded-md border border-slate-100 bg-slate-50/60"
        />
      ))}
    </div>
  ),
};

export function renderBlock(block: Block, ctx: BlockContext): ReactNode {
  // TS 가 union narrowing 을 record 인덱싱에서는 못 해주므로 캐스팅 1회
  const fn = RENDERERS[block.type] as BlockRenderer<typeof block.type>;
  return fn(block as never, ctx);
}
