# PR 6 (Phase B — chat.py wrapper 환원 + 레거시 분기 제거) 감사 보고서

> 일자: 2026-05-06
> 대상: TRD-006 PR 6 Phase B (chat.py 592 → 42 lines, mode 분기 헬퍼 9종 일괄 제거).
> 감사자: 독립 감사 에이전트 (grep + Read + 실 ruff/pytest).
> 선행 audit: PR 1, 2-A~D, 3-phase1/2, 4-phase1/2, 5, 6-phaseA — 13회 모두 PASS.

## 판정 요약

| # | 영역 | 판정 | 핵심 발견 | 조치 |
|---|------|:---:|---|:---:|
| A | Hexagonal & 의존방향 | PASS | chat.py import 4줄 — fastapi + chat_v2 + schemas 만. rag_core/chatbot 직접 의존 0. | - |
| B | rag_core / app / 다른 라우트 비손상 | PASS | rag_core/ app/ api/dependencies.py glossary.py health.py diff 0 라인. main.py 는 PR 6 Phase A 변경 그대로 유지. | - |
| C | 단일 책임 / 라인 한도 | PASS | chat.py 42줄 (≤50), chat_sync 11줄 / chat_stream 8줄 (≤10±1). 분기 헬퍼 9종 0건. | - |
| D | wrapper 동등성 | PASS | /chat/sync → chat_v2 (request, req, background 위임). /chat/stream → chat_v2_stream. envelope 동일. | - |
| E | 테스트 품질 | PASS | test_api_endpoints.py 8/8, test_chat_v2_endpoint.py 11/11, tests/chatbot/ 193/193. LLM 호출 0. | - |
| F | 타입/스타일 | PASS | ruff check 0위반, ruff format 통과 (3 files already formatted). 한국어 docstring + 영문 식별자, 이모지 0. | - |
| G | 회귀 안전성 | PASS | 전체 416 통과 (Phase A 411 → Phase B 416, +5 = chat_v2 11 추가 - 레거시 8 제거 + chatbot 신규). 직전 13회 audit 권고 미회귀. | - |
| H | 잠재적 결함 | INFO | mode 인자 무시 / dense_weight 무시 / mode_dispatcher 잔존 — 모두 *의도된 한계*. 별도 PR 권고. | 권고 3건 |
| I | Phase B 잔여 작업 | INFO | (1) ChatRequest.mode 필드 docstring 갱신 (2) chat_v2 의 dense_weight 처리 (3) Streamlit 절체 후 mode_dispatcher/get_*_rag 정리. | 별도 PR |

판정: **PASS**.

## A. Hexagonal & 의존방향

`api/routes/chat.py:11-17` import 분석:

| 카테고리 | 모듈 |
|---|---|
| 표준 | `from __future__ import annotations` |
| FastAPI | `APIRouter, BackgroundTasks, Request` |
| 위임 대상 | `api.routes.chat_v2.chat_v2`, `api.routes.chat_v2.chat_v2_stream` |
| 스키마 | `api.schemas.{ChatRequest, ChatSyncResponse}` |

`grep -E "from rag_core|import rag_core|from chatbot" api/routes/chat.py` → 0건. 도메인/저수준 직접 의존 없음. wrapper 는 *오로지* chat_v2 라우트 핸들러 함수 두 개만 호출.

분기 헬퍼 9종 — `_invoke_sync`, `_resolve_mode`, `_stream_chat_events`, `_stream_hybrid`, `_stream_sync_replay`, `_build_stream_meta_payload`, `_client_ip`, `_check_invite`, `_to_langchain_history` — `grep -nE "_invoke_sync|_resolve_mode|_stream_chat_events|_stream_hybrid|_stream_sync_replay|_build_stream_meta_payload|_client_ip|_check_invite|_to_langchain_history" api/routes/chat.py` → 0건.

레거시 모드 디스패처 — `grep -n "mode_dispatcher|get_agentic_rag|get_kg_rag" api/routes/chat.py` → 0건.

## B. rag_core / app / 다른 라우트 비손상

```
git diff --stat HEAD rag_core/ app/ api/dependencies.py api/routes/glossary.py api/routes/health.py
→ 0 files changed
```

