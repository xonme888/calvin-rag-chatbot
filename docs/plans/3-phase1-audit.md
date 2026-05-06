# PR 3 Phase 1 Audit — Orchestrator 사전 분해 (Protocols + Nodes + Tests)

대상: PR 3.1 / 3.2 / 3.3
일자: 2026-05-06
방식: grep + Read + 실제 pytest / ruff 실행

## 1. 요약 판정

**PASS**

- Hexagonal 의존방향 위반 0건. application 레이어가 `chatbot.infrastructure.*` 또는 `langgraph` / `langchain` 을 import 하지 않음 (grep 결과 0).
- 노드는 모두 `state -> state` 시그니처 + 단일 책임. 다른 노드 호출 0.
- `tests/chatbot/test_nodes.py` 16/16 PASS, `tests/chatbot/` 158/158 PASS, 레거시 213/213 PASS.
- ruff check / format 통과 (10 files already formatted).
- LLM 호출 0 (모든 의존성을 자체 Fake 로 격리).
- 권고 사항 2건 (P2 / P3) — 차후 PR 에서 정리 가능, 본 phase 차단 아님.

---

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS

| 항목 | 결과 |
|---|---|
| application → infrastructure 직접 import | 0건 (grep `from chatbot.infrastructure` / `from chatbot.infra`) |
| application → langgraph / langchain | 0건 |
| `_protocols.py` import | `domain.conversation` (Message, Turn), `domain.intent` (Intent), `domain.retrieval` (RetrievalResult), `domain.strategy` (RetrievalStrategy) — 도메인만 |
| 노드 5개 import | `application._protocols` + `chatbot.domain.*` + 표준 라이브러리(`datetime`, `time`) — 외부 라이브러리 0 |

근거: `chatbot/application/_protocols.py:15-22`, `chatbot/application/nodes/*.py` 상단.

### B. rag_core / api 비손상 — PASS

`git status --short rag_core/ api/` 결과 0줄. (작업트리 전체 modified 는 `infra/env_loader.py`, `pyproject.toml` 두 건뿐 — 본 phase 와 무관한 인프라 작업.)

### C. 단일 책임 / 라인 한도 — PASS

| 파일 | 줄 수 | 한도 | 상태 |
|---|---:|---:|:---:|
| `_protocols.py` | 92 | 200 | OK |
| `nodes/__init__.py` | 19 | 200 | OK |
| `nodes/classify_intent.py` | 23 | 100 | OK |
| `nodes/rewrite_question.py` | 35 | 100 | OK |
| `nodes/select_strategy.py` | 42 | 100 | OK |
| `nodes/invoke_strategy.py` | 40 | 100 | OK |
| `nodes/compose_answer.py` | 60 | 100 | OK |
| `tests/chatbot/test_nodes.py` | 275 | — | OK (테스트는 한도 비대상) |

함수 길이 (AST 기반):

| 함수 | 줄 | 한도 30 | 비고 |
|---|---:|:---:|---|
| `classify_intent` | 11 | OK | |
| `rewrite_question` | 11 | OK | |
| `select_strategy` | 20 | OK | |
| `invoke_strategy` | 12 | OK | |
| `compose_answer` | 36 | **WARN** | 한도 30 의 6 줄 초과. Turn 필드 8개 인라인 대입 (l.35-45). 헬퍼 추출 시 해소 가능 (P3 권고). |
| `_history_messages` (compose) | 6 | OK | |
| `_to_request` (select) | 5 | OK | |
| `_to_request` (invoke) | 13 | OK | (코드 중복 — H 항목) |

### D. 노드 동작 검증 — PASS

| 노드 | 검증 포인트 | 근거 |
|---|---|---|
| `classify_intent` | `pending_intent` 만 채움. 다른 필드 보존 — `state.model_copy(update={...})` 사용 | `nodes/classify_intent.py:23` |
| `rewrite_question` | FOLLOWUP 분기 시 LLM, 외 분기는 `pending_standalone = user_message.content` (passthrough 일관) | `nodes/rewrite_question.py:20-24` |
| `select_strategy` | 후보 0개 가드 + router None 가드 동시 보유 | `nodes/select_strategy.py:28,35` |
| `invoke_strategy` | `pending_strategy is None` → `return state` 패스스루 | `nodes/invoke_strategy.py:20-21` |
| `compose_answer` | `Conversation.append_turn` 호출 — 새 인스턴스 반환 (`conversation.py:82-84`, frozen 모델). pending_answer 채움. | `nodes/compose_answer.py:46-52` |

### E. 타입 / 스타일 — PASS

- ruff check: All checks passed.
- ruff format --check: 10 files already formatted.
- 모든 함수/메서드 타입힌트 부착 (`*.py` AST 검사 결과 누락 0).
- 한국어 docstring + 영문 식별자 (이모지 0).
- frozen 모델 갱신은 모두 `model_copy(update={...})`. 직접 필드 대입 0건.

### F. 테스트 품질 — PASS

