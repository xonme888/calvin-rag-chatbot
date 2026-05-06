---
status: draft
group: B
created: 2026-05-06
related_prd: docs/prd/draft/002-multi-device-sync.md
related_trd: docs/trd/draft/006-conversation-first-orchestrator.md
---

# TRD-011: Supabase 영속화 (ConversationStore + 다기기 동기화)

PR 1~6 의 chat_v2 orchestrator 위에 *영속화 + 다기기 동기화* 를 합류한다. 도메인 모델
(``Conversation``, ``Turn``, ``Message``) 은 frozen Pydantic 이라 변경 0 — 인프라 어댑터
1개와 application 의 의존성 주입 변경만으로 본격 영속화.

PRD-002 §9 의 4가지 결정 (Supabase Auth Magic Link / JSONB 1-table / 자체 ConversationStore
/ 진실원천 Supabase) 을 기술 구현으로 옮긴다.

## 1. AS-IS 분석

### 1.1 현재 영속화 — 클라이언트 single source of truth

```
api/routes/chat_v2.py:_orchestrator()       매 요청 lru_cache 부트스트랩
api/routes/_chat_v2_envelope.py:to_state    req.chat_history → 가짜 Turn 시퀀스
                                            (PR 6 의 chat_history wiring fix 후)
chatbot/domain/state.py                     ConversationState 가 in-memory only
web/lib/sessionStore.ts                     IndexedDB single source of truth
```

문제:
1. **다기기 동기화 부재** — IndexedDB 는 브라우저 별. 노트북에서 만든 세션이 폰에서 안 보임.
2. **사용자 식별 부재** — `chat_v2` 가 익명 요청 그대로. trace_id 만 있고 user_id 없음.
3. **History 전송 비용** — 매 요청마다 전체 chat_history 를 body 에 실어 보낸다. turn 수가
   많아지면 request payload 가 비대해짐 (특히 SSE 스트림 시작 직전).
4. **서버 측 상태 0** — orchestrator 가 매 호출 *첫 턴* 으로 시작. META_REFERENCE 의
   "방금 그래프" 같은 메타 후속이 *클라이언트가 history 를 정확히 전송* 해야만 풀림.
5. **Audit 격리 어려움** — `audit_log` 가 trace_id 만 있고 user_id 없어 사용자별 활동 추적
   불가. PRD-4 quota 도 현재 IP 기반.

### 1.2 영향 받는 파일

| 영역 | 파일 | 현재 상태 |
|---|---|---|
| 도메인 | `chatbot/domain/conversation.py` | frozen — 변경 0 |
| 도메인 (신규) | `chatbot/domain/persistence.py` | 없음 — 본 TRD 가 추가 |
| 인프라 | `chatbot/infrastructure/persistence/` | 없음 — 본 TRD 가 추가 |
| 애플리케이션 | `chatbot/application/bootstrap.py` | ConversationStore 주입 추가 |
| 라우트 | `api/routes/_chat_v2_envelope.py:to_state` | chat_history → conversation_id 로 절체 |
| 라우트 (신규) | `api/routes/conversations.py` | 없음 — 사이드바용 GET/DELETE |
| 스키마 | `api/schemas.py:ChatRequest` | conversation_id 필드 추가, chat_history deprecation |
| 프론트 | `web/lib/sessionStore.ts` | IndexedDB → Supabase REST + IndexedDB 캐시 |
| 인증 | `web/components/InviteGate.tsx` 또는 신규 | invite_code → Supabase Auth Magic Link |

## 2. TO-BE 설계

### 2.1 신규 도메인 추상 — `chatbot/domain/persistence.py`

```python
@runtime_checkable
class ConversationStore(Protocol):
    """대화의 영속 저장소. 사용자 단위 격리. 직렬화는 frozen Conversation 의 model_dump."""

    def save(self, conversation: Conversation, *, user_id: str) -> None: ...

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None: ...

    def list_for_user(
        self, user_id: str, *, limit: int = 50, before: datetime | None = None,
    ) -> list[ConversationSummary]: ...

    def delete(self, conversation_id: str, *, user_id: str) -> None: ...


class ConversationSummary(BaseModel, frozen=True):
    """list_for_user 응답의 가벼운 요약 — 사이드바용."""
    id: str
    title: str | None  # 첫 user_message.content 의 첫 30자 등
    last_turn_at: datetime
    turn_count: int


@runtime_checkable
class UserIdentifier(Protocol):
    """request → user_id 추출. Supabase Auth JWT 검증 어댑터 또는 익명 fallback."""

    def current_user_id(self, request: Request) -> str | None: ...
```

### 2.2 Supabase 어댑터 — `chatbot/infrastructure/persistence/supabase_store.py`

