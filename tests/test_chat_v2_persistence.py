"""``/chat/v2`` 의 영속화 통합 시나리오 — Authorization header → user_id, conversation_id
처리, background save. FakeStore + FakeIdentifier 로 LLM/Supabase 호출 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.dependencies import reset_dependency_cache
from api.main import app
from api.routes import chat_v2 as chat_v2_module
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.corpus import Citation, DocumentRef
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult
from chatbot.domain.turn_artifact import make_retrieval_result_ref


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch) -> Any:  # type: ignore[no-untyped-def]
    reset_dependency_cache()
    app.dependency_overrides.clear()
    # rate limiter 누적 차단 — testclient IP 가 모든 테스트에서 동일하므로 매번 storage reset.
    from api.middleware.rate_limiter import limiter

    limiter.reset()
    yield monkeypatch
    app.dependency_overrides.clear()


# ============================================================
# Fakes
# ============================================================
class _FakeStore:
    def __init__(self, *, preload: dict | None = None) -> None:
        self._data: dict[tuple[str, str], Conversation] = {}
        if preload:
            self._data.update(preload)
        self.save_calls: list[tuple[str, str, int]] = []  # (cid, uid, turn_count)
        self.load_calls: list[tuple[str, str]] = []

    def save(self, conversation: Conversation, *, user_id: str) -> None:
        self.save_calls.append((conversation.id, user_id, len(conversation.turns)))
        self._data[(user_id, conversation.id)] = conversation

    def load(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        self.load_calls.append((conversation_id, user_id))
        return self._data.get((user_id, conversation_id))

    def list_for_user(self, user_id, *, limit=50, before=None):  # type: ignore[no-untyped-def]
        return []

    def delete(self, conversation_id: str, *, user_id: str) -> None:
        self._data.pop((user_id, conversation_id), None)


class _FakeIdentifier:
    def __init__(self, *, user_id: str | None) -> None:
        self.user_id = user_id

    def current_user_id(self, request: Any) -> str | None:
        return self.user_id


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.save_calls: list[tuple[str, str, int]] = []

    def save_if_absent(self, artifact, *, user_id: str) -> None:  # type: ignore[no-untyped-def]
        self.save_calls.append((artifact.conversation_id, user_id, artifact.turn_index))

    def load_by_turn(self, conversation_id, turn_index, *, user_id):  # type: ignore[no-untyped-def]
        return None

    def load_by_ref(self, retrieval_result_ref, *, user_id):  # type: ignore[no-untyped-def]
        return None


class _AppendTurnOrch:
    """orchestrator stub — pending_user_message 를 새 Turn 으로 append."""

    def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
        answer = Message(role="assistant", content=f"echo:{state.pending_user_message.content}")
        return state.model_copy(
            update={
                "conversation": state.conversation.append_turn(
                    Turn(
                        user_message=state.pending_user_message,
                        intent=Intent.NEW_QUESTION,
                        answer=answer,
                        trace_id=state.trace_id,
                        elapsed_ms=1,
                        started_at=datetime.now(UTC),
                    )
                ),
                "pending_intent": Intent.NEW_QUESTION,
                "pending_answer": answer,
            }
        )


class _AppendTurnWithRetrievalOrch:
    """retrieval 결과를 함께 반환해 artifact save 경로를 검증."""

    def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
        turn_index = len(state.conversation.turns)
        retrieval_ref = make_retrieval_result_ref(state.conversation.id, turn_index)
        answer = Message(role="assistant", content=f"echo:{state.pending_user_message.content}")
        retrieval = RetrievalResult(
            documents=(
                DocumentRef(
                    corpus_id="calvin",
                    source_id="institutes_v1",
                    chunk_id="chunk-1",
                    page=10,
                    content="본문",
                    score=0.9,
                ),
            ),
            citations=(
                Citation(
                    corpus_id="calvin",
                    source_id="institutes_v1",
                    page_label="p.11",
                    snippet="본문",
                ),
            ),
            metadata={"pattern": "hybrid"},
        )
        return state.model_copy(
            update={
                "conversation": state.conversation.append_turn(
                    Turn(
                        user_message=state.pending_user_message,
                        intent=Intent.NEW_QUESTION,
                        selected_strategy="hybrid",
                        standalone_question=state.pending_user_message.content,
                        retrieval_result_ref=retrieval_ref,
                        answer=answer,
                        trace_id=state.trace_id,
                        elapsed_ms=1,
                        started_at=datetime.now(UTC),
                    )
                ),
                "pending_intent": Intent.NEW_QUESTION,
                "pending_answer": answer,
                "pending_retrieval": retrieval,
            }
        )


def _install(  # type: ignore[no-untyped-def]
    monkeypatch,
    *,
    store,
    identifier,
    orch=None,
    artifact_store=None,
    index_version: str = "idx-v1",
) -> None:
    monkeypatch.setattr(chat_v2_module, "_persistence", lambda: (store, identifier))
    monkeypatch.setattr(chat_v2_module, "_orchestrator", lambda: orch or _AppendTurnOrch())
    monkeypatch.setattr(chat_v2_module, "_artifact_store", lambda: artifact_store)
    monkeypatch.setattr(chat_v2_module, "_artifact_index_version", lambda: index_version)


# ============================================================
# 시나리오 1: 인증 + conversation_id 있음 → store.load + 응답 후 save
# ============================================================
def test_authenticated_with_conversation_id_loads_and_saves(_reset_state) -> None:  # type: ignore[no-untyped-def]
    existing = Conversation(
        id="conv-1",
        turns=(
            Turn(
                user_message=Message(role="user", content="이전질문"),
                intent=Intent.NEW_QUESTION,
                answer=Message(role="assistant", content="이전답변"),
                trace_id="t",
                elapsed_ms=0,
                started_at=datetime.now(UTC),
            ),
        ),
        created_at=datetime.now(UTC),
    )
    store = _FakeStore(preload={("user-1", "conv-1"): existing})
    identifier = _FakeIdentifier(user_id="user-1")
    _install(_reset_state, store=store, identifier=identifier)

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "후속질문", "conversation_id": "conv-1"},
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert resp.status_code == 200

    # 1. store.load 가 (conv-1, user-1) 로 호출됨
    assert ("conv-1", "user-1") in store.load_calls

    # 2. background save 가 호출됨 — 기존 1 turn + 새 1 turn = 2 turns
    # FastAPI BackgroundTasks 는 응답 후 실행되지만 TestClient 가 동기 처리
    assert len(store.save_calls) == 1
    cid, uid, turn_count = store.save_calls[0]
    assert cid == "conv-1"
    assert uid == "user-1"
    assert turn_count == 2  # 이전 1 + 새 1


# ============================================================
# 시나리오 2: 인증 + conversation_id 없음 → 새 conversation 생성
# ============================================================
def test_authenticated_without_conversation_id_creates_new(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    identifier = _FakeIdentifier(user_id="user-1")
    _install(_reset_state, store=store, identifier=identifier)

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "첫질문"},
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert resp.status_code == 200

    # store.load 호출 0 (conversation_id 없음)
    assert store.load_calls == []
    # save 1번 — 새 conversation
    assert len(store.save_calls) == 1


# ============================================================
# 시나리오 3: 인증 X (anon) → store 미사용, chat_history fallback
# ============================================================
def test_anonymous_no_persistence(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    identifier = _FakeIdentifier(user_id=None)  # 익명
    _install(_reset_state, store=store, identifier=identifier)

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={
            "question": "Q",
            "chat_history": [
                {"role": "user", "content": "이전 Q"},
                {"role": "assistant", "content": "이전 A"},
            ],
        },
    )
    assert resp.status_code == 200

    # store.load / save 모두 호출 0 — 익명
    assert store.load_calls == []
    assert store.save_calls == []


# ============================================================
# 시나리오 4: store=None (env 미설정) → save 시도 0
# ============================================================
def test_store_미설정_save_skip(_reset_state) -> None:  # type: ignore[no-untyped-def]
    identifier = _FakeIdentifier(user_id="user-1")
    _reset_state.setattr(chat_v2_module, "_persistence", lambda: (None, identifier))
    _reset_state.setattr(chat_v2_module, "_orchestrator", lambda: _AppendTurnOrch())

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "Q"},
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert resp.status_code == 200
    # store=None 이라 save 자체 안 됨


# ============================================================
# 시나리오 5: 다른 사용자 conversation_id 시도 → load=None → 새 conversation
# ============================================================
def test_different_user_conversation_id_load_returns_none(_reset_state) -> None:  # type: ignore[no-untyped-def]
    other_user_conv = Conversation(id="conv-1", created_at=datetime.now(UTC))
    store = _FakeStore(preload={("other-user", "conv-1"): other_user_conv})
    identifier = _FakeIdentifier(user_id="user-1")
    _install(_reset_state, store=store, identifier=identifier)

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "Q", "conversation_id": "conv-1"},
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert resp.status_code == 200
    assert ("conv-1", "user-1") in store.load_calls
    # save 호출 → user-1 의 새 conversation 으로 (id=conv-1, 그러나 다른 user 라 충돌 X)
    assert store.save_calls[0][1] == "user-1"


def test_retrieval_turn_아티팩트_저장(_reset_state) -> None:  # type: ignore[no-untyped-def]
    store = _FakeStore()
    artifact_store = _FakeArtifactStore()
    identifier = _FakeIdentifier(user_id="user-1")
    _install(
        _reset_state,
        store=store,
        identifier=identifier,
        orch=_AppendTurnWithRetrievalOrch(),
        artifact_store=artifact_store,
        index_version="idx-v9",
    )

    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "근거 보여줘"},
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert resp.status_code == 200
    assert len(store.save_calls) == 1
    assert len(artifact_store.save_calls) == 1
    cid, uid, turn_index = artifact_store.save_calls[0]
    assert uid == "user-1"
    assert turn_index == 0
    assert cid
