---
status: draft
group: A
created: 2026-05-06
related_prd: docs/prd/draft/006-conversation-first-orchestrator.md
related_trd: docs/trd/draft/006-conversation-first-orchestrator.md
---

# TRD-009: KG 모드 분해 (KnowledgeGraphRAG → KGStrategy)

KG 모드는 4개 모드 중 *이미 가장 잘 분리된* 모드다 (`rag_core/kg/` 8개 파일, 1144줄, 각 파일이 단일 책임을 어느 정도 지킴). 본 TRD 의 작업은 *남은 분해* 와 *chatbot/ 새 추상으로의 매핑* 에 집중한다 — 변경 반경이 다른 모드보다 작다.

## 1. AS-IS 분석

### 1.1 kg/ 디렉토리 — 책임별 정량

| 파일 | 라인 | 메서드 | 책임 |
|---|---|---|---|
| `config.py` | 44 | 2 | Neo4j 연결 설정 + URI scheme → mode 자동 감지 |
| `pipeline.py` | 270 | 7 | KG + Hybrid 검색 합성 오케스트레이션 |
| `port.py` | 82 | 6 | KnowledgeGraphPort + SubgraphData 모델 (이미 도메인 포트) |
| `neo4j_adapter.py` | 276 | 11 | Port 구현: LLMGraphTransformer + Cypher + APOC |
| `factory.py` | 41 | 2 | 싱글톤 어댑터 팩토리 |
| `entity_normalizer.py` | 125 | 3 | Alias 통합 + 노이즈 노드 필터링 |
| `section_filter.py` | 153 | 4 | PDF 단원 범위 필터링 + 비용 추정 |
| `graph_renderer.py` | 128 | 6 | SubgraphData → streamlit-agraph/pyvis 변환 (UI envelope) |
| **합계** | **1144** | **41** | |

### 1.2 KGPipeline.query 호출 시퀀스 (pipeline.py:158-241)

```
1. extract_entities(question)              → list[str] (LLM 구조화 출력)
   pipeline.py:188
2. kg.get_subgraph(entity_names, hops=2)   → SubgraphData (Cypher)
   pipeline.py:193
3. hybrid.retriever.retrieve(question)     → list[Document] (BM25+Dense+RRF)
   pipeline.py:199
4. chain.invoke({...})                     → str (LLM 통합 답변)
   pipeline.py:205
5. generate_followups(question, answer)    → list[str]
   pipeline.py:238
```

→ KG 는 *그래프 + 본문 둘 다* 보고 답변. Subgraph 는 UI 시각화에도 노출.

### 1.3 인덱싱 파이프라인 (이미 4단계 분리됨, 그러나 함수 흩어져 있음)

| 단계 | 위치 | 매핑 대상 |
|---|---|---|
| Loader (PDF) | `KnowledgeGraphRAG.index_documents()` (pipeline.py:127) | `chatbot.domain.Loader` |
| Splitter | `Hybrid.retriever.text_splitter` (pipeline.py:138) — Hybrid 모듈에서 빌림 | `chatbot.domain.Splitter` |
| Embedder (LLM 그래프 변환) | `LLMGraphTransformer` (neo4j_adapter.py:85-110) | `chatbot.domain.Embedder` *유사 추상* — 본 TRD 는 GraphIndexer 라는 KG 전용 추상 도입 |
| Store (Neo4j) | `add_graph_documents()` + APOC (neo4j_adapter.py:121) | `chatbot.domain.Store` 와 *시그니처 다름* — 별도 GraphStore 추상 |

**중요**: 일반 벡터 Store 와 GraphStore 는 검색 인터페이스가 다르다 (벡터 vs Cypher). 본 TRD 는 `chatbot.domain` 에 GraphStore 추상을 *추가하지 않는다* — KG 는 Strategy 안에 Neo4j 의존을 직접 보유하고, Retriever Protocol 을 만족하는 어댑터를 둘 뿐.

### 1.4 graph_renderer 의 위치

UI envelope 변환 책임 (`SubgraphData → streamlit-agraph Node/Edge` 또는 `pyvis HTML`). 본 TRD 의 도메인 매핑에서는 *프론트엔드/UI 레이어로 이동* — 도메인의 Subgraph 모델은 그대로 두고, agraph/pyvis 변환은 web/components/SubgraphView.tsx 또는 별도 Streamlit adapter 가 담당.

### 1.5 entity_normalizer / section_filter 호출 위치

| 모듈 | 호출 | 입출력 |
|---|---|---|
| `normalize_subgraph()` | `neo4j_adapter.py:188` (get_subgraph 내부) | SubgraphData → alias 통합/노이즈 제거 SubgraphData |
| `filter_chunks_by_sections()` | `pipeline.py:139` (index_documents 내부) | Chunk 시퀀스 → 1-indexed page 범위 매칭 |
| `estimate_cost()` | `pipeline.py:148` | 청크 수 → {usd, krw, minutes} |

두 모듈 모두 *Stage 단위로 잘 분리됨* — 본 TRD 의 매핑은 위치 이동만, 로직 변경 없음.

## 2. TO-BE 설계

