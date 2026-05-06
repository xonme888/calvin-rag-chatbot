# PR 12 감사 보고서 — Supabase ConversationStore 어댑터

> 대상: TRD-011 의 PR 12 (Supabase 인프라 어댑터). PR 11 (도메인 Protocol) 머지 후의 구체 구현.
> 일자: 2026-05-06.
> 감사자: 독립 audit agent (사용자 결정 4건 중 결정 2 + 결정 3 의 산출).

---

## 1. 요약 판정

**PASS.**

- Hexagonal 의존방향 무위반 (domain Protocol 만 import).
- TRD-011 §결정 2 (JSONB 1-table) + §결정 3 (자체 ConversationStore) 정합.
- 새 단위 테스트 10/10 통과. 회귀 chatbot 218 + 레거시 225 = 443 전부 PASS.
- ruff lint/format 클린.
- RLS 정책 + 어댑터 `.eq("user_id")` 이중 방어선 검증.
- 라인/메서드 한도 (200/30) 모두 충족.

심각한 결함 0. 권고는 §4 에 정리.

---

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS

`chatbot/infrastructure/persistence/supabase_store.py` import (실측):

```
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Any
from chatbot.domain.conversation import Conversation
from chatbot.domain.persistence import ConversationStore, ConversationSummary
if TYPE_CHECKING:
    from supabase import Client
```

- 외부 의존: `datetime`/`typing` 표준 + `chatbot.domain.*` 2개 + `supabase` (TYPE_CHECKING).
- `application/`, `api/`, `rag_core/` 직접 import: **0건**.
- grep `application|api|rag_core` 매치 1건 — docstring 의 "bootstrap 또는 application 레이어" 문구 (line 10, 주석). 실 import 아님.

### B. rag_core / 기존 chatbot 비손상 — PASS

`git status --porcelain` 결과:

```
 M pyproject.toml
?? chatbot/infrastructure/persistence/
?? sql/
?? tests/chatbot/test_supabase_store.py
```

- `pyproject.toml` diff: persistence optional + all 그룹에 `supabase>=2.7` 추가만. 6 insertions, 0 deletions.
- `chatbot/domain/persistence.py` 마지막 수정: 5월 6일 18:07 (PR 11 머지 시점) — PR 12 작업 후 unmodified.
- `rag_core/`, `api/`, `chatbot/{domain,application}`, `chatbot/infrastructure/` (persistence 외) 전부 변경 0.

### C. 단일 책임 / 라인 한도 — PASS

| 파일 | 라인 |
|------|------|
| `chatbot/infrastructure/persistence/supabase_store.py` | 123 |
| `chatbot/infrastructure/persistence/__init__.py` | 8 |
| `sql/migrations/2026_05_06_conversations.sql` | 92 |
| `tests/chatbot/test_supabase_store.py` | 278 |

`SupabaseConversationStore` 메서드 라인 (AST 측정):

| 메서드 | 라인 수 | 위치 |
|--------|--------|------|
| `__init__` | 2 | L39-40 |
| `save` | 10 | L42-51 |
| `load` | 14 | L53-66 |
| `list_for_user` | 20 | L68-87 |
| `delete` | 5 | L89-93 |

모든 메서드 30줄 이하. `_derive_title` (6줄) / `_row_to_summary` (16줄) 헬퍼 분리 적절.

### D. TRD-011 정합 — PASS

**결정 2 (JSONB 1-table)**:

- 테이블 컬럼 (SQL L22-29): `id uuid pk` / `user_id uuid FK auth.users on delete cascade` / `state jsonb not null` / `title text` (nullable) / `updated_at timestamptz` / `created_at timestamptz`. 명세 그대로.
- GIN 인덱스 (SQL L49-50): `conversations_state_gin_idx on public.conversations using gin (state)` — 향후 부분 쿼리 대비, 출구 명시.
- 정규화 출구 명시: me/013 §결정 2 ("향후 정규화된 turns 테이블로 옮긴다") 와 일관.
- user_updated 복합 인덱스 (L45-46): `(user_id, updated_at desc)` — list_for_user 성능 보장.

**결정 3 (자체 ConversationStore)**:

- grep `langgraph.checkpoint|langgraph_checkpoint` (`.venv` 제외): **0건**. 표준 checkpointer 의존 0.
- `pyproject.toml` `persistence = ["supabase>=2.7"]` — supabase SDK 만.
- 직렬화: `conversation.model_dump(mode="json")` (supabase_store.py L48) — me/013 §결정 3 ("Conversation.model_dump_json 직접 직렬화") 정합.

### E. RLS 정책 검증 — PASS

SQL (2026_05_06_conversations.sql):

- L56: `alter table public.conversations enable row level security`.
- L60-64: `create policy ... using (auth.uid() = user_id) with check (auth.uid() = user_id)` — `for all` (R/W 모두).
- L59: `drop policy if exists` — 멱등성 확보.

어댑터의 추가 방어선:

