/**
 * 서버 진실원천 — `/conversations` REST API 클라이언트 (PR 15).
 *
 * 흐름:
 * - 로그인 사용자만 — getAccessToken 이 null 이면 호출 자체 안 함.
 * - GET /conversations: 사용자별 ConversationSummary 목록.
 * - GET /conversations/{id}: full Conversation (state.turns 포함).
 * - DELETE /conversations/{id}: 삭제 (silent no-op for 다른 사용자).
 *
 * 백엔드 구조 (chatbot.domain.Conversation) 와 web/lib/sessionStore 의 ChatSession 형태가
 * 다르므로 ``serverConversationToSession`` 변환 헬퍼 포함.
 */

import { getAccessToken } from "./supabase";
import type { ChatSession, SessionMessage } from "./sessionStore";
import type { ChatSyncResponse, Mode } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface ServerConversationSummary {
  id: string;
  title: string | null;
  last_turn_at: string;
  turn_count: number;
}

interface ServerTurn {
  user_message: { role: "user"; content: string };
  answer: { role: "assistant"; content: string };
  selected_strategy: string | null;
  standalone_question: string | null;
  retrieval_result_ref: string | null;
  trace_id: string;
  elapsed_ms: number;
  started_at: string;
}

interface ServerConversation {
  id: string;
  turns: ServerTurn[];
  created_at: string;
}

interface TurnArtifactResponse {
  artifact: {
    pattern: string | null;
    selected_strategy: string | null;
    standalone_question: string | null;
    citations: Array<{ page: number | null; page_label: string; source: string }>;
    documents: Array<{
      source_id: string;
      page: number | null;
      chunk_ref: string;
      score: number | null;
      preview: string;
    }>;
    graph: {
      graph_node_count: number;
      graph_edge_count: number;
      top_nodes: string[];
      top_edges: string[];
    } | null;
    tool_call_count: number;
    tool_names: string[];
    index_version: string;
  };
  freshness: {
    is_stale: boolean;
    artifact_index_version: string;
    current_index_version: string;
    ttl_days: number;
  };
  stale_reasons: string[];
  requery_hint: { question: string; mode: string };
  notice: string;
}

async function authedHeaders(): Promise<Record<string, string> | null> {
  const token = await getAccessToken();
  if (!token) return null;
  return { Authorization: `Bearer ${token}` };
}

/** 사용자의 대화 목록. 미로그인 시 빈 배열. */
export async function fetchConversationList(
  limit = 50,
): Promise<ServerConversationSummary[]> {
  const headers = await authedHeaders();
  if (!headers) return [];
  const r = await fetch(`${API_BASE}/conversations?limit=${limit}`, { headers });
  if (!r.ok) return [];
  const j = (await r.json()) as { items: ServerConversationSummary[] };
  return j.items ?? [];
}

/** 특정 대화의 full Conversation. 미로그인 또는 없음/타인 소유 시 null. */
export async function fetchConversation(
  conversationId: string,
): Promise<ServerConversation | null> {
  const headers = await authedHeaders();
  if (!headers) return null;
  const r = await fetch(`${API_BASE}/conversations/${conversationId}`, { headers });
  if (!r.ok) return null;
  const j = (await r.json()) as { conversation: ServerConversation };
  return j.conversation ?? null;
}

async function fetchTurnArtifact(
  conversationId: string,
  turnIndex: number,
): Promise<TurnArtifactResponse | null> {
  const headers = await authedHeaders();
  if (!headers) return null;
  const r = await fetch(
    `${API_BASE}/conversations/${conversationId}/turns/${turnIndex}/artifact`,
    { headers },
  );
  if (!r.ok) return null;
  return (await r.json()) as TurnArtifactResponse;
}

/**
 * 익명 IndexedDB 대화 일괄 업로드 → Supabase. 미로그인 시 no-op.
 * 반환: { saved, skipped } — 실패한 단건은 skipped 로 카운트.
 */
