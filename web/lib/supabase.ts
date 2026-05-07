/**
 * Supabase 클라이언트 + Auth helpers (PRD-002 / TRD-011 PR 14).
 *
 * 사용 패턴:
 * - 환경변수 NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 빌드 시 정적 치환.
 * - 둘 중 하나라도 없으면 ``client = null`` — 레거시 InviteGate fallback (AUTH_ENABLED=false
 *   환경 동등). 기존 익명 흐름을 깨뜨리지 않는다.
 * - Magic Link: ``signInWithOtp(email)`` → 사용자 메일로 매직 링크 전송 → 클릭 시 콜백 URL
 *   (예: ``/auth/callback``) 으로 돌아와 세션 자동 저장.
 * - ``getAccessToken()`` 가 현재 JWT 반환 — api.ts 가 Authorization 헤더에 첨부.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/** Supabase 미설정 환경(로컬 dev 등)에서는 null. 호출자는 null 가드 후 익명 fallback. */
export const supabase: SupabaseClient | null =
  SUPABASE_URL && SUPABASE_ANON_KEY
    ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true, // Magic Link 콜백의 #access_token 자동 처리
        },
      })
    : null;

export const isSupabaseEnabled = (): boolean => supabase !== null;

/** 현재 로그인된 사용자의 access token (JWT). 미로그인이면 null. */
export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Magic Link 발송. 사용자가 메일 링크 클릭 → emailRedirectTo 로 돌아오면 세션 자동 저장. */
export async function sendMagicLink(
  email: string,
  emailRedirectTo?: string,
): Promise<{ error: string | null }> {
  if (!supabase) return { error: "Supabase 가 설정되지 않았습니다" };
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: emailRedirectTo ? { emailRedirectTo } : undefined,
  });
  return { error: error?.message ?? null };
}

export async function signOut(): Promise<void> {
  if (!supabase) return;
  await supabase.auth.signOut();
}

/** 현재 사용자 — 없으면 null. UI 의 "로그인 됨" 표시에 사용. */
export interface CurrentUser {
  id: string;
  email: string | null;
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getUser();
  if (!data.user) return null;
  return { id: data.user.id, email: data.user.email ?? null };
}

/** Auth 상태 변화 구독 — 로그인/로그아웃 즉시 UI 반영. cleanup 함수 반환. */
export function onAuthChange(
  listener: (user: CurrentUser | null) => void,
): () => void {
  if (!supabase) return () => undefined;
  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((_event, session) => {
    if (!session?.user) {
      listener(null);
      return;
    }
    listener({ id: session.user.id, email: session.user.email ?? null });
  });
  return () => subscription.unsubscribe();
}