### 2.1 신규/이전 모듈

```
chatbot/infrastructure/
├── strategies/
│   └── kg_strategy.py                  RetrievalStrategy 어댑터
├── retrievers/
│   ├── hybrid_retriever.py             [TRD-007 와 공유]
│   └── graph_retriever.py              그래프 기반 Retriever (Cypher 검색)
├── stores/
│   └── neo4j_graph_store.py            Neo4jAdapter 흡수 (KG 전용)
├── indexers/
│   └── llm_graph_indexer.py            LLMGraphTransformer 흡수 (텍스트 → 그래프)
├── stages/
│   ├── extract_entities_stage.py       엔티티 추출 (Stage)
│   ├── normalize_subgraph_stage.py     entity_normalizer 흡수
│   └── section_filter_stage.py         section_filter 흡수
└── corpora/
    └── calvin_institutes.py            [TRD-007 와 공유, KG 인덱싱 메타 추가]

chatbot/domain/
└── graph.py                            [신규 — Subgraph/GraphNode/GraphEdge 는 retrieval.py
                                         에 이미 있음, 본 TRD 는 GraphStore Protocol 추가]
```

### 2.2 GraphStore 도메인 추상 추가

`chatbot/domain/graph.py` 를 신설해 그래프 저장소의 Protocol 을 분리한다. 이유: 일반 벡터 Store(`indexing.py:Store`) 와 시그니처가 다르므로 같은 Protocol 로 묶으면 인터페이스가 비대해진다.

```python
# chatbot/domain/graph.py
@runtime_checkable
class GraphStore(Protocol):
    name: str

    def health_check(self) -> tuple[bool, str | None]: ...

    def index_chunks(
        self,
        chunks: list[Chunk],
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> int: ...

    def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_subgraph(
        self,
        entity_names: list[str],
        hops: int = 2,
    ) -> Subgraph: ...

    def stats(self) -> dict[str, int]: ...

    def clear(self) -> None: ...
```

기존 `kg/port.py:KnowledgeGraphPort` 는 *그대로* 유지하되, 본 도메인 Protocol 의 *구체 구현이 KnowledgeGraphPort 를 만족* 하도록 어댑터를 만든다.

### 2.3 책임 매핑

| 기존 (rag_core/kg/) | 새 위치 | 비고 |
|---|---|---|
| `config.py` | `infrastructure/stores/neo4j_graph_store.py` 의 _Settings | 외부 노출 X |
| `pipeline.py:127-156` index_documents | `kg_strategy.py:index_corpus()` (선택, run() 과 분리) | corpus 인덱싱은 챗봇 로딩 시 1회 |
| `pipeline.py:158-241` query | `kg_strategy.run()` | Stage Pipeline 으로 30~50줄 축소 |
| `pipeline.py:243-263` extract_entities | `stages/extract_entities_stage.py` | LLM 구조화 출력 단독 |
| `port.py:KnowledgeGraphPort` | `domain/graph.py:GraphStore` (어댑터로 호환) | 도메인 표준화 |
| `neo4j_adapter.py` (276줄) | `infrastructure/stores/neo4j_graph_store.py` + `infrastructure/indexers/llm_graph_indexer.py` 분리 | 검색·인덱싱 책임 분리 |
| `entity_normalizer.py` | `infrastructure/stages/normalize_subgraph_stage.py` | 로직 동일 |
| `section_filter.py` | `infrastructure/stages/section_filter_stage.py` | 로직 동일 |
| `graph_renderer.py` | `web/components/SubgraphView.tsx` (이미 존재) + 백엔드 정리만 | 도메인 밖 |
| `factory.py` | `application/registries.py` 의 GraphStore 싱글톤 | 통합 |

### 2.4 KGStrategy.run() Pipeline 스케치

```python
# chatbot/infrastructure/strategies/kg_strategy.py
class KGStrategy:
    name = "kg"
    label = "Knowledge Graph"

    def __init__(
        self,
        *,
        graph_store: GraphStore,
        text_retriever: Retriever,                  # Hybrid retriever 재사용
        extract_entities: Stage[str, list[str]],
        normalize: Stage[Subgraph, Subgraph],
        generate: Stage,
    ) -> None: ...

    def is_available(self) -> tuple[bool, str | None]:
        return self._graph_store.health_check()

    def supports(self, request: RetrievalRequest) -> bool:
        # 라우터가 "관계/사이/누가/그래프/계보" 키워드 또는 LLM 분류로 KG 라우팅한 경우.
        # 본 메서드는 attachments 만 거부 (vision 으로 양보).
        return not request.attachments

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        entities = self._extract.run(request.standalone_question)
        subgraph_raw = self._graph_store.get_subgraph(entities, hops=2)
        subgraph = self._normalize.run(subgraph_raw)
        documents = self._text_retriever.retrieve(request)
        # generate stage 가 entities + subgraph + documents 받아 답변 합성
        ...
        return RetrievalResult(
            documents=tuple(documents),
            citations=...,
            subgraph=subgraph,
            metadata={"pattern": "kg", "entity_count": str(len(entities))},
        )
```

