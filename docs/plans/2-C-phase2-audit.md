# PR 2-C Phase 2 독립 감사 보고서

대상: `chatbot/infrastructure/strategies/{_config.py, kg_strategy.py, __init__.py}`,
`tests/chatbot/{test_graph_store.py, test_kg_stages.py, test_kg_strategy.py}`

기준: TRD-009 PR 2-C.5~6, 선행 audit (2-A/2-B/2-C-phase1) 권고 회귀 미발생.

## 1. 요약 판정

**PASS** (조건부 권고 4건 — 모두 비차단, PR 2-D 진행 가능).

핵심 근거:
- `pytest tests/chatbot/ -q`: **118 passed in 0.71s** (KG 신규 29 케이스 포함)
- `pytest tests/ --ignore=tests/chatbot -q`: **213 passed** (legacy 회귀 0)
- `git diff rag_core/`: **0 라인** (불변 유지)
- `ruff check` / `ruff format --check`: **All checks passed / 6 files already formatted**
- `kg_strategy.py` 166줄 (한도 200), `run()` 32줄 (한도 60)

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS
- `kg_strategy.py:23-44` import: `chatbot.domain.*`, `chatbot.infrastructure.{parsers,stages,strategies._config}` 만. LangChain `BaseChatModel` 은 `TYPE_CHECKING` (라인 43-44), `ChatPromptTemplate` 은 `run()` 내부 lazy import (라인 84). 도메인 레이어 통과.
- `chatbot/domain/{graph.py,retrieval.py}` 에 langchain/openai/neo4j import 0 (`grep -rE "import (langchain|openai|...)"`).
- 테스트 3종: `chatbot.application` import 0건. `test_graph_store.py` 만 `rag_core/kg/port` 를 *합법적으로* import — 어댑터 변환 검증 책임이므로 정당.

### B. rag_core 비손상 — PASS
- `git diff rag_core/`: 0 라인.
- `rag_core/kg/pipeline.py` 시그니처 그대로 (`grep`):
  - `class EntityExtraction (line 37)`, `class KnowledgeGraphRAG (74)`, `PATTERN_NAME = "Knowledge Graph RAG" (81)`,
  - `def index_documents (127)`, `def extract_entities (153)`, `def query (158)`, `def _format_subgraph_for_llm (244)`.
- mtime 비교: `rag_core/kg/pipeline.py` 2026-05-05 17:52, `chatbot/infrastructure/strategies/kg_strategy.py` 2026-05-06 11:38 — pipeline.py 가 phase 작업 *이전* 시점.

### C. 단일 책임 / 라인 한도 — PASS
| 파일 | 라인 | 한도 | 상태 |
|------|-----:|-----:|:----:|
| `kg_strategy.py` | 166 | 200 | OK |
| `_config.py` | 79 | (3 dataclass) | OK |
| `__init__.py` | 25 | — | OK |
| `test_graph_store.py` | 127 | 200 | OK |
| `test_kg_stages.py` | 157 | 200 | OK |
| `test_kg_strategy.py` | 148 | 200 | OK |

- `run()` 라인 (83-114) = 32줄, 한도 60 충족. `_fetch_subgraph(116-121)` 6줄, `_build_result(123-150)` 28줄. 단일 책임 분리 적절.
- `_config.py` 의 3 dataclass (Hybrid/KG/Agentic) 는 서로 *공유 필드 없음* — `top_k`, `label`, `pattern_name`, `system_prompt` 가 dataclass 별로 독립 정의. 한 파일 묶음은 위반 아님 (단일 책임 = "strategy 노브 모음", 50줄 미만이면 분리 비용이 더 큼).

### D. 동등성 / 정합성 검증 — PASS (envelope 변경은 *의도된* 차이)
- `_format_subgraph_for_llm` (kg_strategy.py:153-166) vs rag_core/kg/pipeline.py:244-262 — 의미 동등:
  - 빈 edges 일 때 nodes top 10 라벨 노출 (도메인 `n.label`, 레거시 `n.label`).
  - edges 30개 컷, `f"- {src} --[{label or 'RELATED_TO'}]--> {dst}"`.
  - 신 버전은 `label_by_id` dict pre-build 로 O(N+E) 보장 (레거시 `_find_node_label` 은 O(N·E) 선형 탐색) — *성능 개선*, 의미는 같음.
