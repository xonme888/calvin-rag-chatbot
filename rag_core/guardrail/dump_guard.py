"""저작권 보호 — 본문 전체/한 장 전체 출력 요청 차단.

사용자가 책 본문을 통째로 받아내려는 시도를 입력 단계에서 거절.
좁은 키워드 매칭 — 정상 학습 질문은 통과.
"""

from __future__ import annotations

import re

from rag_core.guardrail.port import GuardrailDecision, GuardrailDirection

# "전문/전체/모든 본문" 류 — 책 dump 시도
_DUMP_REQUEST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(전문|전체|모든)\s*(본문|텍스트|내용|chapter|장)\s*(보여|출력|알려|줘|주세요|달라)"),
    re.compile(r"(\d+권|\d+장)\s*(전체|전문|모두|다)\s*(보여|출력|알려|줘)"),
    re.compile(r"(책\s*)?처음부터\s*끝까지"),
    re.compile(r"전체\s*(목차|텍스트|구절)\s*(나열|열거|출력)"),
    re.compile(r"(verbatim|word[- ]for[- ]word|literal text)", re.IGNORECASE),
]

_BLOCK_MESSAGE = (
    "저작권상 본문 전체/장 전체 출력은 어렵습니다. "
    "구체적 주제·인물·교리를 묻거나 핵심 요약을 요청해 주세요."
)


class DumpGuard:
    """입력 단계 — 본문 dump 요청 차단."""

    name = "dump_request"

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        if direction != GuardrailDirection.INPUT:
            return GuardrailDecision(allow=True)

        for pattern in _DUMP_REQUEST_PATTERNS:
            if pattern.search(text):
                return GuardrailDecision(
                    allow=False,
                    reason=_BLOCK_MESSAGE,
                    metadata={"matched": "dump_request"},
                )
        return GuardrailDecision(allow=True)
