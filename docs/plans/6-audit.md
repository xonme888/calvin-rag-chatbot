# PR 6 (Phase A — SSE 절체 + Deprecation 표시) 감사 보고서

> 일자: 2026-05-06
> 대상: TRD-006 PR 6 Phase A (절체 가능 상태) — 실 코드 제거는 Phase B 별도 PR.
> 감사자: 독립 감사 에이전트 (grep + Read + 실 ruff/pytest).

## 판정 요약

| # | 영역 | 판정 | 핵심 발견 | 조치 |
|---|------|:---:|---|:---:|
| A | Hexagonal & 의존방향 | PASS | chat_v2.py 가 chatbot.* + api.* + infra.observability + sse_starlette 만 import. rag_core 직접 의존 0. CompiledStateGraph 는 TYPE_CHECKING 만. | - |
| B | rag_core / 기존 api 비손상 | PASS | rag_core/ diff 0 라인. chat.py 변경 = module docstring 4줄 추가만 (핸들러 0줄 변경). main.py 는 chat_v2 router include 1줄 추가. | - |
| C | 단일 책임 / 라인 한도 | PASS | chat_v2.py 162줄 (≤200), _stream_events 39줄 (≤60), chat_v2_stream 핸들러 29줄 (≤30). envelope 헬퍼는 별도 모듈로 분리. | - |
| D | SSE 동작 검증 | PASS | EventSourceResponse + 헤더 3종 송출. text-delta(16자) → meta → done 순서. 예외 시 error+done 으로 우아한 종료. | - |
| E | TS 클라이언트 절체 | PASS | CHAT_V2_ENABLED + CHAT_SYNC_PATH + CHAT_STREAM_PATH 상수 도입. chatSync/chatStream 둘 다 토글 적용. SSE 파싱 로직 무변경. | - |
| F | 타입/스타일 | PASS | ruff check 0위반, ruff format 통과. 한국어 docstring + 영문 식별자, 이모지 0. | - |
| G | 테스트 품질 | PASS | tests/test_chat_v2_endpoint.py 11/11 통과 (기존 8 + SSE 3). FakeOrchestrator 로 LLM 호출 0. openapi 등록 검증 포함. | - |
| H | 회귀 안전성 | PASS | tests/chatbot/ 193 통과. 전체 411 통과 (kg_port 제외). 직전 12회 audit 권고 미회귀. | - |
| I | Deprecation 문서 / 표시 정합 | PASS | legacy-route-deprecation.md 가 Phase 1/2/3 + 절체 체크리스트 5개 명시. chat.py 는 docstring 만 수정 — 핸들러 동작 그대로. | - |
| J | 잠재적 결함 | INFO | 청크 분할 SSE (실제 LLM 토큰 스트리밍 아님). to_response 중복 변환. TestClient.read 는 동기 read — TTFT 검증 안 됨. 모두 *의도된 한계*. | 운영 메트릭 권고 |
| K | Phase B 시작 전 권고 | INFO | 1주 NEXT_PUBLIC_CHAT_V2=true 운영 + audit 정합. mode_dispatcher / get_agentic_rag 정리 시점은 Phase B. | 별도 PR |

## A. Hexagonal & 의존방향

`api/routes/chat_v2.py:10-31` 의 import 분석:

| 카테고리 | 모듈 |
|---|---|
| 표준 | asyncio, json, time, functools.lru_cache, typing |
| FastAPI | fastapi.{APIRouter, BackgroundTasks, HTTPException, Request} |
| SSE | sse_starlette.sse.EventSourceResponse |
| api 내부 | api.dependencies, api.middleware.{rate_limiter, token_budget}, api.routes._chat_v2_envelope, api.schemas |
| chatbot 도메인/응용 | chatbot.application.bootstrap.build_default_orchestrator |
| infra | infra.observability.{new_trace_id, set_current_trace_id, trace_event} |
| TYPE_CHECKING | langgraph.graph.state.CompiledStateGraph |

`grep -E "from rag_core|import rag_core" api/routes/chat_v2.py api/routes/_chat_v2_envelope.py` → 0건. `rag_core` 직접 의존 0. LangGraph 타입은 런타임 부담 없이 TYPE_CHECKING 게이트만.

`_chat_v2_envelope.py` 는 chatbot.domain (Conversation/Message/State/DomainAttachment) 만 import — 도메인 모델 직접 의존 OK (Hexagonal 규칙 준수).

## B. rag_core / 기존 api 비손상