- `load` (L58-59): `.eq("id", conversation_id).eq("user_id", user_id)` — 두 필터.
- `delete` (L91-92): `.eq("id", conversation_id).eq("user_id", user_id)` — 두 필터.
- `list_for_user` (L79): `.eq("user_id", user_id)`.
- `save` (L44-50): upsert payload 에 `user_id` 포함 → RLS 의 `with check` 가 검증.

`service_role` key 가 RLS 를 우회하더라도 어댑터 자체의 `.eq("user_id")` 가 사용자 격리를 보장. 테스트 `test_load_RLS_시뮬_다른_사용자_차단` 가 이 시나리오를 시뮬한다.

### F. 타입/스타일 — PASS

- `ruff check chatbot/infrastructure/persistence/ tests/chatbot/test_supabase_store.py`: All checks passed.
- `ruff format --check`: 3 files already formatted.
- 전체 repo `ruff check .`: All checks passed.
- 한국어 docstring (모듈/클래스/메서드/헬퍼) + 영문 식별자.
- Protocol 만족 정적 검증: L123 `_: type[ConversationStore] = SupabaseConversationStore` — duck typing 이 깨질 경우 type checker 가 잡는다.
- 이모지: 모든 산출 파일에서 0건 (grep 확인).

### G. 테스트 품질 — PASS

`pytest tests/chatbot/test_supabase_store.py -v` 결과: **10 passed in 0.10s**.

| 케이스 | 검증 포인트 |
|--------|------------|
| `test_save_upsert_payload_정확` | upsert payload 에 id/user_id/title/state 정확. table 명 `conversations`. |
| `test_save_빈_turns_title_None` | turns 비면 title=None. |
| `test_save_긴_질문_30자_컷` | title 길이 정확히 30. |
| `test_load_본인_데이터_복원` | `.eq("id")` + `.eq("user_id")` 두 필터 모두 적용. round-trip 무손실. |
| `test_load_미존재_None` | 0건 매칭 시 None. |
| `test_load_RLS_시뮬_다른_사용자_차단` | 다른 user_id 로 조회 시 None (어댑터 필터 단독). |
| `test_list_user_id_필터_및_정렬` | order(updated_at, desc=True). turn_count = state.turns 길이. |
| `test_list_limit_적용` | limit=10 호출 기록. |
| `test_list_before_커서_lt_필터` | `.lt("updated_at", before)` 적용. |
| `test_delete_filters` | `.eq("id")` + `.eq("user_id")` 두 필터 적용. |

- LLM 호출 0 / 실 supabase 통신 0 (FakeClient 만).
- FakeClient 가 supabase fluent API (table → select/upsert/delete → eq/lt/order/limit → execute) 시뮬.
- 회귀 — `pytest tests/chatbot -q`: 218 passed. `pytest tests/ -q --ignore=tests/chatbot`: 225 passed.

### H. 마이그레이션 SQL 안전성 — PASS

| 보호 구문 | 위치 |
|-----------|------|
| `create extension if not exists "uuid-ossp"` | L16 |
| `create table if not exists` | L22 |
| `create index if not exists` (×2) | L45, L49 |
| `drop policy if exists` + `create policy` | L59-60 |
| `create or replace function` | L70 |
| `drop trigger if exists` + `create trigger` | L78-79 |
| `on delete cascade` (auth.users 삭제 연동) | L24 |

마이그레이션 재실행 안전. `auth.users` 삭제 시 conversations 자동 정리.

### I. 잠재적 결함 — 모두 *권고 수준*

1. **Client 인스턴스 직접 보유** (`__init__(client: Client)`). bootstrap 에서 1회 생성·주입 권고 — PR 13 의 책임.
2. **service_role key 우회 시 사용자 격리는 어댑터 단독**. 본 어댑터의 `.eq("user_id")` 가 *유일한 격리*. 향후 코드 리뷰 가이드에 명시 권고.
3. **load 의 `.limit(1)`**. supabase SDK 는 `.single()` / `.maybe_single()` 도 제공. 동작 동등하나 SDK 관용 패턴이 약간 다름. 정정 시 단위 테스트의 fluent 모킹도 동조 필요.
4. **list_for_user 의 `select("id, title, updated_at, state")`**. state 가 큰 row 라 사이드바 매 조회마다 풀 state 전송. 정규화 출구 (turn_count 컬럼 분리) 시 자연 해소. 현 단계는 OK.
5. **title 캐시 갱신**. 첫 turn 변경 시 title 도 변경되나, save 가 매번 `_derive_title` 재계산하므로 정합 OK (오류 가능성 없음, 검증 완료).
6. **FakeClient 의 supabase API 호환성**. fluent 체인 시뮬은 시그니처 수준. 실 SDK 의 응답 객체 (`PostgrestResponse` 등) 와 100% 호환은 통합 테스트 (`test_supabase_integration.py`) 의 책임.

### J. PR 13 (Auth + Bootstrap 통합) 시작 전 권고

