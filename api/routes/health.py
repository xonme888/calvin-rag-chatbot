"""헬스 + 모드 가용성 라우트."""

from __future__ import annotations

from fastapi import APIRouter

# dependencies import 부수효과 — mode_registry 에 모드 등록을 트리거
import api.dependencies  # noqa: F401
from api.schemas import HealthResponse, ModeInfo, ModesResponse
from rag_core.mode_registry import all_entries

router = APIRouter(tags=["meta"])


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
    """사용 가능 모드 목록 — registry 순회.

    새 모드 추가 = ``rag_core/mode_registry.register(...)`` 한 번. 이 라우트는 무수정.
    """
    out: list[ModeInfo] = []
    for entry in all_entries():
        available, reason = entry.health()
        out.append(
            ModeInfo(
                name=entry.name,
                label=entry.label,
                available=available,
                reason=reason,
            )
        )
    return ModesResponse(modes=out)
