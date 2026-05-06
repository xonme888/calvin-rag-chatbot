# PR 3 Phase 2 Audit — Orchestrator(LangGraph) + 통합 시나리오 + Phase 1 권고 반영

대상: PR 3.4 / 3.5 + Phase 1 권고 P2(헬퍼 분리), P3(compose_answer 축소)
일자: 2026-05-06
방식: grep + Read + 실제 pytest / ruff 실행

---

## 1. 요약 판정

**PASS**

- Hexagonal 의존방향 위반 0건. `chatbot/application/` 안에 `chatbot.infrastructure` import 없음.
- LangGraph 의존이 `orchestrator.py` 안에서만 발생 — `TYPE_CHECKING` (`CompiledStateGraph`) + `build_orchestrator` 함수 본문 내부의 lazy import. 노드 5개 어디에도 `langgraph` import 0건.
- Phase 1 권고 2건 모두 해소: P2(`_to_request` 중복) → `nodes/_helpers.py` 신설로 일원화, P3(`compose_answer` 36줄) → 22줄로 축소 + `_build_turn` 헬퍼 분리.
- `tests/chatbot/test_orchestrator.py` 5/5 PASS, `tests/chatbot/test_nodes.py` 16/16 PASS, 전체 `tests/chatbot/` 163/163 PASS, 레거시 `tests/` (excl. chatbot) 213/213 PASS.
- ruff check + format 통과 (13 files already formatted).
- 함수/파일 라인 한도 모두 준수 (orchestrator.py 87줄 ≤ 200, `build_orchestrator` 33줄 ≤ 60, `_route_after_classify` 15줄 ≤ 30, `compose_answer` 본문 17줄 ≤ 30).
- 차단 위반 0건. 권고 3건 (모두 PR 4 또는 그 이후 합류) — 본 phase 차단 아님.

---

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS

| 항목 | 결과 |
|---|---|
| `chatbot/application/` → `chatbot.infrastructure` import | 0건 (grep) |
| `chatbot/application/nodes/` 안 `langgraph` import | 0건 (grep) |
| `orchestrator.py` 의 langgraph import 위치 | line 35 `TYPE_CHECKING` 가드 내부 (`CompiledStateGraph`), line 50 `build_orchestrator` 함수 본문 내부 — lazy import 충족 |
| `_helpers.py` import | `chatbot.domain.conversation`, `chatbot.domain.retrieval`, `chatbot.domain.state` — 도메인만 |
| 노드들이 `StrategyRegistry` Protocol(`chatbot.domain.strategy:50`) 의존 | 확인 — `InMemoryStrategyRegistry` 구체 의존 0 |

근거: `chatbot/application/orchestrator.py:13-35`, `:50`; `chatbot/application/nodes/_helpers.py:9-11`; `chatbot/application/nodes/select_strategy.py:9-12`, `invoke_strategy.py:8-10`.

### B. rag_core / api 비손상 — PASS

`git diff --stat HEAD -- rag_core/ api/` 결과 0줄. PR 3 이전 베이스라인 그대로.

### C. Phase 1 권고 P2 / P3 반영 검증 — PASS (RESOLVED)

#### P2 — `_to_request` 중복 → `nodes/_helpers.py` 일원화

| 항목 | 결과 |
|---|---|
| `nodes/_helpers.py` 신설 | 38줄. `to_retrieval_request(state) -> RetrievalRequest`, `history_messages(state) -> tuple[Message, ...]` 두 함수 + 모듈 docstring |
| 노드 파일에 `_to_request` / `def _to_request` 잔존 | grep 0건 |
| `select_strategy.py` 사용처 | line 10 `from ._helpers import to_retrieval_request`, line 25 / 30 호출 |
| `invoke_strategy.py` 사용처 | line 8 import, line 22 `strategy.run(to_retrieval_request(state))` |
| `rewrite_question.py` 사용처 | line 10 `from ._helpers import history_messages`, line 24 `history=history_messages(state)` |
| `compose_answer.py` 사용처 | line 13 import, line 29 `history=history_messages(state)` |
| 헬퍼의 도메인-only 의존 | `_helpers.py:9-11` 도메인만 import, 부수효과 0, 순수 변환 함수 |

근거: `chatbot/application/nodes/_helpers.py`, 사용처 4개 노드 파일 import 라인.

#### P3 — `compose_answer` 함수 본문 ≤ 30줄

