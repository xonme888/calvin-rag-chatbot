"""FastAPI 엔드포인트 단위 테스트.

LLM/네트워크 호출 0회 — TestClient + Mock dependency.
RAG 본 호출은 Mock 으로 우회 (FastAPI dependency_overrides).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.dependencies import (
    reset_dependency_cache,
)
from api.main import app


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    """각 테스트마다 RAG 인스턴스/통계 캐시 초기화."""
    reset_dependency_cache()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ====================================================================
# /health
# ====================================================================
def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ====================================================================
# /modes — KG 가용성 따라 available 변동
# ====================================================================
def test_modes_returns_registered_options() -> None:
    """등록된 모든 모드 (hybrid/agentic/kg/vision) 응답에 포함."""
    client = TestClient(app)
    resp = client.get("/modes")
    assert resp.status_code == 200
    modes = resp.json()["modes"]
    names = {m["name"] for m in modes}
    assert names == {"hybrid", "agentic", "kg", "vision"}
    # hybrid/agentic/vision 은 항상 available, kg 는 Neo4j 의존
    by_name = {m["name"]: m for m in modes}
    assert by_name["hybrid"]["available"] is True
    assert by_name["agentic"]["available"] is True
    assert by_name["vision"]["available"] is True


# ====================================================================
# /stats — 빈 통계
# ====================================================================
def test_stats_returns_empty_when_no_calls() -> None:
    client = TestClient(app)
    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 0
    assert data["total_input_tokens"] == 0
    assert data["total_cost_krw"] == 0.0
    assert data["by_mode"] == {}


# ====================================================================
# /chat/sync — 입력 가드 검증
# ====================================================================
def test_chat_sync_blocks_too_long_input() -> None:
    """2,000자 초과 입력은 LengthGuard가 400으로 차단."""
    client = TestClient(app)
    resp = client.post(
        "/chat/sync",
        json={"question": "a" * 3000, "mode": "hybrid"},
    )
    # Pydantic max_length 검증으로도 422 가능, 또는 가드로 400
    assert resp.status_code in (400, 422)


def test_chat_sync_rejects_empty_question() -> None:
    client = TestClient(app)
    resp = client.post("/chat/sync", json={"question": "", "mode": "hybrid"})
    assert resp.status_code == 422  # min_length=1


def test_chat_sync_rejects_invalid_mode() -> None:
    client = TestClient(app)
    resp = client.post(
        "/chat/sync",
        json={"question": "Q", "mode": "unknown"},
    )
    assert resp.status_code == 422


def test_chat_sync_rejects_invalid_dense_weight() -> None:
    """dense_weight 0~1 범위 외는 거절."""
    client = TestClient(app)
    resp = client.post(
        "/chat/sync",
        json={"question": "Q", "mode": "hybrid", "dense_weight": 2.0},
    )
    assert resp.status_code == 422


# ====================================================================
# /chat/sync — chat_v2 wrapper 동등성 (PR 6 Phase B)
# ====================================================================
# 본 라우트는 ``api/routes/chat_v2.chat_v2`` 로 위임 — mode 인자는 무시되고 orchestrator
# 가 자동 라우팅한다. 입력 가드 / Pydantic 검증은 chat_v2 도 동일하게 적용.
#
# 정상 흐름의 envelope 검증은 ``tests/test_chat_v2_endpoint.py`` 가 별도로 다룬다.


def test_chat_sync_wrapper_위임(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/chat/sync`` 가 ``/chat/v2`` 와 동일 envelope 반환 — wrapper 동등성."""
    from chatbot.domain.conversation import Message, Turn
    from chatbot.domain.intent import Intent
    from datetime import UTC, datetime
    from api.routes import chat_v2 as chat_v2_module

    class _FakeOrchestrator:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            answer = Message(role="assistant", content="wrapped answer")
            turn = Turn(
                user_message=state.pending_user_message,
                intent=Intent.NEW_QUESTION,
                standalone_question=state.pending_user_message.content,
                selected_strategy="hybrid",
                answer=answer,
                trace_id=state.trace_id,
                elapsed_ms=1,
                started_at=datetime.now(UTC),
            )
            return state.model_copy(
                update={
                    "conversation": state.conversation.append_turn(turn),
                    "pending_intent": Intent.NEW_QUESTION,
                    "pending_strategy": "hybrid",
                    "pending_answer": answer,
                }
            )

    monkeypatch.setattr(chat_v2_module, "_orchestrator", lambda: _FakeOrchestrator())
    client = TestClient(app)
    resp = client.post("/chat/sync", json={"question": "Q", "mode": "hybrid"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "wrapped answer"
    assert data["metadata"]["selected_strategy"] == "hybrid"
    assert data["metadata"]["intent"] == "new_question"