```python
class SupabaseConversationStore:
    """JSONB 1-table 직렬화. RLS 가 user_id 격리."""

    def __init__(self, *, client: Client) -> None:
        self._client = client

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        self._client.table("conversations").upsert({
            "id": conversation.id,
            "user_id": user_id,
            "state": conversation.model_dump(mode="json"),
            "updated_at": "now()",
        }).execute()

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        res = (self._client.table("conversations")
                  .select("state")
                  .eq("id", conversation_id)
                  .eq("user_id", user_id)
                  .maybe_single()
                  .execute())
        if not res.data:
            return None
        return Conversation.model_validate(res.data["state"])
    ...
```

### 2.3 스키마 + RLS — `sql/migrations/2026_05_06_conversations.sql`

```sql
-- 본 마이그레이션은 ``supabase db push`` 또는 dashboard 에서 1회 실행.

create extension if not exists "uuid-ossp";

create table public.conversations (
    id           uuid primary key default uuid_generate_v4(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    state        jsonb not null,
    title        text,                              -- 첫 user_message 의 첫 30자 (낙관적 캐시)
    updated_at   timestamptz not null default now(),
    created_at   timestamptz not null default now()
);

create index conversations_user_updated_idx on public.conversations (user_id, updated_at desc);
create index conversations_state_gin_idx    on public.conversations using gin (state);

alter table public.conversations enable row level security;

-- 사용자 격리 — 자기 데이터만 조회/수정 가능
create policy "사용자 본인 conversations 만"
    on public.conversations
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- updated_at 자동 갱신 트리거
create or replace function public.touch_updated_at()
returns trigger as $$ begin new.updated_at = now(); return new; end; $$ language plpgsql;

create trigger conversations_updated_at
    before update on public.conversations
    for each row execute function public.touch_updated_at();
```

### 2.4 Bootstrap 변경

```python
# chatbot/application/bootstrap.py
def build_default_orchestrator(
    *,
    hybrid_rag: HybridRAG,
    llm: BaseChatModel,
    conversation_store: ConversationStore | None = None,  # 신규 — None 이면 stateless
) -> CompiledStateGraph:
    ...
```

### 2.5 chat_v2 라우트 변경

```python
# api/routes/_chat_v2_envelope.py
def to_state(*, req: ChatRequest, trace_id: str, store: ConversationStore | None = None,
             user_id: str | None = None) -> ConversationState:
    if store is not None and user_id is not None and req.conversation_id:
        # Supabase 에서 기존 대화 로드 (진실원천)
        existing = store.load(req.conversation_id, user_id=user_id)
        if existing is not None:
            return ConversationState(
                conversation=existing,
                pending_user_message=...,
                ...
            )
    # 폴백 — chat_history 로 부분 복원 (PR 6 의 fix 와 동일)
    ...
```

응답 후 비동기 background task 로 ``store.save(state.conversation, user_id=user_id)``.

### 2.6 ChatRequest 스키마 변경

```python
class ChatRequest(BaseModel):
    question: str
    mode: Mode = "auto"
    conversation_id: str | None = None  # 신규 — Supabase 의 conversations.id (uuid)
    chat_history: list[ChatMessage] = Field(
        default_factory=list,
        deprecated="conversation_id 사용 권장. chat_history 는 익명 모드에서만 fallback.",
    )
    attachments: list[Attachment] = Field(default_factory=list)
```

### 2.7 새 라우트 — 사이드바 동기화

| 메서드 | 경로 | 응답 | 권한 |
|---|---|---|---|
| GET | `/conversations` | `list[ConversationSummary]` | 본인 user_id 만 (RLS) |
| GET | `/conversations/{id}` | `Conversation` (full state) | 본인 user_id 만 |
| DELETE | `/conversations/{id}` | 204 | 본인 user_id 만 |

PUT/POST 는 *없음* — `/chat/v2` 응답 후 background task 가 자동 save. *명시 저장* 은 향후
"제목 수정" 같은 부분 수정 시 추가.

### 2.8 프론트 절체

`web/lib/sessionStore.ts` 의 `useSessions` 훅:
- 외부 인터페이스 (sessions / activeSession / appendMessage / ...) **불변**
- 내부 어댑터: IndexedDB → Supabase JS SDK + IndexedDB 캐시
- Supabase Realtime 구독으로 다기기 즉시 반영

## 3. 마이그레이션 시퀀스 (PR 11 ~ PR 17)