### 2.5 인덱싱 분리 (`index_corpus`)

KG 인덱싱은 *챗봇 부팅 시* 1회 또는 *재인덱싱 명령* 으로만 일어난다. 따라서 `run()` 과 같은 Strategy 인터페이스에 두지 않고, 별도 명령 라인 / 헬퍼로 분리:

```python
# chatbot/infrastructure/strategies/kg_strategy.py
class KGStrategy:
    def index_corpus(
        self,
        corpus: Corpus,
        loader: Loader,
        splitter: Splitter,
        section_filter: Stage,
        indexer: GraphIndexer,
        progress_cb: ...,
    ) -> KGIndexStats: ...
```

`scripts/index_kg.py` 가 이 헬퍼를 호출. 챗봇 런타임은 인덱싱 코드를 import 안 함 — LLMGraphTransformer 와 langchain_experimental 의존이 런타임에 끌려 들어오지 않도록.

## 3. 마이그레이션 단계

| 단계 | 작업 | 검증 |
|---|---|---|
| 2-C.1 | `domain/graph.py:GraphStore` Protocol 추가 | smoke test |
| 2-C.2 | `infrastructure/stores/neo4j_graph_store.py` (Neo4jAdapter 흡수, search 부분만) | 동일 entity_names 입력에 대한 Subgraph 동일 |
| 2-C.3 | `infrastructure/indexers/llm_graph_indexer.py` (LLMGraphTransformer 흡수) | 인덱싱 비용 추정치 동일 |
| 2-C.4 | `infrastructure/stages/{extract_entities,normalize_subgraph,section_filter}_stage.py` | 입출력 동일 |
| 2-C.5 | `infrastructure/strategies/kg_strategy.py` 조립 | 기존 KG 응답 envelope 와 키 동일, subgraph 노드/엣지 수 동일 |
| 2-C.6 | `scripts/index_kg.py` 분리 | 인덱싱 결과 stats 동일 |
| 2-C.7 | tests | unit + 통합 |

KG 인덱스가 이미 Neo4j 에 적재되어 있다면 *재인덱싱 불필요* — 어댑터 작업은 *읽기* 만 영향. 회귀 검증은 동일 entity 시나리오 10건의 SubgraphData 직렬화 비교.

## 4. 테스트 계획

### 4.1 단위

| 모듈 | 케이스 | Fake |
|---|---|---|
| GraphStore (Neo4j) | health_check / get_subgraph / query_cypher | testcontainers Neo4j 또는 Fake |
| extract_entities_stage | 정상 / LLM 구조화 출력 실패 | FakeLLM |
| normalize_subgraph_stage | alias 통합 / 노이즈 노드 필터 / 빈 입력 | - |
| section_filter_stage | 단원 범위 매칭 / 범위 밖 청크 / 1-indexed 경계 | - |
| GraphIndexer | 청크 10개 → 그래프 / 배치 / 진행 콜백 | FakeLLMGraphTransformer |
| KGStrategy.is_available | Neo4j 미연결 시 False | FakeGraphStore |

### 4.2 통합

| 시나리오 | 검증 |
|---|---|
| "칼빈과 베자의 관계" | entities ["칼빈", "베자"] 추출 → 서브그래프 노드/엣지 수 동일 |
| 첨부 있음 | supports() False (vision 양보) |
| Neo4j 미연결 | is_available() False, supports() 무관 |

### 4.3 회귀

기존 KG 응답 envelope (`metadata.subgraph`, `metadata.cited_pages`, `metadata.pattern="kg"`) 가 RetrievalResult 로 그대로 노출. `chat.py:_build_stream_meta_payload` 가 이 키들을 사용 중.

## 5. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| GraphStore 어댑터의 SubgraphData ↔ Subgraph 변환 누락 | UI 그래프 안 보임 | 변환 함수 단독 테스트 + 노드/엣지 수 비교 |
| Neo4j health_check 타임아웃 | KG 영구 비활성 | health_check 의 timeout 명시, fallback 시 trace event |
| LLMGraphTransformer 비용 폭주 | 인덱싱 시 토큰 폭주 | 본 TRD 는 estimate_cost() 보존, 인덱싱 batch 10청크 유지 |
| section_filter 의 1-indexed 경계 회귀 | 범위 밖 청크 잘못 포함/배제 | 경계 케이스 (page=N, page=N+1) 테스트 |
| `port.py:KnowledgeGraphPort` 와 `domain/graph.py:GraphStore` 의 이중화 | 어떤 인터페이스를 만족해야 할지 혼란 | 본 TRD 머지 후 `port.py` 는 deprecate, 1개 PR 후 제거 |

## 6. 후속

- corpus 추가 가이드에 *그래프 인덱싱이 비싼* 도메인은 어떤 절충(엔티티 타입 축소, hops=1)이 가능한지 명시.
- `entity_normalizer.py` 의 ENTITY_ALIASES 수동 관리 → 자동 임베딩 유사도 도입은 별도 PRD.
- run_stream — KG 는 LLM 호출 1회 + 그래프 조회 → SSE 변환은 단순 청크 분할로 충분 (TRD-006 PR 4 이후).
