// FastAPI 클라이언트 — 자체 fetch + ReadableStream 으로 SSE 파싱.
// Vercel AI SDK useChat 의 stream protocol 호환성 회피 (단순/통제 가능).

import { inviteHeaders } from "./invite";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// 실제 백엔드 RAG 모드
export type RagMode = "hybrid" | "agentic" | "kg" | "vision";
// 클라이언트가 보낼 수 있는 값 — "auto" 면 백엔드 라우터가 결정
export type Mode = "auto" | RagMode;

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Attachment {
  type: "image";
  data_url: string; // data:image/jpeg;base64,... 또는 https:// URL
  name?: string;
}

export interface ChatRequest {
  question: string;
  mode: Mode;
  chat_history?: ChatMessage[];
  dense_weight?: number;
  previous_mode?: RagMode; // '다른 모드로 재시도' 시 직전 라우팅 모드
  attachments?: Attachment[]; // 이미지 등 — 비어있지 않으면 vision 모드 강제
}

// 단일 페이지 인용 라벨 — 백엔드 rag_core/citation_label.CitationLabel 와 동기화
export interface CitationLabel {
  page: number;
  section_slug: string | null;
  section_label: string | null;
  book: number | null;
  chapter: number | null;
  display: string; // 예: "p.780 (3권 21장)" 또는 "p.50"
}

// SSE stream 종료 직전 emit 되는 메타데이터 (event: meta)
export interface ChatStreamMeta {
  cited_pages: number[];
  source_documents: string[];
  source_pages: Array<number | null>;
  source_pages_label: Array<CitationLabel | null>;
  elapsed_seconds: number | null;
  confidence: number | null;
  pattern: string;
  mode: RagMode;
  routed_mode?: RagMode; // 라우터가 실제로 호출한 모드
  auto_routed?: boolean;
  tokens: { input: number; output: number };
  suggested_followups?: string[];
  // KG 모드 — sync/stream 양쪽에서 동일 envelope
  subgraph?: {
    nodes: Array<{ id: string; label: string; type?: string }>;
    edges: Array<{ source: string; target: string; label?: string }>;
  } | null;
  // Agentic 모드 — 도구 호출 정보
  tool_calls?: Array<Record<string, unknown>>;
  tool_call_count?: number;
  // LLM 캐시 통계 — 답변이 캐시에서 왔는지 표시
  cache_hits?: number;
  cache_misses?: number;
  cache_total?: number;
  cache_hit_rate?: number;
  from_cache?: boolean; // 모든 LLM 호출이 캐시 hit 이면 true
  // 글로서리 매칭 — 답변 안 inline tooltip 데이터
  matched_terms?: MatchedTerm[];
}

export interface MatchedTerm {
  term: string;
  aliases: string[];
  definition: string;
  sources: Array<{ page: number; label: string }>;
}

export interface ChatSyncResponse {
  answer: string;
  source_documents: string[];
  metadata: Record<string, unknown>;
  elapsed_seconds: number;
}

export interface ModeInfo {
  name: Mode; // "auto" 또는 RagMode 가능 (auto 는 프론트가 가상 추가)
  label: string;
  available: boolean;
  reason: string | null;
}

/** 글로서리 — 첫 진입 시 한 번 fetch, 이후 캐시. */
export async function fetchGlossary(): Promise<MatchedTerm[]> {
  try {
    const r = await fetch(`${API_BASE}/glossary`, { cache: "force-cache" });
    if (!r.ok) return [];
    const j = (await r.json()) as { terms?: MatchedTerm[] };
    return j.terms ?? [];
  } catch {
    return [];
  }
}

/**
 * 첫 답변 종료 후 cheap LLM 으로 짧은 세션 제목 생성.
 * 실패 시 빈 문자열 — 호출측은 deriveTitle 폴백.
 */
