"""헬스 + 모드 가용성 라우트."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import get_kg_rag_or_none
from api.schemas import HealthResponse, ModeInfo, ModesResponse

router = APIRouter(tags=["meta"])


class HealthResponse_:  # placeholder so import order doesn't fail
    pass


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """간단한 liveness probe — 앱 부팅만 확인."""
    return HealthResponse(
        status="ok",
        service="calvin-rag-chatbot-api",
        version="0.1.0",
    )


@router.get("/modes", response_model=ModesResponse)
async def modes() -> ModesResponse:
    """사용 가능 모드 목록 — KG는 Neo4j 가용 시만 ``available=True``.

    Streamlit `_check_kg_available()` 와 동일 사상 — graceful degradation.
    """
    kg_instance = get_kg_rag_or_none()
    return ModesResponse(
        modes=[
            ModeInfo(name="hybrid", label="Hybrid (BM25+Dense+RRF)", available=True),
            ModeInfo(name="agentic", label="Agentic (create_agent)", available=True),
            ModeInfo(
                name="kg",
                label="Knowledge Graph (Neo4j+Cypher)",
                available=kg_instance is not None,
                reason=None
                if kg_instance is not None
                else "Neo4j 미연결 또는 그래프 비어 있음",
            ),
        ]
    )
