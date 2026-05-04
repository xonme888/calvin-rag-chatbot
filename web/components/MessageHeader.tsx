"use client";

import type { ChatStreamMeta, ChatSyncResponse, Mode } from "@/lib/api";

interface Props {
  mode: Mode | null;
  syncMeta?: ChatSyncResponse;
  streamMeta?: ChatStreamMeta;
}

const MODE_LABEL: Record<string, string> = {
  hybrid: "Hybrid",
  agentic: "Agentic",
  kg: "Knowledge Graph",
  auto: "자동",
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
  // 라우터 결과 우선 — 사용자에게는 실제로 호출된 모드를 보여준다
  const routedMode =
    (syncMeta?.metadata.routed_mode as string | undefined) ??
    streamMeta?.routed_mode ??
    null;
  const autoRouted =
    (syncMeta?.metadata.auto_routed as boolean | undefined) ??
    streamMeta?.auto_routed ??
    false;

  const baseMode =
    routedMode ?? (mode && mode !== "auto" ? mode : null);
  const pattern = baseMode
    ? autoRouted
      ? `자동 → ${MODE_LABEL[baseMode] ?? baseMode}`
      : MODE_LABEL[baseMode] ?? baseMode
    : (syncMeta?.metadata.pattern as string | undefined) ??
      streamMeta?.pattern ??
      null;

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
