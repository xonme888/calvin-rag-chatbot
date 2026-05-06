---
status: draft
group: A
created: 2026-05-06
related_prd: docs/prd/draft/006-conversation-first-orchestrator.md
---

# TRD-006: 대화 우선 오케스트레이터 (마스터)

본 TRD 는 `chatbot/` 패키지 도입의 *마스터 문서*다. 도메인 모델은 PR 1 (이미 머지) 로
정의되어 있고, 본 문서는 그 위에 application/orchestrator + 기존 4개 모드를 Strategy 로
환원하는 전체 그림을 담는다. 모드별 깊은 분해는 TRD-007 (Hybrid), TRD-008 (Agentic),
TRD-009 (KG), TRD-010 (Vision) 에서 다룬다.

## 1. AS-IS 분석

### 1.1 챗봇 본체가 RAG 모드 안에 있다

```
api/routes/chat.py:147-189   _invoke_sync — 모드별 시그니처 분기
api/routes/chat.py:75-124    _resolve_mode — 라우터 호출 + auto fallback
rag_core/router.py:61        route_question(question) — 한 줄 키워드 매칭
```

`_invoke_sync` (chat.py:180-189) 의 분기:

```python
if req.mode == "hybrid":
    history = _to_langchain_history(req.chat_history)
    return breaker.call(rag.query, req.question, chat_history=history, callbacks=callbacks)
if req.mode == "vision":
    return breaker.call(rag.query, req.question, attachments=..., callbacks=callbacks)
return breaker.call(rag.query, req.question, callbacks=callbacks)  # agentic, kg
```

→ `chat_history` 를 받는 모드는 **Hybrid 단 하나**. 그 외 모드는 시그니처에 history 파라미터 자체가 없다 (`agentic.py:290`, `kg/pipeline.py:158`, `vision_rag.py:60`).

### 1.2 라우터가 단일 질문만 본다

`router.py:61` `route_question(question: str) -> Mode` — 한 줄을 휴리스틱(`_KG_HINTS`, `_AGENTIC_HINTS`) 또는 LLM 분류기(`ROUTER_LLM_CLASSIFIER=true`) 로 본다. **chat_history 인자가 없다.**

→ "위 내용 요약" 같은 메타 질문은 `_KG_HINTS` 도 `_AGENTIC_HINTS` 도 매칭 안 됨 → Hybrid 디폴트 → 검색기가 "요약" 단어로 PDF 청크 검색.

### 1.3 모드 등록과 호출이 두 곳으로 갈라져 있다

```
rag_core/mode_registry.py    ModeEntry(name, label, factory, health, tracker_mode)
rag_core/mode_dispatcher.py  병렬 모드 호출 (Hybrid only 인 듯, 사용처 한정)
api/routes/chat.py:159       get_mode_entry(req.mode).factory().query(...)
```

새 모드를 추가하려면 `mode_registry.py` 에 entry 등록 + `_invoke_sync` 의 분기 (Hybrid/Vision 만) 수정 가능성 + 모드 클래스 자체 작성. 변경 반경이 *registry 한 곳* 으로 떨어지지 않는다.

### 1.4 turn-level 메타가 보존되지 않는다

API 응답의 `metadata` 에 `subgraph` / `cited_pages` / `tool_calls` 가 들어가지만 (`chat.py:469-517` `_build_stream_meta_payload`), 그 메타는 *프론트엔드 메모리* 에만 있다. 다음 턴의 백엔드 호출에는 history 의 텍스트 본문만 전달되고 (`chat.py:137-144` `_to_langchain_history`), 직전 턴의 그래프·인용은 사라진다.

→ "방금 그 그래프 다시" 가 백엔드 차원에서 풀 수 없다.

### 1.5 한계 / 변경 비용 / 회귀 위험

| 항목 | 현재 비용 | 위험 |
|---|---|---|
| 멀티턴을 모든 모드에 통일 | 4개 모드 + `_invoke_sync` 동시 수정 | 4개 모드 각각 회귀 |
| 후속 질문(대명사) 처리 | rewrite 노드 부재 → 휴리스틱 라우팅 오류 | 라우터 정확도 저하 |
| 메타-참조 (요약·되짚기) | RAG 강제 호출 → 의미 무관 답변 | UX 신뢰 저하 |
| 새 corpus 추가 (어거스틴 등) | 모드별 데이터 로딩 코드 수정 | 4개 모드 모두 영향 |
| 새 도구/MCP 추가 | Agentic 내부 수정 (PRD-001 에서 부분 해결) | Agentic 회귀 |

## 2. TO-BE 설계

### 2.1 패키지 레이어 (PR 1 머지 결과 + 본 TRD 가 추가할 것)