| 항목 | 결과 |
|---|---|
| `compose_answer` 함수 본문(line 18~34) | 17줄 (이전 36줄에서 축소, 한도 30 충족) |
| `_build_turn` 헬퍼 분리(line 37~50) | 14줄 — Turn freeze 책임 1개 |
| 두 함수 책임 분리 | `compose_answer` = answerer 호출 + Conversation.append + state model_copy / `_build_turn` = 메타(elapsed_ms, started_at) 계산 + Turn freeze. 단일 책임 충족 |

근거: `chatbot/application/nodes/compose_answer.py:18-50`.

### D. 단일 책임 / 라인 한도 — PASS

| 파일 | 줄 수 | 한도 | 상태 |
|---|---:|---:|:---:|
| `orchestrator.py` | 87 | 200 | OK |
| `_helpers.py` | 38 | 200 | OK |
| `compose_answer.py` | 50 | 200 | OK |
| `select_strategy.py` | 33 | 200 | OK |
| `invoke_strategy.py` | 23 | 200 | OK |
| `rewrite_question.py` | 27 | 200 | OK |
| `classify_intent.py` | 23 | 200 | OK (변경 없음) |
| 함수 `build_orchestrator` | 33 | 60 | OK |
| 함수 `_route_after_classify` | 15 | 30 | OK |
| 함수 `compose_answer` | 17 | 30 | OK |
| 함수 `_build_turn` | 14 | 30 | OK |

### E. 노드 동작 회귀 (P2/P3 반영 후) — PASS

```
tests/chatbot/test_nodes.py 16 passed in 0.16s
```

세부:
- `test_invoke_chat_history_전달` — `history_messages` 헬퍼로 변환된 chat_history 가 `RetrievalRequest.chat_history` 로 전달됨 검증 (`len == 2`).
- `test_rewrite_followup_LLM_호출` — `history_messages(state)` 가 빈 history 면 빈 tuple 반환, FOLLOWUP 시 rewriter 1회 호출.
- `test_compose_정상_Turn_append`, `test_compose_누적_turn`, `test_compose_META_RECAP_retrieval_없음`, `test_compose_intent_None_RuntimeError` — `_build_turn` 분리 후에도 동일 동작.
- `history_messages` 반환 타입: `tuple[Message, ...]` (line 32, 38) — Protocol 시그니처(`QueryRewriter.rewrite.history`, `AnswerComposer.compose.history`)와 일치.

### F. Orchestrator 동작 검증 — PASS

```
tests/chatbot/test_orchestrator.py 5 passed in 0.16s
```

| # | 시나리오 | 결과 |
|---|---|:---:|
| 1 | NEW_QUESTION → hybrid 라우팅 | PASS |
| 2 | Hybrid → KG → META_RECAP 멀티턴 가로지름 (history 누적, RAG 우회) | PASS |
| 3 | FOLLOWUP rewrite 적용 (standalone 갱신, strategy 에 전달) | PASS |
| 4 | 첨부 → vision 자동 라우팅 (supports() 분기) | PASS |
| 5 | SMALLTALK → strategy 호출 0 | PASS |

세부 검증:
- `build_orchestrator(...)` 가 `CompiledStateGraph` 반환 — `graph.invoke(state)` 가능 (`test_orchestrator.py:140`).
- LangGraph result 의 dict/모델 양쪽 분기 처리: `_invoke` 헬퍼가 `isinstance(result, dict)` → `ConversationState(**result)` (line 141-143).
- 조건부 엣지 `_route_after_classify` 가 5개 Intent 분기 모두 커버:
  - `FOLLOWUP` → `rewrite` (line 83-84)
  - `NEW_QUESTION` → `select` (line 85-86, `needs_retrieval=True`)
  - `META_RECAP` / `META_REFERENCE` / `SMALLTALK` → `compose` (line 87, `needs_retrieval=False`)
  - `pending_intent is None` 폴백 → `compose` (line 81-82, 안전 폴백)
- `Conversation` frozen + `append_turn` 새 인스턴스 반환(`chatbot/domain/conversation.py:70-82`) — Pydantic v2 model_copy 와 LangGraph state mutability 호환 확인.
- 시나리오 2 의 `_Strategy.runs` 카운트 + META_RECAP 의 `selected_strategy is None` + history 에 두 답변 포함 → `RAG 우회` 의미 충족.

### G. 타입 / 스타일 — PASS

