"use client";

/**
 * Block 타입별 Renderer.
 *
 * 새 결과 타입 (이미지 / tool_call_trace / chart / MCP 결과) 추가 = blocks.ts 에
 * 타입 한 줄, 여기 RENDERERS 에 entry 한 줄. ChatPanel 무수정.
 */

import { type ReactNode } from "react";
import type { Block } from "@/lib/blocks";
import type { CitationLabel } from "@/lib/api";
import { FollowupChips } from "./FollowupChips";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { MessageHeader } from "./MessageHeader";
import { SourceCarousel } from "./SourceCarousel";
import { SubgraphView } from "./SubgraphView";
import type { SubgraphData } from "./SubgraphView";

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
}

type BlockRenderer<T extends Block["type"]> = (
  block: Extract<Block, { type: T }>,
  ctx: BlockContext,
) => ReactNode;

const RENDERERS: { [K in Block["type"]]: BlockRenderer<K> } = {
  user_text: (block) => (
    <div className="whitespace-pre-wrap leading-relaxed">{block.content}</div>
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
};

export function renderBlock(block: Block, ctx: BlockContext): ReactNode {
  // TS 가 union narrowing 을 record 인덱싱에서는 못 해주므로 캐스팅 1회
  const fn = RENDERERS[block.type] as BlockRenderer<typeof block.type>;
  return fn(block as never, ctx);
}
