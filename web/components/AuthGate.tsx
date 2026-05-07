"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Mail, LogOut } from "lucide-react";
import {
  getCurrentUser,
  isSupabaseEnabled,
  onAuthChange,
  sendMagicLink,
  signOut,
  type CurrentUser,
} from "@/lib/supabase";

interface Props {
  children: ReactNode;
}

type Phase = "loading" | "needs-login" | "link-sent" | "authenticated" | "skip";

/**
 * Supabase Auth 게이트 — Magic Link 로그인 (PR 14).
 *
 * 흐름:
 * 1. Supabase 미설정 (NEXT_PUBLIC_SUPABASE_URL/ANON_KEY 없음) → 즉시 통과 (skip).
 *    → InviteGate 또는 익명 흐름이 children 책임.
 * 2. 설정됨 → getCurrentUser. 로그인 상태면 통과 (authenticated).
 * 3. 미로그인 → 이메일 입력 → signInWithOtp → 메일 링크 클릭 → 콜백에서 세션 자동 저장.
 *
 * onAuthChange 구독 — 메일 링크 클릭 후 세션 저장 즉시 children 노출.
 */
export function AuthGate({ children }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isSupabaseEnabled()) {
      setPhase("skip");
      return;
    }
    let cancelled = false;
    (async () => {
      const u = await getCurrentUser();
      if (cancelled) return;
      if (u) {
        setUser(u);
        setPhase("authenticated");
      } else {
        setPhase("needs-login");
      }
    })();
    const unsub = onAuthChange((u) => {
      setUser(u);
      setPhase(u ? "authenticated" : "needs-login");
    });
    return () => {
      cancelled = true;
      unsub();
    };
  }, []);

  if (phase === "loading") {
    return null;
  }
  if (phase === "skip" || phase === "authenticated") {
    return (
      <>
        {phase === "authenticated" && user && <UserBadge user={user} />}
        {children}
      </>
    );
  }

  // needs-login / link-sent
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="w-full max-w-md p-8 bg-white rounded-lg shadow">
        <div className="flex items-center gap-2 mb-4">
          <Mail size={20} className="text-primary" />
          <h2 className="text-lg font-semibold">Calvin RAG 챗봇 로그인</h2>
        </div>
        {phase === "link-sent" ? (
          <p className="text-sm text-slate-600">
            <strong>{email}</strong> 로 로그인 링크를 전송했습니다. 메일을 열어 링크를 클릭하면
            자동으로 돌아옵니다.
          </p>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setError(null);
              setBusy(true);
              const { error: err } = await sendMagicLink(
                email.trim(),
                typeof window !== "undefined" ? window.location.origin : undefined,
              );
              setBusy(false);
              if (err) {
                setError(err);
                return;
              }
              setPhase("link-sent");
            }}
          >
            <label className="block text-sm font-medium text-slate-700 mb-1">
              이메일 주소
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded mb-3 text-sm"
              placeholder="you@example.com"
              autoFocus
            />
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            <button
              type="submit"
              disabled={busy || !email.trim()}
              className="w-full px-4 py-2 bg-primary text-white rounded disabled:opacity-50 text-sm"
            >
              {busy ? "전송 중..." : "로그인 링크 받기"}
            </button>
            <p className="mt-3 text-xs text-slate-500">
              비밀번호 없이 이메일로 로그인합니다. 메일 링크를 클릭하면 즉시 사용 가능합니다.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

function UserBadge({ user }: { user: CurrentUser }) {
  return (
    <div className="fixed top-2 right-2 flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-full shadow-sm text-xs z-50">
      <span className="text-slate-600 max-w-[160px] truncate">{user.email ?? user.id}</span>
      <button
        type="button"
        onClick={() => void signOut()}
        title="로그아웃"
        className="text-slate-400 hover:text-slate-700"
      >
        <LogOut size={12} />
      </button>
    </div>
  );
}
