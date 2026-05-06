# PR 13 감사 보고서 — Auth 어댑터 + bootstrap 통합 + chat_v2 wiring

작성: 2026-05-06 / 대상 브랜치: `main` (working tree, 미커밋) / TRD-011 결정 1·4

---

## 1. 요약 판정

**CONDITIONAL PASS** — 기능 요건·Hexagonal·테스트·회귀 모두 통과. 단, 운영 환경에서 *시나리오 2 (인증+conv_id 없음)* 실행 시 SQL 캐스팅 실패가 예상되는 **CRITICAL 잠재 결함 1건**이 존재한다. PR 14 절체 직전 또는 본 PR 머지 전 1줄 수정 필요.

핵심 수치:
- 회귀: tests/chatbot/ **218 passed**, tests/ (chatbot 외) **230 passed**, 신규 **5 passed**, 합계 **448 passed / 0 failed**.
- ruff check + format: **All checks passed / 8 files already formatted**.
- 변경 파일 4 + 신규 5 (auth 3 + 테스트 1 + sql 0). rag_core/, api/dependencies.py, api/routes/chat.py, api/main.py, chatbot/domain/persistence.py, chatbot/infrastructure/persistence/* **변경 0**.

---

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS

- `chatbot/infrastructure/auth/{__init__.py, anonymous.py, supabase_auth.py}` 가 application/api 레이어를 import 하는 라인 **0건** (`grep -rn "from chatbot\.application\|from api\." chatbot/infrastructure/auth/`).
- supabase 패키지는 *모두* TYPE_CHECKING 또는 함수 본문 lazy:
  - `chatbot/infrastructure/auth/supabase_auth.py:18` — `if TYPE_CHECKING: from supabase import Client`
  - `chatbot/infrastructure/persistence/supabase_store.py:22` — 동일
  - `chatbot/application/bootstrap.py:102` — `from supabase import create_client` (함수 본문 안)
- `api/routes/chat_v2.py` 에 supabase 직접 import **0건** — `build_persistence_from_env()` 만 호출(`chat_v2.py:28-29, 57`).
- Protocol 만족 검증 (런타임): `isinstance(AnonymousUserIdentifier(), UserIdentifier) → True`, `isinstance(SupabaseUserIdentifier(client=stub), UserIdentifier) → True`.

### B. rag_core / 기존 chatbot/api 비손상 — PASS

`git diff --stat HEAD` 결과:
```
api/routes/_chat_v2_envelope.py  | 50 +++
api/routes/chat_v2.py            | 71 +++
api/schemas.py                   |  7 +++
chatbot/application/bootstrap.py | 49 +++
```
대상 외 (rag_core/, api/dependencies.py, api/routes/chat.py, api/main.py, chatbot/domain/persistence.py, chatbot/infrastructure/persistence/*) 변경 **0건**. PR 12 산출물 그대로.

### C. 단일 책임 / 라인 한도 — CONDITIONAL PASS (권고 위반 3건)

| 단위 | 라인 | 한도 | 판정 |
|---|---:|---:|:---:|
| `bootstrap.py` 전체 | 272 | 200 | **WARN** |
| `chat_v2.py` 전체 | 223 | 200 | **WARN** |
| `_chat_v2_envelope.py` 전체 | 227 | 200 | **WARN** |
| `supabase_auth.py` 전체 | 61 | 100 | OK |
| `build_persistence_from_env()` | 45 | 50 (추정) | OK |
| `to_state()` | 27 | 30 | OK |
| `_resolve_conversation()` | 19 | 30 | OK |
| `_save_conversation_safe()` | 16 | 30 | OK |
| `_persistence()` / `_orchestrator()` | 6 / 4 | 30 | OK |
| `chat_v2()` | 42 | 30 | **WARN** |
| `chat_v2_stream()` | 37 | 30 | **WARN** |
| `_stream_events()` | 50 | 30 | **WARN** |
| `current_user_id()` (Supabase) | 12 | 30 | OK |

권고: bootstrap.py 는 *기능 추가 정당화* (KG/Agentic/Vision 게이트가 함께 있어 분해 시 cohesion 저하). chat_v2.py 는 SSE 핸들러 분리 가능 (`api/routes/_chat_v2_stream.py`) — PR 14 직전 검토.

### D. 익명 fallback 정확성 — PASS

`bootstrap.build_persistence_from_env()` 분기 표:

| 조건 | 결과 | 로그 |
|---|---|---|
| `AUTH_ENABLED=false` | `(None, AnonymousUserIdentifier())` | `warning: Persistence disabled — AUTH_ENABLED=false` |
| `SUPABASE_URL` 또는 `SUPABASE_SERVICE_KEY` 미설정 | 동일 | `warning: Persistence not configured — ... 미설정. 익명 모드.` |
| `from supabase import create_client` ImportError | 동일 | `warning: Persistence import 실패 (supabase 미설치): ...` |
| `create_client(...)` 예외 | 동일 | `warning: Supabase client 생성 실패: ...` |
| 정상 | `(SupabaseConversationStore, SupabaseUserIdentifier)` | `warning: Persistence registered (Supabase)` |

운영 가시성: 모든 경로가 `logger.warning` — INFO 차단 환경에서도 노출. (의도된 격상)

### E. chat_v2 라우트 wiring — PASS

- Authorization Bearer header → `SupabaseUserIdentifier.current_user_id(request)` (`supabase_auth.py:33-44`, `_extract_bearer_token` 47-61). FastAPI Request 또는 dict-like 양쪽 호환.
- `_resolve_conversation` (`_chat_v2_envelope.py:51-69`) 분기:
  - `store + user_id + req.conversation_id` 모두 truthy + `store.load(...) is not None` → 기존 conversation 반환.
  - 그 외 → 새 `Conversation(id=req.conversation_id or trace_id, ...)`.
  - 즉 *3개 중 1개라도 None → 새 conversation* 정확.
- `chat_v2()` 응답 후 `background.add_task(_save_conversation_safe, store, result, user_id)` (라인 107-108) — `store is not None and user_id` 가드. 동기 응답 latency 영향 0.
- `chat_v2_stream()` 도 동일 패턴 — `_stream_events` 안에서 `background.add_task(...)` (라인 196-197). SSE 시작 직전이지만 `BackgroundTasks` 는 응답 종료 후 실행.
- `_save_conversation_safe()` 가 `Exception` 을 잡아 `logger.warning` — 부팅·응답 영향 X.

### F. 타입/스타일 — PASS

- `ruff check ...` → **All checks passed**.
- `ruff format --check ...` → **8 files already formatted**.
- 한국어 docstring + 영문 식별자 — 검사 8 파일 모두 일관.
- 이모지 grep (🚀✅❌⚠️🎯🔥) — **0건**.
- Protocol 만족 — D 섹션 검증.

### G. 테스트 품질 — PASS

`pytest tests/test_chat_v2_persistence.py -v` → **5 passed in 0.81s**.

| # | 시나리오 | 검증 |
|---|---|---|
| 1 | 인증+conv_id 있음 | `load_calls == [("conv-1","user-1")]`, save 1회, `turn_count == 2` (1+1) |
| 2 | 인증+conv_id 없음 | `load_calls == []`, save 1회 — 새 conversation |
| 3 | 익명 (user_id=None) | `load_calls == [] && save_calls == []` |
| 4 | store=None | save 호출 자체 안 됨 (200 응답 확인) |
| 5 | 다른 사용자 conv_id | `load_calls` 에 호출 기록, save user_id == "user-1" — 격리 |

- LLM 호출 0 / Supabase 통신 0: `_AppendTurnOrch` stub + `_FakeStore` + `_FakeIdentifier` 만 사용.
- `_reset_state` autouse fixture 가 `reset_dependency_cache()` + `app.dependency_overrides.clear()` + `limiter.reset()` — 다른 테스트 누설 차단.

### H. 회귀 안전성 — PASS

| 묶음 | 통과 |
|---|---|
| `tests/chatbot/` | 218 / 218 |
| `tests/` (chatbot 외) | 230 / 230 |
| **전체 `tests/`** | **448 / 448** |

- ChatRequest.conversation_id 는 `default=None` — 외부 클라이언트(미설정) 영향 0.
- api/main.py 의 startup hook 변경 0 (검증: git diff 결과 미포함).

### I. 잠재적 결함

#### I-1. **CRITICAL — `trace_id` 가 UUID 형식이 아님 → Supabase upsert 시 캐스팅 실패 예상**

`infra/observability.py:33-35`:
```python
def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]   # 16자 hex (예: "a1b2c3d4e5f60718")
```

그러나 `sql/migrations/2026_05_06_conversations.sql:23`:
```sql
id  uuid primary key default uuid_generate_v4()
```

흐름:
1. 시나리오 2 (인증+conv_id 없음). 클라이언트가 `conversation_id=null` 로 첫 요청.
2. `_resolve_conversation` 의 `new_id = req.conversation_id or trace_id` → 16자 hex 사용 (`_chat_v2_envelope.py:64`).
3. `Conversation(id=new_id)` 생성. orchestrator 실행 후 `store.save(conv, user_id=...)`.
4. `SupabaseConversationStore.save()` 가 `{"id": conversation.id, ...}` 그대로 upsert (`supabase_store.py:46`).
5. Postgres 가 `"a1b2c3d4e5f60718"` 를 `uuid` 로 캐스팅 시도 → **InvalidTextRepresentation** 예외.
6. 예외는 `_save_conversation_safe` 의 broad-except 에서 `logger.warning` 으로 *조용히 삼켜짐* — 사용자에겐 200 OK, 데이터 유실.

**FakeStore 테스트는 `tuple(str, str)` dict 키라 통과. 운영 환경 첫 익명 → 인증 전환 흐름에서 즉시 발현.**

권고 수정 (택 1):
- (A) `_resolve_conversation` 에서 `new_id = req.conversation_id or str(uuid.uuid4())` — trace_id 분리 (트레이스/식별자는 본래 별개 의미).
- (B) `new_trace_id()` 자체를 full UUID 로 교체 — 다른 호출자 영향 검토 필요 (요청 헤더 X-Trace-Id 표시 등).

권장 (A) — trace_id 의 의미·길이 보존.

#### I-2. WARN — `_persistence()` lru_cache stale

`@lru_cache(maxsize=1)` 가 환경변수 변경 후에도 이전 값 보유. 운영 환경에서 SUPABASE_* 갱신 시 **컨테이너 재시작 필요**. README 또는 운영 가이드에 명시 필요.

#### I-3. WARN — JWT 검증마다 Supabase 서버 호출

`SupabaseUserIdentifier.current_user_id` 가 `self._client.auth.get_user(token)` 호출 — *매 요청* Supabase Auth 서버 round-trip. 트래픽 증가 시 latency·비용 부담. 향후 *로컬 JWT 검증 (JWKS 캐시)* 권고. 현재 트래픽에서는 OK.

#### I-4. WARN — background save 실패 시 사용자 알림 없음

`_save_conversation_safe` broad-except + `logger.warning` 패턴. 데이터 유실이 사용자에게 가시화되지 않는다. PRD-005 (데이터 거버넌스) 합류 시 alerting (Sentry 등) 또는 재시도 큐 권고.

#### I-5. INFO — SSE background save 타이밍

`_stream_events` 가 `background.add_task` 를 SSE *시작 직전* 등록. FastAPI BackgroundTasks 는 응답 *종료 후* 실행이므로 SSE 스트림 종료 후 save — 정상 패턴. (확인됨)

---

## 3. 회귀 검증 (재기재)

```
tests/chatbot/                 218 passed
tests/ (chatbot 외, 신규 포함) 230 passed
tests/ (전체)                  448 passed, 0 failed in 3.57s
```

ruff: clean. `git diff` 가 영향 외 파일 0.

---

## 4. 위반/권고 요약

| # | 영역 | 심각도 | 파일:라인 | 조치 |
|---|---|:---:|---|---|
| 1 | trace_id ≠ uuid → Supabase upsert 실패 | **CRITICAL** | `_chat_v2_envelope.py:64` + `infra/observability.py:35` | 1줄 수정 (택 A 권장) |
| 2 | bootstrap.py 272줄 > 200 | WARN | `chatbot/application/bootstrap.py` | 분해 검토 또는 정당화 문서화 |
| 3 | chat_v2.py 223줄 > 200 | WARN | `api/routes/chat_v2.py` | SSE 핸들러 분리 검토 (PR 14 직전) |
| 4 | _chat_v2_envelope.py 227줄 > 200 | WARN | `api/routes/_chat_v2_envelope.py` | metadata builder 분해 검토 |
| 5 | `chat_v2()` 42줄, `chat_v2_stream()` 37줄, `_stream_events()` 50줄 > 30 | WARN | `chat_v2.py:68/135/174` | 라우트 *single-screen* 정당화 가능 |
| 6 | `_persistence()` lru_cache stale | WARN | `chat_v2.py:51-57` | 운영 가이드에 컨테이너 재시작 명시 |
| 7 | JWT 검증 매 요청 외부 호출 | WARN | `supabase_auth.py:38` | JWKS 캐시 (PR 후속) |
| 8 | background save 실패 silent | WARN | `chat_v2.py:120-127` | PRD-005 합류 시 alerting |

위반 0, 권고 7. CRITICAL 1건은 본 PR 또는 PR 14 시작 전 반드시 처리.

---

## 5. 통계

| 지표 | 값 |
|---|---:|
| 변경 파일 | 4 (modified) + 4 (new auth+test) = 8 |
| 추가 라인 (modified 만) | 159 |
| 삭제 라인 | 18 |
| 신규 파일 LOC | auth 88 + test 220 = 308 |
| 신규 테스트 | 5 / 5 PASS |
| 회귀 (전체) | 448 / 448 PASS |
| ruff | 0 위반 |
| supabase 직접 import (auth/api) | 0 (모두 lazy/TYPE_CHECKING) |
| Hexagonal 위반 | 0 |
| 이모지 | 0 |

---

## 6. TRD-011 결정 1·4 정합 평가

### 결정 1 — Magic Link 인증

- **PASS (어댑터 측면)**. `SupabaseUserIdentifier` 가 Authorization Bearer JWT 를 추출 → `auth.get_user(token)` 검증. Magic Link 발급 자체는 프론트엔드(supabase-js) 책임 — PR 14 영역.
- 백엔드 계약 충족: JWT 가 도착하면 `sub` claim 의 user uuid 를 반환.

### 결정 4 — Supabase 진실원천

- **CONDITIONAL PASS**. `_resolve_conversation` 이 `store.load` 우선, fallback 으로 `chat_history` — 정확.
- 단, **결함 I-1** 으로 인해 *첫 익명→인증 전환 또는 클라이언트가 conv_id 미생성 시* 진실원천 경로가 깨진다. 1줄 수정 후 완전 PASS.

---

## 7. PR 14 (프론트 절체) 시작 전 권고

1. **CRITICAL I-1 수정**: `_resolve_conversation` 에서 `new_id = req.conversation_id or str(uuid.uuid4())`. trace_id 와 conversation_id 는 *직교* 이므로 의미 분리도 자연.
2. `web/lib/sessionStore.ts` — Supabase JS SDK (`@supabase/supabase-js`) 도입. `auth.signInWithOtp({email})` 로 Magic Link 발급.
3. `web/components/AuthGate.tsx` 신규 — 미로그인 시 이메일 입력 + Magic Link 발송 UI. 콜백 라우트 `/auth/callback` 에서 세션 수립.
4. `web/lib/api.ts` — fetch 시 `Authorization: Bearer <session.access_token>` 자동 부착. (`supabase.auth.getSession()` 활용)
5. `ChatPanel` — 새 대화 시작 시 클라이언트가 `crypto.randomUUID()` 로 `conversation_id` 생성·전송. 결함 I-1 우회용 방어선.
6. 마이그레이션: 기존 IndexedDB 의 conversation 들을 *서명 후* Supabase 에 upsert 일회성 스크립트. (PRD-002 §결정 4 의 *진실원천 일원화*)
7. 운영 환경 환경변수: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `AUTH_ENABLED=true` 세팅 후 부팅 로그에 `Persistence registered (Supabase)` 노출 확인.
8. 부팅 후 health check: `select count(*) from public.conversations` 권한 확인 (RLS 정책 동작).

---

종합: PR 13 의 산출물은 Hexagonal·테스트·회귀 기준에서 견고하다. 단 1건의 CRITICAL (trace_id↔uuid 불일치) 만 1줄로 해소하면 PR 14 절체 작업이 안전하다.
