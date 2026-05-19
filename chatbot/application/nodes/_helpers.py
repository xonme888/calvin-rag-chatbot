"""노드 공통 헬퍼 — state ↔ 도메인 모델 변환.

여러 노드가 같은 변환을 반복하는 코드 중복 방지. 본 모듈은 *노드 외부에서* 사용 X
(밑줄 prefix). 변환 함수만 두고 부수효과 없음.
"""

from __future__ import annotations

import os

from chatbot.domain.conversation import Attachment, Message
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.domain.state import ConversationState

_MAX_HISTORY_MESSAGES = max(2, int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "12")))
_MAX_HISTORY_CHARS = max(500, int(os.getenv("CHAT_HISTORY_MAX_CHARS", "4000")))


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
    history = _bounded_history(history)
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
    return tuple(_bounded_history(out))


def _bounded_history(messages: list[Message]) -> list[Message]:
    """대화 히스토리 상한 적용 + 초과분 요약 압축."""
    if not messages:
        return []

    # 최근 메시지 우선으로 길이·개수 제한을 동시에 만족시킨다.
    picked: list[Message] = []
    chars = 0
    for msg in reversed(messages):
        next_chars = chars + len(msg.content)
        if len(picked) >= _MAX_HISTORY_MESSAGES or next_chars > _MAX_HISTORY_CHARS:
            break
        picked.append(msg)
        chars = next_chars

    kept = list(reversed(picked))
    dropped_count = len(messages) - len(kept)
    if dropped_count <= 0:
        return kept

    # 초과된 앞부분은 간단 요약 메시지로 압축해 컨텍스트 단절을 완화한다.
    dropped_preview = " / ".join(
        f"{'U' if m.role == 'user' else 'A'}:{m.content[:40]}" for m in messages[: min(3, dropped_count)]
    )
    summary = Message(
        role="assistant",
        content=f"[이전 대화 요약: {dropped_count}개 메시지 생략] {dropped_preview}",
    )
    return [summary, *kept]
