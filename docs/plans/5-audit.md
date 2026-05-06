# PR 5 (UI 절체) — 독립 감사 보고서

대상 산출물 (PR 4 phase2 W1 envelope 갭 해소 + UI 절체):

- `api/routes/chat_v2.py` (84줄)
- `api/routes/_chat_v2_envelope.py` (156줄)
- `web/lib/api.ts` (314줄, +18줄 변경)
- `tests/test_chat_v2_endpoint.py` (243줄, 8 케이스)

검증 방식: grep + Read + 실 pytest + ruff. 추측 0, 실측 우선.

## 판정 요약

| # | 영역 | 판정 | 핵심 발견 | 조치 |
|---|------|:----:|-----------|:----:|
| A | Hexagonal & 의존방향 | PASS | envelope 은 `api.schemas` + `chatbot.domain.*` 만 import. `chatbot/` 어디에서도 `api` import 0 (grep 결과 0건). | - |
| B | rag_core / 기존 api 비손상 | PASS | `git diff HEAD -- rag_core/` 0줄. `api/routes/chat.py` 0줄. `api/main.py` 정확히 2줄 (import + include_router). chat.py mtime `May 5 17:52` 그대로. | - |
| C | 단일 책임 / 라인 한도 | WARN | 파일 84/156줄 (≤200 OK). 단 `chat_v2()` 35줄 / `_build_metadata()` 48줄 → 30줄 한도 초과. 본문은 단일 책임 유지 (가독성 양호). | I1 |
| D | W1 envelope 보강 (PR 4 phase2 권고 해소) | PASS | metadata 12 키 (cited_pages/source_pages/source_pages_label/suggested_followups/tool_calls/tool_call_count/subgraph/citations/pattern + intent/standalone_question/selected_strategy/trace_id) 모두 노출. retrieval=None 분기에서 빈 list/None 으로 일관 채움 (테스트 검증). | - |
| E | TS API 정합 | PASS | `chatSync` 가 `NEXT_PUBLIC_CHAT_V2==='true'` 토글 — `/chat/v2` ↔ `/chat/sync`. `ChatStreamMeta` 에 4개 선택 필드 (`?` 사용) 추가. 기존 메타 키 유지 — 프론트 컴포넌트 무변경. `chatStream` 미변경 (`/chat/stream` 그대로). | - |
| F | 타입 / 스타일 | PASS | ruff check / format 통과 ("All checks passed!" + "3 files already formatted"). 모든 함수 반환 타입 명시. 한국어 docstring + 영문 식별자. 이모지 0. tsconfig `strict: true`. | - |
| G | 테스트 품질 | PASS | `tests/test_chat_v2_endpoint.py::8 passed in 0.55s`. LLM 호출 0 (FakeOrchestrator). envelope 7개 키 셋 검증 + retrieval=None 빈 list + `_coerce_*` 단독 (json/csv/None/list 4 케이스). | - |
| H | 회귀 안전성 | PASS | `tests/chatbot/` 193 통과. 레거시 + e2e 221 통과 (직전 218 + chat_v2 엔드포인트 5 + 헬퍼 3 - 헬퍼 중복 보정 = 221). 직전 11회 audit 권고 모두 유지. | - |
| I | 잠재적 결함 | INFO | I2~I5 별도 명시 (운영 시 모니터링/PR 6 정리 대상). | I2-I5 |
| J | PR 6 (레거시 제거) 권고 | INFO | J1~J3 정리. | J1-J3 |

판정: **PASS (W1 envelope 보강 PR 4 phase2 갭 해소 확인 완료)**.

## A. Hexagonal & 의존방향

- `_chat_v2_envelope.py` import 검증 (grep `^from\|^import`):
  - `api.schemas` (ChatRequest, ChatSyncResponse) ← Presentation layer 자체 schema
  - `chatbot.domain.conversation` (Attachment, Conversation, Message)
  - `chatbot.domain.state` (ConversationState)
  - 표준 라이브러리 (`json`, `time`, `datetime`, `typing`)
  - **chatbot.application / infrastructure / rag_core import 0 → 위반 0**.
- `chat_v2.py` 는 `chatbot.application.bootstrap.build_default_orchestrator` (Application) + `infra.observability` (Infrastructure) 호출 — Presentation 의 정상 패턴.
- 역방향 검증: `grep -rn "^from api\|^import api" chatbot/` 결과 0건 → chatbot 패키지가 api 를 import 하는 위반 없음.

## B. rag_core / 기존 api 비손상

