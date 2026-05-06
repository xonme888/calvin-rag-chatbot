"""Neo4jGraphStore 어댑터 테스트 — KnowledgeGraphPort → GraphStore 변환."""

from __future__ import annotations

from typing import Any

from rag_core.kg.port import GraphEdge as LegacyEdge
from rag_core.kg.port import GraphNode as LegacyNode
from rag_core.kg.port import SubgraphData

from chatbot.domain.indexing import Chunk
from chatbot.domain.retrieval import Subgraph
from chatbot.infrastructure.stores import port_to_graph_store


class _FakePort:
    """KnowledgeGraphPort Protocol 만족하는 in-memory fake."""

    def __init__(self) -> None:
        self.last_chunks: list = []
        self.last_cypher: tuple[str, dict | None] | None = None
        self.cleared = False

    def health_check(self) -> bool:
        return True

    def index_chunks(self, chunks, progress_callback=None) -> int:  # type: ignore[no-untyped-def]
        self.last_chunks = chunks
        return len(chunks)

    def query_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        self.last_cypher = (cypher, params)
        return [{"row": 1}]

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> SubgraphData:
        return SubgraphData(
            nodes=[
                LegacyNode(
                    id="어거스틴", label="어거스틴", type="Person", properties={"desc": "교부"}
                ),
                LegacyNode(id="칼빈", label="칼빈", type="Person", properties={}),
            ],
            edges=[
                LegacyEdge(source="어거스틴", target="칼빈", label="INFLUENCES", properties={}),
            ],
        )

    def stats(self) -> dict[str, int]:
        return {"nodes": 5, "edges": 7}

    def clear(self) -> None:
        self.cleared = True


def test_health_check_정상():
    store = port_to_graph_store(_FakePort())
    ok, reason = store.health_check()
    assert ok is True
    assert reason is None


def test_health_check_예외_포착_False():
    class _BadPort(_FakePort):
        def health_check(self) -> bool:  # type: ignore[override]
            raise ConnectionError("연결 실패")

    store = port_to_graph_store(_BadPort())
    ok, reason = store.health_check()
    assert ok is False
    assert "ConnectionError" in (reason or "")


def test_get_subgraph_legacy_to_domain_변환():
    store = port_to_graph_store(_FakePort())
    sg = store.get_subgraph(["어거스틴", "칼빈"], hops=2)
    assert isinstance(sg, Subgraph)
    assert len(sg.nodes) == 2
    assert sg.nodes[0].id == "어거스틴"
    assert sg.nodes[0].metadata == {"desc": "교부"}
    assert sg.nodes[0].type == "Person"
    assert len(sg.edges) == 1
    assert sg.edges[0].source == "어거스틴"
    assert sg.edges[0].label == "INFLUENCES"


def test_get_subgraph_빈_properties_빈_metadata():
    """legacy properties={} → domain metadata={}, None 값은 스킵."""
    store = port_to_graph_store(_FakePort())
    sg = store.get_subgraph(["x"])
    # 칼빈 노드의 properties={} 였음
    calvin = next(n for n in sg.nodes if n.id == "칼빈")
    assert calvin.metadata == {}


def test_index_chunks_위임():
    port = _FakePort()
    store = port_to_graph_store(port)
    chunks = [
        Chunk(id="c:1", content="본문", metadata={"page": "0"}),
        Chunk(id="c:2", content="본문2", metadata={"page": "1"}),
    ]
    n = store.index_chunks(chunks)
    assert n == 2
    # legacy port 가 받은 chunks 는 langchain Document 시퀀스
    assert len(port.last_chunks) == 2
    assert port.last_chunks[0].page_content == "본문"
    assert port.last_chunks[0].metadata == {"page": "0"}


def test_query_cypher_위임():
    port = _FakePort()
    store = port_to_graph_store(port)
    out = store.query_cypher("MATCH (n) RETURN n", {"k": 1})
    assert out == [{"row": 1}]
    assert port.last_cypher == ("MATCH (n) RETURN n", {"k": 1})


def test_stats_위임():
    store = port_to_graph_store(_FakePort())
    assert store.stats() == {"nodes": 5, "edges": 7}


def test_clear_위임():
    port = _FakePort()
    store = port_to_graph_store(port)
    store.clear()
    assert port.cleared is True