| 항목 | 결과 |
|---|---|
| ruff check (`chatbot/application/`, `tests/chatbot/test_orchestrator.py`, `tests/chatbot/test_nodes.py`) | All checks passed |
| ruff format --check | 13 files already formatted |
| 모든 함수 타입힌트 | 노드 5개 + `_helpers` 2개 + `build_orchestrator` + `_route_after_classify` + `_build_turn` 모두 명시 |
| docstring 한국어 / 식별자 영문 | 일관 |
| 이모지 | 0건 (grep 정규식) |

### H. 회귀 안전성 — PASS

| 스코프 | 결과 |
|---|---|
| `tests/chatbot/` 전체 | 163 passed in 0.54s |
| 레거시 `tests/` (excl. chatbot) | 213 passed in 4.95s |
| 직전 audit (PR 1, 2-A/B/C/D, 3-phase1) 권고 위반 | grep 재검사 결과 0건 — 본 phase 에서 새로 깨진 것 없음 |

### I. 잠재적 결함 / 권고 (CRITICAL/HIGH 0)

본 phase 진행을 차단하는 결함 없음. 아래 3건은 PR 4 또는 그 이후 합류 권고.

- **P-A (LOW)**: `_route_after_classify` 의 `pending_intent is None` 폴백("compose")이 trace event 를 남기지 않는다. 분류기 silent fail 시 디버깅 정보 부족 가능. PR 4 의 trace 합류 시 `state.append_event("classify_failed_fallback")` 권고. 근거: `chatbot/application/orchestrator.py:80-82`.
- **P-B (LOW)**: LangGraph checkpointer 미사용 — in-memory 만. PRD-002(SQLite 영속화) 합류 시 `graph.compile(checkpointer=SqliteCheckpointer(...))` 로 교체 필요. 본 phase 의 계약 영향은 없음. 근거: `chatbot/application/orchestrator.py:70`.
- **P-C (LOW)**: `test_orchestrator.py` 시나리오 2 가 `_Strategy(name="kg", subgraph=Subgraph(...))` 를 등록하지만, `META_REFERENCE` 시나리오(`last_turn.subgraph` 재사용 검증)는 본 phase 에 포함되지 않음. PR 4 wiring 후 별도 phase 에서 `_Answerer.compose` 가 `last_turn` 의 retrieval/subgraph 를 참조하는 시나리오 추가 권고. 근거: `tests/chatbot/test_orchestrator.py:115-122`, `:101-104`.

### J. PR 4 (라우트 wiring) 시작 전 권고

- 새 `/chat/v2` 엔드포인트 (예: `api/routes/chat.py`) 가 `build_orchestrator(...)` 를 *세션당 한 번만* 빌드하도록 의존성 주입 컨테이너를 통해 캐시. 매 요청 빌드 시 LangGraph 컴파일 비용이 누적된다.
- `infrastructure/intent_llm.py` / `infrastructure/rewriter_llm.py` / `infrastructure/router_*.py` / `infrastructure/answer_composer.py` 각 1파일씩 — 휴리스틱 우선 + LLM fallback (PRD-006 §5 결정 1).
- in-memory `InMemoryStrategyRegistry` 부트스트랩 헬퍼는 `chatbot/composition/` (또는 `chatbot/wiring/`) 모듈 1개에 모으고, FastAPI 의존성으로 `Depends(get_orchestrator)` 형태 노출 — application 에 FastAPI 침투 차단.
- LangGraph result 가 dict 일 가능성에 대비, 라우트 어댑터에도 `_invoke` 와 동일한 dict→state 변환 분기 적용. test 의 `_invoke` 헬퍼(`tests/chatbot/test_orchestrator.py:138-143`)를 production 코드로 승격해도 좋다.

---

## 3. Phase 1 권고 P2 / P3 반영 검증 (요약)

| 권고 | Phase 1 상태 | Phase 2 상태 | 근거 |
|---|---|---|---|
| P2 — `_to_request` 중복 (rewrite/select/invoke 3곳) | 미해소 | RESOLVED — `nodes/_helpers.py` 신설, 4개 노드 모두 import 사용. 노드 파일에 `def _to_request` 잔존 0 | `_helpers.py:14-29`, grep 결과 |
| P3 — `compose_answer` 36줄 (한도 30 초과) | 미해소 | RESOLVED — 17줄로 축소 + `_build_turn`(14줄) 분리 | `compose_answer.py:18-50` |