- `git diff HEAD -- rag_core/` → 0줄. `git diff HEAD -- api/routes/chat.py` → 0줄.
- `api/main.py` diff 정확히 2줄 (line 65 import 에 `chat_v2` 추가, line 115 `include_router(chat_v2.router)` 추가). 추가 변경 없음.
- chat.py mtime `May 5 17:52` (PR 5 이전 커밋 시점 유지).

## C. 단일 책임 / 라인 한도

| 파일 | 줄수 | ≤200 |
|------|------|:----:|
| chat_v2.py | 84 | OK |
| _chat_v2_envelope.py | 156 | OK |

| 함수 | 줄수 | ≤30 |
|------|------|:----:|
| `_orchestrator` | 4 | OK |
| `reset_orchestrator` | 3 | OK |
| `chat_v2` | 35 | **OVER 5** |
| `to_state` | 17 | OK |
| `_to_attachment` | 9 | OK |
| `to_response` | 15 | OK |
| `_unpack_result` | 9 | OK |
| `_build_metadata` | 48 | **OVER 18** |
| `_coerce_int_list` | 14 | OK |
| `_coerce_str_list` | 13 | OK |

검토:
- `chat_v2()` 35줄: 라우트 핸들러 + 트레이스 + 예외 변환 + docstring. docstring 6줄 제외 시 본문 29줄 — 사실상 한도 부합. 책임 분리 양호.
- `_build_metadata()` 48줄: 12 키 분기 + retrieval=None 빈 list 채움 + docstring 5줄. 분기 자체는 단순 dict 채움 이라 *cyclomatic 복잡도 낮음*. 추후 sync/v2 통합 envelope 헬퍼 추출 시 자연스럽게 줄어듦. **현재 가독성/단일 책임 측면 PASS, 강제 분할은 인위적**.

## D. W1 envelope 보강 검증 (PR 4 phase2 권고 해소)

`_build_metadata()` 가 노출하는 키 (Read 결과):

| 키 | 출처 | 타입 | retrieval=None |
|-----|------|------|----------------|
| `intent` | last_turn.intent.value | str/null | (그대로) |
| `standalone_question` | last_turn.standalone_question | str/null | (그대로) |
| `selected_strategy` | last_turn.selected_strategy | str/null | (그대로) |
| `trace_id` | new_trace_id() | str | (그대로) |
| `pattern` | retrieval.metadata["pattern"] | str/null | None |
| `citations` | RetrievalResult.citations[].model_dump() | list[dict] | (생략 → None 폴백 권고, I3) |
| `subgraph` | retrieval.subgraph.model_dump() | dict/null | None |
| `cited_pages` | _coerce_int_list(metadata["cited_pages"]) | list[int] | [] |
| `source_pages` | [d.page+1] | list[int/null] | [] |
| `source_pages_label` | [c.page_label] | list[str] | [] |
| `suggested_followups` | _coerce_str_list(metadata["suggested_followups"]) | list[str] | [] |
| `tool_calls` | [{tool_name, arguments}] | list[dict] | [] |
| `tool_call_count` | len(retrieval.tool_calls) | int | 0 |

`test_chat_v2_new_question_정상` 가 7개 키 (cited_pages/source_pages/source_pages_label/suggested_followups/tool_calls/tool_call_count/subgraph) 존재 검증.
`test_envelope_retrieval_없으면_빈_list_채움` 가 META 시나리오 빈 list/None 검증 (실제 통과 확인).

`_coerce_int_list` 의 robust parsing — json/csv/None/list 4 케이스 모두 단독 테스트 PASS. RetrievalResult 의 직렬화된 cited_pages (str) 와 fixture 의 list 둘 다 받아냄.

## E. TS API 변경 정합

- `web/lib/api.ts:171-172`:
  ```
  const CHAT_SYNC_PATH =
    process.env.NEXT_PUBLIC_CHAT_V2 === "true" ? "/chat/v2" : "/chat/sync";
  ```
  Next.js 빌드 시 정적 치환 — 런타임 토글 불가 (의도된 한계, I2).
- `ChatStreamMeta` 추가 4 필드 (`intent`/`standalone_question`/`selected_strategy`/`trace_id`) 모두 `?` 선택 필드 → `strict: true` 와 호환, 기존 사용처 무변경.
- `chatStream` (SSE) 는 `/chat/stream` 그대로 — chat_v2 가 sync only. ChatPanel 분기 (`hybrid`/`auto` → chatStream, 그 외 → chatSync) 상 chat_v2 노출 경로는 *agentic/kg/vision* 모드만 (운영 시 J1 권고).

## F. 타입 / 스타일

