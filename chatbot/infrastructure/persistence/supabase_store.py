"""SupabaseConversationStore — domain.ConversationStore 의 Supabase Postgres 어댑터.

설계:
- JSONB 1-table (`conversations.state`) — TRD-011 §결정 2.
- 사용자 격리는 *RLS 정책* 이 1차 방어선. 본 어댑터는 user_id 필터를 *추가* 방어선으로
  명시 (SECURITY 가 RLS 우회 service_role key 사용 시에도 보장).
- 직렬화는 ``Conversation.model_dump(mode='json')`` — frozen Pydantic 이라 안전.

Supabase 클라이언트 (``supabase.Client``) 는 외부에서 주입 — 본 어댑터는 SDK 호출만.
연결·인증 책임은 bootstrap 또는 application 레이어.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from chatbot.domain.conversation import Conversation
from chatbot.domain.persistence import ConversationStore, ConversationSummary

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "conversations"


class SupabaseConversationStore:
    """ConversationStore 의 Supabase 구현. JSONB 1-table 기반.

    스키마 (sql/migrations/2026_05_06_conversations.sql):
        id uuid pk, user_id uuid, state jsonb, title text,
        updated_at timestamptz, created_at timestamptz.

    RLS 정책: ``auth.uid() = user_id`` (자기 데이터만 R/W).
    """

    name: str = "supabase"

    def __init__(self, *, client: Client) -> None:
        self._client = client

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        """upsert — 같은 id 면 갱신, 다르면 새 row. user_id 는 RLS 정책이 추가 검증."""
        self._client.table(_TABLE).upsert(
            {
                "id": conversation.id,
                "user_id": user_id,
                "state": conversation.model_dump(mode="json"),
                "title": _derive_title(conversation),
            }
        ).execute()

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        """없거나 다른 사용자 소유면 None. user_id 필터는 RLS 와 *이중 방어*."""
        res = (
            self._client.table(_TABLE)
            .select("state")
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return Conversation.model_validate(rows[0]["state"])

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[ConversationSummary]:
        """``updated_at desc``. ``before`` 가 있으면 그보다 이전만 (커서 페이지네이션)."""
        query = (
            self._client.table(_TABLE)
            .select("id, title, updated_at, state")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(limit)
        )
        if before is not None:
            query = query.lt("updated_at", before.isoformat())
        res = query.execute()
        rows = res.data or []
        return [_row_to_summary(row) for row in rows]

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        """다른 사용자 소유면 RLS 가 0건 매칭 → silent no-op."""
        self._client.table(_TABLE).delete().eq("id", conversation_id).eq(
            "user_id", user_id
        ).execute()


def _derive_title(conversation: Conversation) -> str | None:
    """첫 user_message.content 의 첫 30자. turns 비면 None."""
    if not conversation.turns:
        return None
    text = conversation.turns[0].user_message.content.strip()
    return text[:30] if text else None


def _row_to_summary(row: dict[str, Any]) -> ConversationSummary:
    """DB row → ConversationSummary. state 의 turns 길이로 turn_count 계산."""
    state = row.get("state") or {}
    turns = state.get("turns") or []
    updated_at_raw = row.get("updated_at")
    last_turn_at = (
        datetime.fromisoformat(str(updated_at_raw).replace("Z", "+00:00"))
        if updated_at_raw
        else datetime.now()
    )
    return ConversationSummary(
        id=str(row["id"]),
        title=row.get("title"),
        last_turn_at=last_turn_at,
        turn_count=len(turns),
    )


# Protocol 만족 — 정적 type checker 가 SupabaseConversationStore 를 ConversationStore 로 인식.
_: type[ConversationStore] = SupabaseConversationStore  # type: ignore[type-abstract]
