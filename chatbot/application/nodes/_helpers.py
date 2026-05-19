"""노드 공통 헬퍼 — state ↔ 도메인 모델 변환.

여러 노드가 같은 변환을 반복하는 코드 중복 방지. 본 모듈은 *노드 외부에서* 사용 X
(밑줄 prefix). 변환 함수만 두고 부수효과 없음.
"""

from __future__ import annotations

from chatbot.domain.conversation import Attachment, Message
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.domain.state import ConversationState


def to_retrieval_request(state: ConversationState) -> RetrievalRequest:
    """state → RetrievalRequest. select/invoke 노드가 공유.

    standalone 우선, 없으면 user_message.content 폴백. chat_history 는 turns 누적에서.
    """
    attachments: tuple[Attachment, ...] = state.pending_user_message.attachments
    standalone = state.pending_standalone or state.pending_user_message.content
    history: list[Message] = []
    for turn in state.conversation.turns:
        history.append(turn.user_message)
        history.append(turn.answer)
    return RetrievalRequest(
        standalone_question=standalone,
        chat_history=tuple(history),
        attachments=attachments,
        metadata_filter={"dense_weight": f"{state.requested_dense_weight:.4f}"},
    )


def history_messages(state: ConversationState) -> tuple[Message, ...]:
    """turns 누적 → user/assistant 페어 시퀀스. compose_answer / rewrite_question 공유."""
    out: list[Message] = []
    for turn in state.conversation.turns:
        out.append(turn.user_message)
        out.append(turn.answer)
    return tuple(out)