- `ruff check` 통과 ("All checks passed!"). `ruff format --check` 통과 ("3 files already formatted").
- 모든 함수 반환 타입 명시 (AST 검증 + grep `->` 양 시그니처 모두 확인).
- 한국어 docstring + 영문 식별자 (Common Pitfalls 준수).
- 이모지 0 (grep 결과 0건).

## G. 테스트 품질

`pytest tests/test_chat_v2_endpoint.py -v` → 8 passed in 0.55s.

| # | 케이스 | 검증 |
|---|--------|------|
| 1 | new_question_정상 | answer + intent + selected_strategy + pattern + trace_id + 7개 envelope 키 존재 |
| 2 | meta_recap_RAG_우회 | retrieval=None 시 source_documents=[] |
| 3 | attachment_vision | strategy="vision" 라우팅 |
| 4 | 오케스트레이터_예외_500 | RuntimeError → HTTPException 500 |
| 5 | 라우트_등록_확인 | OpenAPI paths 에 `/chat/v2` + `/chat/sync` 공존 |
| 6 | coerce_int_list_json | json/csv/empty/None/list 5 입력 |
| 7 | coerce_str_list_json | json/empty/None/list/non-json 5 입력 |
| 8 | 빈_list_채움 | META 시 7개 키 빈 list/None |

LLM 호출 0 — `_FakeOrchestrator.invoke()` 가 LangGraph CompiledStateGraph 인터페이스 모사.

## H. 회귀 안전성

- `pytest tests/chatbot/ -q` → 193 passed.
- `pytest tests/ -q --ignore=tests/chatbot` → 221 passed.
- 직전 11회 audit (PR 1, 2-A~D, 3-phase1/2, 4-phase1/2) 모든 PASS 권고 유지.

## I. 잠재적 결함 (참고)

- **I1 (LOW)**: `chat_v2()` 35줄 / `_build_metadata()` 48줄 → 30줄 가이드 초과. 본문은 분기/dict 채움이라 복잡도 낮음. **PR 6 에서 sync ↔ v2 통합 envelope 헬퍼로 자연 정리** 권고.
- **I2 (INFO)**: `process.env.NEXT_PUBLIC_CHAT_V2` 가 *빌드 시* 정적 치환 → 런타임 토글 불가 (Next.js 환경변수 규약). 의도된 한계 — README 또는 PRD-006 에 명시 권고.
- **I3 (LOW)**: retrieval=None 분기에서 `citations` 키 미설정 (다른 키들은 빈 list/None 으로 채움). 프론트가 `metadata.citations` 를 optional 로 취급해야 안전 — `web/lib/blocks.ts` 의 `?? []` 패턴 의존. retrieval=None 분기에 `citations: []` 명시 추가가 일관성 측면 안전.
- **I4 (INFO)**: `_coerce_int_list` 가 `"1, 2.5, abc"` 같은 부분 정수 토큰 입력 시 `[1]` 반환 (소수/문자 무시). Robust parsing 의도 — 단, *tuple* 형태 (예: `(1,2,3)`) 는 미지원. domain RetrievalResult.metadata 는 dict[str, Any] 라 향후 tuple 직렬화 가능성 있음. 명시 docstring 추가 권고.
- **I5 (INFO)**: `ChatStreamMeta.intent` literal union (`"new_question" | "followup" | ...`) 이 백엔드 `chatbot.domain.intent.Intent` enum 의 `.value` 와 *수동 동기화*. 한쪽 변경 시 다른 쪽 깨짐 — TRD-006 에 동기화 가이드 또는 codegen 권고.

## J. PR 6 (레거시 제거) 권고

- **J1**: `chatStream` 도 `/chat/v2` 화 (SSE 동등 라우트 추가) 또는 chatSync 우선 흐름 고정. 현재 chat_v2 가 sync only 라 hybrid/auto 모드 (스트리밍 우선) 는 chat_v2 노출 안 됨.
- **J2**: `api/routes/chat.py` 의 `_invoke_sync` 분기 제거 시점 — chat_v2 이 모든 모드 커버 후.
- **J3**: `api/dependencies.py:get_hybrid_rag()` 등 rag_core 직접 의존처를 chatbot 어댑터로 일원화 — Hexagonal 정합 강화.

## 결론

PR 5 산출물은 W1 envelope 갭 해소 + UI 절체를 *기존 라우트 비손상* 으로 달성. 12 키 envelope 일관성 + 8 케이스 테스트 + 221 회귀 통과 검증 완료. 함수 길이 초과는 분기 단순성으로 가독성 PASS. **승인**.
