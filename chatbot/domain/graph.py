"""그래프 저장소 도메인 — KG 검색에만 사용되는 별도 Protocol.

일반 벡터 ``Store`` (chatbot/domain/indexing.py) 와 시그니처가 다르므로 같은 Protocol 로
묶지 않는다. KG 만 본 추상에 의존 — Hybrid/Agentic/Vision 은 무관.

분리 이유:
- 벡터 Store 는 query embedding + filter 로 검색.
- 그래프 Store 는 entity_names + hops 로 부분 그래프, 또는 Cypher 직접 질의.

본 Protocol 은 ``rag_core/kg/port.py:KnowledgeGraphPort`` 와 *의도가 같다*. 어댑터를 통해
양쪽 호환 — 도메인 Subgraph (chatbot/domain/retrieval.py) 가 단일 표현형이다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from chatbot.domain.indexing import Chunk
from chatbot.domain.retrieval import Subgraph


@runtime_checkable
class GraphStore(Protocol):
    """그래프 저장소 어댑터 인터페이스.

    Neo4j (Local/Aura), NetworkX in-memory 등이 구현 가능. KGStrategy 가 본 Protocol 에만
    의존 — Mock 어댑터로 단위 테스트.
    """

    name: str

    def health_check(self) -> tuple[bool, str | None]:
        """연결 상태 확인. 챗봇 부팅 시 헬스 프로브용."""
        ...

    def index_chunks(
        self,
        chunks: list[Chunk],
        progress_callback: Any | None = None,
    ) -> int:
        """청크에서 트리플을 추출해 그래프에 영속.

        실 LLMGraphTransformer 호출은 GraphIndexer 가 따로 책임 — 본 메서드는 *결과 적재*.
        구현체는 trace event 또는 progress_callback 으로 진행률 노출 가능.
        """
        ...

    def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Cypher 쿼리 실행. 디버깅·고급 질의에 사용 — strategy 가 일상적으로 호출 X."""
        ...

    def get_subgraph(
        self,
        entity_names: list[str],
        hops: int = 1,
    ) -> Subgraph:
        """엔티티 주변 N홉 부분 그래프. UI 시각화 + LLM 컨텍스트 합류용."""
        ...

    def stats(self) -> dict[str, int]:
        """``{nodes, edges}`` 등 그래프 통계."""
        ...

    def clear(self) -> None:
        """전체 노드/엣지 삭제 (재인덱싱 시)."""
        ...


@runtime_checkable
class GraphIndexer(Protocol):
    """청크 → 그래프 트리플 변환기. Store.index_chunks 와 분리 책임.

    LLMGraphTransformer 같은 *비싼 추출기* 를 격리한다. 인덱싱 1회 cost 가 크므로
    estimate_cost 로 사전 추정 — strategy 는 본 Protocol 에 의존.
    """

    name: str

    def estimate_cost(self, chunks: list[Chunk]) -> dict[str, float]:
        """LLM 호출 없이 청크 수 기반 비용·시간 추정.

        Returns:
            ``{"chunks": N, "usd": ..., "krw": ..., "minutes": ...}``.
        """
        ...

    def index_into(
        self,
        chunks: list[Chunk],
        store: GraphStore,
        progress_callback: Any | None = None,
    ) -> int:
        """청크 → 트리플 추출 + store 에 적재. 적재된 청크 수 반환."""
        ...
