"""generate_followups 단위 테스트 — FakeListLLM 으로 외부 호출 차단."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from rag_core.followup import generate_followups


class _FakeStructuredLLM(BaseChatModel):
    """with_structured_output 만 지원하는 최소 가짜 LLM (Runnable pipe 호환)."""

    response_questions: list[str] = []
    raise_on_call: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake-structured"

    def _generate(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
        return AIMessage(content="")

    def with_structured_output(self, schema: Any, **_kwargs: Any) -> Any:
        outer = self

        def _run(_inputs: dict[str, Any]) -> Any:
            if outer.raise_on_call:
                raise RuntimeError("LLM 일시 장애")
            return schema(questions=list(outer.response_questions))

        return RunnableLambda(_run)


def test_빈_답변이면_곧바로_빈_리스트():
    # Given — answer 가 공백
    llm = _FakeStructuredLLM(response_questions=["a", "b", "c"])

    # When
    result = generate_followups("질문", "   ", llm)

    # Then — LLM 호출 없이 빈 리스트
    assert result == []


def test_정상_3개_생성():
    # Given
    llm = _FakeStructuredLLM(
        response_questions=[
            "예정론과 어거스틴의 관계는?",
            "칼빈은 자유의지를 어떻게 보았는가?",
            "이중예정론의 근거 본문은?",
        ]
    )

    # When
    result = generate_followups("예정론이란?", "예정론은 ...", llm)

    # Then
    assert len(result) == 3
    assert all(isinstance(q, str) and q for q in result)


def test_max_count_초과시_상위만_반환():
    # Given — LLM 이 5개 반환해도
    llm = _FakeStructuredLLM(response_questions=["q1", "q2", "q3", "q4", "q5"])

    # When
    result = generate_followups("Q", "A", llm, max_count=3)

    # Then
    assert result == ["q1", "q2", "q3"]


def test_빈_문자열_및_공백_항목_필터링():
    # Given
    llm = _FakeStructuredLLM(response_questions=["q1", "  ", "", "q4"])

    # When
    result = generate_followups("Q", "A", llm)

    # Then — 공백/빈 항목 제거 후 max_count 까지
    assert result == ["q1", "q4"]


def test_LLM_장애시_빈_리스트_안전_폴백():
    # Given — LLM 호출이 실패하더라도
    llm = _FakeStructuredLLM(raise_on_call=True)

    # When
    result = generate_followups("Q", "A", llm)

    # Then — 예외 전파하지 않고 빈 리스트
    assert result == []