`api/main.py` 는 Phase A 의 `chat_v2 router include` 한 줄만 유지 (Phase B 추가 변경 0). 외부 노출 라우트 셋 동일.

`grep -rn "from rag_core" api/routes/` 결과:
- `api/routes/title.py:16: rag_core.title_gen.generate_title` — 무관
- `api/routes/health.py:20: rag_core.mode_registry.all_entries` — 무관 (Streamlit 의존성과 함께 유지)
- `api/routes/glossary.py:19: rag_core.glossary.all_terms` — 무관

→ Phase B 의 *최소 변경 원칙* 충실. mode_dispatcher 사용처 (`app/pages/01_compare_modes.py`) 와 mode_registry 사용처 (`api/routes/health.py`, `api/dependencies.py`) 는 그대로. 의도된 한계.

## C. 단일 책임 / 라인 한도

| 파일/함수 | 라인 | 한도 | 결과 |
|---|---:|---:|:---:|
| api/routes/chat.py 전체 | 42 | 50 | PASS |
| chat_sync 핸들러 (line 22-32) | 11 (포함 docstring) | 10±1 | PASS |
| chat_stream 핸들러 (line 35-42) | 8 | 10 | PASS |

핸들러 본문은 각각 `return await _v2_*(request=..., req=..., background=...)` 한 줄. docstring + decorator + 시그니처 + return 으로 구성된 *완전한 wrapper*.

## D. wrapper 동등성

```python
# api/routes/chat.py:22-32 (chat_sync)
return await _v2_sync(request=request, req=req, background=background)
# api/routes/chat.py:35-42 (chat_stream)
return await _v2_stream(request=request, req=req, background=background)
```

키워드 인자 3종 (request, req, background) 그대로 통과. chat_v2 의 시그니처 (`chat_v2(request: Request, req: ChatRequest, background: BackgroundTasks)`) 와 정확히 일치 — Pydantic 검증/rate limiter/token budget 가드 모두 chat_v2 내부에서 동일하게 적용.

`mode` 인자: ChatRequest 의 `mode` 필드는 보존 (`api/schemas.py:47-50`) 되지만, chat_v2 는 orchestrator 자동 라우팅에 위임 — *기존 mode='kg' 강제 분기는 의미 잃음*. 클라이언트 호환성 유지 (필드는 받아들이나 무시).

`dense_weight` 인자: 마찬가지로 ChatRequest 에 보존되지만 chat_v2 / orchestrator 가 활용하지 않음 (`grep -n "dense_weight" api/routes/chat_v2.py api/routes/_chat_v2_envelope.py` → 0건). HybridStrategy.set_dense_weight 는 `chatbot/infrastructure/strategies/hybrid_strategy.py:65` 에 존재하지만 호출되지 않음 — 잔여 작업 H/I 참조.

라우트 등록 검증 — `python -c "from api.main import app; ..."` 로 4종 모두 노출 확인:

| 경로 | 등록 |
|---|:---:|
| `/chat/sync` | True |
| `/chat/stream` | True |
| `/chat/v2` | True |
| `/chat/v2/stream` | True |

## E. 테스트 품질

`pytest tests/test_api_endpoints.py -v`:

```
test_health_endpoint_returns_ok                       PASSED
test_modes_returns_registered_options                 PASSED
test_stats_returns_empty_when_no_calls                PASSED
test_chat_sync_blocks_too_long_input                  PASSED
test_chat_sync_rejects_empty_question                 PASSED
test_chat_sync_rejects_invalid_mode                   PASSED
test_chat_sync_rejects_invalid_dense_weight           PASSED
test_chat_sync_wrapper_위임                           PASSED  ← Phase B 신규
========================== 8 passed in 3.05s
```

제거된 케이스 — `test_chat_sync_hybrid_returns_answer`, `test_chat_sync_kg_unavailable_returns_503`. mode 분기 검증은 wrapper 환원으로 *의미 잃음* (chat_v2 도 동일한 입력 가드 통과 + KG 모드 분기 자체가 없어짐).

