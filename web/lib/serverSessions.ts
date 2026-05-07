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
import type { Mode } from "./api";

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
  trace_id: string;
  elapsed_ms: number;
  started_at: string;
}

interface ServerConversation {
  id: string;
  turns: ServerTurn[];
  created_at: string;
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
): ChatSession {
  const messages: SessionMessage[] = [];
  for (const turn of conv.turns) {
    messages.push({ role: "user", content: turn.user_message.content });
    messages.push({ role: "assistant", content: turn.answer.content });
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
    if (conv) sessions.push(serverConversationToSession(conv, summary));
  }
  return sessions;
}