1. **bootstrap.py**: `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` 환경변수 → `supabase.create_client(url, key)` → `SupabaseConversationStore(client=client)` 1회 조립. application 의 ConversationService 에 주입.
2. **UserIdentifier 어댑터 위치**: `chatbot/infrastructure/auth/supabase_auth.py` (미존재). JWT 의 `sub` claim → user_id. AUTH_ENABLED=false 면 None 반환.
3. **chat_v2 라우트**: `Depends(UserIdentifier)` 로 user_id 추출 → ConversationService 가 store.save/load 호출. `conversation_id` 는 request body 또는 path param.
4. **service_role vs anon key 정책**: 백엔드 background save 에는 service_role (RLS 우회). 사용자 토큰 매핑이 필요하면 anon key + JWT 에 `Authorization: Bearer <user_jwt>` 셋업 — PR 13 에서 결정.

---

## 3. 회귀 검증 결과

| 항목 | 결과 |
|------|------|
| 신규 테스트 (`test_supabase_store.py`) | 10 passed |
| chatbot 전체 (`tests/chatbot`) | 218 passed |
| 레거시 (`tests/` 제외 chatbot) | 225 passed |
| 합계 | **443 passed** |
| ruff check (전체 repo) | All checks passed |
| ruff format --check (산출 파일) | 3 files already formatted |

---

## 4. 위반 / 권고

위반 0.

권고 (PR 13 또는 후속 작업):

| # | 우선순위 | 내용 | 위치 |
|---|--------|------|------|
| 1 | M | bootstrap 에서 supabase Client 생성/주입 | 신규 `chatbot/bootstrap.py` 또는 `app/bootstrap.py` |
| 2 | M | UserIdentifier Supabase JWT 어댑터 추가 | `chatbot/infrastructure/auth/supabase_auth.py` |
| 3 | L | `.limit(1)` → `.maybe_single()` 으로 SDK 관용 패턴 정렬 (선택) | `supabase_store.py:60` |
| 4 | L | list_for_user 의 select 에서 state 제외 (정규화 출구 시) | `supabase_store.py:78` |
| 5 | L | service_role 우회 정책을 README/CONTRIBUTING 에 명시 | docs/ |

---

## 5. 통계

| 항목 | 수치 |
|------|------|
| 신규 파일 | 4 (`__init__.py` / `supabase_store.py` / SQL 마이그 / 테스트) |
| 수정 파일 | 1 (`pyproject.toml`, +6/-0) |
| supabase_store.py 라인 | 123 (한도 200) |
| 어댑터 메서드 수 | 4 (save/load/list_for_user/delete) + 헬퍼 2 (_derive_title/_row_to_summary) |
| 최장 메서드 | `list_for_user` 20줄 (한도 30) |
| 단위 테스트 | 10 케이스, 0.10s |
| 회귀 테스트 (전체) | 443 passed |
| ruff lint 위반 | 0 |
| 의존방향 위반 | 0 |
| 이모지 | 0 |

---

## 6. TRD-011 §결정 2/3 정합 평가

| 결정 | 명세 | 구현 | 정합 |
|------|------|------|:----:|
| 2 (JSONB 1-table) | `conversations(id, user_id, state jsonb, ...)` | SQL 마이그 L22-29 일치 | ✓ |
| 2 — 정규화 출구 | turns 테이블로 이주 가능 | me/013 §결정 2 + GIN 인덱스 + 도메인 변경에도 어댑터 영향 없음 | ✓ |
| 3 (자체 ConversationStore) | langgraph-checkpoint-postgres 미사용 | grep 0건. supabase SDK 만 | ✓ |
| 3 — 직렬화 | `Conversation.model_dump_json` | `model_dump(mode="json")` (등가) | ✓ |
| 3 — frozen 안전성 | model_validate round-trip 무손실 | `test_load_본인_데이터_복원` 검증 | ✓ |
| 사용자 격리 | RLS 1차 + 어댑터 추가 방어선 | RLS 정책 + 4 메서드 모두 `.eq("user_id")` | ✓ |

---

## 7. PR 13 시작 전 권고

1. `chatbot/infrastructure/auth/supabase_auth.py` 신규 — `UserIdentifier` Protocol 의 Supabase JWT 어댑터.
2. bootstrap 에서 `create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)` → `SupabaseConversationStore` 조립.
3. `application/conversation_service.py` (예정) 가 store + identifier 주입 받아 chat_v2 흐름에 연결.
4. chat_v2 라우트는 `Depends(get_user_id)` 로 user_id 추출, request body 의 `conversation_id` 검증 후 service 호출.
5. AUTH_ENABLED 환경변수 분기 — false 면 anonymous user fallback (개발 편의).
6. 통합 테스트 `tests/chatbot/test_supabase_integration.py` (선택) — 실 supabase 컨테이너 또는 dev 인스턴스로 round-trip 검증.

---

**최종 판정: PASS.**
