"use client";

import { useCallback, useEffect, useState } from "react";

import type { ChatStreamMeta, ChatSyncResponse, Mode } from "./api";

/**
 * 멀티 세션 영속화 — 1차 구현은 localStorage.
 *
 * 향후 확장:
 * - MCP/도구/이미지 검색이 추가되면 ``SessionMessage.attachments`` 만 채워지면 됨
 * - 서버 영속화(SQLite/Cloud) 로 옮길 때 ``useSessions`` 인터페이스만 유지하면 swap 가능
 */

export interface SessionAttachment {
  /** 향후 도구 결과(MCP/web search/image search) 첨부용. 형태는 도구별로 자유. */
  type: string;
  payload: Record<string, unknown>;
}

export interface SessionMessage {
  role: "user" | "assistant";
  content: string;
  meta?: ChatSyncResponse;
  streamMeta?: ChatStreamMeta;
  streaming?: boolean;
  attachments?: SessionAttachment[]; // 향후 MCP/도구 결과
}

export interface ChatSession {
  id: string;
  title: string;
  mode: Mode;
  messages: SessionMessage[];
  createdAt: number;
  updatedAt: number;
}

const KEY_SESSIONS = "calvin-chat:sessions";
const KEY_ACTIVE = "calvin-chat:active";

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function generateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function newSession(mode: Mode = "hybrid"): ChatSession {
  const now = Date.now();
  return {
    id: generateId(),
    title: "새 대화",
    mode,
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

/** 첫 사용자 질문 앞 30자를 세션 타이틀로. */
export function deriveTitle(messages: SessionMessage[]): string {
  const firstUser = messages.find((m) => m.role === "user");
  if (!firstUser) return "새 대화";
  const t = firstUser.content.replace(/\s+/g, " ").trim();
  if (!t) return "새 대화";
  return t.length > 30 ? t.slice(0, 30) + "…" : t;
}

export interface UseSessionsResult {
  sessions: ChatSession[];
  activeId: string | null;
  active: ChatSession | null;
  createNew: (mode?: Mode) => string;
  setActive: (id: string) => void;
  remove: (id: string) => void;
  updateActive: (
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
  ready: boolean;
}

export function useSessions(): UseSessionsResult {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // mount 후 localStorage 로딩 (SSR/CSR mismatch 회피)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const loaded = safeParse<ChatSession[]>(
      localStorage.getItem(KEY_SESSIONS),
      [],
    );
    const storedActive = localStorage.getItem(KEY_ACTIVE);

    if (loaded.length === 0) {
      const fresh = newSession();
      setSessions([fresh]);
      setActiveId(fresh.id);
    } else {
      setSessions(loaded);
      const matched = loaded.find((s) => s.id === storedActive);
      setActiveId(matched ? matched.id : loaded[0].id);
    }
    setReady(true);
  }, []);

  // sessions 변경 시 영속화
  useEffect(() => {
    if (!ready || typeof window === "undefined") return;
    localStorage.setItem(KEY_SESSIONS, JSON.stringify(sessions));
  }, [sessions, ready]);

  useEffect(() => {
    if (!ready || !activeId || typeof window === "undefined") return;
    localStorage.setItem(KEY_ACTIVE, activeId);
  }, [activeId, ready]);

  const active = sessions.find((s) => s.id === activeId) ?? null;

  const createNew = useCallback((mode: Mode = "hybrid"): string => {
    const fresh = newSession(mode);
    setSessions((prev) => [fresh, ...prev]);
    setActiveId(fresh.id);
    return fresh.id;
  }, []);

  const setActive = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const remove = useCallback((id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      if (next.length === 0) {
        const fresh = newSession();
        setActiveId(fresh.id);
        return [fresh];
      }
      setActiveId((curr) => (curr === id ? next[0].id : curr));
      return next;
    });
  }, []);

  const updateActive = useCallback(
    (
      patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
    ) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeId) return s;
          const updated =
            typeof patch === "function" ? patch(s) : { ...s, ...patch };
          return { ...updated, updatedAt: Date.now() };
        }),
      );
    },
    [activeId],
  );

  return {
    sessions,
    activeId,
    active,
    createNew,
    setActive,
    remove,
    updateActive,
    ready,
  };
}
