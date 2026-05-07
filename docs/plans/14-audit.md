# PR 14 — 프론트 Supabase 절체 감사 보고서

TRD-011 PR 14 (사용자 결정 1 Magic Link Auth + 결정 4 Supabase 진실원천 + IndexedDB 캐시)
의 *프론트엔드* 산출물에 대한 독립 감사. 본 문서는 grep + Read + 실제 빌드/테스트
실행으로 작성되었다.

---

## 1. 요약 판정

**PASS**

- TypeScript strict (`tsc --noEmit`) 위반 0.
- 백엔드 회귀 (chatbot/ + chat_v2 + persistence + api_endpoints) **244 통과**.
- 결정 1 (Magic Link Auth) 구현: `signInWithOtp` + `onAuthChange` + `UserBadge` + `signOut`.
- 결정 4 (Supabase JWT → 백엔드 영속화) 통합: `Authorization: Bearer <JWT>` 첨부 +
  `ChatRequest.conversation_id` 송신.
- Supabase 미설정 환경에서 *기존 익명 흐름 회귀 0* (AuthGate 가 phase="skip" 통과 →
  InviteGate 가 children 책임).
- 클라이언트 anon key 외 비밀 키 노출 0 (web/ 트리에 SERVICE_KEY/SERVICE_ROLE 검색 결과 0건).

---

## 2. 체크리스트 결과

### A. 환경변수 정합 — PASS

- `web/lib/supabase.ts:15-16` — `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  만 사용. SUPABASE_SERVICE_KEY 미참조.
- `web/lib/supabase.ts:19-28` — 둘 중 하나라도 없으면 `supabase = null`.
  `isSupabaseEnabled()` (line 30) 가 이를 노출 → AuthGate.tsx:39 에서 phase="skip" 분기.

### B. 백엔드 envelope 호환 — PASS

- `web/lib/api.ts:46` — `conversation_id?: string` (TS).
- `api/schemas.py:64` — `conversation_id: str | None = Field(default=None, ...)` (Python).
- 키/타입 동일. optional 의미 동등 (없거나 null).
- `api.ts:11-18 authHeaders()` — invite_code (legacy) + Bearer JWT 통합.
  미로그인 시 `getAccessToken()` null → Authorization 헤더 미첨부 → 백엔드 익명 처리.

### C. 단일 책임 / 라인 한도 — PASS

| 파일 | 라인 | 한도 | 비고 |
|---|---:|---:|---|
| web/lib/supabase.ts | 85 | 100 | OK |
| web/components/AuthGate.tsx | 151 | 200 | OK (Magic Link UI + UserBadge 포함) |
| web/lib/api.ts authHeaders | 8 | 15 | OK (라인 11–18) |
| web/app/page.tsx | 53 | — | AuthGate→InviteGate→ChatHome 중첩만 |

### D. Supabase 미설정 fallback — PASS

- supabase=null → `isSupabaseEnabled()=false`.
- `getAccessToken()` → null (line 33-37) → `authHeaders()` 가 Authorization 미첨부.
- `AuthGate` (line 39-42) 즉시 phase="skip" → children 그대로 노출.
- 결과: PR 13 이전과 동일하게 InviteGate → 익명 chat 흐름.

### E. 인증 흐름 — PASS

- `sendMagicLink(email, emailRedirectTo)` (supabase.ts:40-50) — `signInWithOtp` 호출.
- AuthGate.tsx:97 — `window.location.origin` 을 emailRedirectTo 로 전달.
- `detectSessionInUrl: true` (supabase.ts:25) — Magic Link 콜백의 `#access_token` 자동 처리.
- `onAuthChange` 구독 (AuthGate.tsx:54-57) — 세션 저장 즉시 phase="authenticated" 갱신.
- UserBadge 의 signOut 클릭 (AuthGate.tsx:143) → onAuthChange 가 phase="needs-login" 복원.

### F. ChatPanel 통합 — PASS

- `ChatPanel.tsx:121` — `startedSessionId = session.id` (sessionStore.ts 의 crypto.randomUUID()
  발급 uuid → Supabase uuid 컬럼 호환).
- `ChatPanel.tsx:164, 197` — chatStream/chatSync 둘 다 `conversation_id: startedSessionId` 첨부.
- 미로그인 상태에서도 호출 가능 (Authorization 미첨부 → chat_v2 의 SupabaseUserIdentifier 가
  user_id=None 으로 처리 → store.save 미실행).

### G. TypeScript strict — PASS

- `cd web && npx tsc --noEmit` 종료 코드 0, 출력 0줄.
- 신규 인터페이스 (`CurrentUser`, `ChatRequest.conversation_id`) 모두 명시 타입.

### H. 백엔드 회귀 — PASS

- `python -m pytest tests/chatbot/ tests/test_chat_v2_endpoint.py
  tests/test_chat_v2_persistence.py tests/test_api_endpoints.py -q`
- 결과: **244 passed, 5 warnings in 4.72s** (DeprecationWarning 만, 비차단).

### I. 잠재적 결함 — INFO (작성 시점 미차단)

1. `persistSession=true` (supabase.ts:23) → localStorage 사용. 시크릿/멀티탭 동작은 Supabase
   기본 정책에 위임됨. README 또는 운영 가이드에 1줄 명시 권고.
