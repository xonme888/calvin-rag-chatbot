"use client";

import { get as idbGet, set as idbSet } from "idb-keyval";
import { useCallback, useEffect, useState } from "react";

import type {
  Attachment,
  ChatStreamMeta,
  ChatSyncResponse,
  Mode,
  ToolCallWire,
} from "./api";
import {
  deleteConversation as serverDeleteConversation,
  fetchAllConversations,
} from "./serverSessions";
import { getCurrentUser, onAuthChange } from "./supabase";

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
  /** 스트리밍 중 수신한 도구 호출(trace) 임시 버퍼. */
  streamToolCalls?: ToolCallWire[];
  streaming?: boolean;
  attachments?: SessionAttachment[]; // 향후 MCP/도구 결과
  /** 사용자 첨부 이미지 (vision 모드) — IndexedDB 에 base64 보관. */
  user_attachments?: Attachment[];
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

export function newSession(mode: Mode = "auto"): ChatSession {
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
  /** 특정 sessionId 를 직접 갱신. 백그라운드 답변이 startedSessionId 로 commit 할 때 사용. */
  updateById: (
    id: string,
    patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
  ) => void;
  /** 진행 중 답변이 있는 session id 집합 (메모리 only, 영속화 안 함). */
  pendingIds: ReadonlySet<string>;
  markPending: (id: string, pending: boolean) => void;
  ready: boolean;
}

export function useSessions(): UseSessionsResult {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);

  // mount 후 로딩:
  //   1) 로그인 사용자 → 서버 진실원천 fetchAllConversations (Supabase). 비어있으면
  //      IndexedDB fallback (옛 익명 세션 보존).
  //   2) 미로그인 → IndexedDB only (이전 동작 그대로).
  //   3) onAuthChange 구독 — 로그인/로그아웃 즉시 재로딩.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;

    async function loadSessions(): Promise<void> {
      const user = await getCurrentUser();
      if (cancelled) return;
      setIsAuthenticated(Boolean(user));

      let loaded: ChatSession[] | undefined;
      let storedActive: string | undefined = await idbGet(KEY_ACTIVE);

      if (user) {
        // 로그인 사용자 → 서버 진실원천 *only*. 비어있으면 빈 사이드바 (IndexedDB fallback X).
        // 익명 IndexedDB 데이터는 SessionMigrationPrompt 가 처리.
        loaded = await fetchAllConversations();
        if (cancelled) return;
      } else {
        // 익명 모드 → IndexedDB
        loaded = await idbGet(KEY_SESSIONS);
        // localStorage → IndexedDB 일회성 마이그레이션 (legacy)
        if (!loaded) {
          const lsRaw = localStorage.getItem(KEY_SESSIONS);
          if (lsRaw) {
            const fromLs = safeParse<ChatSession[]>(lsRaw, []);
            if (fromLs.length > 0) {
              await idbSet(KEY_SESSIONS, fromLs);
              loaded = fromLs;
              const lsActive = localStorage.getItem(KEY_ACTIVE);
              if (lsActive) {
                await idbSet(KEY_ACTIVE, lsActive);
                storedActive = lsActive;
              }
              localStorage.removeItem(KEY_SESSIONS);
              localStorage.removeItem(KEY_ACTIVE);
            }
          }
        }
      }
      if (cancelled) return;

      if (!loaded || loaded.length === 0) {
        const fresh = newSession();
        setSessions([fresh]);
        setActiveId(fresh.id);
      } else {
        setSessions(loaded);
        const matched = loaded.find((s) => s.id === storedActive);
        setActiveId(matched ? matched.id : loaded[0].id);
      }
      setReady(true);
    }

    void loadSessions();
    // 로그인/로그아웃 → 재로딩 (다기기 동기화 1차 — 새 디바이스 로그인 시 즉시 sync)
    const unsub = onAuthChange(() => {
      setReady(false);
      void loadSessions();
    });
    return () => {
      cancelled = true;
      unsub();
    };
  }, []);

  // sessions 변경 시 영속화 (비동기, fire-and-forget)
  useEffect(() => {
    if (!ready || isAuthenticated || typeof window === "undefined") return;
    void idbSet(KEY_SESSIONS, sessions);
  }, [sessions, ready, isAuthenticated]);

  useEffect(() => {
    if (!ready || isAuthenticated || !activeId || typeof window === "undefined")
      return;
    void idbSet(KEY_ACTIVE, activeId);
  }, [activeId, ready, isAuthenticated]);

  const active = sessions.find((s) => s.id === activeId) ?? null;

  const createNew = useCallback((mode: Mode = "auto"): string => {
    const fresh = newSession(mode);
    setSessions((prev) => [fresh, ...prev]);
    setActiveId(fresh.id);
    return fresh.id;
  }, []);

  const setActive = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const remove = useCallback((id: string) => {
    // 서버에도 삭제 요청 (로그인 시) — fire-and-forget
    void serverDeleteConversation(id);
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

  const updateById = useCallback(
    (
      id: string,
      patch: Partial<ChatSession> | ((s: ChatSession) => ChatSession),
    ) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== id) return s;
          const updated =
            typeof patch === "function" ? patch(s) : { ...s, ...patch };
          return { ...updated, updatedAt: Date.now() };
        }),
      );
    },
    [],
  );

  const markPending = useCallback((id: string, pending: boolean) => {
    setPendingIds((prev) => {
      const next = new Set(prev);
      if (pending) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  return {
    sessions,
    activeId,
    active,
    createNew,
    setActive,
    remove,
    updateActive,
    updateById,
    pendingIds,
    markPending,
    ready,
  };
}
