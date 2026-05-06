"""대화 도메인 — Message, Attachment, Turn, Conversation.

Conversation 은 Turn 의 append-only 시퀀스다. Turn 은 한 사용자 입력에서 한 답변까지의
모든 결정과 산출물을 담은 불변 레코드다. 디버깅·재현은 Conversation 한 덩어리를
직렬화하면 충분해야 한다 — 이 파일의 모든 모델이 frozen 인 이유.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chatbot.domain.intent import Intent


class Attachment(BaseModel):
    """사용자 첨부 — 이미지가 1차 use case. 추후 PDF/Audio 도 같은 envelope 로 확장."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["image_url", "image_base64"]
    value: str
    """URL 또는 base64 데이터. kind 가 결정한다."""
    mime_type: str | None = None


class Message(BaseModel):
    """대화의 단일 발화. 이미지·도구 결과 등은 Turn 에 별도 보존하고 여기엔 텍스트만."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: str
    attachments: tuple[Attachment, ...] = ()
    """tuple 로 보유 — frozen Message 의 불변성 일관성."""


class Turn(BaseModel):
    """한 턴의 모든 결정과 산출물.

    노드 시퀀스가 진행될 때마다 필드가 채워지며, 마지막에 immutable 로 freeze 되어
    Conversation.turns 에 append 된다. 중간 단계 값(예: standalone_question)을 모두
    보존하므로 후속 턴에서 메타-참조("방금 그래프", "그 인용 페이지") 가 가능하다.
    """

    model_config = ConfigDict(frozen=True)

    user_message: Message
    intent: Intent
    standalone_question: str | None = None
    """rewriter 가 생성한 자기-완결 질문. NEW_QUESTION/SMALLTALK 면 None."""

    selected_strategy: str | None = None
    """선택된 RetrievalStrategy 의 name. META/SMALLTALK 이라 검색을 건너뛴 경우 None."""

    retrieval_result_ref: str | None = None
    """RetrievalResult 영속화 ID — 큰 페이로드(서브그래프/문서)는 별도 저장.

    Turn 자체는 가볍게 유지하기 위함. None 이면 검색이 없었던 턴.
    """

    answer: Message
    trace_id: str
    elapsed_ms: int = Field(ge=0)
    started_at: datetime


class Conversation(BaseModel):
    """append-only Turn 시퀀스. 영속화 단위.

    turns 변경은 항상 ``append_turn`` 으로 — 새 인스턴스를 반환해 불변 보장.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    turns: tuple[Turn, ...] = ()
    created_at: datetime

    def append_turn(self, turn: Turn) -> Conversation:
        """Turn 추가한 새 Conversation 반환. 원본은 변경하지 않는다."""
        return self.model_copy(update={"turns": (*self.turns, turn)})

    @property
    def last_turn(self) -> Turn | None:
        """직전 턴 — 메타-참조(요약·되짚기) 노드가 사용한다."""
        return self.turns[-1] if self.turns else None