```
pytest tests/chatbot/test_nodes.py -q
................                                                         [100%]
16 passed in 0.14s
```

분포 (요청 매핑):

| 노드 | 케이스 수 | 케이스 |
|---|---:|---|
| classify_intent | 3 | pending_intent 채움 / last_turn 전달 / None last_turn |
| rewrite_question | 3 | FOLLOWUP / NEW_QUESTION / META_RECAP |
| select_strategy | 3 | 정상 / 후보 0개 / router None |
| invoke_strategy | 3 | 정상 / strategy None passthrough / chat_history 전달 (2 메시지 평탄화 확인) |
| compose_answer | 4 | 정상 Turn append / META retrieval 없음 / intent None RuntimeError / 누적 turn |
| **합계** | **16** | |

LLM/외부 API 호출 — 모두 자체 Fake 로 격리 (`_FakeClassifier`, `_FakeRewriter`, `_FakeRouter`, `_FakeStrategy`, `_FakeAnswerer`). `langchain_community.fake` 미사용 — Fake 로직이 단순해 자체 정의 적합.

### G. 회귀 안전성 — PASS

| 스위트 | 결과 |
|---|---|
| `tests/chatbot/` 전체 | 158 passed |
| `tests/` 레거시 (chatbot 제외) | 213 passed (3 deprecation warning, swig 관련, 무관) |

이전 PR 2-A/2-B/2-C/2-D audit 권고 회귀 영향 점검:
- 2-A (Conversation/Turn frozen) — `compose_answer` 가 `append_turn` 사용으로 정합. 위반 0.
- 2-B (Intent enum + needs_retrieval/needs_rewrite) — Phase 1 노드는 enum 분기만 사용 (`Intent.FOLLOWUP` 비교). 위반 0.
- 2-C (RetrievalRequest/Result frozen) — `_to_request` 가 `RetrievalRequest(...)` 신규 인스턴스 생성. 위반 0.
- 2-D (StrategyRegistry Protocol + InMemoryStrategyRegistry) — 노드는 `registry.available_for() / get()` 만 호출. Protocol 인터페이스 준수.

### H. 잠재적 결함 — 권고 2건

1. **P2 — `_to_request` 코드 중복** (`select_strategy.py:38-42`, `invoke_strategy.py:28-40`).
   두 노드가 거의 같은 변환을 수행. select 는 `chat_history` 비포함, invoke 는 포함. 헬퍼 모듈(`chatbot/application/nodes/_request_builder.py` 또는 `_helpers.py`) 로 추출 권고.
   - 영향: 향후 `RetrievalRequest` 필드 추가 시 두 곳을 동시 수정해야 함.
   - 차단성: PR 3.4 와 무관. Phase 2 직후 정리 권고.

2. **P3 — `compose_answer` 길이 36 줄** (`compose_answer.py:17-52`).
   Turn 필드 8개 (`user_message`, `intent`, `standalone_question`, `selected_strategy`, `retrieval_result_ref`, `answer`, `trace_id`, `elapsed_ms`, `started_at`) 인라인 대입이 길이 대부분을 차지. `_build_turn(state, answer, elapsed_ms)` 헬퍼 추출 시 본문 ~22 줄로 축소 가능.
   - 영향: 가독성 (한도 30 대비 6 줄 초과).
   - 차단성: 비차단.

검토했으나 결함 아님:
- `rewrite_question._history_messages` 의 turns 펼침 순서 — `Conversation.turns` 가 append-only 이고 `append_turn` 이 `(*self.turns, turn)` 으로 끝에 추가하므로 (`conversation.py:84`) 시간 정렬 OK.
- `pending_standalone` 채움 일관성 — FOLLOWUP 외 분기에서도 `user_message.content` 로 채움 (`rewrite_question.py:24`). 후속 노드들은 `state.pending_standalone or state.pending_user_message.content` 의 fallback 도 함께 가짐 (`select_strategy.py:32,41`, `invoke_strategy.py:31`) — 이중 안전망. OK.
- `compose_answer.elapsed_ms` 단위 — `int(time() * 1000) - state.started_at_ms`. `ConversationState.started_at_ms` 가 ms 가정과 일치 (`state.py:51`). 음수 방지를 `max(0, ...)` 로 처리.
- `retrieval_result_ref=None` 의도성 — Turn 본체를 가볍게 유지하고 대용량 페이로드는 별도 영속화 후 ID 만 보관. `conversation.py:58-62` 의 docstring 과 정합.

### I. Phase 2 (PR 3.4 / 3.5) 시작 전 권고 — INFO

1. **Orchestrator 와이어링 — 조건부 엣지 키**
   - `Intent.needs_retrieval` (true → select_strategy → invoke_strategy → compose_answer) / (false → compose_answer 직진)
   - `Intent.needs_rewrite` (true → rewrite_question 호출) / (false → passthrough — 현재 노드가 자체 분기 가짐, 엣지로 빼면 노드가 더 순수해짐)
   - 결정 포인트: 분기 로직을 *엣지에 둘 것인가, 노드 안에 둘 것인가*. 현 구현은 노드 안 분기 — orchestrator 가 무조건 호출. 단순한 그래프 + 노드 자체 가드. 이 형태 유지 권고 (그래프 SVG 단순, debugging 쉬움).

