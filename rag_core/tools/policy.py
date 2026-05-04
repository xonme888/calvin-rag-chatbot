"""도구별 정책 메타데이터 — 시니어 리뷰 (§5 즉시 보강) 권장.

각 도구는 다음을 선언:
- timeout_seconds: 도구 1회 호출의 최대 대기 시간 (외부 API 행 차단)
- per_call_token_cap: 도구 1회 호출이 LLM 컨텍스트에 추가하는 토큰 한도
- required_role: 도구를 사용할 수 있는 사용자 role (free/paid/admin)
- description_safe: 도구 description 이 prompt injection 무방어 영역에 사용되는지

설계:
- agentic 의 create_agent 호출 직전, allowlist + role 통과 후 도구만 노출
- timeout 위반 → circuit_breaker 가 흡수
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    """단일 도구의 운영 정책."""

    name: str
    timeout_seconds: float = 10.0
    per_call_token_cap: int = 4000
    required_role: str = "free"  # free / paid / admin
    description_safe: bool = True
    """description 이 사용자에게 안전한가 (외부 MCP description 은 sanitize 필요)."""


# role 우선순위 — 높을수록 더 많은 도구 사용 가능
_ROLE_RANK = {"free": 0, "paid": 1, "admin": 2}


def role_meets(user_role: str, required: str) -> bool:
    return _ROLE_RANK.get(user_role, 0) >= _ROLE_RANK.get(required, 0)
