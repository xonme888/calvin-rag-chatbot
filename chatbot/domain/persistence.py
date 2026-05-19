"""대화 영속화 도메인 — ConversationStore + UserIdentifier Protocol.

PRD-002 / TRD-011 합류용. 본 모듈은 *추상만* 정의 — 구체 구현(SupabaseConversationStore
등) 은 ``chatbot/infrastructure/persistence/`` 가 담당.

설계 원칙:
- 사용자 단위 격리 — 모든 메서드가 user_id 인자 강제. 어댑터의 RLS 정책이 *추가 방어선*.
- 직렬화는 ``Conversation.model_dump_json`` — frozen Pydantic 이라 안전.
- 변경 자유 — 도메인 ``Conversation`` 변경 시 어댑터/DB 마이그레이션 0
  (jsonb 1-table 전제, TRD-011 §결정 2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from chatbot.domain.conversation import Conversation
from chatbot.domain.turn_artifact import TurnArtifact


class ConversationSummary(BaseModel):
    """``list_for_user`` 응답의 가벼운 요약. 사이드바 노출용 — 전체 state 미포함.

    title 은 첫 user_message.content 의 첫 30자 또는 별도 제목. 어댑터가 채운다.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    title: str | None = None
    last_turn_at: datetime
    turn_count: int


@runtime_checkable
class ConversationStore(Protocol):
    """대화 저장소. 사용자 단위 격리.

    구현 어댑터 (예: ``SupabaseConversationStore``) 는 RLS 정책 또는 동등한 격리를 별도
    보장한다. 본 Protocol 은 *호출 시그니처* 만.
    """

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        """conversation 을 영속화 — id 가 같으면 upsert, 다르면 새 row."""
        ...

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        """없거나 다른 사용자 소유면 None. 정상 조회 시 frozen Conversation."""
        ...

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[ConversationSummary]:
        """``updated_at`` 내림차순. ``before`` 가 주어지면 그보다 이전만 (커서 페이지네이션)."""
        ...

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        """존재하지 않거나 다른 사용자 소유면 silent no-op (보안 — 존재 여부 노출 X)."""
        ...


@runtime_checkable
class UserIdentifier(Protocol):
    """request → user_id 추출. Auth 어댑터.

    Magic Link 검증 후 JWT 의 ``sub`` claim 을 user_id 로 사용 (Supabase Auth 표준).
    ``AUTH_ENABLED=false`` 환경에서는 익명 fallback — None 반환 가능.
    """

    def current_user_id(self, request: Any) -> str | None:
        """JWT 검증 실패 또는 익명 모드 시 None. 본인 인증 통과 시 user uuid 문자열."""
        ...


@runtime_checkable
class TurnArtifactStore(Protocol):
    """턴 단위 retrieval 아티팩트 저장소.

    대화 본문(Conversation)과 분리 저장. reopen 시 근거 패널 복원에 사용한다.
    """

    def save_if_absent(self, artifact: TurnArtifact, *, user_id: str) -> None:
        """이미 있으면 덮어쓰지 않는다 (immutable snapshot)."""
        ...

    def load_by_turn(
        self,
        conversation_id: str,
        turn_index: int,
        *,
        user_id: str,
    ) -> TurnArtifact | None:
        """없거나 다른 사용자 소유면 None."""
        ...

    def load_by_ref(self, retrieval_result_ref: str, *, user_id: str) -> TurnArtifact | None:
        """retrieval_result_ref 기반 조회."""
        ...
