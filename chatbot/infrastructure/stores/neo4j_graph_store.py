"""Neo4j GraphStore 어댑터 — 기존 KnowledgeGraphPort 를 도메인 GraphStore 로 흡수.

전략:
- 기존 ``rag_core/kg/neo4j_adapter.py:Neo4jAdapter`` 와 ``rag_core/kg/factory.py`` 자산을
  *재사용* 한다 — 코드 중복 0.
- 본 어댑터는 ``KnowledgeGraphPort`` 인스턴스를 *컴포지션* 받아 ``domain.GraphStore`` 시그니처로
  위임한다.
- 핵심 변환: ``rag_core/kg/port.py:SubgraphData`` → ``chatbot/domain/retrieval.py:Subgraph``.
  도메인 frozen 모델로 변환되어 답변 envelope 단일 형식 유지.

새 GraphStore 백엔드 (예: NetworkX in-memory) 추가는 본 디렉토리에 1개 파일 추가.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document

from chatbot.domain.indexing import Chunk
from chatbot.domain.retrieval import GraphEdge, GraphNode, Subgraph

if TYPE_CHECKING:
    from rag_core.kg.port import GraphEdge as LegacyEdge
    from rag_core.kg.port import GraphNode as LegacyNode
    from rag_core.kg.port import KnowledgeGraphPort, SubgraphData


class Neo4jGraphStore:
    """KnowledgeGraphPort 를 GraphStore 로 위임 + Subgraph 변환.

    실 Neo4j 통신은 기존 ``rag_core/kg/neo4j_adapter.Neo4jAdapter`` 가 담당. 본 클래스는
    *시그니처 정합* 만 책임진다.
    """

    name: str = "neo4j"

    def __init__(self, port: KnowledgeGraphPort) -> None:
        self._port = port

    def health_check(self) -> tuple[bool, str | None]:
        """legacy port 의 health_check 는 bool 만 반환 — 실패 사유는 별도 추정 안 함."""
        try:
            ok = bool(self._port.health_check())
        except Exception as e:  # noqa: BLE001
            return (False, f"{type(e).__name__}: {e}")
        return (ok, None if ok else "Neo4j 연결 실패")

    def index_chunks(
        self,
        chunks: list[Chunk],
        progress_callback: Any | None = None,
    ) -> int:
        """domain.Chunk → langchain Document 로 변환 후 legacy port 에 위임."""
        documents = [_chunk_to_document(c) for c in chunks]
        return self._port.index_chunks(documents, progress_callback=progress_callback)

    def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._port.query_cypher(cypher, params)

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> Subgraph:
        legacy = self._port.get_subgraph(entity_names, hops=hops)
        return _legacy_subgraph_to_domain(legacy)

    def stats(self) -> dict[str, int]:
        return self._port.stats()

    def clear(self) -> None:
        self._port.clear()


def port_to_graph_store(port: KnowledgeGraphPort) -> Neo4jGraphStore:
    """KnowledgeGraphPort 인스턴스를 GraphStore 로 감싼다 — 진입점 헬퍼."""
    return Neo4jGraphStore(port)


def _chunk_to_document(chunk: Chunk) -> Document:
    """domain.Chunk → langchain Document. metadata 그대로 보존."""
    return Document(page_content=chunk.content, metadata=dict(chunk.metadata))


def _legacy_subgraph_to_domain(legacy: SubgraphData) -> Subgraph:
    """rag_core/kg/port.SubgraphData → chatbot/domain/retrieval.Subgraph.

    legacy 의 properties (dict[str, Any]) 가 도메인 metadata (dict[str, str]) 로 *문자열화*.
    """
    nodes = tuple(_legacy_node_to_domain(n) for n in legacy.nodes)
    edges = tuple(_legacy_edge_to_domain(e) for e in legacy.edges)
    return Subgraph(nodes=nodes, edges=edges)


def _legacy_node_to_domain(node: LegacyNode) -> GraphNode:
    return GraphNode(
        id=str(node.id),
        label=str(node.label),
        type=str(node.type) if node.type else None,
        metadata={k: str(v) for k, v in (node.properties or {}).items() if v is not None},
    )


def _legacy_edge_to_domain(edge: LegacyEdge) -> GraphEdge:
    return GraphEdge(
        source=str(edge.source),
        target=str(edge.target),
        label=str(edge.label) if edge.label else None,
        metadata={k: str(v) for k, v in (edge.properties or {}).items() if v is not None},
    )
