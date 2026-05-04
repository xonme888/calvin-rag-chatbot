"use client";

import { Database, Zap } from "lucide-react";
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

  // LLM 캐시 통계 — sync/stream 양쪽
  const cacheTotal =
    (syncMeta?.metadata.cache_total as number | undefined) ??
    streamMeta?.cache_total ??
    0;
  const cacheHits =
    (syncMeta?.metadata.cache_hits as number | undefined) ??
    streamMeta?.cache_hits ??
    0;
  const fromCache =
    (syncMeta?.metadata.from_cache as boolean | undefined) ??
    streamMeta?.from_cache ??
    false;

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

  // 캐시 배지 (별도) — LLM 호출이 1회 이상 있었을 때만
  let cacheBadge: { label: string; tone: "cache" | "fresh"; icon: typeof Database } | null = null;
  if (cacheTotal > 0) {
    if (fromCache) {
      cacheBadge = { label: "캐시", tone: "cache", icon: Database };
    } else if (cacheHits > 0) {
      cacheBadge = {
        label: `캐시 ${cacheHits}/${cacheTotal}`,
        tone: "cache",
        icon: Database,
      };
    } else {
      cacheBadge = { label: "신규", tone: "fresh", icon: Zap };
    }
  }

  if (items.length === 0 && !cacheBadge) return null;

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
      {cacheBadge && (
        <span
          className={[
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium ml-auto",
            cacheBadge.tone === "cache"
              ? "bg-sky-50 text-sky-700 border border-sky-200"
              : "bg-amber-50 text-amber-700 border border-amber-200",
          ].join(" ")}
          title={
            cacheBadge.tone === "cache"
              ? "LLM 캐시에서 응답 — 추가 토큰 비용 0"
              : "새로 LLM 호출됨 (캐시 miss)"
          }
        >
          <cacheBadge.icon size={10} />
          {cacheBadge.label}
        </span>
      )}
    </div>
  );
}
