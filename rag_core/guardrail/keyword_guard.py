"""정규식 기반 출력 가드.

좁고 정답이 명확한 영역만 자체 구현 (LLM 가드와 책임 분리):
- API key 패턴 노출 → 마스킹 (sanitize, allow=True)
- 시스템 프롬프트 marker 노출 → 차단 (allow=False)

산업 LLM 가드(Kanana/Moderation)와 다른 책임이라 ROI 높음 (FP 0, 비용 0).
"""

from __future__ import annotations

import re

from rag_core.guardrail.port import GuardrailDecision, GuardrailDirection

# API key 패턴 — 출력에 등장 시 마스킹
_API_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai", re.compile(r"sk-[a-zA-Z0-9_\-]{20,}")),
    ("aws_access", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("google", re.compile(r"\bAIza[a-zA-Z0-9_\-]{35}\b")),
    ("anthropic", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}")),
]

# 시스템 프롬프트 leak 의심 패턴 — 우리 시스템 프롬프트의 distinctive marker
# 정상 답변에는 거의 등장하지 않는 운영 문구로 한정 (FP 회피)
_SYSTEM_PROMPT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"## 답변 가이드"),
    re.compile(r"당신은 칼빈 신학 전문 학습 도우미입니다"),
    re.compile(r"본 챗봇은 칼빈 신학에 한정된 답변만 가능합니다"),
]


class KeywordGuard:
    """출력 정규식 가드 — API key 마스킹 + 시스템 프롬프트 leak 차단."""

    name = "keyword"

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        if direction != GuardrailDirection.OUTPUT:
            return GuardrailDecision(allow=True)

        # 1) 시스템 프롬프트 leak — 즉시 차단
        for pattern in _SYSTEM_PROMPT_PATTERNS:
            if pattern.search(text):
                return GuardrailDecision(
                    allow=False,
                    reason="시스템 프롬프트 노출 시도가 감지되어 답변을 차단했습니다.",
                    metadata={"matched": "system_prompt"},
                )

        # 2) API key 마스킹 — sanitize, allow=True
        sanitized = text
        masked: list[str] = []
        for label, pattern in _API_KEY_PATTERNS:
            if pattern.search(sanitized):
                sanitized = pattern.sub("[REDACTED]", sanitized)
                masked.append(label)

        if masked:
            return GuardrailDecision(
                allow=True,
                sanitized=sanitized,
                reason=f"API key 패턴 마스킹: {', '.join(masked)}",
                metadata={"masked": masked},
            )
        return GuardrailDecision(allow=True)