2. **LangGraph checkpointer 직렬화 호환성**
   - `ConversationState` 는 pydantic v2 BaseModel — `model_dump_json()` 가능. `Conversation` / `Turn` / `Message` 모두 frozen + JSON 직렬화 가능 (필드 모두 primitive 또는 frozen 모델).
   - 단, `pending_retrieval: RetrievalResult` 가 `documents: tuple[Document, ...]` 를 보유 — `Document` 가 frozen + serializable 인지 확인 필요 (`chatbot/domain/retrieval.py` Document 정의 점검).
   - `started_at: datetime` 은 ISO 직렬화 가능. UTC 명시(`datetime.now(UTC)`) 정합.

3. **인프라 구체 구현 위치**
   - Protocol 4개 (IntentClassifier / QueryRewriter / StrategyRouter / AnswerComposer) 의 LLM 기반 구현은 `chatbot/infrastructure/` 에 두는 것이 의존방향에 맞음. 노드는 Protocol 만 의존하므로 무관.
   - 휴리스틱 fallback 의 경우 LLM 미사용 — application 레이어에 둘 수도 있으나, 일관성을 위해 infrastructure 권장.
   - DI 조립은 `chatbot/composition.py` (또는 `bootstrap.py`) 에 모으고, FastAPI 라우터에서 `Depends()` 로 주입.

---

## 3. 통계

| 항목 | 값 |
|---|---:|
| 신규/수정 파일 (PR 3.1~3) | 8 (`__init__.py` × 2 + `_protocols.py` + 노드 5개 + 테스트 1) |
| 프로덕션 코드 합계 | 311 줄 (테스트 제외) |
| 테스트 코드 | 275 줄 |
| Protocol 정의 | 4 (IntentClassifier, QueryRewriter, StrategyRouter, AnswerComposer) |
| 노드 함수 | 5 (classify_intent, rewrite_question, select_strategy, invoke_strategy, compose_answer) |
| 노드 단독 테스트 케이스 | 16 |
| `chatbot/` 전체 테스트 | 158 |
| 레거시 테스트 | 213 |
| ruff check 위반 | 0 |
| 의존방향 위반 | 0 |
| LLM 호출 (테스트 시) | 0 |

---

## 4. PR 2 audit 권고 회귀 점검

| 이전 audit | 권고 핵심 | 본 phase 영향 |
|---|---|---|
| 2-A | Conversation/Turn frozen + append_turn 불변 | `compose_answer` 가 `append_turn` 호출. 위반 0. |
| 2-B | Intent enum + needs_retrieval/needs_rewrite property | `rewrite_question` 이 `Intent.FOLLOWUP` 직접 비교 — needs_rewrite 사용 가능하나 동치. orchestrator 단계에서 needs_retrieval 사용 권고. |
| 2-C | RetrievalRequest/Result frozen | `_to_request` 가 신규 인스턴스 생성. 위반 0. |
| 2-D | StrategyRegistry Protocol + InMemory 구현 | 노드가 Protocol 의 `available_for/get` 만 사용. 위반 0. |

---

## 5. PR 3.4 (orchestrator) 시작 전 권고

1. `_to_request` 헬퍼 추출 — PR 3.4 첫 커밋에서 정리 권고 (P2).
2. orchestrator 는 *얇은* 와이어링만 — 노드 호출 + 조건 엣지. 추가 로직 0.
3. `Intent.needs_retrieval` / `Intent.needs_rewrite` 를 엣지 조건 함수로 직접 사용 (도메인 property 활용 — 본 phase audit 의 needs_retrieval 미사용 지적 회수).
4. checkpointer 결정 — 본 phase 까지는 in-memory 충분. 영속화는 Phase 2 이후 별 PR.
5. PR 3.5 통합 시나리오는 *Fake Protocol 4종 + 실제 InMemoryStrategyRegistry + FakeStrategy* 로 4 Intent 분기 (NEW/FOLLOWUP/META/SMALLTALK) end-to-end 시나리오 1개씩 권고.

---

## 부록: 검증 명령

```bash
# 의존방향
grep -rn "from chatbot.infrastructure\|from chatbot.infra\|import langgraph\|import langchain" chatbot/application/ tests/chatbot/test_nodes.py
# → 0 결과

# rag_core/api 비손상
git status --short rag_core/ api/
# → 0 결과

# 라인 카운트
wc -l chatbot/application/_protocols.py chatbot/application/nodes/*.py

# 테스트
pytest tests/chatbot/test_nodes.py -q   # 16 passed
pytest tests/chatbot/ -q                # 158 passed
pytest tests/ --ignore=tests/chatbot -q # 213 passed

# 스타일
ruff check chatbot/application/ tests/chatbot/test_nodes.py
ruff format --check chatbot/application/ tests/chatbot/test_nodes.py
```
