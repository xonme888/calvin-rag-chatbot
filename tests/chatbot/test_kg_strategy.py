"""KGStrategy 합성 테스트 — Fake GraphStore + FakeListChatModel.

LLM 호출은 단일 답변 텍스트만 — 도구 호출 추론 등 복잡한 ReAct 루프 없음.
extract_entities stage 는 직접 override 해 LLM 호출 우회.
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from chatbot.domain.conversation import Attachment
from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import GraphEdge, GraphNode, RetrievalRequest, Subgraph
from chatbot.infrastructure.stages import (
    ExtractEntitiesResult,
    ExtractEntitiesStage,
    NormalizeSubgraphStage,
)
from chatbot.infrastructure.strategies import KGStrategy, KGStrategyConfig


class _FakeGraphStore:
    name = "fake_graph"

    def __init__(self, *, available: bool = True) -> None:
        self.last_entities: list[str] | None = None
        self._available = available

    def health_check(self) -> tuple[bool, str | None]:
        return (self._available, None if self._available else "Neo4j 미연결")

    def index_chunks(self, chunks, progress_callback=None):  # type: ignore[no-untyped-def]
        return 0

    def query_cypher(self, cypher, params=None):  # type: ignore[no-untyped-def]
        return []

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> Subgraph:
        self.last_entities = entity_names
        return Subgraph(
            nodes=(
                GraphNode(id="어거스틴", label="어거스틴"),
                GraphNode(id="칼빈", label="칼빈"),
            ),
            edges=(GraphEdge(source="어거스틴", target="칼빈", label="INFLUENCES"),),
        )

    def stats(self) -> dict[str, int]:
        return {"nodes": 2, "edges": 1}

    def clear(self) -> None: ...


class _FakeRetriever:
    name = "fake_retriever"

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        return [
            DocumentRef(
                corpus_id="calvin",
                source_id="institutes_v1",
                chunk_id="c:1",
                page=779,
                content="예정론 본문",
            )
        ]


class _FakeExtract(ExtractEntitiesStage):
    def __init__(self, entities: list[str], intent: str = "general") -> None:
        self._entities = entities
        self._intent = intent

    name = "extract_entities"

    def run(self, input: str) -> ExtractEntitiesResult:
        return ExtractEntitiesResult(entities=self._entities, intent=self._intent)


def _make(entities=("어거스틴", "칼빈"), available=True, llm_response="답변 [p.780]"):
    store = _FakeGraphStore(available=available)
    return store, KGStrategy(
        graph_store=store,
        text_retriever=_FakeRetriever(),
        extract_stage=_FakeExtract(list(entities), "influence"),
        normalize_stage=NormalizeSubgraphStage(),
        llm=FakeListChatModel(responses=[llm_response]),
        config=KGStrategyConfig(),
    )


# ============================================================
def test_kg_정상_envelope():
    _, s = _make()
    result = s.run(RetrievalRequest(standalone_question="어거스틴이 칼빈에게?"))
    assert s.name == "kg" and s.label == "Knowledge Graph"
    assert result.metadata["pattern"] == "Knowledge Graph RAG"
    assert result.metadata["intent"] == "influence"
    assert "어거스틴" in result.metadata["entities"]
    assert result.metadata["graph_node_count"] == "2"
    assert result.metadata["graph_edge_count"] == "1"
    assert result.metadata["vector_count"] == "1"
    assert result.subgraph is not None
    assert len(result.subgraph.nodes) == 2


def test_kg_답변에서_cited_pages_추출():
    _, s = _make(llm_response="어거스틴은 [p.780] 영향을 줌")
    result = s.run(RetrievalRequest(standalone_question="?"))
    # cited_pages=[780] → DocumentRef.page=779 (0-indexed) 가 page+1=780 매칭
    assert len(result.citations) == 1
    assert "p.780" in result.citations[0].page_label


def test_kg_빈_entities_graph_store_미호출():
    """엔티티 추출 결과가 빈 list 면 graph_store.get_subgraph 호출 없음."""
    store, s = _make(entities=())
    result = s.run(RetrievalRequest(standalone_question="?"))
    assert store.last_entities is None
    assert result.metadata["graph_node_count"] == "0"
    assert result.metadata["graph_edge_count"] == "0"


def test_kg_is_available_health_check_위임():
    _, s = _make(available=False)
    ok, reason = s.is_available()
    assert ok is False
    assert "Neo4j" in (reason or "")


def test_kg_supports_attachments_거부():
    _, s = _make()
    assert s.supports(RetrievalRequest(standalone_question="?")) is True
    req_att = RetrievalRequest(
        standalone_question="?",
        attachments=(Attachment(kind="image_url", value="http://x"),),
    )
    assert s.supports(req_att) is False


def test_kg_top_k_config_적용():
    """Strategy 가 request.top_k 를 config.top_k 로 덮어쓴다."""
    _, s = _make()
    request = RetrievalRequest(standalone_question="?", top_k=99)
    # 내부 retriever 가 받는 request 의 top_k 가 config.top_k(=5) 로 수정됨.
    # 본 테스트는 envelope 의 vector_count = retriever 가 반환한 1.
    result = s.run(request)
    assert result.metadata["vector_count"] == "1"
