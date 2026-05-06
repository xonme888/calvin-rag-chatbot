---
status: draft
group: A
created: 2026-05-06
related_prd: docs/prd/draft/006-conversation-first-orchestrator.md
related_trd: docs/trd/draft/006-conversation-first-orchestrator.md
---

# TRD-007: Hybrid 모드 분해 (HybridRAG → HybridStrategy)

본 TRD 는 TRD-006 의 PR 2 단계에서 *가장 먼저* 진행되는 모드 분해다. 다른 3개 모드 (Agentic/KG/Vision) 가 본 TRD 의 패턴을 따라가므로 *모범 사례 단위* 로 작성한다.

## 1. AS-IS 분석

### 1.1 한 클래스에 15개 책임

`rag_core/hybrid.py` (607줄, 클래스 1개, 메서드 11개) 안에 다음 책임이 모두 묶여 있다.

| # | 책임 | 라인 | 라인 수 | 매핑 대상 |
|---|---|---|---|---|
| 1 | HybridRAGConfig (설정) | 48-88 | 41 | `chatbot.infrastructure.strategies.hybrid_strategy.HybridConfig` |
| 2 | LLM/Embedding 초기화 | 171-180 | 10 | Strategy 의 의존성 주입 |
| 3 | Retriever 컴포지션 | 183-189 | 7 | `domain.Retriever` 어댑터 (이미 `retriever.py:44-172` 분리됨) |
| 4 | 프롬프트 템플릿 구성 | 193-199 | 7 | `infrastructure.prompts.hybrid_prompt.py` |
| 5 | 검색 오케스트레이션 | 216-230 | 15 | Pipeline `[Retrieve → Rerank → Generate]` |
| 6 | LLM 호출 + 구조화 출력 | 232-287 | 56 | `Stage[GenerateInput, RAGResponse]` |
| 7 | 재랭킹 노드 | 289-310 | 22 | `Stage[list[DocumentRef], list[DocumentRef]]` (이미 `reranker.py:40-134` 분리됨) |
| 8 | Self-RAG 근거도 평가 | 315-351 | 37 | `Stage[RAGResponse, GradeResult]` (별도 추상) |
| 9 | Self-RAG 질문 재작성 | 353-385 | 33 | `Stage[str, str]` (Hybrid 내부 — 본 TRD 의 rewrite_question 노드와 별개) |
| 10 | LangGraph 상태 라우팅 | 387-393 | 7 | LoopOrchestrator (Strategy 내부) |
| 11 | LangGraph 빌드 | 395-431 | 37 | Strategy 의 `__init__` 단계 |
| 12 | 동기 query 인터페이스 | 436-479 | 44 | `RetrievalStrategy.run(request)` |
| 13 | 스트리밍 query 인터페이스 | 481-572 | 92 | 별도: `StreamingStrategy` (선택) — TRD-006 §3 의 PR 4 이후로 분리 |
| 14 | 인용 페이지 추출 | 578-590 | 13 | `infrastructure.parsers.citation_parser.py` |
| 15 | 문서 메타 포매팅 | 593-607 | 15 | `Stage` 내부 헬퍼 (private) |

### 1.2 stream_query 와 query 의 이원화

`stream_query` (line 481-572) 는 LangGraph 그래프를 사용하지 않는다 → Self-RAG 루프(grade/rewrite) 가 스트리밍 경로에서 적용 안 됨. `_last_metadata` (line 500, 554) 에 부수효과로 메타를 적재하고, `chat.py:423` 이 그것을 직접 참조한다 → 동시 요청 시 race condition 위험.

### 1.3 Self-RAG 루프

`_grade_router` (387-393) 가 `_grade_node` 결과로 retrieve 재진입 결정. `_build_graph` (418-427) 의 conditional edge 가 무한 재귀 가능성 보유 (max_retries 미적용 경로). 본 TRD 의 분해 작업은 *Self-RAG 의 루프 자체* 는 건드리지 않고 LoopOrchestrator 라는 추상 안에 *보존* 만 한다.

### 1.4 보조 모듈 — 이미 잘 분리되어 있음

| 모듈 | 라인 | 책임 | 매핑 |
|---|---|---|---|
| `rag_core/retriever.py` | 171 | BM25+Dense+RRF | `domain.Retriever` 어댑터 |
| `rag_core/reranker.py` | 134 | FlashRank + Lost-in-Middle | `domain.Stage` 어댑터 |
| `rag_core/citation_label.py` | 80 | 페이지 → "권 장" 라벨 | 별도 헬퍼 (Strategy 내부) |
| `rag_core/followup.py` | 87 | 후속 질문 생성 | 별도 헬퍼 (compose_answer 노드가 사용) |
| `rag_core/tokenizer.py` | 54 | BM25 토크나이저 | retriever 내부 |
| `rag_core/calvin_builder.py` | 86 | corpus 빌더 | `infrastructure.corpora.calvin_institutes.py` |

## 2. TO-BE 설계

### 2.1 신규 모듈

