# PR 11 Audit — Supabase 영속화 (Phase 0+1+2: 결정 + 문서 + 도메인 Protocol)

> 2026-05-06 / 독립 감사. 산출물 5개 (PRD §9 / TRD-011 / me/013 / persistence.py / test_persistence_protocol.py).

## 1. 요약 판정

**PASS** — 5개 산출물이 작업 원칙 (Hexagonal / 비손상 / 라인 한도 / 한국어 / 정합성) 5개 모두 충족.
선행 audit 14회 회귀 0. 13 케이스 단위 테스트 PASS, ruff clean, 전체 회귀 433 PASS.

## 2. 체크리스트 결과

### A. Hexagonal — PASS
- `chatbot/domain/persistence.py` import: `__future__`, `datetime`, `typing`, `pydantic`, `chatbot.domain.conversation` 만 (persistence.py:13–20). 외부 SDK (langchain / supabase / psycopg / sqlalchemy) 0.
- 테스트도 동일 — `chatbot.domain.{conversation,intent,persistence}` 만 사용. In-memory `_MemConversationStore` 가 외부 호출 0.
- Protocol 은 `runtime_checkable` — 어댑터 임포트 없이 isinstance 검증 가능.

### B. 기존 코드 비손상 — PASS
- `git diff HEAD -- rag_core/ api/ chatbot/` → 출력 0줄.
- `chatbot/domain/`, `chatbot/infrastructure/`, `chatbot/application/` 의 다른 모듈 변경 0.
- `git diff --stat docs/prd/draft/002-multi-device-sync.md` → +58줄 (§9 추가 only). 기존 §1~§8 무영향.
- `grep "from chatbot.domain.persistence" chatbot/ api/` → 매치 0 — 본 phase 가 *추상만* 이고 application/route 통합은 PR 12~14 영역. 의도와 정확히 일치.

### C. 단일 책임 / 라인 한도 — PASS
| 파일 | 라인 | 한도 | 상태 |
|---|---:|---:|:---:|
| `chatbot/domain/persistence.py` | 78 | ≤200 | OK |
| `tests/chatbot/test_persistence_protocol.py` | 200 | ≤250 | OK |
| `docs/trd/draft/011-supabase-persistence.md` | 294 | — | OK |
| `docs/me/013-supabase-persistence-decisions.md` | 93 | — | OK |

함수당 최장 18줄 (`_MemConversationStore.list_for_user`) — 30줄 한도 충족. 도메인 메서드 모두 3~9줄.

### D. PRD-002 / TRD-011 / me/013 정합 — PASS
4 결정의 3-way 정합 (전부 동일 표현):

| 결정 | PRD-002 §9 | TRD-011 | me/013 |
|---|---|---|---|
| 1. 사용자 식별 | 결정 1' Magic Link (§9 첫 단락) | §6 `AUTH_ENABLED` env, §2.1 `UserIdentifier.current_user_id` | §결정 1 Magic Link |
| 2. 스키마 | 결정 2 JSONB 1-table | §2.3 SQL `state jsonb not null` | §결정 2 JSONB |
| 3. Checkpointer | 결정 3 자체 ConversationStore | §2.1 Protocol + §2.2 어댑터 ~150줄 | §결정 3 자체 어댑터 |
| 4. 절체 | 결정 4 Supabase 진실원천 + IndexedDB 캐시 | §2.5 `store.load` 우선 + chat_history fallback | §결정 4 1차 Supabase, 2차 IndexedDB |

RLS 정책 일관성: TRD-011 §2.3 의 `using (auth.uid() = user_id) with check (auth.uid() = user_id)` 가 me/013 §결정 4 의 "RLS 가 사용자 격리 보장" 과 정확히 매칭. PRD-002 §9 의 추상 매핑 표가 TRD-011 §3 PR 시퀀스 (PR 11~17) 와 충돌 없음.

### E. 타입 / 스타일 — PASS
- `ruff check chatbot/domain/persistence.py tests/chatbot/test_persistence_protocol.py` → All checks passed.
- `ruff format --check` → 2 files already formatted.
- 모든 함수/메서드 타입힌트 (Conversation 반환, `*, user_id: str` keyword-only 등).
- 한국어 docstring (persistence.py 의 모듈/클래스/메서드 모두), 식별자 영문, 이모지 0.

