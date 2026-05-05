/**
 * 메시지 → Block 분해. ChatPanel 의 if 분기를 외부화한다.
 *
 * 의도: 새 결과 타입 (이미지 / 도구 trace / 차트 / MCP 결과 등) 이 추가될 때
 * ChatPanel 을 건드리지 않고 Block 타입과 Renderer 한 쌍만 등록하면 끝나도록.
 *
 * 향후 확장 예시:
 * - { type: "image"; url; alt }
 * - { type: "tool_call_trace"; calls: [...] }
 * - { type: "chart"; spec: VegaSpec }
 */

import type { Attachment, CitationLabel, RagMode } from "./api";
import type { SessionMessage } from "./sessionStore";

// SubgraphData 는 컴포넌트 쪽에서 정의 — 순환 import 방지로 inline 재선언
interface SubgraphNode {
  id: string;
  label: string;
  type?: string;
  properties?: Record<string, unknown>;
}
interface SubgraphEdge {
  source: string;
  target: string;
  label?: string;
  properties?: Record<string, unknown>;
}
interface SubgraphPayload {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
}

// ====================================================================
// Block 타입 — 새 종류 추가 시 여기에 한 줄, RENDERERS 에 한 줄.
// ====================================================================
export type Block =
  | { type: "text"; content: string; streaming?: boolean }
  | { type: "user_text"; content: string }
  | { type: "user_images"; attachments: Attachment[] }
  | { type: "header"; mode: string | null; routedMode: string | null; autoRouted: boolean }
  | {
      type: "citations";
      sources: string[];
      labels: Array<CitationLabel | null>;
    }
  | { type: "subgraph"; data: SubgraphPayload }
  | {
      type: "tool_trace";
      calls: Array<{ tool: string; args?: Record<string, unknown> }>;
    }
  | { type: "followups"; questions: string[] }
  | { type: "retry_menu"; previousQuestion: string; currentMode: RagMode | null }
  // streaming 시점 placeholder — 메타 도착 전 영역 구조 유지
  | { type: "skeleton_header" }
  | { type: "skeleton_citations" }
  | { type: "skeleton_followups" };

// ====================================================================
// 메시지 → Block[] 어댑터.
// SessionMessage 구조는 그대로 유지하고 화면 분해만 수행 (백엔드 호환).
// ====================================================================

interface ToBlocksOpts {
  /** 마지막 assistant 메시지인가 — followups 노출 여부에 사용. */
  isLastAssistant: boolean;
  /** 직전 user 메시지의 question — retry_menu block 에 전달. */
  previousUserQuestion?: string;
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

function extractSubgraph(msg: SessionMessage): SubgraphPayload | null {
  // streamMeta 우선 (auto→KG 라우팅 시 SSE 경로) → 없으면 sync metadata
  const sg =
    (msg.streamMeta?.subgraph as SubgraphPayload | null | undefined) ??
    (msg.meta?.metadata.subgraph as SubgraphPayload | undefined);
  if (!sg || !Array.isArray(sg.nodes) || sg.nodes.length === 0) return null;
  return sg;
}

interface ParsedToolCall {
  tool: string;
  args?: Record<string, unknown>;
}

function extractToolCalls(msg: SessionMessage): ParsedToolCall[] {
  const raw =
    msg.streamMeta?.tool_calls ??
    (msg.meta?.metadata.tool_calls as
      | Array<Record<string, unknown>>
      | undefined);
  if (!Array.isArray(raw)) return [];
  const out: ParsedToolCall[] = [];
  for (const c of raw) {
    const tool = (c as Record<string, unknown>).tool;
    if (typeof tool !== "string") continue;
    const args = (c as Record<string, unknown>).args;
    out.push({
      tool,
      args:
        args && typeof args === "object"
          ? (args as Record<string, unknown>)
          : undefined,
    });
  }
  return out;
}

function extractRoutedMode(msg: SessionMessage): {
  routedMode: string | null;
  autoRouted: boolean;
} {
  const routed =
    (msg.meta?.metadata.routed_mode as string | undefined) ??
    msg.streamMeta?.routed_mode ??
    null;
  const auto =
    (msg.meta?.metadata.auto_routed as boolean | undefined) ??
    msg.streamMeta?.auto_routed ??
    false;
  return { routedMode: routed, autoRouted: auto };
}

export function messageToBlocks(
  msg: SessionMessage,
  opts: ToBlocksOpts,
): Block[] {
  if (msg.role === "user") {
    const blocks: Block[] = [];
    if (msg.user_attachments && msg.user_attachments.length > 0) {
      blocks.push({ type: "user_images", attachments: msg.user_attachments });
    }
    blocks.push({ type: "user_text", content: msg.content });
    return blocks;
  }

  const out: Block[] = [];
  const hasMeta = !!(msg.meta || msg.streamMeta);

  // 헤더: meta 도착 시 실제, 진행 중이면 skeleton (영역 자리 유지)
  if (hasMeta) {
    const { routedMode, autoRouted } = extractRoutedMode(msg);
    const mode =
      (msg.meta?.metadata.pattern as string | undefined) ??
      msg.streamMeta?.pattern ??
      null;
    out.push({ type: "header", mode, routedMode, autoRouted });
  } else if (msg.streaming) {
    out.push({ type: "skeleton_header" });
  }

  // 출처 carousel — 도착 전엔 skeleton 으로 자리 잡음
  const { sources, labels } = extractSources(msg);
  if (sources.length > 0) {
    out.push({ type: "citations", sources, labels });
  } else if (msg.streaming) {
    out.push({ type: "skeleton_citations" });
  }

  // KG subgraph
  const sg = extractSubgraph(msg);
  if (sg) {
    out.push({ type: "subgraph", data: sg });
  }

  // Agentic tool 호출 trace (도구 0회면 안 보임)
  const calls = extractToolCalls(msg);
  if (calls.length > 0) {
    out.push({ type: "tool_trace", calls });
  }

  // 본문 (markdown)
  out.push({ type: "text", content: msg.content, streaming: msg.streaming });

  // 후속 질문 — 마지막 답변에만. 진행 중엔 skeleton 으로 자리 잡음
  const followups = extractFollowups(msg);
  if (opts.isLastAssistant && !msg.streaming && followups.length > 0) {
    out.push({ type: "followups", questions: followups });
  } else if (msg.streaming) {
    out.push({ type: "skeleton_followups" });
  }

  // '다른 모드로 재시도' — 답변 완료 시점에 노출 (마지막 답변 외에도 가능)
  if (!msg.streaming && opts.previousUserQuestion) {
    const { routedMode } = extractRoutedMode(msg);
    out.push({
      type: "retry_menu",
      previousQuestion: opts.previousUserQuestion,
      currentMode: (routedMode as RagMode | null) ?? null,
    });
  }

  return out;
}