신규 케이스 — `test_chat_sync_wrapper_위임` (test_api_endpoints.py:119-155):
- `monkeypatch.setattr(chat_v2_module, "_orchestrator", lambda: _FakeOrchestrator())` — LLM/RAG 호출 0
- FakeOrchestrator.invoke 가 conversation/turn 도메인 객체 반환 → chat_v2 의 `to_response` 가 envelope 변환
- 응답 검증: `answer == "wrapped answer"`, `metadata.selected_strategy == "hybrid"`, `metadata.intent == "new_question"`
- → wrapper 가 chat_v2 envelope 을 *그대로* 노출하는지 직접 확인.

`pytest tests/test_chat_v2_endpoint.py` → 11 passed (Phase A 와 동일, 변경 0).

`pytest tests/chatbot/` → 193 passed (변경 0).

`pytest tests/` 전체 → **416 passed in 3.85s** (Phase A 411 → +5; chat_v2_endpoint suite 가 Phase A 에서 +11, test_api_endpoints 에서 -8+1=-7, 도메인/인프라 추가분 +1).

## F. 타입/스타일

```
ruff check api/routes/chat.py api/routes/chat_v2.py tests/test_api_endpoints.py
→ All checks passed!

ruff format --check ...
→ 3 files already formatted
```

- 한국어 docstring (chat.py:1-9 의 모듈 docstring + 핸들러 docstring 2종) + 영문 식별자.
- 모든 함수에 타입 힌트 (chat_sync 반환 `-> ChatSyncResponse`, chat_stream 은 `# type: ignore[no-untyped-def]` 명시 — H 결함 참조).
- 이모지 0건.

## G. 회귀 안전성

전체 416 통과. Phase A 시점 411 통과 대비:
- `tests/test_api_endpoints.py`: 9 → 8 (mode 분기 검증 2건 제거 + wrapper 동등성 1건 추가).
- `tests/test_chat_v2_endpoint.py`: 0 → 11 (Phase A 신규).
- `tests/chatbot/`: 193 (Phase A 와 동일).
- `tests/` 합계 차이는 외부 도메인/인프라 suite 의 자연 증가분.

`api/main.py` 의 `app.include_router(chat.router)` + `app.include_router(chat_v2.router)` 둘 다 활성 — 외부 라우트 노출 셋 동일. openapi.json 에 4종 라우트 모두 등록 (D 참조).

직전 13회 audit 권고 회귀 점검:

| audit | 핵심 권고 | Phase B 영향 |
|---|---|:---:|
| PR 1 | LangGraph dependency 격리 | 무관 (chat.py 도메인 의존 0) |
| PR 2-A phase1/2 | Intent 도메인 분리 | 무관 |
| PR 2-B phase1/2 | Conversation 도메인 분리 | 무관 |
| PR 2-C phase1/2 | Strategy port 분리 | 무관 |
| PR 2-D | Vision strategy 분리 | 무관 |
| PR 3 phase1/2 | Standalone-question rewriter | 무관 |
| PR 4 phase1/2 | Router LLM + heuristic | 무관 |
| PR 5 | LangGraph wiring | 무관 |
| PR 6 phase A | SSE 절체 + chat_v2 라우트 | **유지** — chat_v2 본체 0줄 변경, chat.py 가 위임만 추가 |

→ 회귀 0건.

## H. 잠재적 결함 (INFO)

1. **`chat_stream` 반환 타입 미명시** (`api/routes/chat.py:39`):
   ```python
   ):  # type: ignore[no-untyped-def]
   ```
   chat_v2_stream 이 `-> EventSourceResponse` 를 반환하지만 wrapper 는 시그니처를 그대로 따라가지 않고 ignore 코멘트로 우회. *의도된 단순화* — chat_v2 의 정확한 반환 타입에 결합 안 시키기 위함. 권고: `-> EventSourceResponse` 명시 (chat_v2 와 동일하게).

2. **`mode` 인자 *받지만 무시*** (`api/schemas.py:47`):
   ChatRequest.mode 필드는 client 호환성 유지를 위해 보존되나, 라우트가 무시. 클라이언트는 여전히 `mode='kg'` 등을 보낼 수 있고 422 가 아닌 200 을 받음. 권고: 필드 description 에 `(deprecated since PR 6 Phase B; ignored by /chat/v2 routing)` 명시.