### F. 테스트 품질 — PASS
- `pytest tests/chatbot/test_persistence_protocol.py -q` → 13 passed in 0.18s.
- `pytest tests/chatbot/ -q` → 208 passed.
- LLM 호출 0 (Protocol 단위 테스트 + In-memory FakeStore).
- 핵심 케이스 모두 커버:
  - round-trip (test_persistence_protocol.py:72)
  - save/load 본인 (l.90)
  - 다른 사용자 차단 — RLS 시뮬 (l.101)
  - 미존재 None (l.109)
  - upsert (l.114)
  - list 본인만 (l.130)
  - list limit (l.139)
  - delete 본인 (l.146)
  - delete 다른 사용자 silent no-op (l.153)
  - UserIdentifier 인증/익명 (l.173, l.178)
  - Protocol shape (l.187)
  - Summary frozen (l.197)
- `_MemConversationStore` 의 RLS 시뮬: `(user_id, conversation_id)` 튜플 키로 user_id 격리. 다른 사용자 조회는 `dict.get` 이 None 반환 — 보안적으로 정확.

### G. Conversation 직렬화 무손실 — PASS
- `test_conversation_model_dump_load_round_trip` (l.72) 가 `model_dump(mode="json")` → `model_validate` round-trip 검증.
- 2 Turn 시퀀스 (한글 콘텐츠 "예정론?" / "베자는?") 가 `restored.turns[0].user_message.content` 까지 동등.
- `Conversation.turns: tuple[Turn, ...]` (frozen) ↔ JSON list 변환 무손실 검증됨 — Pydantic v2 가 tuple → list 직렬화, 역방향에서 다시 tuple 로 복원.

### H. 잠재적 결함 — PASS (모두 명시되어 있음)
- `ConversationSummary` frozen 보장: `model_config = ConfigDict(frozen=True)` (persistence.py:29) + 회귀 테스트 `test_summary_불변` (l.197).
- `delete` silent no-op: docstring 에 *"존재하지 않거나 다른 사용자 소유면 silent no-op (보안 — 존재 여부 노출 X)"* (persistence.py:64) + 테스트 `test_store_delete_다른_사용자_silent_no_op` (l.153) 의 한글 docstring 도 동일 보안 의도 명시.
- `UserIdentifier.current_user_id` None 반환: docstring "JWT 검증 실패 또는 익명 모드 시 None" (persistence.py:77) + 테스트 `test_user_identifier_anonymous_fallback` (l.178) 가 `AUTH_ENABLED=false` 환경 명시.
- Application 레이어 미통합: `grep "from chatbot.domain.persistence" chatbot/application/ api/` 매치 0. PR 12~14 영역 — TRD-011 §3 PR 시퀀스와 일치.

### I. 이전 audit 권고 회귀 점검 — PASS
- 14회 audit (2-A~6-phaseB) 의 핵심 권고들 (frozen 모델, Hexagonal 의존성, 한국어 docstring, 라인 한도, 이모지 0, ruff format) 모두 본 phase 에서 유지됨.
- 본 phase 는 *신규 추가* 만 — 회귀 영역 자체가 좁음.

### J. PR 12 (Supabase 어댑터) 시작 전 권고 — 아래 §7 참조

## 3. 회귀 검증 결과

| 영역 | 결과 |
|---|---|
| `ruff check` (persistence.py + test) | All checks passed |
| `ruff format --check` | 2 files already formatted |
| `pytest tests/chatbot/test_persistence_protocol.py -q` | 13 passed in 0.18s |
| `pytest tests/chatbot/ -q` (회귀) | 208 passed |
| `pytest tests/ -q` (전체, eval/integration 제외) | 433 passed, 5 warnings |

## 4. 위반 / 권고

### 위반 — 없음

### 사소한 권고 (다음 PR 에서 검토 가능, 본 PR 머지 차단 X)

1. **`test_summary_불변` 의 `pytest.raises(Exception)`** (test_persistence_protocol.py:199) — `ValidationError` 로 좁히면 더 명시적. 다만 pydantic v2 의 frozen 위반은 실제로 `pydantic_core.ValidationError` 라 `Exception` 으로 잡아도 의도 변질 없음.
2. **`ConversationSummary.title` 길이 제약 미명시** — docstring 의 "첫 30자" 가 어댑터 책임이지만, 도메인 측 `Field(max_length=...)` 로 강제하면 어댑터 버그 방어 가능. PR 12 에서 결정.
3. **`UserIdentifier.current_user_id` 의 `request: Any`** (persistence.py:76) — TRD-011 §2.1 는 `Request` 로 표기. 도메인이 FastAPI 에 의존하지 않으려는 의도라 `Any` 가 옳음. 다만 docstring 에 "FastAPI Request 또는 동등한 컨텍스트 객체" 명시하면 의도 명료. (현재는 모듈 docstring 에서 충분히 추측 가능).

## 5. 통계

