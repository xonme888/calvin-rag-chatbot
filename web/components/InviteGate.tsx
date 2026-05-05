"use client";

import { useEffect, useState, type ReactNode } from "react";
import { KeyRound } from "lucide-react";
import {
  clearStoredInviteCode,
  fetchInviteStatus,
  getStoredInviteCode,
  setStoredInviteCode,
  verifyInviteCode,
} from "@/lib/invite";

interface Props {
  children: ReactNode;
}

type Phase = "loading" | "needs-code" | "passed";

/**
 * 초대 코드 게이트 — 외부 노출 단계의 1차 접근 제한.
 *
 * 흐름:
 * 1. /invite/status 로 enforcement 활성 여부 조회
 * 2. 비활성 → 즉시 통과 (개발 모드)
 * 3. 활성 + localStorage 코드 검증 통과 → 통과
 * 4. 그 외 → 입력 화면 노출
 */
export function InviteGate({ children }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const status = await fetchInviteStatus();
      if (cancelled) return;
      if (!status.enforcement_enabled) {
        setPhase("passed");
        return;
      }
      const stored = getStoredInviteCode();
      if (stored) {
        const ok = await verifyInviteCode(stored);
        if (cancelled) return;
        if (ok) {
          setPhase("passed");
          return;
        }
        // 저장된 코드가 만료/회수된 경우
        clearStoredInviteCode();
      }
      setPhase("needs-code");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(null);
    const trimmed = code.trim();
    const ok = await verifyInviteCode(trimmed);
    setBusy(false);
    if (ok) {
      setStoredInviteCode(trimmed);
      setPhase("passed");
    } else {
      setError("유효하지 않은 코드입니다. 운영자에게 받은 코드를 다시 확인해 주세요.");
    }
  }

  if (phase === "loading") {
    return (
      <main className="h-screen flex items-center justify-center text-sm text-slate-400">
        접근 권한 확인 중…
      </main>
    );
  }

  if (phase === "passed") {
    return <>{children}</>;
  }

  // needs-code
  return (
    <main className="h-screen flex items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm bg-white rounded-lg border border-slate-200 shadow-sm p-6 space-y-4"
      >
        <header className="flex items-center gap-2">
          <KeyRound size={18} className="text-primary" />
          <h1 className="text-base font-semibold">초대 코드 입력</h1>
        </header>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          본 서비스는 비영리 포트폴리오/학습 시연용으로 운영되며, 운영자에게 받은
          초대 코드로만 접근 가능합니다.
        </p>
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="초대 코드"
          autoFocus
          autoComplete="off"
          spellCheck={false}
          disabled={busy}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-primary disabled:bg-slate-100 font-mono"
        />
        {error && (
          <p className="text-[12px] text-rose-600">{error}</p>
        )}
        <button
          type="submit"
          disabled={busy || !code.trim()}
          className="w-full rounded-md bg-primary text-white px-3 py-2 text-sm disabled:opacity-50"
        >
          {busy ? "확인 중…" : "입장"}
        </button>
        <nav className="pt-2 border-t border-slate-100 flex gap-3 text-[11px] text-slate-400">
          <a href="/terms" className="hover:text-primary">서비스 약관</a>
          <a href="/privacy" className="hover:text-primary">개인정보 처리방침</a>
          <a href="/license" className="hover:text-primary">데이터 출처</a>
        </nav>
      </form>
    </main>
  );
}
