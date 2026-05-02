# 008. SRP 리팩토링 — RetrieverPort + Agent 메시지 파서

## 상황
KG / graceful degradation / 관측성 / 멀티페이지까지 챗봇이 시연 가능 상태였지만,
**SRP가 RAG에서 적정하게 적용됐는지** 별도 에이전트에게 검토 요청. 결과:
- "데이터 변경 이유"가 아닌 **교체 가능 단위**가 RAG의 책임 기준
- 현재 가장 큰 균열: `_reciprocal_rank_fusion` 같은 비공개 메서드를
  AgenticRAG / KnowledgeGraphRAG 가 외부에서 직접 호출 — 캡슐화 위반 4곳에서
  같은 검색 로직 복제
- AgenticRAG 의 `query()` 와 `stream_steps()` 가 messages → answer/tools/sources
  파싱을 두 번 중복 작성

## 결정
권장 후보 #1 + #3 만 수행 (1~2시간). #2(stream_query 통합)와 #4(LLMPort)는
oversmithing 으로 판단하고 보류.

### #1 — RetrieverPort 도입
`KnowledgeGraphPort` 와 같은 사상을 검색 인프라에도 대칭 적용.

```
rag_core/retriever.py 신규
  ├── RetrieverPort (Protocol)
  └── HybridRetriever (BM25 + Dense + RRF, public reciprocal_rank_fusion)
```

영향:
- `HybridRAG` 가 retriever 컴포지션 (자체 vector_store/bm25_retriever/text_splitter 제거)
- `AgenticRAG._make_search_tool` 이 `rag.retriever.retrieve()` 만 호출
- `KnowledgeGraphRAG.query` 가 `hybrid.retriever.retrieve()` 만 호출
- `calvin_builder` 가 `retriever.load_prebuilt_index(chunks, vector_store)` 로 디스크 캐시 주입

### #3 — Agent 메시지 파서 분리
`agentic.py` 에 두 헬퍼 추가:

```python
# 1) 일괄 파싱 (query 용)
parse_agent_messages(messages) -> AgentParseResult
    # final_answer + tool_calls + source_documents

# 2) 이벤트 변환 (stream_steps 용, generator)
message_to_stream_events(msg) -> Iterator[dict]
    # 단일 메시지를 0개 이상의 stream 이벤트로 변환
```

`query()` 는 일괄 파서를, `stream_steps()` 는 노드 진행 시 이벤트 변환을 사용.
같은 추출 책임을 두 함수가 *다른 형태*로 노출하지만 로직 중복은 제거.

## 근거

### 묶어 두는 게 맞는 것 — 분리 안 함
- 프롬프트 + LLM 호출 + 출력 스키마(`RAGResponse`) → 한 노드/메서드에 함께
- LangGraph 노드 메서드 (`_retrieve_node`, `_generate_node` 등) 는
  `(state) -> partial state` 가 자체로 SRP 단위 — 별도 클래스화 시 cognitive load만 증가

### 분리하는 게 맞는 것 — 적용
- 검색(BM25 + Dense + RRF) → 다른 retriever(예: dense-only, reranker-only) 교체 대상
- 메시지 파서 → query/stream 두 표현이 같은 추출 책임을 가짐 → 한 곳에 묶어야 변경 비용 절감

### 적용하지 않은 것 — 보류
- LLMPort/EmbeddingsPort: LangChain의 `BaseChatModel`이 이미 Port 역할 → oversmithing
- `stream_query` 와 graph invoke 통합: streaming UX 회귀 위험 + 시연 일정 우선

## 적용 결과

### 코드
- 신규: `rag_core/retriever.py` (130줄), `rag_core/agentic.py` 안의 헬퍼 2개 (60줄)
- 변경: hybrid/agentic/kg/pipeline/calvin_builder/scripts (총 6 파일)
- 삭제: `_reciprocal_rank_fusion` (HybridRAG 비공개 메서드, retriever로 이전)
- 비공개 메서드 외부 호출 — 0건

### 테스트
- `tests/test_retriever.py`: 10/10 PASS (FakeEmbeddings, 외부 호출 0)
- `tests/test_agent_message_parser.py`: 11/11 PASS (Mock 메시지)
- 누적 92/92 PASS (이전 71 + 신규 21)

## 어필 내러티브

> "RAG 시스템에서 SRP는 백엔드와 결을 다르게 해석했습니다. *데이터 변경 이유* 가 아닌
> *교체 가능 단위*를 책임으로 보고, 검색(BM25+Dense+RRF)과 그래프 백엔드(Neo4j)를
> 각각 `RetrieverPort`/`KnowledgeGraphPort` 로 분리했습니다.
>
> 반대로 프롬프트와 출력 스키마, LangGraph 노드는 한 곳에 묶어 컨텍스트 흐름이
> 한눈에 읽히게 했습니다 — 분산하면 디버깅 비용이 검색 정확도 개선보다 커집니다.
>
> Hexagonal 의존성 방향은 양 Port 모두에 엄격히 적용했고, Mock 어댑터로
> LLM/DB 호출 0회로 92개 단위 테스트가 통과합니다.
>
> Spring AI 의 `VectorStore` 인터페이스 + `ToolCallback` + `Advisor` 와 매핑하면
> 각각 `RetrieverPort` + AgenticRAG 의 `@tool` + `UsageTracker` 콜백이
> 정확히 같은 역할입니다."

## 검증 결과
- 누적 92/92 PASS
- 캡슐화 위반 4곳 → 0건
- 메시지 파싱 중복 2곳 → 1곳 (헬퍼)
- 인터페이스 변경: 모두 keyword arg 추가 또는 위임 — 외부 API 호환
