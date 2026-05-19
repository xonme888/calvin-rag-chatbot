"""Orchestrator 통합 시나리오 테스트.

LangGraph 와이어링 + 노드 시퀀스 + 멀티턴 시나리오 (Hybrid → KG → META_RECAP 가로지름).
LLM 호출 0회 — 모든 의존성 Fake.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chatbot.application.orchestrator import build_orchestrator
from chatbot.application.registries import InMemoryStrategyRegistry
from chatbot.domain.conversation import Conversation, Message
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult, Subgraph
from chatbot.domain.state import ConversationState


# ============================================================
# Fake 의존성
# ============================================================
class _ScriptedClassifier:
    """미리 정의된 Intent 시퀀스를 순서대로 반환 — 멀티턴 시나리오용."""

    def __init__(self, intents: list[Intent]) -> None:
        self.intents = list(intents)
        self.calls = 0

    def classify(self, *, message, last_turn):  # type: ignore[no-untyped-def]
        if self.calls >= len(self.intents):
            raise AssertionError("Classifier 호출 횟수 초과")
        intent = self.intents[self.calls]
        self.calls += 1
        return intent


class _Rewriter:
    def rewrite(self, *, message, history):  # type: ignore[no-untyped-def]
        return f"재작성:{message.content}"


class _Router:
    def choose(
        self,
        *,
        candidates,
        standalone_question,
        last_turn,
        previous_mode=None,
    ):  # type: ignore[no-untyped-def]
        # 라벨 기반 수동 매칭 — 다중 후보 중 standalone_question 키워드로 결정
        kw_map = {"관계": "kg", "그래프": "kg", "이미지": "vision"}
        for kw, name in kw_map.items():
            if kw in standalone_question:
                for c in candidates:
                    if c.name == name:
                        return c
        return candidates[0] if candidates else None


class _Strategy:
    """Fake strategy — supports 조건 + run 결과 dictionary 형식."""

    def __init__(
        self,
        name: str,
        *,
        supports_attachments: bool = False,
        subgraph: Subgraph | None = None,
    ) -> None:
        self.name = name
        self.label = name.title()
        self._supports_attachments = supports_attachments
        self._subgraph = subgraph
        self.runs: list[RetrievalRequest] = []

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        if self._supports_attachments:
            return bool(request.attachments)
        return not request.attachments

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        self.runs.append(request)
        return RetrievalResult(
            documents=(),
            citations=(),
            subgraph=self._subgraph,
            metadata={"answer": f"{self.name}:{request.standalone_question}", "pattern": self.name},
        )


class _Answerer:
    """retrieval 있으면 metadata.answer, 없으면 history-aware 메시지."""

    def compose(self, *, intent, user_message, history, last_turn, retrieval_result):  # type: ignore[no-untyped-def]
        if retrieval_result is not None:
            return Message(role="assistant", content=retrieval_result.metadata["answer"])
        # META_RECAP — 직전 턴들의 답변을 합친 요약 시뮬레이션
        if intent == Intent.META_RECAP:
            previous_answers = [m.content for m in history if m.role == "assistant"]
            return Message(role="assistant", content="요약: " + " | ".join(previous_answers))
        # META_REFERENCE — last_turn.subgraph 재사용 시뮬레이션
        if intent == Intent.META_REFERENCE:
            note = "그래프 재사용" if last_turn and last_turn.standalone_question else "이전 없음"
            return Message(role="assistant", content=f"메타-참조: {note}")
        return Message(role="assistant", content=f"smalltalk:{user_message.content}")


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def registry() -> InMemoryStrategyRegistry:
    reg = InMemoryStrategyRegistry()
    reg.register(_Strategy("hybrid"))
    reg.register(
        _Strategy(
            "kg",
            subgraph=Subgraph(nodes=(), edges=(), metadata={"source": "test"}),
        )
    )
    reg.register(_Strategy("vision", supports_attachments=True))
    return reg


def _make_state(*, conversation: Conversation, message: str) -> ConversationState:
    return ConversationState(
        conversation=conversation,
        pending_user_message=Message(role="user", content=message),
        trace_id="t",
        started_at_ms=0,
    )


def _empty_conversation() -> Conversation:
    return Conversation(id="c1", created_at=datetime.now(UTC))


def _invoke(graph: Any, state: ConversationState) -> ConversationState:
    """LangGraph result 가 dict 일 수도 있어 일관 변환."""
    result = graph.invoke(state)
    if isinstance(result, dict):
        return ConversationState(**result)
    return result


# ============================================================
# 시나리오 1: NEW_QUESTION 단일 턴
# ============================================================
def test_new_question_정상(registry):
    graph = build_orchestrator(
        classifier=_ScriptedClassifier([Intent.NEW_QUESTION]),
        rewriter=_Rewriter(),
        strategies=registry,
        router=_Router(),
        answerer=_Answerer(),
    )
    state = _make_state(conversation=_empty_conversation(), message="예정론?")
    out = _invoke(graph, state)

    assert len(out.conversation.turns) == 1
    turn = out.conversation.turns[0]
    assert turn.intent == Intent.NEW_QUESTION
    assert turn.selected_strategy == "hybrid"
    assert turn.answer.content == "hybrid:예정론?"


# ============================================================
# 시나리오 2: 멀티턴 가로지름 — Hybrid → KG → META_RECAP
# ============================================================
def test_multiturn_hybrid_kg_meta_recap(registry):
    classifier = _ScriptedClassifier([Intent.NEW_QUESTION, Intent.NEW_QUESTION, Intent.META_RECAP])
    graph = build_orchestrator(
        classifier=classifier,
        rewriter=_Rewriter(),
        strategies=registry,
        router=_Router(),
        answerer=_Answerer(),
    )
    conversation = _empty_conversation()

    # 1턴: 일반 질문 → hybrid
    state1 = _make_state(conversation=conversation, message="예정론?")
    out1 = _invoke(graph, state1)
    assert out1.conversation.turns[0].selected_strategy == "hybrid"

    # 2턴: 관계 키워드 → kg
    state2 = _make_state(conversation=out1.conversation, message="칼빈과 베자의 관계는?")
    out2 = _invoke(graph, state2)
    assert out2.conversation.turns[1].selected_strategy == "kg"

    # 3턴: 메타 요약 — RAG 우회, history 기반 답변
    state3 = _make_state(conversation=out2.conversation, message="위 두 답변을 요약")
    out3 = _invoke(graph, state3)
    last = out3.conversation.turns[2]
    assert last.intent == Intent.META_RECAP
    assert last.selected_strategy is None  # strategy 호출 0
    assert "요약:" in last.answer.content
    assert "hybrid:예정론?" in last.answer.content
    assert "kg:칼빈과 베자의 관계는?" in last.answer.content


# ============================================================
# 시나리오 3: FOLLOWUP — rewrite 거침
# ============================================================
def test_followup_rewrite_적용(registry):
    graph = build_orchestrator(
        classifier=_ScriptedClassifier([Intent.NEW_QUESTION, Intent.FOLLOWUP]),
        rewriter=_Rewriter(),
        strategies=registry,
        router=_Router(),
        answerer=_Answerer(),
    )
    out1 = _invoke(graph, _make_state(conversation=_empty_conversation(), message="질문1"))
    out2 = _invoke(graph, _make_state(conversation=out1.conversation, message="그러면?"))

    assert out2.conversation.turns[1].standalone_question == "재작성:그러면?"
    # rewrite 결과가 strategy 에 전달
    assert "재작성:그러면?" in out2.conversation.turns[1].answer.content


# ============================================================
# 시나리오 4: 첨부 → vision 자동 라우팅
# ============================================================
def test_attachment_vision_자동_라우팅(registry):
    from chatbot.domain.conversation import Attachment

    graph = build_orchestrator(
        classifier=_ScriptedClassifier([Intent.NEW_QUESTION]),
        rewriter=_Rewriter(),
        strategies=registry,
        router=_Router(),
        answerer=_Answerer(),
    )
    conversation = _empty_conversation()
    state = ConversationState(
        conversation=conversation,
        pending_user_message=Message(
            role="user",
            content="이 도판은?",
            attachments=(Attachment(kind="image_url", value="https://x.com/img.jpg"),),
        ),
        trace_id="t",
        started_at_ms=0,
    )
    out = _invoke(graph, state)
    # supports() 분기로 vision 만 후보 → 라우터가 vision 선택
    assert out.conversation.turns[0].selected_strategy == "vision"


# ============================================================
# 시나리오 5: SMALLTALK — strategy 호출 0
# ============================================================
def test_smalltalk_RAG_우회(registry):
    graph = build_orchestrator(
        classifier=_ScriptedClassifier([Intent.SMALLTALK]),
        rewriter=_Rewriter(),
        strategies=registry,
        router=_Router(),
        answerer=_Answerer(),
    )
    out = _invoke(graph, _make_state(conversation=_empty_conversation(), message="안녕"))
    turn = out.conversation.turns[0]
    assert turn.intent == Intent.SMALLTALK
    assert turn.selected_strategy is None
    assert turn.answer.content == "smalltalk:안녕"
    # 모든 strategy 의 runs 가 0
    for s in registry.all():
        assert s.runs == []  # type: ignore[attr-defined]