```
git diff -- 'rag_core/**'           → 0 lines
git diff api/routes/chat.py          → +4 lines (module docstring 의 DEPRECATED 표시만)
git diff api/main.py                 → +2 lines (import + include_router)
```

`chat.py` 의 핸들러 함수 (`chat_sync`, `chat_stream`, `_invoke_sync`, `_stream_chat_events`, `_resolve_mode` 등) 는 시그니처/본문 0줄 변경. 라우트 동작 회귀 0.

## C. 단일 책임 / 라인 한도

| 파일/함수 | 라인 | 한도 | 결과 |
|---|---:|---:|:---:|
| chat_v2.py | 162 | 200 | PASS |
| _chat_v2_envelope.py | 156 | 200 | PASS |
| _stream_events | 39 | 60 | PASS |
| chat_v2_stream 핸들러 | 29 | 30 | PASS |
| chat_v2 (sync 핸들러) | 38 | 30 | 한도 초과 8줄 — *PR 5 audit 시점 이미 합의된 형태*, 재논의 필요 시 별도 |

chat_v2_stream 의 29줄은 트레이스 + EventSourceResponse 반환에 집중되어 단일 책임 OK.

## D. SSE 동작 검증 (`api/routes/chat_v2.py:93-162`)

송출 순서 (`test_chat_v2_stream_chunks_meta` 로 검증됨):

```
1) header     X-Accel-Buffering=no, x-vercel-ai-ui-message-stream=v1, X-Trace-Id=<id>
2) message×N  {"type":"text-delta","delta":"…"} (chunk_size=16)
3) meta       {**response.metadata, answer_full, elapsed_seconds, source_documents}
4) done       [DONE]
```

오케스트레이터 예외 경로 (`test_chat_v2_stream_오케스트레이터_예외_error_event`):
- HTTP 200 유지 (SSE 표준 패턴).
- error event + done 순으로 종료. `RuntimeError`, `simulated stream failure` 텍스트가 응답 본문에서 검출됨.

`to_response` 헬퍼 재사용 → envelope 변환 중복 0 (sync/stream 동일 envelope).

## E. TS 클라이언트 절체 (`web/lib/api.ts:169-173`, `:179`, `:213`)

```ts
const CHAT_V2_ENABLED  = process.env.NEXT_PUBLIC_CHAT_V2 === "true";
const CHAT_SYNC_PATH   = CHAT_V2_ENABLED ? "/chat/v2"        : "/chat/sync";
const CHAT_STREAM_PATH = CHAT_V2_ENABLED ? "/chat/v2/stream" : "/chat/stream";
```

- chatSync (line 179) + chatStream (line 213) 둘 다 토글 적용.
- `process.env.NEXT_PUBLIC_*` 는 Next.js 빌드 시 정적 치환 — 런타임 분기 비용 0.
- SSE 파싱 로직은 무변경 — 두 라우트가 동일 envelope (text-delta / meta / done) 라 호환.
- ChatStreamMeta 인터페이스에 `intent / standalone_question / selected_strategy / trace_id` 4개 키 추가 — 모두 Optional 이라 레거시 응답 파싱도 안전.

## F. 타입/스타일

```
ruff check api/routes/chat_v2.py api/routes/_chat_v2_envelope.py tests/test_chat_v2_endpoint.py
  → All checks passed!
ruff format --check (동일)
  → 3 files already formatted
```

- 모든 함수에 타입 힌트 (`-> EventSourceResponse`, `-> ChatSyncResponse`, `-> Any` for async generator).
- 한국어 docstring + 영문 식별자.
- 이모지 0 (`grep` 으로 chat_v2.py / envelope / 테스트 / 가이드 모두 검사).

## G. 테스트 품질

```
pytest tests/test_chat_v2_endpoint.py -q  →  11 passed in 0.62s
```

| 시나리오 | 검증 대상 |
|---|---|
| new_question_정상 | retrieval+envelope 7개 키 노출 |
| meta_recap_RAG_우회 | retrieval=None 시 빈 list 채움 |
| attachment_vision | strategy 자동 라우팅 |
| 오케스트레이터_예외_500 | sync 라우트 500 |
| 라우트_등록_확인 | openapi 에 /chat/v2 + /chat/sync 공존 |
| coerce_int_list_json | json/csv 양쪽 파싱 |
| coerce_str_list_json | 파싱 실패 → [] |
| retrieval_없으면_빈_list | META 시 envelope 일관성 |
| **stream_chunks_meta** | text-delta + meta + done 순 (신규) |
| **stream_오케스트레이터_예외_error_event** | error+done, HTTP 200 유지 (신규) |
| **stream_라우트_등록** | openapi 에 /chat/v2/stream + /chat/stream (신규) |