| 지표 | 값 |
|---|---:|
| 신규 코드 파일 | 1 (`chatbot/domain/persistence.py`) |
| 신규 테스트 파일 | 1 (`tests/chatbot/test_persistence_protocol.py`) |
| 신규 문서 파일 | 2 (TRD-011, me/013) |
| 수정 문서 파일 | 1 (PRD-002 §9 추가) |
| 도메인 라인 | 78 |
| 테스트 라인 | 200 |
| 도메인 메서드 수 | 5 (Protocol 4 + UserIdentifier 1) |
| 테스트 케이스 수 | 13 |
| 최장 함수 (도메인) | 9줄 (`list_for_user` Protocol 시그니처) |
| 최장 함수 (테스트) | 18줄 (`_MemConversationStore.list_for_user`) |
| 외부 SDK import | 0 |
| 기존 파일 변경 (코드) | 0 |
| 기존 파일 변경 (문서) | 1 (PRD-002 §9 추가만) |

## 6. PRD / TRD / me 정합 평가

3-way 정합 검증 결과 **충돌 0**. 4가지 결정 (Magic Link / JSONB / 자체 어댑터 / Supabase 진실원천) 이 세 문서 모두에서 동일 표현으로 명시. RLS 정책 (`auth.uid() = user_id`) 이 TRD-011 §2.3 SQL ↔ me/013 §결정 4 ↔ PRD-002 §9 결정 4 사이 일관. PR 시퀀스 (PR 11~17) 가 TRD-011 §3 와 PRD-002 §9 의 추상 매핑 표 (`useSessions` ↔ `SupabaseSessionStore`) 와 충돌 없음.

도메인 추상 (`ConversationStore`, `ConversationSummary`, `UserIdentifier`) 이 TRD-011 §2.1 의 코드 블록과 시그니처 동등 — 단 `UserIdentifier.current_user_id(request: Request)` 가 도메인에서는 `request: Any` 로 *FastAPI 의존 제거*. Hexagonal 방향 강화이며 TRD 의도 (도메인 외부 의존 0) 와 정합.

## 7. PR 12 (Supabase 어댑터) 시작 전 권고

1. **의존 추가 위치**: `pyproject.toml` 의 `[project.optional-dependencies]` 에 `supabase = ["supabase>=2.0", ...]` 같은 그룹으로 분리. 어댑터 미사용 환경 (테스트, dev, 시연) 에서 설치 부담 0.
2. **Conversation.model_dump 의 datetime ISO 8601**: pydantic v2 의 `model_dump(mode="json")` 이 datetime → ISO 8601 string 변환을 기본 보장. Postgres `jsonb` 가 ISO 8601 문자열을 그대로 저장 가능 — 별도 직렬화 변환 불필요. 다만 *역방향* 에서 `Conversation.model_validate` 가 ISO string → datetime 자동 파싱 (Pydantic 기본). round-trip 테스트 (G) 가 이를 이미 검증.
3. **SQL 마이그레이션 dry-run**: TRD-011 §2.3 의 SQL 을 `supabase db push --dry-run` 또는 로컬 Supabase CLI 의 `supabase start` + 별도 schema 에서 1회 검증. CREATE INDEX, RLS, trigger 모두 idempotent 하지 않으므로 (`if not exists` 누락) — `create extension if not exists`, `create policy if not exists` 같은 idempotent 형태로 SQL 보강 권장.
4. **`SupabaseConversationStore` 의 단위 테스트**: `supabase-py` 의 client 를 mock 하는 fake 어댑터 vs. testcontainers/Supabase 통합 테스트 — TRD-011 §5 가 후자를 명시. 로컬 통합 어렵다면 mock 우선 + 별도 manual smoke test (실 Supabase 프로젝트) 분리.
5. **`title` 추출 로직 위치**: 어댑터의 `save(conversation)` 시점에 `conversation.turns[0].user_message.content[:30]` 을 별도 column 으로 저장 (TRD-011 §2.3 의 `title text` 컬럼). 도메인은 이 추출 로직 미보유 — 어댑터 책임으로 분리.
6. **`AUTH_ENABLED=false` 분기**: bootstrap 에서 `UserIdentifier` 를 익명 stub 으로 주입하면 ConversationStore 도 None (stateless fallback) 로 강제. PR 13 의 통합 시점에 분기 1곳에서만 결정 — 라우트 레벨에 분기 누수 방지.
7. **`ConversationSummary.last_turn_at` 의 source**: 어댑터에서 `state->'turns'->-1->>'started_at'` 로 jsonb path 추출하면 별도 column 불필요. GIN 인덱스가 부분 쿼리 가능. 다만 정렬 (`order by last_turn_at desc`) 은 `updated_at` column 으로 대체하면 인덱스 활용 더 명확 — TRD-011 §2.3 의 `conversations_user_updated_idx` 활용.

---

**판정: PASS**