```
chatbot/infrastructure/
├── corpora/
│   └── calvin_institutes.py       기존 calvin_builder.py 흡수
├── retrievers/
│   ├── bm25_retriever.py          기존 retriever.py 의 BM25 부분
│   ├── dense_retriever.py         기존 retriever.py 의 Dense 부분
│   └── hybrid_retriever.py        RRF 합성 (domain.Retriever 어댑터)
├── rerankers/
│   └── flashrank_reranker.py      기존 reranker.py
├── prompts/
│   └── hybrid_prompt.py           프롬프트 템플릿 (line 193-199)
├── parsers/
│   └── citation_parser.py         인용 페이지 추출 (line 578-590)
├── stages/
│   ├── retrieve_stage.py          Stage[RetrievalRequest, list[DocumentRef]]
│   ├── rerank_stage.py            Stage[list[DocumentRef], list[DocumentRef]]
│   ├── generate_stage.py          Stage[GenerateInput, GenerateOutput] (LLM 호출)
│   ├── grade_stage.py             Stage[GradeInput, GradeResult] (Self-RAG)
│   └── rewrite_stage.py           Stage[str, str] (Self-RAG 내부 — 노드의 rewrite_question 과 별개)
└── strategies/
    └── hybrid_strategy.py         RetrievalStrategy 어댑터 + LoopOrchestrator
```

### 2.2 책임 매핑표 (라인 단위 정량)

| 기존 위치 (line) | 새 위치 | 줄 수 변화 |
|---|---|---|
| `hybrid.py:48-88` HybridRAGConfig | `infrastructure/strategies/hybrid_strategy.py` 의 HybridConfig | 동일 |
| `hybrid.py:171-189` LLM/Retriever 초기화 | hybrid_strategy `__init__` | 합쳐서 ~30줄 |
| `hybrid.py:193-199` 프롬프트 | `infrastructure/prompts/hybrid_prompt.py` | 동일 |
| `hybrid.py:216-230` 검색 오케 | hybrid_strategy `run()` 의 Pipeline 빌드 | ~10줄로 축소 |
| `hybrid.py:232-287` 생성 | `infrastructure/stages/generate_stage.py` | 동일 |
| `hybrid.py:289-310` 재랭크 | `infrastructure/stages/rerank_stage.py` (기존 reranker.py 위에 Stage 어댑터) | +20줄 어댑터 |
| `hybrid.py:315-385` Self-RAG | `infrastructure/stages/grade_stage.py` + `rewrite_stage.py` | 분리만 |
| `hybrid.py:387-431` LangGraph 빌드 | hybrid_strategy `_build_loop()` (private) | 동일 |
| `hybrid.py:436-479` query() | hybrid_strategy `run()` | 단순화 |
| `hybrid.py:481-572` stream_query() | hybrid_strategy `run_stream()` (선택) | TRD-006 PR 4 이후 |
| `hybrid.py:578-607` 인용/포매팅 | `infrastructure/parsers/citation_parser.py` + private 헬퍼 | 분리 |

### 2.3 인터페이스 (Python sketch)

```python
# chatbot/infrastructure/strategies/hybrid_strategy.py
class HybridStrategy:
    name: str = "hybrid"
    label: str = "Hybrid"

    def __init__(
        self,
        *,
        retriever: Retriever,                   # domain.Retriever (HybridRetriever 어댑터)
        reranker: Stage[list[DocumentRef], list[DocumentRef]],
        generate: Stage[GenerateInput, GenerateOutput],
        grade: Stage[GradeInput, GradeResult] | None = None,   # None = Self-RAG 비활성
        rewrite: Stage[str, str] | None = None,
        config: HybridConfig,
    ) -> None: ...

    def is_available(self) -> tuple[bool, str | None]:
        """retriever/reranker/generate 모두 가용해야 True."""

    def supports(self, request: RetrievalRequest) -> bool:
        return not request.attachments  # 첨부 있으면 vision 으로 양보

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        """Pipeline 빌드 — Retrieve → Rerank → Generate → (Grade/Rewrite 루프).

        Self-RAG 루프는 LoopOrchestrator 가 Stage 들을 재호출하는 방식으로 격리.
        본 메서드 자체는 30줄 이내.
        """
```

### 2.4 LoopOrchestrator (Self-RAG 격리)

```python
class _SelfRAGLoop:
    """grade/rewrite 루프를 Strategy 내부에 격리. 외부 노출 X.

    max_retries 를 명시적 인자로 — 무한 루프 차단.
    """

    def __init__(
        self,
        *,
        retrieve: Stage,
        generate: Stage,
        grade: Stage,
        rewrite: Stage,
        max_retries: int = 2,
    ) -> None: ...

    def run(self, request: RetrievalRequest) -> RetrievalResult: ...
```

### 2.5 Stage 시그니처 정합

`domain.pipeline.Stage[TIn, TOut]` 가 받는 입력 타입이 단계마다 다르므로, *명시 타입 alias* 로 문서화한다:

