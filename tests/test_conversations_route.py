"""``/conversations`` REST 라우트 — 목록/상세/삭제/마이그레이션 (PR 15)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.dependencies import reset_dependency_cache
from api.main import app
from api.routes import conversations as conv_module
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.persistence import ConversationSummary


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch) -> Any:  # type: ignore[no-untyped-def]
    reset_dependency_cache()
    app.dependency_overrides.clear()
    from api.middleware.rate_limiter import limiter

    limiter.reset()
    yield monkeypatch
    app.dependency_overrides.clear()


# ============================================================
# Fakes — chat_v2 테스트와 동일 패턴
# ============================================================
class _FakeStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Conversation] = {}
        self.save_calls: list[tuple[str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.list_calls: list[tuple[str, int, datetime | None]] = []

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        self.save_calls.append((conversation.id, user_id))
        self._data[(user_id, conversation.id)] = conversation

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        return self._data.get((user_id, conversation_id))

    def list_for_user(
        self, user_id: str, *, limit: int = 50, before: datetime | None = None
    ) -> list[ConversationSummary]:
        self.list_calls.append((user_id, limit, before))
        items = [(cid, conv) for (uid, cid), conv in self._data.items() if uid == user_id]
        return [
            ConversationSummary(
                id=cid,
                title=f"제목 {cid}",
                last_turn_at=conv.created_at,
                turn_count=len(conv.turns),
            )
            for cid, conv in items[:limit]
        ]

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        self.delete_calls.append((conversation_id, user_id))
        self._data.pop((user_id, conversation_id), None)


class _FakeIdentifier:
    def __init__(self, *, user_id: str | None) -> None:
        self.user_id = user_id

    def current_user_id(self, request: Any) -> str | None:
        return self.user_id


def _install(monkeypatch, *, store, identifier) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(conv_module, "_persistence", lambda: (store, identifier))


# ============================================================
# 시나리오 1: 인증 X → 401
# ============================================================
def test_list_미인증_401(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id=None))

    client = TestClient(app)
    resp = client.get("/conversations")
    assert resp.status_code == 401


# ============================================================
# 시나리오 2: store 미설정 (env 없음) → 503
# ============================================================
def test_store_미설정_503(_reset_state) -> None:  # type: ignore[no-untyped-def]
    _reset_state.setattr(
        conv_module, "_persistence", lambda: (None, _FakeIdentifier(user_id="u"))
    )
    client = TestClient(app)
    resp = client.get("/conversations", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 503


# ============================================================
# 시나리오 3: 목록 → 사용자 본인 데이터만
# ============================================================
def test_list_본인_데이터만(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))

    # 본인 conv 1, 타인 conv 1
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="user-1")
    store.save(Conversation(id="c2", created_at=datetime.now(UTC)), user_id="other")

    client = TestClient(app)
    resp = client.get("/conversations", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "c1"


# ============================================================
# 시나리오 4: 상세 — 본인 = 200, 타인 = 404
# ============================================================
def test_get_타인_404(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="other")

    client = TestClient(app)
    resp = client.get("/conversations/c1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 404


# ============================================================
# 시나리오 5: 삭제 — 본인 only, 타인은 silent no-op
# ============================================================
def test_delete_본인(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))
    store.save(Conversation(id="c1", created_at=datetime.now(UTC)), user_id="user-1")

    client = TestClient(app)
    resp = client.delete("/conversations/c1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 204
    assert ("c1", "user-1") in store.delete_calls


# ============================================================
# 시나리오 6: 마이그레이션 — IndexedDB 형태 → Supabase save
# ============================================================
def test_migrate_익명_sessions_업로드(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))

    payload = {
        "conversations": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "title": "old-1",
                "createdAt": 1700000000000,  # ms
                "messages": [
                    {"role": "user", "content": "Q1"},
                    {"role": "assistant", "content": "A1"},
                    {"role": "user", "content": "Q2"},
                    {"role": "assistant", "content": "A2"},
                ],
            },
            {
                "id": "non-uuid-id",  # 새 uuid 발급되어야 함
                "messages": [
                    {"role": "user", "content": "Q"},
                    {"role": "assistant", "content": "A"},
                ],
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "messages": [],  # 비어있음 → skip
            },
        ]
    }

    client = TestClient(app)
    resp = client.post(
        "/conversations/migrate",
        json=payload,
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["saved"] == 2
    assert body["skipped"] == 1
    # 부분 실패 식별자 — 빈 messages 가 그대로 반환 (audit M1)
    assert body["skipped_ids"] == ["22222222-2222-2222-2222-222222222222"]

    # 1개는 원본 id 유지, 다른 1개는 새 uuid (= 'non-uuid-id' 가 아님)
    saved_ids = [cid for cid, _uid in store.save_calls]
    assert "11111111-1111-1111-1111-111111111111" in saved_ids
    assert "non-uuid-id" not in saved_ids
    assert all(uid == "user-1" for _cid, uid in store.save_calls)


# ============================================================
# 시나리오 7: 마이그레이션 — 인증 X → 401
# ============================================================
def test_migrate_미인증_401(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id=None))

    client = TestClient(app)
    resp = client.post(
        "/conversations/migrate",
        json={"conversations": [{"id": "x", "messages": []}]},
    )
    assert resp.status_code == 401


# ============================================================
# 시나리오 8a: list — limit / before 쿼리 파라미터가 store 에 위임되는가
# ============================================================
def test_list_limit_before_위임(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))

    client = TestClient(app)
    resp = client.get(
        "/conversations?limit=10&before=2026-05-01T00:00:00Z",
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert len(store.list_calls) == 1
    uid, limit, before = store.list_calls[0]
    assert uid == "user-1"
    assert limit == 10
    assert before is not None
    assert before.year == 2026 and before.month == 5


# ============================================================
# 시나리오 9: 사이드바 통합 — list + get 페어
# ============================================================
def test_get_본인_full_conversation(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    _install(_reset_state, store=store, identifier=_FakeIdentifier(user_id="user-1"))
    conv = Conversation(
        id="c1",
        turns=(
            Turn(
                user_message=Message(role="user", content="Q"),
                intent=Intent.NEW_QUESTION,
                answer=Message(role="assistant", content="A"),
                trace_id="t",
                elapsed_ms=10,
                started_at=datetime.now(UTC),
            ),
        ),
        created_at=datetime.now(UTC),
    )
    store.save(conv, user_id="user-1")

    client = TestClient(app)
    resp = client.get("/conversations/c1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    body = resp.json()["conversation"]
    assert body["id"] == "c1"
    assert len(body["turns"]) == 1
