"""헬스 + 모드 가용성 라우트.

엔드포인트:
- /health      — backwards compat: /health/live alias
- /health/live — liveness (앱 부팅만, 무조건 200)
- /health/ready — readiness (의존성 ping 결과 포함)
- /modes       — RAG 모드 목록 (registry)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

# dependencies import 부수효과 — mode_registry 에 모드 등록을 트리거
import api.dependencies  # noqa: F401
from api.schemas import HealthResponse, ModeInfo, ModesResponse
from infra.health_probes import overall_status, run_all_probes
from rag_core.mode_registry import all_entries

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness — 앱 부팅만 확인. /health/live 와 동일."""
    return HealthResponse(
        status="ok",
        service="calvin-rag-chatbot-api",
        version="0.1.0",
    )


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """K8s liveness probe — 앱이 죽었는지만 본다."""
    return HealthResponse(
        status="ok",
        service="calvin-rag-chatbot-api",
        version="0.1.0",
    )


@router.get("/health/ready")
async def readiness() -> dict[str, Any]:
    """K8s readiness probe — 의존성별 ping.

    - ok: 모든 의존성 정상
    - degraded: 일부 의존성 실패 (200 반환 — 서비스 부분 가용)
    - failed: 모든 의존성 실패 (503 반환 — LB 가 트래픽 차단)
    """
    probes = run_all_probes()
    status = overall_status(probes)
    body = {
        "status": status,
        "service": "calvin-rag-chatbot-api",
        "version": "0.1.0",
        "dependencies": [p.to_dict() for p in probes],
    }
    if status == "failed":
        raise HTTPException(status_code=503, detail=body)
    return body


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
