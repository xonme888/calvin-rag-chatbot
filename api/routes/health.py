"""헬스 체크 라우트 — `/health`, `/modes`.

Step 1 에선 헬스 체크만. 모드 가용성(KG Neo4j 연결 포함)은 Step 2 에서.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """간단한 liveness probe — 앱이 booting 됐는지만 확인."""
    return HealthResponse(
        status="ok",
        service="calvin-rag-chatbot-api",
        version="0.1.0",
    )