| PR | 범위 | 변경 라인 (목표) | 외부 영향 |
|---|---|---|---|
| 11 | 문서 + 도메인 Protocol (persistence.py + UserIdentifier) | ≤ 200 | 0 |
| 12 | SupabaseConversationStore + 의존성 + SQL 마이그레이션 | ≤ 500 | Supabase 프로젝트 필요 |
| 13 | Auth (UserIdentifier + Magic Link 백엔드 검증) | ≤ 400 | env vars |
| 14 | chat_v2 라우트 통합 (conversation_id 처리) + /conversations 라우트 | ≤ 400 | api 변경 |
| 15 | 프론트 — Supabase JS SDK + sessionStore 절체 | ≤ 600 | UI 인증 화면 |
| 16 | 일회성 IndexedDB → Supabase 마이그레이션 (브라우저 측) | ≤ 200 | 1회만 |
| 17 | 정리 — chat_history 필드 deprecation 강화, audit_log 의 user_id 추가 | ≤ 200 | 0 |

각 PR 끝에 audit-agent (총 7회). PR 12~14 는 *백엔드 단독* — 프론트가 아직 Supabase 사용
안 해도 동작. PR 15 가 절체 시점.

## 4. 위험 / 롤백

| 위험 | 영향 | 완화 |
|---|---|---|
| Supabase 장애 | 대화 로드/저장 실패 | `ConversationStore` 가 None 받으면 stateless fallback. 그동안 IndexedDB 캐시로 동작 |
| 마이그레이션 SQL 실수 | 데이터 손실 | 본 PRD 는 *신규 테이블* 만 — 기존 데이터 무영향 |
| 인증 도입 후 익명 시연 깨짐 | dev/시연 회귀 | `AUTH_ENABLED=false` 환경변수 — UserIdentifier 가 익명 fallback |
| 기존 IndexedDB 사용자 데이터 보존 | UX 회귀 | PR 16 의 *일회성 마이그레이션* + 마이그레이션 후 IndexedDB readonly 보존 |
| RLS 정책 누락 | 다른 사용자 데이터 노출 | RLS 강제 (alter table ... force row level security 추가 검토) + 단위 테스트 |

롤백:
- PR 11~14 만 머지 후 PR 15 보류 — 백엔드는 Supabase 인지하나 프론트는 IndexedDB 그대로.
- 외부 노출은 PR 15 후 안정화 1주.

## 5. 테스트 계획

| 계층 | 테스트 |
|---|---|
| 도메인 | `Conversation.model_dump_json` ↔ `model_validate` round-trip |
| 인프라 | `SupabaseConversationStore` 의 save/load/list/delete (testcontainers Supabase 또는 Fake) |
| 라우트 | conversation_id 있을 때 store.load → state.turns 채워짐 / 응답 후 store.save 호출 |
| RLS | 사용자 A 가 사용자 B 의 conversation 접근 시 403 (또는 빈 결과) |
| 프론트 | sessionStore 어댑터 단위 테스트 + Realtime 충돌 (last-write-wins) |

## 6. 환경변수 + Supabase 프로젝트

운영 사용자 액션:

| 변수 | 위치 | 목적 |
|---|---|---|
| `SUPABASE_URL` | API 컨테이너 (HF Space) | 백엔드 SDK |
| `SUPABASE_SERVICE_KEY` | API 컨테이너 | RLS 우회 키 (서버 사이드 검증용 — *RLS 사용 시 anon key 권장*) |
| `NEXT_PUBLIC_SUPABASE_URL` | Vercel | 프론트 SDK |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Vercel | 프론트 SDK |
| `AUTH_ENABLED` | API + Vercel | `false` 면 익명 모드 (dev/시연) |

스키마 적용:
```bash
# Supabase CLI 또는 dashboard
supabase db push  # sql/migrations/2026_05_06_conversations.sql
```

## 7. 후속 (별도 PRD/TRD)

- **realtime 동기화** — Supabase Realtime 채널로 다기기 메시지 push. 본 TRD 는 polling 도
  허용. PR 18~ 별도.
- **사이드바 검색** — JSONB GIN 인덱스 위에 full-text search.
- **권한/공유** — 다른 사용자에게 read-only 공유. PRD-002 §3 비-목표.
- **Encryption-at-rest** — Supabase 가 디스크 레벨 암호화 제공. column-level 은 별도.
- **백업 / 익스포트** — PRD-005 (데이터 거버넌스) 와 합류.
- **구 IndexedDB 데이터 readonly 보존 정책** — PR 16 의 결정 사항.

## 8. 정량 목표

- conversation save latency ≤ 100ms (background task 라 사용자 체감 0).
- conversation load latency ≤ 200ms (사이드바 첫 로드).
- 다기기 일치율 — Realtime 적용 후 5초 이내 100% (PRD-002 §7 동일).
- 단위 테스트 통과 → 운영 1주 audit log 비교 후 PR 15 (프론트 절체).