export async function generateAutoTitle(
  question: string,
  answer: string,
): Promise<string> {
  try {
    const r = await fetch(`${API_BASE}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...inviteHeaders() },
      body: JSON.stringify({ question, answer: answer.slice(0, 8000) }),
    });
    if (!r.ok) return "";
    const j = (await r.json()) as { title?: string };
    return (j.title ?? "").trim();
  } catch {
    return "";
  }
}

export async function fetchModes(): Promise<ModeInfo[]> {
  const r = await fetch(`${API_BASE}/modes`, { cache: "no-store" });
  if (!r.ok) throw new Error(`/modes ${r.status}`);
  const j = await r.json();
  return j.modes;
}

export async function chatSync(
  req: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatSyncResponse> {
  const r = await fetch(`${API_BASE}/chat/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...inviteHeaders() },
    body: JSON.stringify(req),
    signal,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 200)}`);
  }
  return r.json();
}

// SSE 스트리밍 — 자체 ReadableStream 파싱.
// 백엔드 포맷 (sse-starlette EventSourceResponse):
//   event: message
//   data: {"type":"text-delta","delta":"..."}
//
//   event: meta
//   data: {cited_pages, source_documents, source_pages_label, elapsed, ...}
//
//   event: done
//   data: [DONE]
const DEBUG_SSE = process.env.NODE_ENV !== "production";

// generator yield 형태 — text-delta 또는 종료 직전 1회 meta
export type ChatStreamChunk =
  | { type: "delta"; text: string }
  | { type: "meta"; meta: ChatStreamMeta };

export async function* chatStream(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamChunk> {
  const r = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...inviteHeaders(),
    },
    body: JSON.stringify(req),
    cache: "no-store",
    signal,
  });
  if (!r.ok || !r.body) {
    const text = r.body ? await r.text() : "";
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 200)}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    if (signal?.aborted) {
      try { await reader.cancel(); } catch { /* abort 시 cancel 실패 무시 */ }
      return;
    }
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // CRLF → LF 정규화 (서버/프록시 환경에 따라 \r\n 사용 가능)
    buffer = buffer.replace(/\r\n/g, "\n");

    // SSE 메시지 구분 = 빈 줄 ("\n\n")
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      // SSE: 한 메시지 안의 여러 라인 (event:, data:, id:, retry:)
      let eventType = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        } else if (line.startsWith("data:")) {
          // 공백 없는 형태도 허용
          dataLines.push(line.slice(5));
        } else if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith(":")) {
          // SSE comment (keep-alive ping) — 무시
          continue;
        }
      }
      if (dataLines.length === 0) continue;

      const payload = dataLines.join("\n");

      if (DEBUG_SSE) {
        // eslint-disable-next-line no-console
        console.debug("[SSE]", eventType, payload.slice(0, 80));
      }

      // 종료 시그널
      if (eventType === "done" || payload === "[DONE]") return;

      try {
        const obj = JSON.parse(payload);
        // event: meta — 종료 직전 1회 emit (cited_pages, source_pages_label 등)
        if (eventType === "meta") {
          yield { type: "meta", meta: obj as ChatStreamMeta };
          continue;
        }
        if (obj.type === "text-delta" && typeof obj.delta === "string") {
          yield { type: "delta", text: obj.delta };
        } else if (DEBUG_SSE) {
          // eslint-disable-next-line no-console
          console.warn("[SSE] unknown payload type:", obj);
        }
      } catch {
        // JSON 파싱 실패 — payload 가 [DONE] 등 plain text 일 수 있음
        if (payload && payload !== "[DONE]") {
          yield { type: "delta", text: payload };
        }
      }
    }
  }
}

export interface StatsResponse {
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_cost_krw: number;
  by_mode: Record<string, Record<string, unknown>>;
}

export async function fetchStats(): Promise<StatsResponse> {
  const r = await fetch(`${API_BASE}/stats`, { cache: "no-store" });
  if (!r.ok) throw new Error(`/stats ${r.status}`);
  return r.json();
}
