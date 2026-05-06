"""LLMQueryRewriter 테스트 — _format_history + 예외 fallback."""

from __future__ import annotations

from chatbot.domain.conversation import Message
from chatbot.infrastructure.rewriter_llm import LLMQueryRewriter, _format_history


def test_format_history_user_assistant_프리픽스():
    hist = (
        Message(role="user", content="예정론?"),
        Message(role="assistant", content="예정론은..."),
    )
    text = _format_history(hist)
    assert "사용자: 예정론?" in text
    assert "챗봇: 예정론은..." in text


def test_format_history_빈_안내():
    assert _format_history(()) == "(이전 대화 없음)"


def test_format_history_최근_6개_컷():
    """6개 초과 시 최근 6개만 남는다."""
    many = tuple(
        Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(10)
    )
    text = _format_history(many)
    assert "m0" not in text  # 잘린다
    assert "m9" in text


def test_rewriter_예외_시_원문_fallback():
    """LLM 호환 오류 시 원문 그대로 반환 — 라우팅 동작 중단 X."""

    class _BadLLM:
        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            raise RuntimeError("not supported")

    rewriter = LLMQueryRewriter(llm=_BadLLM())  # type: ignore[arg-type]
    result = rewriter.rewrite(message=Message(role="user", content="그러면?"), history=())
    assert result == "그러면?"


# 정상 LLM 호출 회귀는 PR 4 Phase 2 의 E2E 테스트가 별도로 다룸 — 본 모듈은 *fallback 보장* 만.