---

## 4. 회귀 검증 결과

| 스코프 | 통과 | 시간 |
|---|---:|---|
| `tests/chatbot/test_orchestrator.py` | 5/5 | 0.16s |
| `tests/chatbot/test_nodes.py` | 16/16 | (위와 합산 0.16s) |
| `tests/chatbot/` 전체 | 163/163 | 0.54s |
| 레거시 `tests/` (excl. chatbot) | 213/213 | 4.95s |
| ruff check | clean | — |
| ruff format --check | 13 files already formatted | — |

---

## 5. 위반 / 권고

차단 위반 0건. 권고 3건(P-A/P-B/P-C)은 §2.I 참조 — 모두 LOW, PR 4 이후 합류.

---

## 6. 통계

| 항목 | 값 |
|---|---:|
| 신규/수정 application 파일 | 6 (`orchestrator.py`, `nodes/_helpers.py`, `nodes/compose_answer.py`, `nodes/select_strategy.py`, `nodes/invoke_strategy.py`, `nodes/rewrite_question.py`) |
| 신규 테스트 파일 | 1 (`tests/chatbot/test_orchestrator.py`, 268줄, 5 시나리오) |
| 회귀 테스트 변경 | 1 (`tests/chatbot/test_nodes.py`, 275줄, 16 케이스 — 전부 통과) |
| 신규 application 라인 합계 | 281줄 (위 6개 파일) |
| 신규 헬퍼 함수 | 3 (`to_retrieval_request`, `history_messages`, `_build_turn`) |
| 노드 함수 5개 평균 본문 | ≤ 17줄 |
| 통합 시나리오 | 5 (NEW_QUESTION / 멀티턴 가로지름 / FOLLOWUP rewrite / vision 라우팅 / SMALLTALK) |
| 본 phase 테스트 통과율 | 21/21 (100%) |
| 누적 chatbot 테스트 통과 | 163/163 |

---

## 7. 이전 audit 권고 회귀 점검 (전 8회)

| audit | 권고 | 본 phase 회귀 여부 |
|---|---|:---:|
| PR 1 | corpus/strategy/conversation 모델 frozen | 유지 — `_build_turn` 의 Turn freeze, `Conversation.append_turn` 새 인스턴스 반환 활용 |
| PR 2-A phase 1/2 | RetrievalRequest/Result 의 attachments tuple 보존 | 유지 — `to_retrieval_request` 가 `attachments=state.pending_user_message.attachments` 그대로 전달 |
| PR 2-B phase 1/2 | Strategy Protocol `is_available/supports/run` 분리 | 유지 — `select_strategy` 가 `registry.available_for(req)` 로 `is_available` + `supports` 결합 호출 |
| PR 2-C phase 1/2 | Vision attachment 검증 + supports() 분기 | 유지 — 시나리오 4 (`test_attachment_vision_자동_라우팅`) 가 supports() 기반 라우팅 검증 |
| PR 2-D | KG strategy 의 subgraph 메타 보존 | 유지 — `_Strategy(name="kg", subgraph=...)` 등록, `Subgraph` 도메인 모델 사용 |
| PR 3 phase 1 | P2/P3 권고 | RESOLVED (§3) |

회귀 위반 0건.

---

## 8. PR 4 (라우트 wiring) 시작 전 권고 (요약)

1. `/chat/v2` 엔드포인트는 `build_orchestrator(...)` 를 앱 부트 시 1회 컴파일 후 캐시. FastAPI `Depends` 로 주입.
2. `chatbot/composition/` (또는 `wiring/`) 모듈 신설 — `InMemoryStrategyRegistry` 부트스트랩(corpus 등록 → retriever 빌드 → strategy 등록) 헬퍼 집중.
3. `infrastructure/intent_llm.py`, `rewriter_llm.py`, `router_heuristic.py`, `answer_composer.py` 4개 구체 구현 — 휴리스틱 우선, LLM fallback.
4. LangGraph result 의 dict 분기를 production 어댑터에서 동일 처리 (`_invoke` 헬퍼 승격).
5. `_route_after_classify` 의 `pending_intent is None` 폴백에 trace event 추가 (P-A).
6. PRD-002 SQLite 영속화 합류 시 `graph.compile(checkpointer=...)` 로 교체 (P-B).
7. `META_REFERENCE` (`last_turn.subgraph` 재사용) 시나리오 추가 (P-C).
