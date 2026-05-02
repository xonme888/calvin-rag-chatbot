"""FastAPI 엔드포인트 단위 테스트.

LLM/네트워크 호출 0회 — TestClient + Mock dependency.
RAG 본 호출은 Mock 으로 우회 (FastAPI dependency_overrides).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.dependencies import (
    get_agentic_rag,
    get_hybrid_rag,
    get_kg_rag_or_none,
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
def test_modes_returns_3_options() -> None:
    """3 모드(hybrid/agentic/kg) 모두 응답에 포함."""
    client = TestClient(app)
    resp = client.get("/modes")
    assert resp.status_code == 200
    modes = resp.json()["modes"]
    names = {m["name"] for m in modes}
    assert names == {"hybrid", "agentic", "kg"}
    # hybrid/agentic 은 항상 available
    by_name = {m["name"]: m for m in modes}
    assert by_name["hybrid"]["available"] is True
    assert by_name["agentic"]["available"] is True


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
# /chat/sync — Mock RAG 로 정상 흐름 검증
# ====================================================================
def _make_mock_hybrid(answer: str = "mocked answer", sources: list[str] | None = None) -> Any:
    sources = sources or ["src 1"]

    class _MockHybrid:
        config = SimpleNamespace(dense_weight=0.5)

        def query(self, question: str, chat_history: list | None = None, callbacks: list | None = None) -> dict:
            return {
                "final_answer": answer,
                "source_documents": sources,
                "metadata": {"pattern": "Hybrid", "elapsed_seconds": 0.05},
            }

    return _MockHybrid()


def test_chat_sync_hybrid_returns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock Hybrid 로 정상 흐름 — 입력 가드 통과 → mock 호출 → 출력 가드 → 응답."""
    mock = _make_mock_hybrid(answer="예정론은 칼빈의 핵심 교리다.")
    # api.routes.chat 모듈이 import 한 함수도 같이 갈아끼움
    monkeypatch.setattr("api.routes.chat.get_hybrid_rag", lambda: mock)

    client = TestClient(app)
    resp = client.post(
        "/chat/sync",
        json={"question": "예정론?", "mode": "hybrid", "dense_weight": 0.5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "예정론" in data["answer"]
    assert data["source_documents"] == ["src 1"]
    assert data["metadata"]["pattern"] == "Hybrid"
    assert data["elapsed_seconds"] >= 0


def test_chat_sync_kg_unavailable_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """KG 모드 + 인스턴스 None 일 때 503 반환."""
    monkeypatch.setattr("api.routes.chat.get_kg_rag_or_none", lambda: None)

    client = TestClient(app)
    resp = client.post("/chat/sync", json={"question": "Q", "mode": "kg"})
    assert resp.status_code == 503
    assert "KG" in resp.json()["detail"]
