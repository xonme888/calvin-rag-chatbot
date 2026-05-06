"""classify_intent 노드 — state.pending_user_message → Intent.

Intent 결정의 입력은 *현재 메시지* + *직전 턴 메타*. 이 두 정보만으로 충분 —
chat_history 전체는 rewrite_question 단계에서 사용.
"""

from __future__ import annotations

from chatbot.application._protocols import IntentClassifier
from chatbot.domain.state import ConversationState


def classify_intent(
    state: ConversationState,
    *,
    classifier: IntentClassifier,
) -> ConversationState:
    """state.pending_intent 를 채운다. 다른 필드는 변경하지 않는다."""
    intent = classifier.classify(
        message=state.pending_user_message,
        last_turn=state.conversation.last_turn,
    )
    return state.model_copy(update={"pending_intent": intent})