```python
GenerateInput = TypedDict("GenerateInput", {
    "request": RetrievalRequest,
    "documents": list[DocumentRef],
})
GenerateOutput = TypedDict("GenerateOutput", {
    "answer": str,
    "citations": list[Citation],
})
GradeInput = ...
GradeResult = Literal["sufficient", "insufficient"]
```

타입 anchor 가 *어떤 단계가 어떤 데이터를 주고받는지* 의 단일 진실원천이 된다.

## 3. 구현 인터페이스 (스키마 변환)

| 변환 지점 | 기존 | 신규 |
|---|---|---|
| `query(question, chat_history)` | str + list[BaseMessage] | `RetrievalStrategy.run(RetrievalRequest)` |
| 응답 dict | `{final_answer, source_documents, metadata}` | `RetrievalResult` (envelope) + `compose_answer` 가 final answer 합성 |
| metadata.cited_pages | str list | `RetrievalResult.citations` 의 page_label |
| metadata.tool_calls | dict list | (Hybrid 는 도구 안 씀, 빈 tuple) |
| stream `text-delta` chunks | langchain stream | run_stream() 의 generator (TRD-006 PR 4 이후) |

## 4. 마이그레이션 단계

본 TRD 는 TRD-006 의 PR 2-A (4개 모드 중 첫 분해) 다.

| 단계 | 작업 | 검증 |
|---|---|---|
| 2-A.1 | `corpora/calvin_institutes.py` 신설 (기존 calvin_builder.py 흡수) | 빌드 후 인덱스 캐시 키 동일 (회귀 0) |
| 2-A.2 | `retrievers/{bm25,dense,hybrid}_retriever.py` 분리 | 동일 질문 10건에 대한 검색 결과 동일 |
| 2-A.3 | `rerankers/flashrank_reranker.py` Stage 어댑터 | 재랭킹 결과 동일 |
| 2-A.4 | `prompts/`, `parsers/`, `stages/` 신설 | unit 테스트 단독 통과 |
| 2-A.5 | `strategies/hybrid_strategy.py` 조립 + LoopOrchestrator | 기존 query() 와 동일 입력 50건 비교 (text 차이 ≤ 5%, citations 동일) |
| 2-A.6 | `tests/strategies/test_hybrid_strategy.py` — Fake Retriever 로 노드 단독 검증 | unit 통과 |

각 sub-PR 은 *기존 hybrid.py 를 건드리지 않는다*. orchestrator 는 PR 4 에서 와이어링 — 그 전까지 hybrid_strategy 는 dead code 로 머무른다 (사용처 없음). Hybrid 의 *기존 라우트 동작* 은 PR 6 까지 영향 없음.

## 5. 테스트 계획

### 5.1 단위

| Stage | 테스트 케이스 | Fake 의존성 |
|---|---|---|
| retrieve_stage | 한국어 질문 → DocumentRef 시퀀스 / corpus_id 필터 / k=8 | FakeBM25, FakeDense |
| rerank_stage | 8개 → 4개 압축 / FlashRank 미설치 시 path-through | FlashRank mock |
| generate_stage | 정상 / context 비어있음 / LLM 오류 | FakeLLM (FakeListLLM) |
| grade_stage | sufficient / insufficient 분기 | FakeLLM |
| rewrite_stage | 재작성 / 동일 질문 (no-op) | FakeLLM |
| _SelfRAGLoop | max_retries 도달 / 1회 재시도 후 종료 | 위 Stage Fakes 조합 |

### 5.2 통합

| 시나리오 | 검증 |
|---|---|
| 정상 답변 | 기존 Hybrid 답변과 envelope 키셋 동일 |
| chat_history 다턴 | last_message 가 retrieval에 영향 (기존 동작 유지) |
| 인용 라벨 변환 | "권 7 장 3" 형식 보존 |

### 5.3 회귀

기존 `experiments/results/*.json` 중 Hybrid 결과 1세트를 회귀 baseline 으로 — RAGAS 4지표가 ±5% 이내.

## 6. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| Self-RAG 루프 재구현 시 무한 루프 | 토큰 폭주 | LoopOrchestrator 의 max_retries 인자 필수, default 2 |
| FlashRank lazy import 실수 | 환경에 패키지 없을 시 import error | `is_available()` 에서 import 체크, 미설치 시 path-through |
| stream_query 이원화 유지 | run_stream() 까지 PR 길어짐 | TRD-006 PR 4 이후로 분리 — 본 TRD 는 sync 만 |
| Stage 타입 정합 실수 | 런타임 unpacking 오류 | TypedDict 명시 + mypy strict (개발 시) |

## 7. 후속

- run_stream (TRD-006 PR 4 이후) — Vercel AI SDK 호환 SSE.
- Self-RAG 알고리즘 자체 개선은 별도 PRD/TRD.
- HyDE / Step-back / Decomposition 같은 신규 검색 전략 추가 시 본 패턴 따라 Strategy 1개씩.
