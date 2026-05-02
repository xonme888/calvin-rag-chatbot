"""사용 통계 라우트 — `/stats` (누적 토큰/비용/모드별)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from api.dependencies import get_session_stats
from api.schemas import StatsResponse

router = APIRouter(tags=["meta"])


@router.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    """프로세스 누적 LLM 사용 통계.

    `usage_tracker.SessionStats` 를 그대로 직렬화. 다중 워커 운영 단계에선
    외부 스토어(Redis 등)로 이전 필요 (Phase 3).
    """
    s = get_session_stats()
    return StatsResponse(
        total_calls=s.total_calls,
        total_input_tokens=s.total_input_tokens,
        total_output_tokens=s.total_output_tokens,
        total_cost_usd=round(s.total_cost_usd, 6),
        total_cost_krw=round(s.total_cost_krw, 2),
        by_mode={mode: asdict(ms) for mode, ms in s.by_mode.items()},
    )
