"""글로서리 라우트 — 프론트가 첫 진입 시 한 번 fetch."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from rag_core.glossary import all_terms

router = APIRouter(tags=["meta"])


@router.get("/glossary")
async def get_glossary() -> dict[str, Any]:
    """전체 글로서리 — JSON 배열 + 메타. 캐시 가능 (변경 빈도 낮음)."""
    terms = all_terms()
    return {"terms": terms, "count": len(terms)}
