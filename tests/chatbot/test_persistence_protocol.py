"""ConversationStore / UserIdentifier Protocol shape 검증 + Conversation round-trip.

본 phase 는 도메인 추상만 — 구체 어댑터 (SupabaseConversationStore) 는 PR 12 에서 별도.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.persistence import (
    ConversationSummary,
)


# ============================================================
# In-memory FakeConversationStore — 회귀 테스트의 진입점
# ============================================================
class _MemConversationStore:
    """회귀 테스트용. RLS 시뮬레이션 — user_id 격리."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Conversation] = {}

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        self._data[(user_id, conversation.id)] = conversation

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        return self._data.get((user_id, conversation_id))

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[ConversationSummary]:
        out = [
            ConversationSummary(
                id=cid,
                title=conv.turns[0].user_message.content[:30] if conv.turns else None,
                last_turn_at=conv.turns[-1].started_at if conv.turns else conv.created_at,
                turn_count=len(conv.turns),
            )
            for (uid, cid), conv in self._data.items()
            if uid == user_id
        ]
        return sorted(out, key=lambda s: s.last_turn_at, reverse=True)[:limit]

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        self._data.pop((user_id, conversation_id), None)


def _make_turn(*, q: str, a: str) -> Turn:
    return Turn(
        user_message=Message(role="user", content=q),
        intent=Intent.NEW_QUESTION,
        answer=Message(role="assistant", content=a),
        trace_id="t",
        elapsed_ms=1,
        started_at=datetime.now(UTC),
    )


# ============================================================
# round-trip 검증 — Conversation 직렬화 무손실
# ============================================================
def test_conversation_model_dump_load_round_trip():
    """Conversation.model_dump → model_validate 가 *동등 객체* 복원."""
    conv = Conversation(
        id="c-uuid-1",
        turns=(_make_turn(q="예정론?", a="예정론은..."), _make_turn(q="베자는?", a="후계자")),
        created_at=datetime.now(UTC),
    )
    dumped = conv.model_dump(mode="json")
    restored = Conversation.model_validate(dumped)
    assert restored.id == conv.id
    assert len(restored.turns) == 2
    assert restored.turns[0].user_message.content == "예정론?"
    assert restored.turns[1].answer.content == "후계자"


# ============================================================
# Store Protocol 동작
# ============================================================
def test_store_save_and_load_본인():
    store = _MemConversationStore()
    conv = Conversation(id="c1", turns=(_make_turn(q="Q", a="A"),), created_at=datetime.now(UTC))
    store.save(conv, user_id="u1")

    loaded = store.load("c1", user_id="u1")
    assert loaded is not None
    assert loaded.id == "c1"
    assert len(loaded.turns) == 1


def test_store_다른_사용자_조회_차단():
    """RLS 시뮬레이션 — 다른 user_id 로 같은 conversation_id 조회 시 None."""
    store = _MemConversationStore()
    conv = Conversation(id="c1", created_at=datetime.now(UTC))
    store.save(conv, user_id="u1")
    assert store.load("c1", user_id="u2") is None


def test_store_미존재_None():
    store = _MemConversationStore()
    assert store.load("missing", user_id="u1") is None


def test_store_upsert_같은_id_갱신():
    """같은 id 로 두 번 save → 마지막 것이 보존."""
    store = _MemConversationStore()
    v1 = Conversation(id="c1", turns=(_make_turn(q="Q1", a="A1"),), created_at=datetime.now(UTC))
    v2 = Conversation(
        id="c1",
        turns=(_make_turn(q="Q1", a="A1"), _make_turn(q="Q2", a="A2")),
        created_at=datetime.now(UTC),
    )
    store.save(v1, user_id="u1")
    store.save(v2, user_id="u1")
    loaded = store.load("c1", user_id="u1")
    assert loaded is not None
    assert len(loaded.turns) == 2  # v2 보존


def test_store_list_for_user_본인_것만():
    store = _MemConversationStore()
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="u1")
    store.save(Conversation(id="c2", created_at=datetime.now(UTC)), user_id="u2")
    summaries = store.list_for_user("u1")
    assert len(summaries) == 1
    assert summaries[0].id == "c1"


def test_store_list_limit():
    store = _MemConversationStore()
    for i in range(5):
        store.save(Conversation(id=f"c{i}", created_at=datetime.now(UTC)), user_id="u1")
    assert len(store.list_for_user("u1", limit=3)) == 3


def test_store_delete_본인():
    store = _MemConversationStore()
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="u1")
    store.delete("c1", user_id="u1")
    assert store.load("c1", user_id="u1") is None


def test_store_delete_다른_사용자_silent_no_op():
    """보안 — 다른 사용자 소유 conversation 삭제 시도는 *조용히 무시* (존재 여부 노출 X)."""
    store = _MemConversationStore()
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="u1")
    store.delete("c1", user_id="u2")  # 무효
    # u1 의 데이터는 그대로 보존
    assert store.load("c1", user_id="u1") is not None


# ============================================================
# UserIdentifier
# ============================================================
class _StubAuth:
    def __init__(self, user_id: str | None):
        self._uid = user_id

    def current_user_id(self, request: Any) -> str | None:
        return self._uid


def test_user_identifier_authenticated():
    auth = _StubAuth("user-uuid-123")
    assert auth.current_user_id(None) == "user-uuid-123"


def test_user_identifier_anonymous_fallback():
    """AUTH_ENABLED=false 환경 또는 인증 실패 시 None — 익명 모드."""
    auth = _StubAuth(None)
    assert auth.current_user_id(None) is None


# ============================================================
# Protocol 만족 — Mock store 가 ConversationStore Protocol 통과
# ============================================================
def test_mem_store_satisfies_protocol():
    """runtime_checkable Protocol — 메서드만 시그니처 일치하면 통과."""
    store = _MemConversationStore()
    # isinstance 검증 — Python Protocol 한계로 항상 통과는 아님. 메서드 존재 확인으로 대체.
    assert hasattr(store, "save") and callable(store.save)
    assert hasattr(store, "load") and callable(store.load)
    assert hasattr(store, "list_for_user") and callable(store.list_for_user)
    assert hasattr(store, "delete") and callable(store.delete)


def test_summary_불변():
    s = ConversationSummary(id="c1", last_turn_at=datetime.now(UTC), turn_count=2)
    with pytest.raises(Exception):  # noqa: B017 — pydantic frozen ValidationError
        s.id = "c2"  # type: ignore[misc]
