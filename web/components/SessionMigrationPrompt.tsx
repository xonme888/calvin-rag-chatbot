"use client";

import { Upload, Trash2, Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { del as idbDel, get as idbGet, set as idbSet } from "idb-keyval";

import type { ChatSession } from "@/lib/sessionStore";
import {
  fetchConversationList,
  migrateAnonymousSessions,
} from "@/lib/serverSessions";
import { getCurrentUser } from "@/lib/supabase";

const KEY_SESSIONS = "calvin-chat:sessions";
const KEY_ACTIVE = "calvin-chat:active";

function dismissKey(userId: string): string {
  return `calvin-chat:migration-dismissed:${userId}`;
}

/**
 * 일회성 마이그레이션 다이얼로그 (PR 15.3).
 *
 * 트리거 조건 — 다음을 모두 만족해야 모달 표시:
 *  1. 사용자가 인증됨 (Supabase Auth)
 *  2. IndexedDB 의 KEY_SESSIONS 에 1개 이상의 익명 대화가 있음
 *  3. 해당 user_id 로 dismiss 한 적 없음 (localStorage 플래그)
 *
 * 옵션:
 *  - 계정으로 옮기기: POST /conversations/migrate → 성공 시 IndexedDB clear → 페이지 새로고침
 *    (sessionStore 가 서버 진실원천으로 다시 로딩)
 *  - 익명에 보관 유지: dismiss 플래그만 저장, IndexedDB 그대로
 *  - 삭제: IndexedDB clear → 페이지 새로고침
 */
export function SessionMigrationPrompt(): React.ReactElement | null {
  const [phase, setPhase] = useState<"idle" | "ready" | "uploading" | "done">(
    "idle",
  );
  const [anonSessions, setAnonSessions] = useState<ChatSession[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resultMsg, setResultMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const user = await getCurrentUser();
      if (cancelled || !user) return;
      const dismissed = localStorage.getItem(dismissKey(user.id));
      if (dismissed === "1") return;
      const stored = (await idbGet(KEY_SESSIONS)) as ChatSession[] | undefined;
      const meaningful = (stored ?? []).filter(
        (s) => (s.messages?.length ?? 0) > 0,
      );
      if (cancelled) return;
      if (meaningful.length === 0) return;

      // 과거 버전에서 로그인 세션이 IndexedDB 로 미러링된 경우(오탐) 제외.
      // 서버에 이미 존재하는 conversation id 는 익명 마이그레이션 대상이 아니다.
      const serverList = await fetchConversationList(200);
      if (cancelled) return;
      const serverIds = new Set(serverList.map((c) => c.id));
      const anonymousOnly = meaningful.filter((s) => !serverIds.has(s.id));
      if (anonymousOnly.length === 0) return;

      setUserId(user.id);
      setAnonSessions(anonymousOnly);
      setPhase("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (phase === "idle") return null;

  async function handleUpload(): Promise<void> {
    setError(null);
    setPhase("uploading");
    const result = await migrateAnonymousSessions(anonSessions);
    if (!result) {
      setError("업로드 실패. 잠시 후 다시 시도하세요.");
      setPhase("ready");
      return;
    }
    // 부분 실패 보존 — 성공한 것만 IndexedDB 에서 제거. 실패한 항목은 그대로
    // 잔존시켜 사용자가 재시도하거나 수동으로 처리할 수 있게 한다 (audit M1).
    const skippedSet = new Set(result.skipped_ids ?? []);
    const remaining = anonSessions.filter((s) => skippedSet.has(s.id));
    if (remaining.length === 0) {
      await idbSet(KEY_SESSIONS, []);
      await idbDel(KEY_ACTIVE);
    } else {
      await idbSet(KEY_SESSIONS, remaining);
    }
    setResultMsg(
      `${result.saved}개 대화를 계정으로 옮겼습니다${
        result.skipped > 0
          ? ` (${result.skipped}개는 옮기지 못해 익명 보관소에 남겼습니다)`
          : ""
      }.`,
    );
    setPhase("done");
  }

  async function handleDelete(): Promise<void> {
    await idbSet(KEY_SESSIONS, []);
    await idbDel(KEY_ACTIVE);
    setResultMsg("익명 대화를 삭제했습니다.");
    setPhase("done");
  }

  function handleDismiss(): void {
    if (userId) {
      localStorage.setItem(dismissKey(userId), "1");
    }
    setPhase("done");
    setResultMsg(null);
  }

  function handleClose(): void {
    if (phase === "done" && resultMsg !== null) {
      // 데이터 변경됨 → 사이드바 재로딩
      window.location.reload();
      return;
    }
    setPhase("idle");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="w-full max-w-md p-6 bg-white rounded-lg shadow-lg">
        {phase === "done" ? (
          <div>
            <p className="text-sm text-slate-700 mb-4">
              {resultMsg ?? "이번 세션에선 묻지 않습니다."}
            </p>
            <button
              type="button"
              onClick={handleClose}
              className="w-full px-4 py-2 bg-primary text-white rounded text-sm"
            >
              확인
            </button>
          </div>
        ) : (
          <>
            <h2 className="text-base font-semibold mb-2 text-slate-900">
              이전 익명 대화를 어떻게 처리할까요?
            </h2>
            <p className="text-sm text-slate-600 mb-4">
              로그인 전에 이 브라우저에 저장된{" "}
              <strong>{anonSessions.length}개</strong> 대화가 있습니다. 계정으로
              옮기면 다른 기기에서도 볼 수 있습니다.
            </p>
            {error && (
              <p className="text-sm text-red-600 mb-3">{error}</p>
            )}
            <div className="space-y-2">
              <button
                type="button"
                disabled={phase === "uploading"}
                onClick={() => void handleUpload()}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-white rounded text-sm disabled:opacity-50"
              >
                <Upload size={14} />
                {phase === "uploading" ? "업로드 중..." : "계정으로 옮기기"}
              </button>
              <button
                type="button"
                disabled={phase === "uploading"}
                onClick={handleDismiss}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 rounded text-sm hover:bg-slate-200"
              >
                <Clock size={14} />
                나중에 결정 (이 기기 보관)
              </button>
              <button
                type="button"
                disabled={phase === "uploading"}
                onClick={() => void handleDelete()}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 text-red-600 rounded text-sm hover:bg-red-50"
              >
                <Trash2 size={14} />
                삭제
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
