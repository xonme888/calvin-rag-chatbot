---
status: draft
group: B
created: 2026-05-04
related_prd: docs/prd/draft/002-multi-device-sync.md
---

# TRD-002: 인증 + 다기기 세션 동기화 (Supabase)

## 1. AS-IS 분석

### 1.1 세션 영속화 — 브라우저 localStorage 단일

`web/lib/sessionStore.ts` 219줄. 핵심 로딩/저장 지점:

- line 39~40: `KEY_SESSIONS = "calvin-chat:sessions"`, `KEY_ACTIVE = "calvin-chat:active"`
- line 107~125: mount 시 `localStorage.getItem(KEY_SESSIONS)` 로 한 번 로딩
- line 128~131: `sessions` state 변경마다 `localStorage.setItem` 으로 저장
- line 133~136: activeId 변경마다 동일

소비처:

- `web/app/page.tsx:8` — `const session = useSessions()` 단일 진입점
- `web/components/SessionSidebar.tsx`, `web/components/ChatPanel.tsx` — props 로 전달

결과:
- 브라우저 단위 격리. 데스크톱 ↔ 모바일 세션 공유 불가.
- 시크릿 모드/데이터 삭제 시 전 세션 소실.
- localStorage 5~10MB 한계 (현재는 여유 있음).

### 1.2 인증 — 없음

- `api/main.py:43~49` CORS `allow_origins=["*"]`. 와일드카드.
- `api/middleware/` 에 인증 미들웨어 없음 (rate_limiter, audit_log, token_budget 만).
- `api/routes/chat.py:45~52 _client_ip` — IP 만으로 식별.
- audit_log (`api/middleware/audit_log.py:31~50`) 에 `user_id` 컬럼 없음.
- 결정 사항 #33 (Cloudflare Access JWT) pending — 본 TRD 가 대체/보완.

### 1.3 한계 / 변경 비용 / 회귀 위험

| 항목 | 현재 비용 | 위험 |
|---|---|---|
| 다기기 동기화 | 불가 — localStorage 단일 | UX 결정타 |
| 사용자별 분석 | IP 만 — 동적 IP/공유 IP 식별 불가 | audit log 활용도 낮음 |
| 외부 도메인 노출 | CORS `*` — XSS/CSRF 취약 | 실배포 차단 |
| 세션 store swap 비용 | line 12 주석에 "인터페이스만 유지하면 swap 가능" 명시 — `useSessions` 는 11개 메서드 노출 | 중간 (인터페이스는 안정적) |

## 2. TO-BE 설계

### 2.1 신규 모듈

```
web/
  lib/
    supabase.ts                     신규 — 클라이언트 싱글톤 (createBrowserClient)
    sessionStore.ts                 변경 — load/save 를 supabase 어댑터로 swap
    authClient.ts                   신규 — Magic Link 발송 / 세션 구독
  app/
    auth/callback/route.ts          신규 — OAuth/Magic Link 콜백 처리
    auth/login/page.tsx             신규 — 이메일 입력 화면
  components/
    AuthGate.tsx                    신규 — session 없으면 login 으로 redirect
api/
  middleware/
    auth.py                         신규 — Supabase JWT 검증 (FastAPI Depends)
  dependencies.py                   변경 — get_current_user() 추가
infra/
  supabase_client.py                신규 — 백엔드용 Supabase admin 클라이언트
```

### 2.2 인터페이스

#### 프론트 — useSessions 인터페이스 보존

`web/lib/sessionStore.ts:79~98 UseSessionsResult` 11개 메서드는 그대로. 내부 구현만 swap:

```ts
// 변경 지점 (sessionStore.ts:107~136)
useEffect(() => {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) { setReady(true); return; }
  const { data } = await supabase
    .from("chat_sessions")
    .select("*")
    .eq("user_id", user.id)
    .order("updated_at", { ascending: false });
  setSessions(data ?? []);
  setReady(true);
}, []);
```

`active`, `createNew`, `updateActive` 등 호출 측은 무수정. 이미 `ready: boolean` 플래그 (line 97) 가 있어 비동기 로딩 처리는 컴포넌트에 반영되어 있다.

