"""저장소 어댑터 — domain.Store / domain.GraphStore 구현체.

벡터 store (FAISS/Qdrant) 는 chatbot/domain/indexing.py:Store 에 정합.
그래프 store (Neo4j) 는 chatbot/domain/graph.py:GraphStore 에 정합.
두 추상이 분리된 이유는 검색 시그니처가 본질적으로 다르기 때문.
"""

from chatbot.infrastructure.stores.neo4j_graph_store import (
    Neo4jGraphStore,
    port_to_graph_store,
)

__all__ = ["Neo4jGraphStore", "port_to_graph_store"]
