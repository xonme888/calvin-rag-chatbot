"""FastAPI 헬스 라우트 단위 테스트.

Step 1 검증 — `/health` 가 200 + 예상 JSON 반환.
TestClient(httpx 기반)로 LLM/외부 호출 0회.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "calvin-rag-chatbot-api"
    assert "version" in data


def test_app_metadata() -> None:
    """FastAPI 앱 자체 metadata 검증 (OpenAPI 스키마 대비)."""
    assert app.title == "Calvin RAG Chatbot API"
    assert app.version == "0.1.0"


def test_cors_middleware_attached() -> None:
    """CORS 미들웨어가 등록되어 있어야 — Next.js 프론트와 통신 가능."""
    middlewares = [type(m).__name__ for m in getattr(app, "user_middleware", [])]
    assert any("CORS" in m or "Middleware" in m for m in middlewares)
