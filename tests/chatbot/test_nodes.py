"""5개 노드의 단독 테스트 — Fake 의존성으로 LLM 호출 0.

각 노드는 ``state -> state`` 의 거의 순수 함수 — 입력 state + 의존성 → 출력 state 만 검증.
LangGraph 와이어링은 PR 3.5 에서 별도.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chatbot.application.nodes import (
    classify_intent,
    compose_answer,
    invoke_strategy,
    rewrite_question,
    select_strategy,
)
from chatbot.application.registries import InMemoryStrategyRegistry
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult
from chatbot.domain.state import ConversationState


# ============================================================
# State 빌더
# ============================================================
def _state(*, message="예정론?", turns=(), started_ms=1000) -> ConversationState:
    user = Message(role="user", content=message)
    conv = Conversation(id="c1", turns=tuple(turns), created_at=datetime.now(UTC))
    return ConversationState(
        conversation=conv,
        pending_user_message=user,
        trace_id="t1",
        started_at_ms=started_ms,
    )


def _turn(*, intent: Intent = Intent.NEW_QUESTION, q="이전질문", a="이전답변") -> Turn:
    return Turn(
        user_message=Message(role="user", content=q),
        intent=intent,
        answer=Message(role="assistant", content=a),
        trace_id="t",
        elapsed_ms=1,
        started_at=datetime.now(UTC),
    )


# ============================================================
# Fake 의존성
# ============================================================
class _FakeClassifier:
    def __init__(self, intent: Intent) -> None:
        self.intent = intent
        self.calls: list = []

    def classify(self, *, message: Message, last_turn: Turn | None) -> Intent:
        self.calls.append((message, last_turn))
        return self.intent


class _FakeRewriter:
    def __init__(self, prefix: str = "재작성:") -> None:
        self.prefix = prefix
        self.calls: list = []

    def rewrite(self, *, message: Message, history) -> str:  # type: ignore[no-untyped-def]
        self.calls.append((message, history))
        return f"{self.prefix}{message.content}"


class _FakeRouter:
    def __init__(self, choice_idx: int | None = 0) -> None:
        self.choice_idx = choice_idx
        self.calls: list = []

    def choose(self, *, candidates, standalone_question, last_turn):  # type: ignore[no-untyped-def]
        self.calls.append((candidates, standalone_question, last_turn))
        if self.choice_idx is None:
            return None
        return candidates[self.choice_idx]


class _FakeStrategy:
    def __init__(
        self, name: str = "fake", *, available: bool = True, supports_v: bool = True
    ) -> None:
        self.name = name
        self.label = name.title()
        self._available = available
        self._supports = supports_v
        self.runs: list[RetrievalRequest] = []

    def is_available(self) -> tuple[bool, str | None]:
        return (self._available, None)

    def supports(self, request: RetrievalRequest) -> bool:
        return self._supports

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        self.runs.append(request)
        return RetrievalResult(
            documents=(), citations=(), metadata={"answer": f"answer:{request.standalone_question}"}
        )


class _FakeAnswerer:
    def compose(
        self, *, intent: Intent, user_message: Message, history, last_turn, retrieval_result
    ) -> Message:
        text = retrieval_result.metadata["answer"] if retrieval_result else f"meta:{intent.value}"
        return Message(role="assistant", content=text)


# ============================================================
# classify_intent
# ============================================================
def test_classify_intent_pending_intent_채움():
    state = _state()
    out = classify_intent(state, classifier=_FakeClassifier(Intent.NEW_QUESTION))
    assert out.pending_intent == Intent.NEW_QUESTION


def test_classify_intent_last_turn_전달():
    classifier = _FakeClassifier(Intent.FOLLOWUP)
    state = _state(turns=(_turn(),))
    classify_intent(state, classifier=classifier)
    assert classifier.calls[0][1] is not None


def test_classify_intent_빈_history_None_last_turn():
    classifier = _FakeClassifier(Intent.NEW_QUESTION)
    classify_intent(_state(), classifier=classifier)
    assert classifier.calls[0][1] is None


# ============================================================
# rewrite_question
# ============================================================
def test_rewrite_followup_LLM_호출():
    rewriter = _FakeRewriter()
    state = _state(message="그러면?")
    state = state.model_copy(update={"pending_intent": Intent.FOLLOWUP})
    out = rewrite_question(state, rewriter=rewriter)
    assert out.pending_standalone == "재작성:그러면?"
    assert len(rewriter.calls) == 1


def test_rewrite_NEW_QUESTION_passthrough():
    rewriter = _FakeRewriter()
    state = _state(message="예정론은 무엇인가?")
    state = state.model_copy(update={"pending_intent": Intent.NEW_QUESTION})
    out = rewrite_question(state, rewriter=rewriter)
    assert out.pending_standalone == "예정론은 무엇인가?"
    assert rewriter.calls == []


def test_rewrite_META_RECAP_passthrough():
    state = _state(message="위 내용 요약").model_copy(update={"pending_intent": Intent.META_RECAP})
    out = rewrite_question(state, rewriter=_FakeRewriter())
    assert out.pending_standalone == "위 내용 요약"


# ============================================================
# select_strategy
# ============================================================
def test_select_supports_통과_후보_라우터에_전달():
    reg = InMemoryStrategyRegistry()
    reg.register(_FakeStrategy("hybrid"))
    reg.register(_FakeStrategy("kg"))
    router = _FakeRouter(choice_idx=1)
    state = _state(message="관계?").model_copy(
        update={"pending_intent": Intent.NEW_QUESTION, "pending_standalone": "관계?"}
    )
    out = select_strategy(state, registry=reg, router=router)
    assert out.pending_strategy == "kg"


def test_select_후보_0개_None():
    reg = InMemoryStrategyRegistry()
    reg.register(_FakeStrategy("hybrid", supports_v=False))
    router = _FakeRouter()
    state = _state().model_copy(update={"pending_intent": Intent.NEW_QUESTION})
    out = select_strategy(state, registry=reg, router=router)
    assert out.pending_strategy is None
    assert router.calls == []  # 호출되지 않음


def test_select_router_None_반환():
    reg = InMemoryStrategyRegistry()
    reg.register(_FakeStrategy("hybrid"))
    router = _FakeRouter(choice_idx=None)
    state = _state().model_copy(update={"pending_intent": Intent.NEW_QUESTION})
    out = select_strategy(state, registry=reg, router=router)
    assert out.pending_strategy is None


# ============================================================
# invoke_strategy
# ============================================================
def test_invoke_정상():
    reg = InMemoryStrategyRegistry()
    fake = _FakeStrategy("hybrid")
    reg.register(fake)
    state = _state(message="예정론?").model_copy(
        update={
            "pending_intent": Intent.NEW_QUESTION,
            "pending_standalone": "예정론?",
            "pending_strategy": "hybrid",
        }
    )
    out = invoke_strategy(state, registry=reg)
    assert out.pending_retrieval is not None
    assert out.pending_retrieval.metadata["answer"] == "answer:예정론?"
    assert len(fake.runs) == 1


def test_invoke_strategy_None_passthrough():
    reg = InMemoryStrategyRegistry()
    state = _state().model_copy(update={"pending_strategy": None})
    out = invoke_strategy(state, registry=reg)
    assert out.pending_retrieval is None


def test_invoke_chat_history_전달():
    reg = InMemoryStrategyRegistry()
    fake = _FakeStrategy("hybrid")
    reg.register(fake)
    turns = (_turn(q="첫번째", a="첫답변"),)
    state = _state(turns=turns).model_copy(
        update={"pending_strategy": "hybrid", "pending_standalone": "x"}
    )
    invoke_strategy(state, registry=reg)
    assert len(fake.runs[0].chat_history) == 2  # user + assistant 1세트


# ============================================================
# compose_answer
# ============================================================
def test_compose_정상_Turn_append():
    state = _state(message="예정론?").model_copy(
        update={
            "pending_intent": Intent.NEW_QUESTION,
            "pending_strategy": "hybrid",
            "pending_retrieval": RetrievalResult(
                documents=(), citations=(), metadata={"answer": "예정론은..."}
            ),
        }
    )
    out = compose_answer(state, answerer=_FakeAnswerer())
    assert len(out.conversation.turns) == 1
    assert out.conversation.turns[0].answer.content == "예정론은..."
    assert out.pending_answer is not None


def test_compose_META_RECAP_retrieval_없음():
    state = _state(message="요약").model_copy(update={"pending_intent": Intent.META_RECAP})
    out = compose_answer(state, answerer=_FakeAnswerer())
    assert out.conversation.turns[0].answer.content == "meta:meta_recap"


def test_compose_intent_None_RuntimeError():
    state = _state()
    with pytest.raises(RuntimeError):
        compose_answer(state, answerer=_FakeAnswerer())


def test_compose_누적_turn():
    """이미 turn 1개 있는 state 에 새 Turn 추가."""
    state = _state(turns=(_turn(),)).model_copy(update={"pending_intent": Intent.NEW_QUESTION})
    out = compose_answer(state, answerer=_FakeAnswerer())
    assert len(out.conversation.turns) == 2