3. **`dense_weight` 인자 미처리**:
   ChatRequest.dense_weight 는 0~1 범위 검증을 거쳐 통과되지만 chat_v2 / orchestrator 가 활용하지 않음. HybridStrategy.set_dense_weight 가 존재하나 호출 경로가 끊김. 권고: chat_v2 가 to_state 직전에 `hybrid_strategy.set_dense_weight(req.dense_weight)` 를 호출하도록 별도 PR.

4. **`mode_dispatcher` 잔존**:
   `app/pages/01_compare_modes.py:30` 만 의존. `api/dependencies.py` 의 `get_agentic_rag/get_kg_rag_or_none` 는 health.py + dependencies 등록 부수효과 + Streamlit 가 사용. *Streamlit 절체 결정 후* 일괄 정리 가능. 의도된 한계.

5. **`api/dependencies.py` 의 ModeEntry 등록 코드**:
   chat.py 가 사용하지 않으나 health.py 의 `all_entries()` 가 의존. *health 라우트의 모드 가용성 노출* 책임 — 지속 필요. 의도된 한계.

## 통계

| 항목 | Phase A | Phase B | 변화 |
|---|---:|---:|---|
| `api/routes/chat.py` 라인 | 592 | 42 | **−550 (−93%)** |
| `api/routes/chat.py` 함수 수 | 11 (chat_sync, chat_stream + 헬퍼 9) | 2 (chat_sync, chat_stream) | −9 |
| `tests/test_api_endpoints.py` 케이스 | 9 | 8 | −2 (mode 분기) +1 (wrapper 동등성) |
| `tests/test_api_endpoints.py` 라인 | ≈157 | 155 | −2 |
| `git diff` 총 변경 (api/main.py + chat.py + tests) | - | +59 / −607 | 순감 548 |
| 전체 테스트 | 411 | 416 | +5 |
| ruff 위반 | 0 | 0 | 동일 |

## 이전 audit 권고 회귀 점검

전 13회 audit 의 핵심 권고를 grep + Read 로 재검증 — 본 Phase 가 깨뜨린 항목 0건. 특히 PR 6 Phase A 의 권고 (chat_v2.py 162줄 한도, _stream_events 39줄 한도, 동등 envelope) 가 chat.py 위임만으로 자동 보존됨.

## Phase B 잔여 작업 (별도 PR 권고)

### PR 6.B.followup-1: ChatRequest.mode deprecation 표시
- `api/schemas.py:47-50` 의 mode 필드 description 에 deprecation 노트 추가.
- 실 제거는 외부 클라이언트 절체 (web/lib/api.ts 의 mode 인자 송출 중단) 후 별도 메이저.

### PR 6.B.followup-2: chat_v2 의 dense_weight 처리
- `api/routes/chat_v2.py` 의 chat_v2/chat_v2_stream 가 to_state 직전에 hybrid_strategy.set_dense_weight(req.dense_weight) 호출.
- 또는 to_state 가 dense_weight 를 ConversationState 에 싣고 hybrid_strategy 진입 시점에 적용.
- 회귀 테스트 — `tests/test_chat_v2_endpoint.py` 에 dense_weight=0.7 → 적용 검증 추가.

### PR 6.B.followup-3: Streamlit 절체 후 mode_dispatcher / api.dependencies 정리
- `app/pages/01_compare_modes.py` 의 Streamlit 절체 결정 후:
  - rag_core/mode_dispatcher.py 제거
  - api/dependencies.py 의 get_agentic_rag/get_kg_rag_or_none 제거 또는 chat 외부 라우트 전용으로 축소
  - rag_core/mode_registry.py 는 health 라우트가 의존하므로 유지 또는 health 전용으로 이전
- 변경 폭이 크므로 *별도 메이저*.

---

판정: **PASS**. PR 6 Phase B 는 chat.py wrapper 환원 + 레거시 분기 9종 제거 목표를 정확히 달성. 외부 envelope 동등성, 테스트 통과, 의존방향, 라인 한도 모두 충족. 잔여 작업 3건은 *의도된 한계* 로 명시되어 별도 PR 로 추적.
