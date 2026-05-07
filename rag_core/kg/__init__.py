"""Knowledge Graph 모드 서브패키지.

Hexagonal Architecture:
- ``port.KnowledgeGraphPort``: 도메인 인터페이스 (Protocol)
- ``neo4j_adapter.Neo4jAdapter``: Port 구현 (langchain-neo4j 기반)
- ``config.Neo4jConfig``: 환경(local/aura) 자동 감지
- ``factory.get_kg_adapter``: 환경 기반 어댑터 인스턴스 생성
- ``pipeline.KnowledgeGraphRAG``: Port에 의존하는 RAG 본체 (어댑터 무관)
- ``section_filter``: 단원 page 필터 + 비용 추정

향후 ``Neo4jAdapter`` 외에 ``NetworkXAdapter`` 등을 추가해도
``KnowledgeGraphRAG`` 코드는 무수정.
"""

from rag_core.kg.config import Neo4jConfig
from rag_core.kg.factory import get_kg_adapter
from rag_core.kg.port import KnowledgeGraphPort, SubgraphData

__all__ = [
    "KnowledgeGraphPort",
    "Neo4jConfig",
    "SubgraphData",
    "get_kg_adapter",
]
