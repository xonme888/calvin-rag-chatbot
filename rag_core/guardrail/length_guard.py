"""입력 길이 제한 가드.

토큰 폭주(LLM04 Unbounded Consumption) 1차 방어선.
2000자가 한국어 기준 ~1500 토큰. RAG 컨텍스트와 합쳐 ~5000 토큰 이내로 제한.
"""

from __future__ import annotations

from rag_core.guardrail.port import GuardrailDecision, GuardrailDirection


class LengthGuard:
    """입력 길이 제한. ``direction == INPUT`` 일 때만 검사."""

    name = "length"

    def __init__(self, max_chars: int = 2000) -> None:
        self.max_chars = max_chars

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        if direction != GuardrailDirection.INPUT:
            return GuardrailDecision(allow=True)
        if len(text) > self.max_chars:
            return GuardrailDecision(
                allow=False,
                reason=(
                    f"입력 길이 {len(text):,}자가 한도({self.max_chars:,}자)를 초과합니다. "
                    "더 짧게 작성해 주세요."
                ),
                metadata={"length": len(text), "max_chars": self.max_chars},
            )
        return GuardrailDecision(allow=True, metadata={"length": len(text)})
