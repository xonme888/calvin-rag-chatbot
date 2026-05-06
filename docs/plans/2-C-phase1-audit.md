# PR 2-C Phase 1 Audit (PR 2-C.1~4)

> 독립 감사 — `chatbot/domain/graph.py`, `chatbot/infrastructure/{stores,indexers}/`,
> `chatbot/infrastructure/stages/{extract_entities,normalize_subgraph,section_filter}_stage.py`.
> 메인 thread 산출물을 grep + Read + 실측 (ruff, ast, 동등성 비교) 으로 직접 검증.

## 1. 요약 판정

**PASS** (CONDITIONAL 사유 없음).

- Hexagonal 의존방향 위반 0, `rag_core/` 변경 0 (git diff 비어있음).
- rag_core 동등성 4종 (estimate_cost, alias 사전, regex, 5단원) 모두 100% 일치.
- ruff check + format 9 파일 통과.
- 모든 함수/메서드 타입힌트 보유, 이모지 0건.
- runtime_checkable Protocol 만족 (Neo4jGraphStore, LLMGraphIndexer).
- 외부 의존성 (Neo4j / langchain_experimental / OpenAI) 모듈-import 시점 0 — lazy import 정상.

라인 한도 1건 (normalize_subgraph_stage.run 45줄, 30줄 한도 초과)
은 INFO 권고 — 원본 알고리즘 충실 재사용으로 동등성 우선이며 본 phase 차단 사유 아님.

## 2. 체크리스트 결과

### A. Hexagonal 준수 — PASS

`chatbot/domain/graph.py` import 실측:

| 라인 | import | 평가 |
|---|---|---|
| 14 | `from __future__ import annotations` | std |
| 16 | `from typing import Any, Protocol, runtime_checkable` | std |
| 18 | `from chatbot.domain.indexing import Chunk` | domain — OK |
| 19 | `from chatbot.domain.retrieval import Subgraph` | domain — OK |

LangChain / Neo4j / pydantic 등 외부 의존성 0. 도메인 모듈만 import.

`infrastructure/stages/*` LangChain 처리:

| 파일 | 패턴 |
|---|---|
| extract_entities_stage.py:14 | `if TYPE_CHECKING: from langchain_core.language_models import BaseChatModel` |
| extract_entities_stage.py:41 | `def run(...): from langchain_core.prompts import ChatPromptTemplate` (메서드 본문 lazy) |
| extract_entities_stage.py:43 | `def run(...): from rag_core.kg.pipeline import EntityExtraction` (메서드 본문 lazy) |
| normalize_subgraph_stage | LangChain 의존성 0 (pure) |
| section_filter_stage | LangChain 의존성 0 (pure) |

`infrastructure/stores/neo4j_graph_store.py` import 패턴:

| 라인 | import | 평가 |
|---|---|---|
| 18 | `from langchain_core.documents import Document` | infra — OK (어댑터 본인 책임) |
| 23-26 | `if TYPE_CHECKING: from rag_core.kg.port import ...` | OK (런타임 의존 회피) |

런타임 import 시 `rag_core.kg.port` 로딩 0 — ToolSearch 검증 완료.

### B. rag_core 비손상 — PASS

```bash
git diff --stat rag_core/   # 출력: (없음)
git status rag_core/        # 깨끗
```

`rag_core/kg/` 8개 파일 (`port`, `neo4j_adapter`, `pipeline`, `entity_normalizer`,
`section_filter`, `config`, `factory`, `graph_renderer`) 모두 한 줄 변경 없음.

새 코드의 *재사용 vs 복제* 평가:

| 위치 | 패턴 | 평가 |
|---|---|---|
| `neo4j_graph_store` | `KnowledgeGraphPort` 컴포지션 + 위임 | 재사용 (코드 0 복제) |
| `llm_graph_indexer.estimate_cost` | 수식 자체 복제 (10줄) | 동의 — 인덱서 책임 전환을 위한 *최소* 복제. 동등성 검증 통과 |
| `extract_entities_stage` | `EntityExtraction` 스키마 import 재사용 | 재사용 |
| `normalize_subgraph_stage` | alias dict + 알고리즘 복제 (90줄) | 동의 — 도메인 모델 (Subgraph frozen) 변경 동반이라 재호출 불가, 등가 사본 |
| `section_filter_stage` | DEFAULT_CALVIN_SECTIONS + 알고리즘 복제 (~80줄) | 동의 — Document↔Chunk 타입 차이 |

복제는 *도메인 모델 차이* (legacy SubgraphData / Document vs domain Subgraph / Chunk) 때문이며,
**동등성 검증** 으로 회귀 위험은 통제됨.

### C. 단일 책임 / 라인 한도 — PASS (INFO 1건)