```
chatbot/
├── domain/                              [PR 1 — 이미 머지]
│   ├── conversation.py                  Message, Attachment, Turn, Conversation
│   ├── intent.py                        Intent (NEW/FOLLOWUP/META_RECAP/META_REFERENCE/SMALLTALK)
│   ├── corpus.py                        Corpus, KnowledgeSource, DocumentRef, Citation
│   ├── indexing.py                      Loader, Splitter, Embedder, Store (Protocol)
│   ├── retrieval.py                     Retriever, RetrievalRequest, RetrievalResult, Subgraph
│   ├── tools.py                         Tool, ToolSchema, ToolResult, MCPClient, ToolRegistry
│   ├── strategy.py                      RetrievalStrategy, StrategyRegistry
│   ├── pipeline.py                      Stage[T], Pipeline[T]
│   └── state.py                         ConversationState
│
├── application/                         [본 TRD — PR 4]
│   ├── orchestrator.py                  LangGraph 빌더 — 노드 와이어링
│   ├── nodes/
│   │   ├── classify_intent.py
│   │   ├── rewrite_question.py
│   │   ├── select_strategy.py
│   │   ├── invoke_strategy.py
│   │   └── compose_answer.py
│   └── registries.py                    InMemoryCorpusRegistry/StrategyRegistry/ToolRegistry
│
├── infrastructure/                      [PR 2~5 — 모드별 TRD 가 채움]
│   ├── corpora/                         도메인 어댑터 (calvin_institutes, ...)
│   ├── loaders/  splitters/  embedders/  stores/
│   ├── retrievers/                      hybrid_retriever 등
│   ├── tools/{search,mcp,domain}/
│   ├── strategies/
│   │   ├── hybrid_strategy.py           [TRD-007]
│   │   ├── agentic_strategy.py          [TRD-008]
│   │   ├── kg_strategy.py               [TRD-009]
│   │   └── vision_strategy.py           [TRD-010]
│   ├── intent_llm.py
│   ├── rewriter_llm.py
│   └── checkpointer.py                  LangGraph in-memory (PR 4)
│
└── tests/
    ├── domain/                          [PR 1 — smoke 만 통과]
    ├── nodes/                           [PR 4 — FakeStrategy 로 단독 테스트]
    └── flows/                           [PR 4 — 멀티턴 시나리오, 모드 가로지름]
```

### 2.2 LangGraph 노드 흐름

```
                       ┌─────────────────────┐
   User input  ───────►│  classify_intent    │  Intent enum 결정
                       └─────────┬───────────┘
                                 │
                ┌────────────────┴────────────────┐
                ▼                                 ▼
     [needs_rewrite]                     [META_*/SMALLTALK]
                │                                 │
                ▼                                 │
       ┌─────────────────┐                        │
       │ rewrite_question│                        │
       └────────┬────────┘                        │
                │                                 │
                ▼                                 │
       ┌─────────────────┐                        │
       │ select_strategy │                        │
       └────────┬────────┘                        │
                │                                 │
                ▼                                 │
       ┌─────────────────┐                        │
       │ invoke_strategy │                        │
       └────────┬────────┘                        │
                │                                 │
                ▼                                 ▼
              ┌────────────────────────────────────┐
              │           compose_answer            │
              └─────────────────┬──────────────────┘
                                │
                                ▼
                    Turn append → Conversation
```

조건부 엣지:
- `classify_intent → rewrite_question` (Intent.needs_rewrite=True)
- `classify_intent → select_strategy` (NEW_QUESTION)
- `classify_intent → compose_answer` (META_*/SMALLTALK)
- `select_strategy → compose_answer` (선택된 strategy 가 None — supports() 모두 false)

### 2.3 Strategy 어댑터 (모드 통일)

| Strategy.name | 라벨 | corpus 검색 | 도구 사용 | subgraph | attachments |
|---|---|---|---|---|---|
| `hybrid` | Hybrid | ✓ | ✗ | ✗ | ✗ |
| `agentic` | Agentic | ✓ (Tool 경유) | ✓ | ✗ | ✗ |
| `kg` | Knowledge Graph | ✓ | ✗ | ✓ | ✗ |
| `vision` | Vision | ✗ (선택) | ✗ | ✗ | ✓ |

모든 Strategy 는 `RetrievalRequest → RetrievalResult` 단일 시그니처. `_invoke_sync` 의 분기는 사라진다. supports() 가 라우터의 후보 필터를 담당.

### 2.4 ConversationState (LangGraph StateSchema)