2. `getAccessToken()` 매 호출 시 `supabase.auth.getSession()` 호출 — 캐시 없음.
   chatSync/chatStream 호출 직전 1회 — 메모리 조회 비용은 미미.
3. `onAuthChange` 가 user 상태만 갱신하므로 children 은 re-mount 되지 않는다 → 활성 SSE
   는 세션 변경 직후 끊기지 않음 (의도된 한계, 향후 토큰 갱신 시 SSE 재발신은 PR 16+).
4. `emailRedirectTo = window.location.origin` (AuthGate.tsx:97) → preview/staging 도메인
   에서 동작하려면 Supabase Dashboard 의 "Redirect URLs" 화이트리스트 등록이 운영 작업으로
   필요함. 코드 측 수정 사항은 아님.
5. PR 14 가 *사이드바를 Supabase 로 옮기지 않음* — IndexedDB 그대로. 다기기 동기화는 PR 15+.

### J. PR 15 시작 전 권고 — INFO

- 백엔드 `GET /conversations` 라우트 신설 (목록 + 페이징).
- `web/lib/sessionStore.ts` (useSessions) 의 IndexedDB 어댑터를 *Supabase 1차 + IndexedDB
  캐시* 로 절체. 충돌 정책: server timestamp wins.
- 일회성 마이그레이션 UI (IndexedDB → Supabase) — 첫 로그인 시 1회.
- Realtime 구독 (`postgres_changes`) — 다기기 즉시 반영.

---

## 3. 회귀 검증 결과

| 검증 | 명령 | 결과 |
|---|---|---|
| TypeScript strict | `cd web && npx tsc --noEmit` | exit 0, 출력 0줄 |
| 백엔드 pytest | `pytest tests/chatbot/ tests/test_chat_v2_endpoint.py tests/test_chat_v2_persistence.py tests/test_api_endpoints.py -q` | 244 passed |
| 이모지 grep | `grep` 정규식 (이모지 블록 4개) on 4개 산출물 | 0건 |
| Service key grep | `grep -rn "SERVICE_KEY\|service_key\|SERVICE_ROLE\|service_role" web/` | 0건 |

---

## 4. 위반 / 권고

위반: **없음**.

권고 (비차단):
- README 또는 `docs/guides/` 에 Supabase Dashboard "Redirect URLs" 등록 절차 1단락 추가.
- 운영 환경에서 anon key 가 web bundle 에 포함되는 점 (의도된 동작) 을 보안 문서에 명시 —
  RLS 가 진실원천 보호의 책임을 진다는 점을 명확히.

---

## 5. 통계

- 변경 파일: 6개 (package.json, lib/supabase.ts, lib/api.ts, components/AuthGate.tsx,
  app/page.tsx, components/ChatPanel.tsx).
- 신규 라인 (산출물 합): supabase.ts 85 + AuthGate.tsx 151 = 236 (신규).
- 백엔드 envelope 변경 0 (PR 13 에서 도입된 `conversation_id` 키만 활용).
- 백엔드 테스트: 244 통과 (chatbot 218 + chat_v2 envelope/endpoint/persistence + api_endpoints).
- 의존성 추가: 1개 (`@supabase/supabase-js ^2.105.3`).

---

## 6. TRD-011 결정 정합 평가

### 결정 1 (Magic Link Auth) — 충족

- 비밀번호 미사용 (`signInWithOtp` 만).
- 메일 링크 클릭 → `detectSessionInUrl=true` 가 콜백 토큰 자동 처리.
- `onAuthChange` → 즉시 UI 반영. 별도 `/auth/callback` 라우트 불필요.

### 결정 4 (Supabase 진실원천 + IndexedDB 캐시) — 부분 충족 (의도된 단계)

- 충족: 인증 토큰 → 백엔드 → conversations/messages 영속화 (PR 13 백엔드 + PR 14 프론트
  헤더 + conversation_id 송신).
- 미충족 (PR 15 영역): 세션 목록/메시지의 *조회 측* 절체 — 사이드바는 여전히 IndexedDB 가
  진실원천. 다기기 동기화는 다음 PR.
- 본 PR 의 본질은 "*서버측 영속화 활성화*" 이며, 이 범위에서는 충족.

### 단일 사용자 (혼자 + RLS) 가정 — 충족

- anon key 가 web bundle 에 노출되지만 RLS 로 보호되는 모델 (백엔드 store.load 가 user_id
  필터링 — chat_v2 envelope 에서 검증됨).
- ServiceKey 노출 0건 (grep 검증).

---

## 7. PR 15 시작 전 권고 재확인

1. `GET /conversations` (페이징, user_id 필터링은 RLS 또는 SupabaseUserIdentifier 의존).
2. `useSessions` 의 IndexedDB → Supabase 1차 절체. AsyncIterable + 낙관적 업데이트.
3. 마이그레이션 UI: 첫 로그인 시 IndexedDB 의 sessions 를 Supabase 로 1회 push.
4. Realtime 구독: `postgres_changes` 채널 → 다기기 즉시 반영. 본 PR 14 의 `onAuthChange`
   패턴과 유사하게 cleanup unsubscribe 명시.
5. 충돌 정책: server timestamp wins. updated_at 기준 last-write-wins.
