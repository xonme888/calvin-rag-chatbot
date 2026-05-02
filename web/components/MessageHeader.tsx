"use client";

import type { ChatStreamMeta, ChatSyncResponse, Mode } from "@/lib/api";

interface Props {
  mode: Mode | null;
  syncMeta?: ChatSyncResponse;
  streamMeta?: ChatStreamMeta;
}

const MODE_LABEL: Record<Mode, string> = {
  hybrid: "Hybrid",
  agentic: "Agentic",
  kg: "Knowledge Graph",
};

/**
 * 답변 카드 상단 1행 — 응답시간 · 모드 · 토큰(in/out) · confidence.
 * Perplexity 스타일 답변 헤더.
 */
export function MessageHeader({ mode, syncMeta, streamMeta }: Props) {
  // sync 와 stream 양쪽에서 메타 추출
  const elapsed =
    syncMeta?.elapsed_seconds ?? streamMeta?.elapsed_seconds ?? null;
  const confidence =
    (syncMeta?.metadata.confidence as number | null | undefined) ??
    streamMeta?.confidence ??
    null;
  const tokensIn = streamMeta?.tokens?.input ?? null;
  const tokensOut = streamMeta?.tokens?.output ?? null;
  const pattern =
    (syncMeta?.metadata.pattern as string | undefined) ??
    streamMeta?.pattern ??
    (mode ? MODE_LABEL[mode] : null);

  // sync 응답에서 cached_hits 등 (Agentic mode 메타)
  const toolCallCount =
    (syncMeta?.metadata.tool_call_count as number | undefined) ?? null;

  const items: Array<{ label: string; value: string }> = [];
  if (elapsed != null) {
    items.push({ label: "응답", value: `${elapsed.toFixed(2)}초` });
  }
  if (pattern) {
    items.push({ label: "모드", value: pattern });
  }
  if (tokensIn != null || tokensOut != null) {
    items.push({
      label: "토큰",
      value: `in ${(tokensIn ?? 0).toLocaleString()} / out ${(tokensOut ?? 0).toLocaleString()}`,
    });
  }
  if (confidence != null) {
    items.push({ label: "신뢰도", value: confidence.toFixed(2) });
  }
  if (toolCallCount != null) {
    items.push({ label: "도구", value: `${toolCallCount}회` });
  }

  if (items.length === 0) return null;

  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
      {items.map((item, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          <span className="text-slate-400">{item.label}</span>
          <span className="font-medium text-slate-600">{item.value}</span>
          {i < items.length - 1 && (
            <span className="text-slate-300 ml-2">·</span>
          )}
        </span>
      ))}
    </div>
  );
}
