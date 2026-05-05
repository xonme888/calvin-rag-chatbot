"use client";

/**
 * 초대 코드 — localStorage 저장 + 백엔드 verify 호출 + fetch 헤더 첨부.
 *
 * 서버: GET /invite/status → enforcement_enabled
 *       POST /invite/verify {code} → 200 ok / 401 invalid
 * 클라: 첫 진입 시 status 조회. enforcement_enabled=false 면 InviteGate 자동 통과.
 *       enabled=true 면 localStorage 코드 검증 후 통과 / 실패 시 입력 화면.
 */

const KEY_INVITE_CODE = "calvin-chat:invite-code";

const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE) ||
  "http://localhost:8000";

export function getStoredInviteCode(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(KEY_INVITE_CODE);
}

export function setStoredInviteCode(code: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(KEY_INVITE_CODE, code);
}

export function clearStoredInviteCode(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(KEY_INVITE_CODE);
}

export interface InviteStatus {
  ok: boolean;
  enforcement_enabled: boolean;
}

/** 서버 검증 활성 여부 조회. 네트워크 실패 시 enforcement_enabled=true 보수적 반환. */
export async function fetchInviteStatus(): Promise<InviteStatus> {
  try {
    const r = await fetch(`${API_BASE}/invite/status`, { cache: "no-store" });
    if (!r.ok) return { ok: false, enforcement_enabled: true };
    return (await r.json()) as InviteStatus;
  } catch {
    return { ok: false, enforcement_enabled: true };
  }
}

/** 코드 검증 — 200 ok 시 true, 401 또는 네트워크 실패 시 false. */
export async function verifyInviteCode(code: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/invite/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

/** 모든 백엔드 fetch 에 자동 첨부할 헤더. */
export function inviteHeaders(): Record<string, string> {
  const code = getStoredInviteCode();
  return code ? { "X-Invite-Code": code } : {};
}
