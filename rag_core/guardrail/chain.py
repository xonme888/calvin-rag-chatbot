"""다중 가드 체인.

규칙:
- 첫 block 에서 단락 (이후 가드 호출 안 함)
- sanitize 결과는 다음 가드의 입력으로 전달 (누적 마스킹 가능)
- 모든 가드의 metadata 를 누적 (audit log 용)
"""

from __future__ import annotations

from typing import Any

from rag_core.guardrail.port import GuardrailDecision, GuardrailDirection, GuardrailPort


class CompositeGuardrail:
    """가드 체인 — 첫 block 에서 단락, sanitize 는 누적 전달."""

    name = "composite"

    def __init__(self, guards: list[GuardrailPort]) -> None:
        self.guards = guards

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        sanitized_text = text
        accumulated: dict[str, Any] = {}
        sanitize_log: list[str] = []

        for guard in self.guards:
            decision = guard.check(sanitized_text, direction)
            accumulated[guard.name] = decision.metadata

            if not decision.allow:
                return GuardrailDecision(
                    allow=False,
                    reason=f"[{guard.name}] {decision.reason or '차단'}",
                    metadata=accumulated,
                )

            if decision.sanitized is not None:
                sanitized_text = decision.sanitized
                if decision.reason:
                    sanitize_log.append(f"[{guard.name}] {decision.reason}")

        # 체인 통과 — 누적 sanitize 가 있으면 결과로 반환
        sanitized_final = sanitized_text if sanitized_text != text else None
        return GuardrailDecision(
            allow=True,
            sanitized=sanitized_final,
            reason=" | ".join(sanitize_log) if sanitize_log else None,
            metadata=accumulated,
        )
