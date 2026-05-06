"""compose_answer 노드 — Turn 을 freeze 해 conversation.turns 에 append.

AnswerComposer 가 *내부에서* retrieval 유무를 판단해 답변 생성 — 노드는 단일 호출.
완료 후 state.conversation 이 새 Turn 을 가진 인스턴스로 교체된다 (Conversation 은 frozen).
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import time

from chatbot.application._protocols import AnswerComposer
from chatbot.application.nodes._helpers import history_messages
from chatbot.domain.conversation import Message, Turn
from chatbot.domain.state import ConversationState


def compose_answer(
    state: ConversationState,
    *,
    answerer: AnswerComposer,
) -> ConversationState:
    """답변 합성 + Turn append + pending_* 정리."""
    if state.pending_intent is None:
        raise RuntimeError("compose_answer 호출 전에 classify_intent 가 실행되어야 합니다.")
    answer = answerer.compose(
        intent=state.pending_intent,
        user_message=state.pending_user_message,
        history=history_messages(state),
        last_turn=state.conversation.last_turn,
        retrieval_result=state.pending_retrieval,
    )
    new_conversation = state.conversation.append_turn(_build_turn(state, answer))
    return state.model_copy(update={"conversation": new_conversation, "pending_answer": answer})


def _build_turn(state: ConversationState, answer: Message) -> Turn:
    """state + 합성된 answer → Turn freeze."""
    elapsed_ms = max(0, int(time() * 1000) - state.started_at_ms)
    return Turn(
        user_message=state.pending_user_message,
        intent=state.pending_intent,  # type: ignore[arg-type]
        standalone_question=state.pending_standalone,
        selected_strategy=state.pending_strategy,
        retrieval_result_ref=None,
        answer=answer,
        trace_id=state.trace_id,
        elapsed_ms=elapsed_ms,
        started_at=datetime.now(UTC),
    )