#### 백엔드 — JWT 검증

```python
# api/middleware/auth.py
from fastapi import Depends, HTTPException, Header
from jose import jwt

async def get_current_user(authorization: str = Header(...)) -> dict:
    """Bearer <jwt> → user dict. JWKS 캐시는 supabase_client 가 담당."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, _jwks(), audience="authenticated")
    except jwt.JWTError:
        raise HTTPException(401, "유효하지 않은 토큰")
    return payload  # {sub, email, role, ...}

# api/routes/chat.py 진입부
@router.post("/sync")
async def chat_sync(req: ChatRequest, user = Depends(get_current_user), ...):
    ...
```

### 2.3 Supabase 스키마

```sql
create table public.chat_sessions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  title       text not null,
  mode        text not null,
  messages    jsonb not null default '[]'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index on public.chat_sessions (user_id, updated_at desc);

alter table public.chat_sessions enable row level security;

create policy "own sessions" on public.chat_sessions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

`messages: jsonb` 는 현재 `SessionMessage` 구조 (line 21~28) 와 동형. `attachments` 도 jsonb 안에 자연 수용.

### 2.4 의존성 방향

```
web/components/* → web/lib/sessionStore.ts → web/lib/supabase.ts → @supabase/ssr
                                              ↓
web/app/auth/* → web/lib/authClient.ts ──────┘

api/routes/chat.py → api/middleware/auth.py → infra/supabase_client.py → python-jose
```

도메인(rag_core)은 인증을 모른다 (Hexagonal 유지).

## 3. 변경 사항 단계 (커밋 단위)

### C1. Supabase 프로젝트 + 스키마 (인프라, 코드 0줄)

- Supabase 프로젝트 생성 (free tier)
- 위 SQL 적용, RLS enable 확인
- `.env.example` 에 `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` 추가
- 검증: SQL editor 에서 anon 키로 read 시 RLS 차단 확인

### C2. 프론트 인증 골격 (백엔드 무영향)

- 신규: `web/lib/supabase.ts`, `web/lib/authClient.ts`
- 신규: `web/app/auth/login/page.tsx`, `web/app/auth/callback/route.ts`
- 신규: `web/components/AuthGate.tsx` — `session === null` 이면 `/auth/login` 으로 redirect
- 변경: `web/app/page.tsx` 를 AuthGate 로 감싼다
- 검증: Magic Link 수신 → 콜백 → 메인 페이지 접근. 세션 store 는 아직 localStorage 사용 (회귀 0)

### C3. 세션 store swap (Supabase Postgres + Realtime)

- 변경: `web/lib/sessionStore.ts:107~136` — localStorage 호출을 supabase 어댑터로 교체
- 변경: 저장 측 (`updateActive`, `updateById`) 에 debounce 추가 (300ms 또는 streaming 종료 시점)
- 추가: Realtime subscribe — 다른 기기 변경 시 `setSessions` 갱신

```ts
// 쓰기 throttle (streaming 중 수십 chunk 발생 → DB 부담 회피)
const flushPending = debounce(async (session: ChatSession) => {
  await supabase.from("chat_sessions").upsert(session);
}, 300);
```

- 검증: 두 브라우저 동시 로그인 → 한 쪽에서 질문 → 다른 쪽에서 1초 내 반영

### C4. 백엔드 JWT 미들웨어

- 신규: `api/middleware/auth.py`, `infra/supabase_client.py`
- 의존성: `pyproject.toml` 에 `python-jose[cryptography]` 추가
- 변경: `api/routes/chat.py` `/chat/sync`, `/chat/stream` 에 `Depends(get_current_user)` 주입
- 변경: `api/middleware/audit_log.py:31` AuditRecord 에 `user_id: str | None = None` 추가, ALTER 컬럼 (line 75~84 패턴)
- 변경: `api/routes/chat.py` 의 audit 호출에 `user_id=user["sub"]` 추가
- 검증: Authorization 헤더 없으면 401, 유효 토큰으로 정상 응답

### C5. CORS 도메인 한정

- 변경: `api/main.py:45` `allow_origins=["*"]` → `[FRONTEND_URL]` (env 기반)
- 검증: 다른 origin 에서 요청 차단

### C6. 데이터 마이그레이션 (선택)

- 기존 localStorage 사용자가 로그인하면 1회성 `migrateLocalToSupabase()` 호출
- localStorage 데이터를 `chat_sessions` 에 upsert 후 localStorage 비움
- 검증: 마이그레이션 후 두 번째 로그인 시 중복 X

### C7. (옵션) device_id + IndexedDB 익명 모드

PRD 가 "인증 보류, 다기기 동기화 우선" 결정 시:
- localStorage 에 `device_id` UUID 발급
- chat_sessions.device_id 컬럼 (RLS 없이) → 익명 사용
- 추후 로그인 시 device_id → user_id 병합

## 4. 마이그레이션 전략

- 데이터: localStorage → Supabase 1회 마이그레이션 (C6). 비파괴 (둘 다 보존 가능).
- 코드 호환: `useSessions` 인터페이스 보존 → 컴포넌트 무수정.
- 운영:
  - C2~C3 은 별도 브랜치 + Vercel preview 로 검증 후 main merge
  - C4 백엔드 변경은 프론트가 토큰 전송 전이면 401 — 동시 배포 필요. Feature flag 로 `AUTH_REQUIRED=false` 단계적 롤아웃 권장
  - 다운타임 0 (DB 신규 테이블, 기존 audit_log 는 ALTER ADD COLUMN)

## 5. 검증 계획

### 5.1 단위 테스트

```python
# tests/test_auth_middleware.py
def test_invalid_token_returns_401():
    response = client.post("/chat/sync", headers={"Authorization": "Bearer x"})
    assert response.status_code == 401

def test_valid_token_passes():
    token = mock_supabase_token(sub="user-1", email="a@b.c")
    response = client.post("/chat/sync", headers={"Authorization": f"Bearer {token}"}, json=...)
    assert response.status_code == 200
```

```ts
// web/__tests__/sessionStore.supabase.test.ts
test("로그인 후 sessions 가 supabase 에서 로드된다", async () => {
  mockSupabase.auth.getUser.mockResolvedValue({ user: { id: "u1" } });
  mockSupabase.from("chat_sessions").select.mockResolvedValue({ data: [...] });
  const { result } = renderHook(useSessions);
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(result.current.sessions).toHaveLength(2);
});
```

### 5.2 E2E

- 로그인 → 질문 → 다른 브라우저 로그인 → 동일 세션 보임
- 로그아웃 → `/chat/sync` 401
- RLS 검증 — 다른 user_id 로 직접 SQL 시도 → 차단

### 5.3 정량 지표

| 지표 | 목표 |
|---|---|
| `useSessions` 호출 측 변경 파일 | 0 |
| Streaming 중 supabase write 호출 | 1회 (종료 시점) — debounce 300ms |
| 401 응답 시간 (캐시 적중) | < 50ms (JWKS 캐싱 후) |
| 회귀 테스트 (기존 chat 통합) | PASS |

## 6. 위험 / 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| Supabase 무료 티어 한도 (500MB DB / 50k MAU) | 한도 초과 시 결제 | 모니터링 + 1년 demo 한정 |
| Streaming 중 다수 write → DB rate limit | session 저장 실패 | 종료 시점 1회 또는 1초 debounce |
| Magic Link 이메일 도달 실패 | 로그인 불가 | Supabase 의 SMTP 대체 옵션 + 사용자 안내 |
| JWKS endpoint 다운 | 401 폭주 | JWKS 1시간 캐시 + stale-while-revalidate |
| Realtime 구독 비용 | 동시 접속 폭증 시 비용 증가 | Polling 모드 fallback |

## 7. 비-목표 / TRD 범위 외

- OAuth 다중 provider (Google/GitHub) — Magic Link 이후 추가
- 팀/조직 공유 세션 — 개인 워크로드만
- 세션 검색/태그/즐겨찾기 — TRD-003 (UX) 또는 별도
- 토큰 사용량 사용자별 quota — audit_log 기반 후속
- 백엔드 세션 영속화 (chat_history 를 backend 가 보관) — 프론트가 보내는 현재 패턴 유지