- `ExtractEntitiesResult (TypedDict)` 키: `entities`, `intent` — `EntityExtraction` (rag_core) 의 두 필드와 1:1 호환. `extract_entities_stage.py:53-55` 가 명시 변환.
- metadata 키 비교 (의도된 차이):
  | 키 | rag_core/kg/pipeline.query() | KGStrategy.run() | 차이 |
  |----|---|---|---|
  | `pattern` | "Knowledge Graph RAG" | 동일 | OK |
  | `entities` | `list[str]` | `",".join(...)` (str) | str 직렬화 — `RetrievalResult.metadata: dict[str, str]` 계약 |
  | `intent` | str | str | 동일 |
  | `subgraph` | dict | (envelope `RetrievalResult.subgraph` 필드) | 도메인 envelope 격상 |
  | `graph_node_count` / `_edge_count` | int | str(int) | str 직렬화 |
  | `vector_count` | int | str(int) | 동일(직렬화) |
  | `elapsed_seconds` | float | (`elapsed_ms` int→str) | 단위 ms 표준화 (Hybrid/Agentic 와 정합) |
  | `source_pages` / `source_pages_label` | list | (envelope `citations`) | citations 필드로 격상 |
  | `tool_calls` / `suggested_followups` / `cache_delta` | dict | (없음) | KG 는 도구·followup 미생성 — 의도 |
  | `answer` | (별도 `final_answer` 키) | metadata.answer | 합성 노드가 metadata 에서 추출 |

  결론: KG strategy 는 `RetrievalResult` envelope 통일 계약을 따르고, 누락 키(suggested_followups, cache_delta) 는 *상위 layer 가 합성* 하는 책임 분리.

### E. 타입/스타일 — PASS (권고 1건)
- ruff check: All checks passed.
- ruff format --check: 6 files already formatted.
- 한국어 docstring + 식별자 영문 — 모든 파일 준수.
- 이모지 0건 (`grep -P "[\x{1F300}-\x{1FAFF}]"` 결과 없음).
- 모든 함수에 타입 힌트 — *예외 1건*: `_build_result(extraction, ...)` (라인 128) 에 타입 힌트 부재. `ExtractEntitiesResult` (TypedDict) 명시 권고 → §4 권고 R1.

### F. 테스트 품질 — PASS
- `pytest tests/chatbot/`: 118 passed.
- LLM 호출 0:
  - `test_kg_strategy.py`: `FakeListChatModel(responses=["답변 [p.780]"])` (라인 87) + `_FakeExtract` (직접 stage override, 라인 69-77).
  - `test_kg_stages.py`: NormalizeSubgraphStage / SectionFilterStage 는 LLM 미호출. ExtractEntitiesStage 는 `llm=None` 으로 인스턴스화만 검증 (라인 156).
  - `test_graph_store.py`: `_FakePort` 인메모리 fake (라인 16-52).
- 테스트 케이스 수:
  | 파일 | 케이스 | 요구 | 상태 |
  |------|------:|-----:|:----:|
  | `test_kg_strategy.py` | 6 | ≥6 | OK (envelope, cited_pages, 빈 entities, is_available, supports, top_k) |
  | `test_kg_stages.py` (Normalize) | 4 | ≥4 | OK (alias, 노이즈, dedup, self-loop) |
  | `test_kg_stages.py` (SectionFilter) | 7 | ≥6 | OK (단원, page 없음, str, 변환실패, 시작/끝/밖, 메타보존) |
  | `test_graph_store.py` | 8 | ≥6 | OK (health 정상/예외, legacy→domain, 빈 metadata, index/cypher/stats/clear) |