export async function migrateAnonymousSessions(
  sessions: ChatSession[],
): Promise<{ saved: number; skipped: number; skipped_ids: string[] } | null> {
  const headers = await authedHeaders();
  if (!headers) return null;
  const r = await fetch(`${API_BASE}/conversations/migrate`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ conversations: sessions }),
  });
  if (!r.ok) return null;
  return (await r.json()) as {
    saved: number;
    skipped: number;
    skipped_ids: string[];
  };
}

/** 삭제. 미로그인 시 no-op. */
export async function deleteConversation(conversationId: string): Promise<void> {
  const headers = await authedHeaders();
  if (!headers) return;
  await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: "DELETE",
    headers,
  });
}

/**
 * 서버 Conversation → 클라이언트 ChatSession 변환. turns 시퀀스를 user/assistant 페어로 펼친다.
 * mode 는 `"auto"` 디폴트 (서버 메타에 mode 가 없음 — 라우터가 매 요청 결정).
 */
export function serverConversationToSession(
  conv: ServerConversation,
  summary: ServerConversationSummary,
  artifactByTurn: Record<number, TurnArtifactResponse | null> = {},
): ChatSession {
  const messages: SessionMessage[] = [];
  for (const [turnIndex, turn] of conv.turns.entries()) {
    messages.push({ role: "user", content: turn.user_message.content });
    const artifact = artifactByTurn[turnIndex];
    const assistant: SessionMessage = {
      role: "assistant",
      content: turn.answer.content,
    };
    if (artifact?.artifact) {
      assistant.meta = artifactToSyncMeta(artifact, turn.answer.content);
    }
    messages.push(assistant);
  }
  const ts = Date.parse(summary.last_turn_at) || Date.now();
  return {
    id: conv.id,
    title: summary.title ?? messages[0]?.content?.slice(0, 30) ?? "새 대화",
    mode: "auto" as Mode,
    messages,
    createdAt: Date.parse(conv.created_at) || ts,
    updatedAt: ts,
  };
}

function artifactToSyncMeta(
  raw: TurnArtifactResponse,
  answer: string,
): ChatSyncResponse {
  const sourceDocuments = raw.artifact.documents.map((d) => d.preview);
  const toolCalls = raw.artifact.tool_names.map((name) => ({ tool_name: name }));
  return {
    answer,
    source_documents: sourceDocuments,
    elapsed_seconds: 0,
    metadata: {
      pattern: raw.artifact.pattern,
      selected_strategy: raw.artifact.selected_strategy,
      standalone_question: raw.artifact.standalone_question,
      source_pages: raw.artifact.documents.map((d) => d.page),
      source_pages_label: raw.artifact.citations.map((c) => c.page_label),
      graph_summary: raw.artifact.graph,
      tool_call_count: raw.artifact.tool_call_count,
      tool_calls: toolCalls,
      stale_reasons: raw.stale_reasons,
      is_stale: raw.freshness.is_stale,
      requery_hint: raw.requery_hint,
      artifact_notice: raw.notice,
    },
  };
}

/**
 * 사용자의 모든 대화를 *목록 + 상세* 로 fetch. 첫 로딩 시 N+1 호출이라 단순한 사이드바엔
 * 목록만으로 충분 — 본 함수는 *full hydrate* (메시지 본문까지) 옵션. lazy loading 권장.
 */
export async function fetchAllConversations(): Promise<ChatSession[]> {
  const list = await fetchConversationList();
  if (list.length === 0) return [];
  const sessions: ChatSession[] = [];
  for (const summary of list) {
    const conv = await fetchConversation(summary.id);
    if (!conv) continue;
    const artifactByTurn: Record<number, TurnArtifactResponse | null> = {};
    const tasks = conv.turns.map((turn, idx) => {
      if (!turn.retrieval_result_ref) return Promise.resolve<[number, TurnArtifactResponse | null]>([idx, null]);
      return fetchTurnArtifact(conv.id, idx).then((artifact) => [idx, artifact] as const);
    });
    const results = await Promise.all(tasks);
    for (const [idx, artifact] of results) artifactByTurn[idx] = artifact;
    sessions.push(serverConversationToSession(conv, summary, artifactByTurn));
  }
  return sessions;
}