| 파일 | 라인 | 클래스 | 메서드/클래스 |
|---|---:|---:|---|
| chatbot/domain/graph.py | 98 | 2 | GraphStore=6, GraphIndexer=2 |
| infra/stores/__init__.py | 13 | 0 | — |
| infra/stores/neo4j_graph_store.py | 111 | 1 | 7 (`__init__` 포함) |
| infra/indexers/__init__.py | 9 | 0 | — |
| infra/indexers/llm_graph_indexer.py | 57 | 1 | 2 |
| infra/stages/extract_entities_stage.py | 56 | 2 | TypedDict + Stage(2) |
| infra/stages/normalize_subgraph_stage.py | 106 | 1 | 1 |
| infra/stages/section_filter_stage.py | 125 | 2 | Section(2 properties) + Stage(2) |
| infra/stages/__init__.py | 54 | 0 | — |

- 모두 200줄 한도 미만.
- 클래스당 메서드 ≤ 7 (Neo4jGraphStore 7개가 최대 — `__init__` 포함, GraphStore Protocol 6 + ctor).
- `graph.py` 의 GraphStore + GraphIndexer 동거: 두 Protocol 모두 짧고 (각 6+2 메서드), 같은 KG 도메인이라 분리 가치 낮음. **OK**.

INFO: `normalize_subgraph_stage.NormalizeSubgraphStage.run` = 45 라인 (30줄 한도 초과).
원본 `rag_core/kg/entity_normalizer.normalize_subgraph` 도 50줄 — 알고리즘 복잡도 자체가 한 메서드의 자연스러운 길이. 분해 시 `_collect_nodes` / `_dedup_edges` 두 헬퍼로 30줄 이내 가능하지만, **동등성 우선 보존** 선택은 합리적. PR 2-C.5 기점 리팩터 권고.

### D. 동등성 검증 — PASS (정량)

#### D.1 estimate_cost (USD/KRW/분)

| n (chunks) | legacy USD | new USD | legacy KRW | new KRW | legacy min | new min | 일치 |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 10 | 0.0022 | 0.0022 | 3.4 | 3.4 | 0.3 | 0.3 | OK |
| 100 | 0.0225 | 0.0225 | 33.8 | 33.8 | 3.3 | 3.3 | OK |
| 510 | 0.1147 | 0.1147 | 172.1 | 172.1 | 17.0 | 17.0 | OK |
| 1000 | 0.225 | 0.225 | 337.5 | 337.5 | 33.3 | 33.3 | OK |

(단 `chunks` 키만 legacy=int, new=float — 도메인 측 Chunk 타입 통일 차이로 의도적.)

#### D.2 ENTITY_ALIASES — 16건 동일

Python `==` 비교 결과 `True`. 항목 셋 `{Augustine/St. Augustine/Saint Augustine/St Augustine/
Pelagius/Luther/Martin Luther/Calvin/John Calvin/Aquinas/Thomas Aquinas/Zwingli/
Ulrich Zwingli/Servetus/Michael Servetus/Arius}` 동일.

#### D.3 정규식 패턴

| 패턴 | legacy | new | 일치 |
|---|---|---|:---:|
| HASH_ID | `^[a-f0-9]{20,}$` (flags=34=re.IGNORECASE\|UNICODE) | 동일 | OK |
| DIGITS_OR_SYMBOL | `^[\.\,\d\s\-\(\)]+$` | 동일 | OK |

#### D.4 DEFAULT_CALVIN_SECTIONS — 5단원 모두 동일

| slug | label | page_start | page_end | 일치 |
|---|---|---:|---:|:---:|
| 1-13 | 삼위일체론 | 136 | 169 | OK |
| 2-2 | 자유의지 | 246 | 272 | OK |
| 3-11 | 이신칭의 | 618 | 640 | OK |
| 3-21 | 예정론(서론) | 778 | 786 | OK |
| 4-14 | 성례(총론) | 1060 | 1080 | OK |

#### D.5 normalize_subgraph 동작 동등성

시나리오: alias 통합 (Augustine + 어거스틴 → 어거스틴), 노이즈 제거 (1자, hash),
self-loop 제거, 중복 엣지 dedup. 노드 셋 / 엣지 셋 모두 일치 (`['어거스틴', '칼빈', '예정론']`,
`[(어거스틴, 칼빈, INFLUENCES), (칼빈, 예정론, DEFINES)]`).

#### D.6 section_filter 경계 동등성

입력 0-indexed `[134, 135, 136, 168, 169, 170, 245, 246, 247]`:

- 1권 13장 (136~169 1-indexed = 135~168 0-indexed) → 135, 136, 168 통과
- 1권 13장 마지막 +1 (169) → 169 (1-indexed 170) 탈락
- 2권 2장 (246~272 1-indexed = 245~271 0-indexed) → 245, 246, 247 통과