### G. 회귀 안전성 — PASS
- `pytest tests/ --ignore=tests/chatbot -q`: **213 passed, 3 warnings (SwigPyPacked 무관)**.
- `git status api/routes/chat.py`: 변경 없음. mtime 2026-05-05 17:52 (phase 시작 전).
- PR 2-A phase2 audit 4건 회귀 점검 (§6 참조) — 모두 유지.

### H. 잠재적 결함 — 권고로 분류 (모두 비차단)
- `_build_result(extraction, ...)` 타입 힌트 부재 → §4 R1 (TypedDict 명시).
- `run()` 매 호출마다 `ChatPromptTemplate.from_messages(...)` 재생성 (라인 96-98) — 호출당 ~수 µs 비용. Hybrid/Agentic 과 *비대칭* (Hybrid 는 `GenerateStage` 가 prompt 보유). → §4 R2.
- `_format_subgraph_for_llm` 의 `[:10]`, `[:30]` 매직 넘버 (라인 157, 162) → §4 R3.
- `cited_pages` 추출 단일 패턴 `[p.N]` 만 (`extract_cited_pages` 의존). 'p.1', 'page 1' 변형 무시 — *의도된 한계*: prompt(라인 49) 가 정확히 `[p.N]` 형식 강제. 권고 없음.
- KG 에 `generate_stage` 미사용 — LLM 호출이 strategy 안에 직접 박힘 (라인 99-106). Hybrid 는 `GenerateStage` 위임. → §4 R4 (Vision 진행 시 `KGGenerateStage` 분리 검토).

### I. PR 2-A/2-B audit 권고 회귀 점검 — PASS
| 권고 | 경로 | 상태 |
|------|------|:----:|
| 2-A.§3.1 RRF dedup | `infrastructure/retrievers/hybrid_retriever.py` (변경 없음) | OK |
| 2-A.§3.2 FlashRank 인스턴스 단일 — `RerankInput` envelope | `hybrid_strategy.py:147-149`, `rerankers/flashrank_reranker.py:18, 85` | OK |
| 2-A.§3.3 `json.dumps(cited_pages)` 직렬화 | `hybrid_strategy.py:132,137` | OK |
| 2-A.§3.4 `FollowupFn: TypeAlias` | `hybrid_strategy.py:28` | OK |
| 2-A 200줄 한도 | `hybrid_strategy.py` 182줄 | OK |
| 2-B Agentic ToolPolicy enforce 한계 docstring | (변경 없음) | OK |

### J. PR 2-D (Vision) 시작 전 권고 — §7 참조

## 3. 회귀 검증 결과

| 항목 | 결과 |
|------|------|
| `pytest tests/chatbot/ -q` | 118 passed in 0.71s |
| `pytest tests/ --ignore=tests/chatbot -q` | 213 passed |
| `git diff rag_core/` | 0 라인 |
| `git diff api/routes/chat.py` | 0 라인 |
| `ruff check` (6 file) | All checks passed |
| `ruff format --check` (6 file) | already formatted |

## 4. 위반 / 권고

차단 위반 없음. 비차단 권고 4건:

- **R1** (LOW) `kg_strategy.py:128` — `_build_result(extraction, ...)` 에 `extraction: ExtractEntitiesResult` 타입 힌트 추가. 글로벌 규칙 "모든 함수의 파라미터/반환 타입 힌트" 약한 위반.
- **R2** (LOW) `kg_strategy.py:96-98` — `ChatPromptTemplate` 을 `__init__` 에서 한 번 생성해 self 에 보관 권고 (Hybrid/Agentic 의 stage 분리 패턴과 정합). 현재는 매 `run()` 마다 재생성.
- **R3** (LOW) `kg_strategy.py:157,162` — `[:10]`, `[:30]` 을 `KGStrategyConfig.max_subgraph_nodes_in_prompt`, `max_subgraph_edges_in_prompt` 로 외부화 권고. 도메인별 튜닝 여지 확보.
- **R4** (LOW, PR 2-D 와 함께) KG 의 LLM 호출이 strategy 본문에 직박혀 있음. 향후 `KGGenerateStage` (graph_text + chunk_text + question → answer) 로 분리하면 GenerateStage 패턴과 정합. 현재 phase 에서는 라인 한도 안에 있어 차단 사유 아님.

