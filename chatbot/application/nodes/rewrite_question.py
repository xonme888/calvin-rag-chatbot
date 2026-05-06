"""rewrite_question 노드 — Intent.FOLLOWUP 일 때만 발동.

다른 Intent 는 *passthrough* — pending_standalone 을 user_message.content 로 채운다.
이 일관성 덕분에 다음 노드들은 항상 pending_standalone 을 사용 (None 가드 불필요).
"""

from __future__ import annotations

from chatbot.application._protocols import QueryRewriter
from chatbot.application.nodes._helpers import history_messages
from chatbot.domain.intent import Intent
from chatbot.domain.state import ConversationState


def rewrite_question(
    state: ConversationState,
    *,
    rewriter: QueryRewriter,
) -> ConversationState:
    """FOLLOWUP 이면 LLM 으로 standalone 재구성, 아니면 원문 그대로."""
    if state.pending_intent == Intent.FOLLOWUP:
        rewritten = rewriter.rewrite(
            message=state.pending_user_message,
            history=history_messages(state),
        )
        return state.model_copy(update={"pending_standalone": rewritten})
    return state.model_copy(update={"pending_standalone": state.pending_user_message.content})