```python
class ConversationState(BaseModel):
    conversation: Conversation                  # turns: append-only
    pending_user_message: Message
    pending_intent: Intent | None
    pending_standalone: str | None
    pending_strategy: str | None
    pending_retrieval: RetrievalResult | None
    pending_answer: Message | None
    trace_id: str
    started_at_ms: int
```

LangGraph checkpointer 가 `conversation.id` 키로 영속화 (PR 4 는 in-memory, PRD-002 합류 시 SQLite/Postgres).

### 2.5 라우팅 결정의 입력 변화

```
AS-IS:  route_question(question)                                  # 한 줄
TO-BE:  route(standalone_question, intent, last_turn) -> name     # 다턴 + 직전 메타
```

후속 메타-참조 (META_REFERENCE) 는 `last_turn.selected_strategy` 를 그대로 따라간다 — "방금 그 그래프" 가 KG 로 다시 가지 않고 last_turn.retrieval.subgraph 재사용으로 처리된다.

## 3. 마이그레이션 시퀀스 (PR 단위)

각 PR 은 *독립적으로 머지·롤백 가능*. 의존성은 PR 번호 순.

| PR | 범위 | 변경 라인 (목표) | 새 엔드포인트 | 영향받는 기존 코드 |
|---|---|---|---|---|
| 1 | 도메인 모델 + Protocol | ✓ 머지됨 (~750줄) | 없음 | 없음 |
| 2 | RetrievalStrategy/Retriever/Tool 어댑터 4개 | ≤ 800줄 | 없음 | 없음 (어댑터만 추가, 호출 측 미변경) |
| 3 | application/nodes 5개 + registries | ≤ 600줄 | 없음 | 없음 (FakeStrategy 로 노드 단독 테스트) |
| 4 | orchestrator.py + 새 라우트 `/chat/v2` | ≤ 600줄 | `/chat/v2` | api/routes/chat.py 끝에 새 핸들러 추가 |
| 5 | 프론트엔드 절체 (`/chat/v2` 사용) | ≤ 400줄 (web/) | - | web/lib/api.ts, web/components/ChatPanel.tsx |
| 6 | 레거시 제거 (`_invoke_sync` 분기, 옛 라우트) | -800줄 | `/chat/v2` → `/chat/sync` rename | api/routes/chat.py, rag_core/* 일부 |

PR 2~5 의 *깊은 분해 작업* 은 모드별 TRD 들이 담당한다:

- TRD-007: Hybrid 분해 (PR 2 의 일부)
- TRD-008: Agentic 분해 + ToolRegistry 정합 (PR 2 의 일부)
- TRD-009: KG 분해 (PR 2 의 일부)
- TRD-010: Vision 분해 + 보안 게이팅 (PR 2 의 일부)

PR 2 는 모드별로 다시 4개의 sub-PR 로 나누어 진행한다 — 한 번에 한 모드씩 깊은 분해 + 어댑터 + 단독 테스트. 모드 1개 분해 후 다음 모드로 이동하기 전에 단독 어댑터 테스트가 통과해야 한다.

## 4. 구현 인터페이스 (sketch)

```python
# chatbot/application/registries.py
class InMemoryStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, RetrievalStrategy] = {}

    def register(self, strategy: RetrievalStrategy) -> None: ...
    def all(self) -> list[RetrievalStrategy]: ...
    def get(self, name: str) -> RetrievalStrategy: ...
    def available_for(self, request: RetrievalRequest) -> list[RetrievalStrategy]: ...


# chatbot/application/nodes/classify_intent.py
def classify_intent(state: ConversationState, *, classifier: IntentClassifier) -> ConversationState:
    """state -> state. classifier 는 의존성 주입."""
    intent = classifier.classify(
        message=state.pending_user_message,
        last_turn=state.conversation.last_turn,
    )
    return state.model_copy(update={"pending_intent": intent})


# chatbot/application/nodes/select_strategy.py
def select_strategy(
    state: ConversationState,
    *,
    registry: StrategyRegistry,
    router: Router,
) -> ConversationState:
    candidates = registry.available_for(_to_request(state))
    if not candidates:
        return state.model_copy(update={"pending_strategy": None})
    selected = router.choose(state, candidates)
    return state.model_copy(update={"pending_strategy": selected.name})


# chatbot/application/orchestrator.py
def build_orchestrator(
    *,
    strategies: StrategyRegistry,
    classifier: IntentClassifier,
    rewriter: QueryRewriter,
    router: Router,
    answerer: AnswerComposer,
) -> CompiledStateGraph:
    graph = StateGraph(ConversationState)
    graph.add_node("classify", partial(classify_intent, classifier=classifier))
    graph.add_node("rewrite", partial(rewrite_question, rewriter=rewriter))
    graph.add_node("select", partial(select_strategy, registry=strategies, router=router))
    graph.add_node("invoke", partial(invoke_strategy, registry=strategies))
    graph.add_node("compose", partial(compose_answer, answerer=answerer))

    graph.add_conditional_edges("classify", _intent_route, {
        "rewrite": "rewrite",
        "select": "select",
        "compose": "compose",
    })
    graph.add_edge("rewrite", "select")
    graph.add_conditional_edges("select", _has_strategy, {"invoke": "invoke", "compose": "compose"})
    graph.add_edge("invoke", "compose")
    graph.add_edge("compose", END)
    return graph.compile(checkpointer=in_memory_checkpointer())
```

## 5. 테스트 계획

### 5.1 단위 (노드 단독)

각 노드는 `state -> state` 의 순수 함수에 가깝게 — 외부 의존(LLM, registry, classifier) 은 인자로 주입.

| 노드 | 테스트 케이스 |
|---|---|
| `classify_intent` | 5개 Intent 각각 1건 + 모호한 메시지 1건 (LLM fallback 경로) |
| `rewrite_question` | 대명사 후속 / 생략 후속 / FOLLOWUP 아닌 케이스 (no-op) |
| `select_strategy` | NEW_QUESTION + corpus 매칭 / 첨부 있음 → vision / 모든 strategy unavailable |
| `invoke_strategy` | FakeStrategy 로 retrieval result 주입 / strategy=None 패스스루 |
| `compose_answer` | RAG 결과 있음 / META_RECAP (history 만) / META_REFERENCE (last_turn.subgraph 재사용) |

FakeStrategy / FakeIntentClassifier / FakeRewriter 는 `chatbot/tests/fakes/` 에 둔다. LLM 호출 0회.

### 5.2 통합 (멀티턴 시나리오)

| 시나리오 | 검증 |
|---|---|
| Hybrid → KG → META_RECAP | 마지막 턴이 RAG 우회, history 만으로 답변 |
| KG 답변 → META_REFERENCE | 직전 turn.retrieval.subgraph 재사용 (Neo4j 호출 0) |
| Vision → META_RECAP | RAG 우회, history 만으로 답변 |
| 대명사 후속 → standalone rewrite → KG | rewrite 결과가 답변 메타에 노출 |

### 5.3 회귀 (기존 라우트와의 호환)

PR 4 시점에 `/chat/sync` (legacy) 와 `/chat/v2` (신규) 를 동일 입력 100건 (audit log 샘플) 으로 호출, 답변 텍스트는 차이 허용하되 envelope 키 셋이 동일해야 한다 (스냅샷 비교).

## 6. 위험 / 롤백 / 모니터링

| 위험 | 영향 | 완화 |
|---|---|---|
| 의도 분류기 오분류 (META 를 NEW 로) | 메타 질문에 RAG 검색 잘못 호출 | rewrite 결과를 답변 메타에 항상 노출 — 사용자가 "이렇게 이해됨" 검증 가능 |
| 라우팅 분포 변화 | KG/Agentic 호출 비율이 ±10%p 이상 변동 | PR 4 시 24시간 audit 로그 비교, 임계 초과 시 라우터 가중치 조정 |
| Vision 첨부 흐름 회귀 | 이미지 업로드 후 답변 안 옴 | PR 4 의 시나리오 테스트에 vision 케이스 1건 필수 |
| LangGraph checkpointer 직렬화 실패 | 후속 턴에서 state 복원 안 됨 | in-memory 단계에선 영향 없음. PRD-002 합류 시 영속화 백엔드 별도 검증 |
| 라우터 LLM 호출 비용 증가 | 토큰 +20% 추정 | 휴리스틱 우선 + 모호 시만 LLM (PRD §5 결정 1) |

롤백 단위는 *PR 단위*. PR 4 만 롤백하면 `/chat/v2` 가 사라지고 기존 동작 그대로. PR 5 롤백 시 프론트만 옛 라우트로 되돌림. PR 6 (레거시 제거) 만 따로 보류 가능 — 1주 안정화 후 진행.

## 7. 후속 작업 (별도 PRD/TRD)

- PRD-002 합류: LangGraph checkpointer 를 SQLite/Postgres 로. `Conversation.id` 가 사용자 ID 와 매핑.
- PRD-001 합류: Tool/MCP 통합. TRD-008 이 정합점 정의.
- 새 corpus 추가 가이드: `docs/guides/adding-a-corpus.md` (어거스틴 고백록 시범).
- 모드별 알고리즘 개선 (Self-RAG 루프 안정화 등): TRD-007/008/009/010 의 후속 PRD.
