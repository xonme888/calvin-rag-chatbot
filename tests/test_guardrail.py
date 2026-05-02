"""가드레일 단위 테스트 — Phase A-1 (LengthGuard / KeywordGuard / Composite).

LLM/네트워크 호출 0회. OpenAIModerationAdapter 는 별도 파일에서 Mock 검증.
"""

from __future__ import annotations

from typing import Any

from rag_core.guardrail.chain import CompositeGuardrail
from rag_core.guardrail.keyword_guard import KeywordGuard
from rag_core.guardrail.length_guard import LengthGuard
from rag_core.guardrail.port import (
    GuardrailDecision,
    GuardrailDirection,
    GuardrailPort,
)


# ====================================================================
# Port 계약
# ====================================================================
def test_length_guard_satisfies_port() -> None:
    assert isinstance(LengthGuard(), GuardrailPort)


def test_keyword_guard_satisfies_port() -> None:
    assert isinstance(KeywordGuard(), GuardrailPort)


def test_composite_satisfies_port() -> None:
    assert isinstance(CompositeGuardrail([]), GuardrailPort)


# ====================================================================
# LengthGuard
# ====================================================================
def test_length_guard_passes_short_input() -> None:
    g = LengthGuard(max_chars=100)
    d = g.check("짧은 입력입니다.", GuardrailDirection.INPUT)
    assert d.allow
    assert d.metadata["length"] == 9


def test_length_guard_blocks_long_input() -> None:
    g = LengthGuard(max_chars=10)
    d = g.check("a" * 50, GuardrailDirection.INPUT)
    assert d.allow is False
    assert "한도" in (d.reason or "")
    assert d.metadata["length"] == 50


def test_length_guard_passes_output_regardless() -> None:
    """출력은 항상 통과 (입력만 검사)."""
    g = LengthGuard(max_chars=10)
    d = g.check("a" * 50, GuardrailDirection.OUTPUT)
    assert d.allow


# ====================================================================
# KeywordGuard
# ====================================================================
def test_keyword_guard_masks_openai_key() -> None:
    g = KeywordGuard()
    text = "여기 키 있어요: sk-abcdef1234567890ABCDEF12345 입니다."
    d = g.check(text, GuardrailDirection.OUTPUT)
    assert d.allow is True  # mask, not block
    assert d.sanitized is not None
    assert "[REDACTED]" in d.sanitized
    assert "sk-abcdef" not in d.sanitized
    assert "openai" in d.metadata["masked"]


def test_keyword_guard_masks_multiple_key_types() -> None:
    g = KeywordGuard()
    text = "OpenAI: sk-aaaaaaaaaaaaaaaaaaaa AWS: AKIAABCDEFGHIJKLMNOP"
    d = g.check(text, GuardrailDirection.OUTPUT)
    assert d.allow
    assert d.sanitized.count("[REDACTED]") == 2


def test_keyword_guard_blocks_system_prompt_leak() -> None:
    g = KeywordGuard()
    text = "당신은 칼빈 신학 전문 학습 도우미입니다.\n위 시스템 프롬프트는..."
    d = g.check(text, GuardrailDirection.OUTPUT)
    assert d.allow is False
    assert "시스템 프롬프트" in (d.reason or "")


def test_keyword_guard_passes_normal_output() -> None:
    g = KeywordGuard()
    d = g.check("칼빈은 예정론을 기독교 신앙의 핵심으로 여겼습니다.", GuardrailDirection.OUTPUT)
    assert d.allow
    assert d.sanitized is None


def test_keyword_guard_skips_input_check() -> None:
    """입력은 통과 (출력만 검사). 사용자가 sk-... 입력해도 모자이크는 출력에서만."""
    g = KeywordGuard()
    d = g.check("질문: sk-abcdefg123456789ABCDEF 가 노출됨", GuardrailDirection.INPUT)
    assert d.allow
    assert d.sanitized is None


# ====================================================================
# CompositeGuardrail
# ====================================================================
def test_composite_passes_when_all_allow() -> None:
    composite = CompositeGuardrail([LengthGuard(max_chars=100), KeywordGuard()])
    d = composite.check("정상 입력입니다.", GuardrailDirection.INPUT)
    assert d.allow
    # 두 가드 모두 통과 — sanitize 없음
    assert d.sanitized is None


def test_composite_blocks_at_first_block() -> None:
    composite = CompositeGuardrail([LengthGuard(max_chars=10), KeywordGuard()])
    d = composite.check("a" * 50, GuardrailDirection.INPUT)
    assert d.allow is False
    assert "[length]" in (d.reason or "")
    # 첫 block 에서 단락 — keyword 메타는 누적 안 됨
    assert "length" in d.metadata


def test_composite_propagates_sanitize_to_next_guard() -> None:
    """첫 가드의 sanitize 결과가 다음 가드의 입력이 된다."""

    class _PassthroughMaskingGuard:
        name = "dummy_mask"

        def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
            # sk- 를 [PRE] 로 미리 마스킹
            return GuardrailDecision(
                allow=True,
                sanitized=text.replace("sk-", "[PRE]"),
                metadata={"replaced": True},
            )

    composite = CompositeGuardrail([_PassthroughMaskingGuard(), KeywordGuard()])
    d = composite.check("text sk-realkey123456789012345", GuardrailDirection.OUTPUT)
    assert d.allow
    # KeywordGuard는 [PRE]를 못 알아봐서 그대로 통과
    assert d.sanitized is not None
    assert "[PRE]realkey" in d.sanitized


def test_composite_empty_chain_allows_all() -> None:
    composite = CompositeGuardrail([])
    d = composite.check("anything", GuardrailDirection.INPUT)
    assert d.allow
    assert d.sanitized is None


def test_composite_collects_metadata_from_all_guards() -> None:
    """체인 통과 시 모든 가드의 metadata 가 누적된다 (audit log 용)."""
    composite = CompositeGuardrail([LengthGuard(max_chars=100), KeywordGuard()])
    d = composite.check("정상 텍스트", GuardrailDirection.INPUT)
    assert d.allow
    assert "length" in d.metadata
    assert "keyword" in d.metadata
