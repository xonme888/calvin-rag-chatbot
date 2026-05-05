"""Token budget cap — 사용자/IP 별 토큰 한도 초과 시 차단.

설계:
- 1차 (전역 누적, 기존): SessionStats 기반 — 비용 폭주 마지막 방어선
- 2차 (사용자/IP, PRD-4): infra.budget — role 별 한도, Redis backed 가능

인증 전 단계에선 ip 기반 키, 인증 후엔 user_id 키 사용.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from infra.budget import budget_key, check_budget
from infra.usage_tracker import SessionStats


def _global_cap() -> int:
    """환경변수 ``DAILY_TOKEN_CAP`` (기본 1,000,000 토큰 = ~₩300)."""
    return int(os.getenv("DAILY_TOKEN_CAP", "1000000"))


def check_token_budget(stats: SessionStats) -> None:
    """전역 누적 토큰 cap — 마지막 안전망.

    Raises:
        HTTPException: 429 Too Many Requests
    """
    used = stats.total_input_tokens + stats.total_output_tokens
    cap = _global_cap()
    if used >= cap:
        raise HTTPException(
            status_code=429,
            detail=(
                f"일일 전역 토큰 한도 초과: {used:,} / {cap:,}. "
                "시간이 지나거나 환경변수 DAILY_TOKEN_CAP 조정 필요."
            ),
        )


def check_user_budget(user_id: str | None, ip: str, role: str = "free") -> None:
    """사용자/IP 별 일일 한도 체크. 초과 시 429.

    인증 전: user_id=None → ip 기반 키.
    인증 후 (PRD-2): user_id 키 + role 별 한도.
    """
    key = budget_key(user_id, ip)
    allowed, usage, cap = check_budget(key, role)
    if not allowed:
        used = usage.tokens if usage else 0
        raise HTTPException(
            status_code=429,
            detail=(
                f"일일 사용자 토큰 한도 초과: {used:,} / {cap:,} ({role}). "
                "한도 상향은 plan 업그레이드 또는 관리자 문의."
            ),
        )