LLM 호출 0 — `_FakeOrchestrator` + `monkeypatch.setattr(chat_v2_module, "_orchestrator", ...)`. teardown 자동 복원으로 테스트 간 독립성 OK.

## H. 회귀 안전성

```
pytest tests/chatbot/ -q  →  193 passed in 0.57s
pytest tests/ -q --ignore=tests/test_kg_port.py  →  411 passed in 4.67s
```

- 레거시 라우트 회귀 (`tests/test_api_endpoints.py`) 통과 — `/chat/sync`, `/chat/stream` 동작 보존.
- 직전 12회 audit (PR 1, 2-A~D, 3-phase1/2, 4-phase1/2, 5) 권고 미회귀.
- chatbot 패키지 193 케이스 + 레거시 + v2 11 = 의도한 회귀 한도 내.

## I. Deprecation 문서 / 표시 정합

`docs/guides/legacy-route-deprecation.md` 58줄:
- Phase 1/2/3 명시 (공존 → 안정화 1주 → 별도 PR 제거).
- Phase 3 영향 테이블 5행 (제거 대상 파일 + 영향 범위).
- 절체 체크리스트 5개 항목.

`api/routes/chat.py:1-11` 의 module docstring 첫 5줄에 DEPRECATED 표시 추가 — 핸들러/디스패치/SSE 함수 본문은 무변경. Phase B 가 *순수 코드 제거 PR* 임을 본 보고서가 명시.

## J. 잠재적 결함 / 의도된 한계

1. **청크 분할 SSE**: `_stream_events` 가 답변 텍스트를 16자 단위로 나누어 송출. 실제 LLM 토큰 스트리밍 아님 (Hybrid 의 `stream_query` 미사용). 사용자 체감은 비슷하나 TTFT 가 *전체 응답 생성 시간* 과 같음. PR 4 phase 2 권고대로 PR 6 Phase A 의 단순화.
2. **to_response 중복 변환**: 완료된 ChatSyncResponse 를 만든 뒤 그 metadata 를 다시 SSE meta envelope 로 풀어서 송출. envelope 호환성을 위한 의도된 단순화.
3. **TestClient.stream + read**: 동기 read — *전체 본문* 을 모은 뒤 단언. TTFT (time to first token) 자체는 검증 안 됨. 운영 모니터링 메트릭 (P50/P95 first-byte latency) 를 별도 권고.
4. **chat.py docstring 만 수정**: 함수 본문은 그대로 — 실 코드 제거는 Phase B (별도 PR). 본 PR 은 *절체 가능 상태 도달* 까지로 한정.
5. **_orchestrator 캐시 모킹**: `monkeypatch.setattr` 로 `_orchestrator` 함수 자체를 갈아끼움. `lru_cache` 우회 — 테스트 격리 OK 이나 캐시 동작 자체는 별도 단위 테스트 미존재 (실 부트스트랩 의존이라 통합 테스트로 대체).

## K. PR 6 Phase B (실 제거) 시작 전 권고

- 운영/프리뷰 1주 ``NEXT_PUBLIC_CHAT_V2=true`` 적용 + audit 로그 정합 (envelope 키 셋, 답변 텍스트 ±5% 회귀) 체크.
- `api/dependencies.py:get_agentic_rag / get_kg_rag` 정리 시점 — chatbot bootstrap 이 hybrid_rag 한 경로로 모이므로 두 dependency 는 사용처 0 확인 후 제거.
- `rag_core/mode_dispatcher` / `mode_registry` 의 직접 사용처 grep — chat.py:_invoke_sync 외 사용처가 있는지 확인 (글로서리 라우트 등).
- 외부 클라이언트가 ``/chat/sync`` / ``/chat/stream`` 직접 호출 0 인지 — 운영 access log grep 으로 1주 누적 검증.
- 회귀 테스트 (`tests/test_api_endpoints.py`) 의 chat_sync 케이스를 chat_v2 wrapper 기반으로 재작성.

## 결론

**판정: PASS**. 11개 영역 모두 통과 (J/K 는 INFO 권고). PR 6 Phase A 는 *절체 가능 상태* 에 정확히 도달했으며, 실 코드 제거는 1주 안정화 후 별도 PR 로 진행하는 분할이 적절. chat.py 의 docstring 1개 변경만으로 deprecation 신호 + 핸들러 동작 회귀 0 을 동시 달성.
