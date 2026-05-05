"""글로서리 라우트.

엔드포인트:
- GET /glossary             — 전체 60개 (정의 + sources)
- GET /glossary/{term}/graph — 해당 용어의 KG 1-hop subgraph

향후 옵션 D 마이그레이션 시 ``rag_core.glossary.load_glossary`` 의 source 만
swap (JSON → Neo4j export). 라우트 무수정.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from api.dependencies import get_kg_rag_or_none
from rag_core.glossary import all_terms

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


@router.get("/glossary")
async def get_glossary() -> dict[str, Any]:
    """전체 글로서리 — JSON 배열 + 메타. 캐시 가능 (변경 빈도 낮음)."""
    terms = all_terms()
    return {"terms": terms, "count": len(terms)}


@router.get("/glossary/{term}/graph")
async def term_graph(term: str) -> dict[str, Any]:
    """특정 용어의 KG 1-hop 부분 그래프.

    KG 비활성 시 ``kg_available=False`` + 빈 nodes/edges 로 graceful fallback.
    프론트는 이 응답으로 '관계 정보 준비 중' UI 결정 가능.
    """
    kg = get_kg_rag_or_none()
    if kg is None:
        return {"nodes": [], "edges": [], "kg_available": False}
    try:
        subgraph = kg.kg.get_subgraph([term], hops=1)
        return {**subgraph.model_dump(), "kg_available": True}
    except Exception as e:  # noqa: BLE001
        logger.warning("term_graph 실패 [%s]: %s", term, e)
        return {"nodes": [], "edges": [], "kg_available": False}