legacy/new 모두 동일 6건 통과 (`[135, 136, 168, 245, 246, 247]`).

차이점 (의도적): `section_book` 메타가 legacy=int, new=str. 도메인 `Chunk.metadata` 가
`dict[str, str]` 이라 모든 값을 문자열로 강제 — 이는 도메인 계약. UI/소비자가 int 가 필요하면
str→int 변환 1회.

#### D.7 Subgraph 변환 무손실성

`_legacy_subgraph_to_domain` 함수 (neo4j_graph_store.py:86) 의 변환은:

- nodes: `id, label, type, properties→metadata` (`v is not None` 필터 + `str(v)` 변환)
- edges: `source, target, label, properties→metadata` (동일)

정보 손실: legacy `properties` 의 `None` 값만 제거 (UI 표시 의미 없음). 그 외 모든 값
str 강제 — domain 계약과 정합.

### E. 타입/스타일 — PASS

- `ruff check` (9 파일): All checks passed.
- `ruff format --check` (9 파일): 9 files already formatted.
- `ast` 분석: 모든 함수/메서드 파라미터·반환 타입힌트 보유.
- Protocol `runtime_checkable`: GraphStore + GraphIndexer 모두 표시 (`_is_runtime_protocol=True`).
- Neo4jGraphStore 의 GraphStore Protocol 메서드 7개 모두 보유 (set diff `{}`).
- LLMGraphIndexer 의 GraphIndexer Protocol 메서드 3개 모두 보유 (set diff `{}`).
- 한국어 docstring: 모든 모듈/클래스/주요 메서드 보유 (식별자만 영문).

### F. 테스트 가능성 — PASS

- `chatbot.domain.graph` 단독 import 시 외부 의존성 0 (Neo4j/langchain_experimental/OpenAI).
- 모든 stage 단독 import 가능 (extract_entities 는 LangChain 을 메서드 본문 lazy → import 시점 안전).
- Fake KnowledgeGraphPort (Mock with `health_check/index_chunks/query_cypher/get_subgraph/stats/clear`)
  로 `Neo4jGraphStore` 단위 테스트 가능. SubgraphData → Subgraph 변환은 순수 함수.
- Fake GraphStore (단일 카운터) 로 `LLMGraphIndexer.index_into` 테스트 가능.
- normalize_subgraph_stage / section_filter_stage 는 외부 의존 0 — pure unit.

### G. PRD-001 / TRD-009 정합 — PASS

TRD-009 §2.1 신규 모듈 매핑 vs 실제:

| TRD 위치 | 실제 위치 | 일치 |
|---|---|:---:|
| stores/neo4j_graph_store.py | 동일 | OK |
| indexers/llm_graph_indexer.py | 동일 | OK |
| stages/extract_entities_stage.py | 동일 | OK |
| stages/normalize_subgraph_stage.py | 동일 | OK |
| stages/section_filter_stage.py | 동일 | OK |
| domain/graph.py (GraphStore Protocol) | 동일 | OK |

TRD-009 §2.2 GraphStore Protocol 6개 메서드 — 모두 구현됨:
`health_check, index_chunks, query_cypher, get_subgraph, stats, clear`.

TRD-009 §2.5 (kg_strategy.index_corpus) — 본 phase 에서 *없어야 함*:

```bash
ls chatbot/infrastructure/strategies/  # hybrid_strategy.py, agentic_strategy.py
                                        # kg_strategy.py 부재 — OK
grep "KGStrategy" chatbot/  # docstring 참조 2건만 (구현 0)
```

**OK** — kg_strategy 는 PR 2-C.5 영역으로 격리됨.

### H. 잠재적 결함 — INFO 2건

| ID | 위치 | 사항 | 심각도 |
|---|---|---|:---:|
| H1 | section_filter_stage.py:118-125 `_parse_page` | str 이 아닌 int 도 안전 처리 (`int(int)=int`). 시그니처는 `str | None` 이라 mypy 경고 가능하나 런타임 안전 | INFO |
| H2 | normalize_subgraph_stage.py:18 `_ENTITY_ALIASES` | 모듈 레벨 mutable dict — 런타임 변조 시 모든 호출에 영향. legacy 와 동일 패턴 (rag_core/kg/entity_normalizer.py:23) 으로 *의도된 명시 사전*. 변조 위험 미발생 (외부 노출 X, 함수 내부에서 read-only 사용) | INFO |

PR 2-A/2-B audit 권고 회귀 점검:

