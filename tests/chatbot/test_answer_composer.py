"""HistoryAwareAnswerComposer 테스트 — retrieval 우선 + META/SMALLTALK LLM 호출 격리."""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from chatbot.domain.conversation import Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult
from chatbot.infrastructure.answer_composer import (
    HistoryAwareAnswerComposer,
    _format_history_for_recap,
    _from_retrieval,
)


def _last_turn(*, answer: str = "이전답변", strategy: str | None = "hybrid") -> Turn:
    return Turn(
        user_message=Message(role="user", content="이전질문"),
        intent=Intent.NEW_QUESTION,
        selected_strategy=strategy,
        answer=Message(role="assistant", content=answer),
        trace_id="t",
        elapsed_ms=1,
        started_at=datetime.now(UTC),
    )


# ============================================================
# retrieval 우선 — LLM 미호출
# ============================================================
def test_retrieval_있으면_metadata_answer_그대로():
    llm = FakeListChatModel(responses=["should_not_be_called"])
    composer = HistoryAwareAnswerComposer(llm=llm)
    result = composer.compose(
        intent=Intent.NEW_QUESTION,
        user_message=Message(role="user", content="?"),
        history=(),
        last_turn=None,
        retrieval_result=RetrievalResult(
            documents=(), citations=(), metadata={"answer": "예정론은..."}
        ),
    )
    assert result.content == "예정론은..."
    assert llm.i == 0  # LLM 미호출


def test_retrieval_metadata_answer_없음_fallback():
    llm = FakeListChatModel(responses=["unused"])
    composer = HistoryAwareAnswerComposer(llm=llm)
    result = composer.compose(
        intent=Intent.NEW_QUESTION,
        user_message=Message(role="user", content="?"),
        history=(),
        last_turn=None,
        retrieval_result=RetrievalResult(documents=(), citations=(), metadata={}),
    )
    assert "죄송" in result.content


# ============================================================
# META_RECAP — LLM 호출
# ============================================================
def test_meta_recap_LLM_호출_history_주입():
    composer = HistoryAwareAnswerComposer(llm=FakeListChatModel(responses=["요약된 답변"]))
    history = (
        Message(role="user", content="예정론?"),
        Message(role="assistant", content="예정론은..."),
    )
    result = composer.compose(
        intent=Intent.META_RECAP,
        user_message=Message(role="user", content="요약"),
        history=history,
        last_turn=None,
        retrieval_result=None,
    )
    assert result.content == "요약된 답변"


def test_meta_recap_LLM_실패시_fallback():
    class _BadLLM:
        def __or__(self, other):
            raise RuntimeError("simulated")

    composer = HistoryAwareAnswerComposer(llm=_BadLLM())  # type: ignore[arg-type]
    result = composer.compose(
        intent=Intent.META_RECAP,
        user_message=Message(role="user", content="요약"),
        history=(),
        last_turn=None,
        retrieval_result=None,
    )
    assert "이전 대화" in result.content


# ============================================================
# META_REFERENCE
# ============================================================
def test_meta_reference_last_turn_없음_안내():
    composer = HistoryAwareAnswerComposer(llm=FakeListChatModel(responses=["unused"]))
    result = composer.compose(
        intent=Intent.META_REFERENCE,
        user_message=Message(role="user", content="?"),
        history=(),
        last_turn=None,
        retrieval_result=None,
    )
    assert "이전 답변이 없" in result.content


def test_meta_reference_LLM_호출():
    composer = HistoryAwareAnswerComposer(llm=FakeListChatModel(responses=["메타 재안내"]))
    result = composer.compose(
        intent=Intent.META_REFERENCE,
        user_message=Message(role="user", content="?"),
        history=(),
        last_turn=_last_turn(answer="이전 그래프 설명"),
        retrieval_result=None,
    )
    assert result.content == "메타 재안내"


# ============================================================
# SMALLTALK
# ============================================================
def test_smalltalk_LLM_호출():
    composer = HistoryAwareAnswerComposer(llm=FakeListChatModel(responses=["반갑습니다"]))
    result = composer.compose(
        intent=Intent.SMALLTALK,
        user_message=Message(role="user", content="안녕"),
        history=(),
        last_turn=None,
        retrieval_result=None,
    )
    assert result.content == "반갑습니다"


# ============================================================
# 헬퍼 함수
# ============================================================
def test_format_history_for_recap_프리픽스():
    text = _format_history_for_recap(
        (Message(role="user", content="Q1"), Message(role="assistant", content="A1"))
    )
    assert "사용자: Q1" in text
    assert "챗봇: A1" in text


def test_format_history_for_recap_빈():
    assert _format_history_for_recap(()) == "(이전 대화 없음)"


def test_format_history_for_recap_최근_8개():
    many = tuple(
        Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(12)
    )
    text = _format_history_for_recap(many)
    assert "m0" not in text
    assert "m11" in text


def test_from_retrieval_헬퍼():
    result = _from_retrieval(RetrievalResult(documents=(), citations=(), metadata={"answer": "x"}))
    assert result.content == "x"
