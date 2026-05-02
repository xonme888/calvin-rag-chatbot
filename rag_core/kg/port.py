"""KG 백엔드 Port 정의 (Hexagonal 도메인 인터페이스).

이 모듈은 langchain-neo4j 등 외부 라이브러리에 의존하지 않는다 (Domain은 Infra 무의존).
Adapter는 ``langchain_core.documents.Document`` 만 외부 의존성으로 받는다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from langchain_core.documents import Document
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """시각화/RAG에서 사용할 그래프 노드."""

    id: str = Field(description="고유 식별자 (보통 엔티티 이름)")
    label: str = Field(description="화면 표시용 라벨")
    type: str = Field(default="Entity", description="노드 타입 (Concept, Person 등)")
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """시각화/RAG에서 사용할 그래프 엣지."""

    source: str = Field(description="src 노드 id")
    target: str = Field(description="dst 노드 id")
    label: str = Field(description="관계 라벨 (predicate)")
    properties: dict[str, Any] = Field(default_factory=dict)


class SubgraphData(BaseModel):
    """엔티티 주변 부분 그래프 (시각화 입력)."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


@runtime_checkable
class KnowledgeGraphPort(Protocol):
    """KG 백엔드 추상화. Neo4j(Local/Aura), NetworkX 등이 구현 가능.

    구현체는 외부 시스템(Neo4j)과의 모든 I/O를 캡슐화한다.
    ``KnowledgeGraphRAG``는 이 Port에만 의존하므로 Mock으로 단위 테스트 가능.
    """

    def health_check(self) -> bool:
        """연결 상태 확인. 챗봇 시작 시 헬스 체크에 사용."""
        ...

    def index_chunks(
        self,
        chunks: list[Document],
        progress_callback: Any | None = None,
    ) -> int:
        """청크에서 트리플을 추출해 그래프에 영속한다.

        Args:
            chunks: 인덱싱할 청크. ``metadata["page"]`` 등 출처 보존.
            progress_callback: 선택. 진행률 콜백 ``(current, total) -> None``.

        Returns:
            인덱싱된 청크 수.
        """
        ...

    def query_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Cypher 쿼리 실행."""
        ...

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> SubgraphData:
        """엔티티 주변 N홉 부분 그래프 반환 (시각화용)."""
        ...

    def clear(self) -> None:
        """전체 노드/엣지 삭제 (재인덱싱 시 사용)."""
        ...

    def stats(self) -> dict[str, int]:
        """``{nodes, edges}`` 등 그래프 통계."""
        ...