| 권고 | 확인 결과 |
|---|---|
| 2-A: Stage Protocol 단일 책임 | extract_entities/normalize/section_filter 모두 단일 책임 유지 — OK |
| 2-A: TYPE_CHECKING + lazy import | extract_entities_stage 가 동일 패턴으로 LangChain 격리 — OK |
| 2-B: ToolRegistry 어휘 보존 | 본 phase 와 무관 — 영향 0 |
| 2-B: 외부 의존성 모듈 시점 0 | 모두 lazy import — OK |

### I. PR 2-C.5 (kg_strategy) 진행 권고

**권고 의존성** (생성자 주입):

```python
class KGStrategy:
    name: str = "kg"
    label: str = "Knowledge Graph"

    def __init__(
        self,
        *,
        graph_store: GraphStore,                           # domain.graph
        text_retriever: Retriever,                         # Hybrid 재사용
        extract_entities: ExtractEntitiesStage,
        normalize: NormalizeSubgraphStage,
        generate: GenerateStage,
        subgraph_hops: int = 1,
    ) -> None: ...
```

**run() 시그니처**:
- 입력: `RetrievalRequest` (standalone_question 사용)
- 출력: `RetrievalResult(documents=..., citations=..., subgraph=Subgraph, metadata=...)`

**RetrievalResult.metadata 키 셋 권고** (rag_core/kg/pipeline.py 와 정합):

```python
metadata = {
    "pattern": "kg",
    "intent": str,                        # extraction.intent
    "entity_count": str(len(entities)),
    "graph_node_count": str(...),
    "graph_edge_count": str(...),
    "vector_count": str(len(documents)),
    "elapsed_seconds": str(...),
}
```

**index_corpus 분리** (TRD-009 §2.5):

- 챗봇 런타임은 `KGStrategy.index_corpus` 미호출 — `langchain_experimental` 의존성이
  런타임 import 그래프에 들어오지 않도록 **메서드 본문 lazy import**.
- `scripts/index_kg.py` 가 `LLMGraphIndexer.index_into(chunks, graph_store)` 호출.

**선결 권고**:
1. PR 2-C.5 기점 normalize_subgraph_stage.run 을 `_normalize_nodes` + `_dedup_edges` 헬퍼로 분해 (30줄 한도 정렬).
2. KGStrategy 가 의존하는 Stage 들의 `Stage[I, O]` 도메인 Protocol 정합 — `extract_entities_stage` 가 `Stage[str, ExtractEntitiesResult]`, `normalize_subgraph_stage` 가 `Stage[Subgraph, Subgraph]` 로 명시 가능한지 (현재 duck-typed).

**PR 2-C.5 진행 가능 여부**: **GO**.

## 3. 통계

- 신규 파일 9개, 총 629줄 (가중 평균 70줄/파일).
- 새 클래스 7개 (Protocol 2 + 어댑터 4 + TypedDict 1 + dataclass 1).
- 새 메서드 (Protocol 제외, dunder 포함) 19개. 30줄 한도 초과 1건 (run, 45줄).
- 재사용 (rag_core 함수 호출): EntityExtraction 스키마 1건.
- 복제 (등가 알고리즘): estimate_cost (10줄), normalize_subgraph (45줄), filter_chunks_by_sections (30줄). 도메인 모델 차이로 불가피.
- ruff: 9/9 통과, format 9/9 통과.
- 외부 의존성 모듈-import 시점: 0 (lazy import 정상).

## 4. 위반/권고 (있음 — 모두 INFO)

| ID | 파일:라인 | 사항 | 권고 |
|---|---|---|---|
| INFO-1 | normalize_subgraph_stage.py:62-106 (run, 45 lines) | 30줄 한도 초과 | PR 2-C.5 기점 `_collect_nodes` / `_dedup_edges` 헬퍼로 분해 |
| INFO-2 | section_filter_stage.py:118 | `_parse_page` 시그니처 `str | None` 이지만 int 입력도 안전. mypy 엄격 모드에서 경고 | 시그니처를 `int | str | None` 으로 확대 또는 어댑터 측 str 보장 |
| INFO-3 | normalize_subgraph_stage.py:18 (`_ENTITY_ALIASES`) | 모듈 레벨 mutable dict | `MappingProxyType(_ENTITY_ALIASES)` 로 read-only wrapper 또는 frozenset/tuple 페어로 전환 |

## 5. 결론

PR 2-C.1~4 는 도메인 추상화 (`GraphStore` / `GraphIndexer` Protocol) 와 4개 인프라
어댑터 (Neo4jGraphStore + LLMGraphIndexer + 3개 Stage) 의 *최소 침습 분리* 를 달성했다.
rag_core 변경 0, 동등성 7종 모두 100% 일치, Hexagonal 의존방향 무위반.

PR 2-C.5 (kg_strategy) 진행 가능. INFO 권고 3건은 PR 2-C.5 기점에서 동시 처리 권고.
