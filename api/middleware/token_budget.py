"""Token budget cap — 누적 토큰 한도 초과 시 차단.

`SessionStats.total_input_tokens + total_output_tokens` 가 환경변수 한도를 초과하면
HTTP 429 로 차단. 비용 폭주(LLM04) 방어.

운영 환경에선 일일 한도 + 사용자별 한도 두 단계 (사용자별은 인증 필수).
시연/단일 프로세스에선 전역 누적만 체크.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from infra.usage_tracker import SessionStats


def _budget_cap() -> int:
    """환경변수 ``DAILY_TOKEN_CAP`` (기본 1,000,000 토큰 = ~₩300)."""
    return int(os.getenv("DAILY_TOKEN_CAP", "1000000"))


def check_token_budget(stats: SessionStats) -> None:
    """누적 토큰이 cap 초과 시 ``HTTPException(429)``.

    Raises:
        HTTPException: 429 Too Many Requests + 잔여 budget 정보
    """
    used = stats.total_input_tokens + stats.total_output_tokens
    cap = _budget_cap()
    if used >= cap:
        raise HTTPException(
            status_code=429,
            detail=(
                f"일일 토큰 한도 초과: {used:,} / {cap:,}. "
                "시간이 지나거나 환경변수 DAILY_TOKEN_CAP 조정 필요."
            ),
        )