## 5. 통계

- 신규 프로덕션 파일 라인: `kg_strategy.py` 166 + `_config.py` (KGStrategyConfig 부분 ~28) ≈ 194줄.
- 신규 테스트 파일 라인: 127 + 157 + 148 = **432줄**.
- 신규 테스트 케이스: 8 + 15 + 6 = **29 case**.
- 메서드 수: KGStrategy 7개 (`__init__`, `name`, `label`, `is_available`, `supports`, `run`, `_fetch_subgraph`, `_build_result`) + 모듈 함수 1개 (`_format_subgraph_for_llm`).
- import 회귀: 도메인→인프라 0, 인프라→애플리케이션 0, 외부 SDK 직접 import 0 (TYPE_CHECKING / lazy 만).

## 6. PR 2-A/2-B audit 권고 회귀 점검 (상세)

PR 2-A phase2 audit 의 권고 4건:
1. RRF dedup — `hybrid_retriever.py` 미변경. 본 phase 는 `hybrid_*` 무관.
2. FlashRank 인스턴스 단일화 + `RerankInput` 패턴 — `hybrid_strategy.py:147-149` 의 `self._reranker.run(RerankInput(query=query, documents=documents))` 그대로.
3. `cited_pages` / `suggested_followups` `json.dumps` 직렬화 — `hybrid_strategy.py:132,137` 그대로.
4. `FollowupFn: TypeAlias = Callable[[str, str], list[str]]` — `hybrid_strategy.py:28` 그대로.

PR 2-B Agentic 권고:
- `agentic_strategy.py` 135줄 (한도 200). 본 phase 변경 없음.
- `ToolPolicy.enforce` 한계 docstring — 변경 없음.

PR 2-C phase1 권고 회귀:
- `domain/graph.py` 99줄, langchain import 0 — 유지.
- `Neo4jGraphStore.health_check` 예외 포착 → `(False, "ConnectionError: ...")` — `test_graph_store.py:62` 가 검증.
- `port_to_graph_store` 헬퍼 — `__init__.py:13` export 유지.

## 7. PR 2-D (Vision) 진행 가능 여부 + 시작 전 권고

진행 **가능**. KGStrategy 가 조립 패턴(주입 인자 + lazy LangChain import + envelope 통일) 의 reference 가 됨.

Vision strategy 가 따를 부분:
- **조립 패턴**: `__init__(*, llm, image_prompt_stage, vision_retriever, config: VisionStrategyConfig)` — KG 와 동일한 keyword-only injection.
- **`supports(request)`**: KG 의 *역조건* 적용 — `request.attachments` 가 비어있지 *않을 때* True. KG/Hybrid 가 거부한 첨부를 Vision 이 받아낸다.
- **envelope**: `RetrievalResult.metadata` 에 `vision_image_count`, `image_modality` 등 *str 직렬화*. citations 는 텍스트 페이지 인용 + 이미지 caption ID 양쪽 가능.
- **TYPE_CHECKING/lazy**: 멀티모달 LLM (gpt-4o, gemini) SDK 도 `if TYPE_CHECKING` 블록 + `run()` 내부 import.

다른 부분 (asymmetry 인지하고 의도 분리):
- Vision 은 `attachments` 검증 stage 가 *별도 모듈* 이어야 함 (URL/MIME/크기 한도). 본 phase 의 `NormalizeSubgraphStage`/`SectionFilterStage` 와 무관 — KG 단원/엔티티 정규화 로직과 섞지 말 것.
- `cited_pages` 패턴이 image caption 영역으로 확장될 가능성. 현재 `extract_cited_pages` 가 `[p.N]` 만 인지 — Vision 단계에서 `[img.N]` 또는 `[fig.N]` 패턴 추가 시 별도 parser 권고.

권고:
- `KGStrategy` 의 R1 (TypedDict 힌트) 와 R3 (매직 넘버 외부화) 는 Vision 진행 *전* 가벼운 후속 PR 로 닫고 진행하면 일관성 유지에 좋음. 차단은 아님.
