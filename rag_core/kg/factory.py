"""KG 어댑터 팩토리.

환경변수 기반으로 적절한 어댑터를 생성.
v1: Neo4jAdapter 단일 (로컬/Aura는 Config가 자동 분기)
v2 확장 여지: ``KG_BACKEND=neo4j|networkx|...`` 환경변수로 다중 백엔드 지원 가능.
"""

from __future__ import annotations

from functools import lru_cache

from rag_core.kg.config import Neo4jConfig
from rag_core.kg.port import KnowledgeGraphPort


@lru_cache(maxsize=1)
def get_kg_adapter(config: Neo4jConfig | None = None) -> KnowledgeGraphPort:
    """환경에 맞는 KG 어댑터 인스턴스를 반환한다 (싱글톤).

    Args:
        config: 명시적 설정. None이면 ``.env`` 기반 자동 로드.
            테스트에서 Mock Adapter를 주입하려면 별도 함수 사용 권장.

    Returns:
        KnowledgeGraphPort 구현체.

    Raises:
        ImportError: Neo4j 어댑터 의존성 미설치 시.
            ``uv pip install -e '.[kg]'``
    """
    cfg = config or Neo4jConfig()

    # v1: Neo4j 단일. 향후 KG_BACKEND 환경변수로 분기 가능.
    from rag_core.kg.neo4j_adapter import Neo4jAdapter

    return Neo4jAdapter(cfg)


def reset_adapter_cache() -> None:
    """싱글톤 캐시 초기화. 테스트에서 환경/Config 바꿀 때 사용."""
    get_kg_adapter.cache_clear()
