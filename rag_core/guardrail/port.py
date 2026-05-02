"""가드레일 추상화 — Port + Decision + Direction.

Hexagonal: 도메인이 가드 백엔드에 의존하지 않음. 어댑터(OpenAI Moderation,
Kanana Safeguard, Lakera 등)는 같은 Port를 구현해 swap 가능.

설계 원칙:
- 입력/출력 같은 인터페이스 (`direction` 파라미터로 분기)
- ``GuardrailDecision``: allow / reason / sanitized / metadata
  - sanitized: 차단 대신 마스킹 (예: API key → [REDACTED]). 다음 가드에 전달
  - metadata: audit log/디버깅 (가드별 점수, 매치 패턴 등)
- 가드 실패는 fail-open 권장 (외부 의존 가드가 다운돼도 서비스 죽이지 않게)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class GuardrailDirection(Enum):
    """가드 방향 — 입력 검증 vs 출력 검증."""

    INPUT = "input"
    OUTPUT = "output"


@dataclass
class GuardrailDecision:
    """단일 가드의 판정 결과."""

    allow: bool
    reason: str | None = None
    sanitized: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailPort(Protocol):
    """가드 인터페이스. 입력/출력 모두 동일 메서드."""

    name: str

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        """텍스트를 검증하고 판정 반환.

        Args:
            text: 검증 대상 (입력 prompt 또는 LLM 출력)
            direction: 입력/출력 구분 — 가드가 한쪽만 의미 있을 때 분기

        Returns:
            ``GuardrailDecision`` — allow=False면 즉시 차단,
            sanitized가 있으면 다음 가드에 전달.
        """
        ...
