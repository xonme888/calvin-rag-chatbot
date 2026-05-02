// FastAPI 클라이언트 — 자체 fetch + ReadableStream 으로 SSE 파싱.
// Vercel AI SDK useChat 의 stream protocol 호환성 회피 (단순/통제 가능).

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type Mode = "hybrid" | "agentic" | "kg";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  question: string;
  mode: Mode;
  chat_history?: ChatMessage[];
  dense_weight?: number;
}

export interface ChatSyncResponse {
  answer: string;
  source_documents: string[];
  metadata: Record<string, unknown>;
  elapsed_seconds: number;
}

export interface ModeInfo {
  name: Mode;
  label: string;
  available: boolean;
  reason: string | null;
}

export async function fetchModes(): Promise<ModeInfo[]> {
  const r = await fetch(`${API_BASE}/modes`, { cache: "no-store" });
  if (!r.ok) throw new Error(`/modes ${r.status}`);
  const j = await r.json();
  return j.modes;
}

export async function chatSync(req: ChatRequest): Promise<ChatSyncResponse> {
  const r = await fetch(`${API_BASE}/chat/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 200)}`);
  }
  return r.json();
}

// SSE 스트리밍 — 자체 ReadableStream 파싱.
// 백엔드 포맷 (sse-starlette EventSourceResponse):
//   data: {"type":"text-delta","delta":"..."}
//   ... (event: done) data: [DONE]
export async function* chatStream(req: ChatRequest): AsyncGenerator<string> {
  const r = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok || !r.body) {
    const text = r.body ? await r.text() : "";
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 200)}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 메시지 = "\n\n" 으로 구분
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      // "data: ..." 라인만 파싱 (event:, id: 등은 무시)
      const dataLines = raw
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6));
      if (dataLines.length === 0) continue;

      const payload = dataLines.join("\n");
      if (payload === "[DONE]") return;

      try {
        const obj = JSON.parse(payload);
        if (obj.type === "text-delta" && typeof obj.delta === "string") {
          yield obj.delta;
        }
      } catch {
        // JSON 아닌 chunk — 그대로 yield
        yield payload;
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
