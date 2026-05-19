"""``/chat/v2`` 엔드포인트 통합 테스트.

LLM 호출 0 — orchestrator 자체를 *Fake* 로 우회. bootstrap 의 실 부트스트랩(LLM 의존)은
대신 PR 5 (UI 절체) 의 회귀 검증에 위임.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.dependencies import reset_dependency_cache
from api.main import app
from api.routes import chat_v2 as chat_v2_module
from chatbot.domain.conversation import Message
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch) -> Any:  # type: ignore[no-untyped-def]
    """각 테스트마다 dependency cache 초기화 + monkeypatch 로 _orchestrator 복원 보장."""
    reset_dependency_cache()
    app.dependency_overrides.clear()
    # 원본 _orchestrator 보존 — monkeypatch 가 yield 후 자동 복원
    yield monkeypatch
    app.dependency_overrides.clear()
    app.dependency_overrides.clear()


# ============================================================
# Fake orchestrator
# ============================================================
class _FakeOrchestrator:
    """LangGraph CompiledStateGraph 호환 — invoke() 만 구현."""

    def __init__(self, *, retrieval: RetrievalResult | None, intent: Intent, strategy: str | None):
        self._retrieval = retrieval
        self._intent = intent
        self._strategy = strategy

    def invoke(self, state, config: dict | None = None):  # type: ignore[no-untyped-def]

        from chatbot.domain.conversation import Turn

        answer = Message(
            role="assistant",
            content=self._retrieval.metadata["answer"]
            if self._retrieval is not None
            else f"meta:{self._intent.value}",
        )
        turn = Turn(
            user_message=state.pending_user_message,
            intent=self._intent,
            standalone_question=state.pending_user_message.content,
            selected_strategy=self._strategy,
            answer=answer,
            trace_id=state.trace_id,
            elapsed_ms=1,
            started_at=datetime.now(UTC),
        )
        new_conv = state.conversation.append_turn(turn)
        return state.model_copy(
            update={
                "conversation": new_conv,
                "pending_intent": self._intent,
                "pending_strategy": self._strategy,
                "pending_retrieval": self._retrieval,
                "pending_answer": answer,
            }
        )


def _install_orchestrator(monkeypatch, orchestrator) -> None:  # type: ignore[no-untyped-def]
    """monkeypatch 로 _orchestrator 함수를 갈아끼움 — fixture teardown 시 자동 복원."""

    def _factory():  # type: ignore[no-untyped-def]
        return orchestrator

    monkeypatch.setattr(chat_v2_module, "_orchestrator", _factory, raising=False)


# ============================================================
# 시나리오 1: NEW_QUESTION — retrieval 결과 응답
# ============================================================
def test_chat_v2_new_question_정상(_reset_state) -> None:  # type: ignore[no-untyped-def]
    fake = _FakeOrchestrator(
        retrieval=RetrievalResult(
            documents=(),
            citations=(),
            metadata={"answer": "예정론은...", "pattern": "Hybrid RAG"},
        ),
        intent=Intent.NEW_QUESTION,
        strategy="hybrid",
    )
    _install_orchestrator(_reset_state, fake)
    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "예정론은 무엇인가?", "mode": "auto", "chat_history": []},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "예정론은..."
    assert body["metadata"]["intent"] == "new_question"
    assert body["metadata"]["selected_strategy"] == "hybrid"
    assert body["metadata"]["routed_mode"] == "hybrid"
    assert body["metadata"]["auto_routed"] is True
    assert body["metadata"]["pattern"] == "Hybrid RAG"
    assert "trace_id" in body["metadata"]
    # envelope 호환성 — 기존 /chat/sync 가 노출하던 키들
    for key in (
        "cited_pages",
        "source_pages",
        "source_pages_label",
        "suggested_followups",
        "tool_calls",
        "tool_call_count",
        "subgraph",
    ):
        assert key in body["metadata"], f"envelope 누락 키: {key}"


# ============================================================
# 시나리오 2: META_RECAP — retrieval 없이 응답
# ============================================================
def test_chat_v2_meta_recap_RAG_우회(_reset_state) -> None:  # type: ignore[no-untyped-def]
    fake = _FakeOrchestrator(retrieval=None, intent=Intent.META_RECAP, strategy=None)
    _install_orchestrator(_reset_state, fake)
    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "위 내용 요약", "mode": "auto", "chat_history": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metadata"]["intent"] == "meta_recap"
    assert body["metadata"]["selected_strategy"] is None
    assert body["source_documents"] == []
    assert "meta:meta_recap" in body["answer"]


# ============================================================
# 시나리오 3: 첨부 — vision 자동 라우팅
# ============================================================
def test_chat_v2_attachment_vision(_reset_state) -> None:  # type: ignore[no-untyped-def]
    fake = _FakeOrchestrator(
        retrieval=RetrievalResult(
            documents=(),
            citations=(),
            metadata={"answer": "이미지 분석", "pattern": "Vision"},
        ),
        intent=Intent.NEW_QUESTION,
        strategy="vision",
    )
    _install_orchestrator(_reset_state, fake)
    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={
            "question": "이 도판은?",
            "mode": "auto",
            "chat_history": [],
            "attachments": [
                {"type": "image", "data_url": "https://example.com/img.jpg", "name": "img.jpg"}
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metadata"]["selected_strategy"] == "vision"


# ============================================================
# 시나리오 4: 오케스트레이터 예외 — 500
# ============================================================
def test_chat_v2_오케스트레이터_예외_500(_reset_state) -> None:  # type: ignore[no-untyped-def]
    class _BadOrch:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated")

    _install_orchestrator(_reset_state, _BadOrch())
    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={"question": "?", "mode": "auto", "chat_history": []},
    )
    assert resp.status_code == 500
    assert "오케스트레이터" in resp.json()["detail"]


# ============================================================
# 시나리오 5: 기존 /chat/sync 회귀 0 — 별도 라우트라 영향 없음
# ============================================================
def test_chat_v2_라우트_등록_확인() -> None:
    """라우터가 정상 등록됐는지 — OPTIONS 또는 OpenAPI 스키마로 확인."""
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/chat/v2" in paths


# ============================================================
# envelope 변환 헬퍼 단독 — _coerce_int_list / _coerce_str_list
# ============================================================
def test_envelope_coerce_int_list_json() -> None:
    """metadata.cited_pages 가 json.dumps 문자열로 와도 list[int] 로 복원."""
    from api.routes._chat_v2_envelope import _coerce_int_list

    assert _coerce_int_list("[1, 5, 780]") == [1, 5, 780]
    assert _coerce_int_list("1,5,780") == [1, 5, 780]
    assert _coerce_int_list("") == []
    assert _coerce_int_list(None) == []
    assert _coerce_int_list([1, 2, 3]) == [1, 2, 3]


def test_envelope_coerce_str_list_json() -> None:
    from api.routes._chat_v2_envelope import _coerce_str_list

    assert _coerce_str_list('["a", "b"]') == ["a", "b"]
    assert _coerce_str_list("") == []
    assert _coerce_str_list(None) == []
    assert _coerce_str_list(["a", "b"]) == ["a", "b"]
    assert _coerce_str_list("not_json") == []  # 파싱 실패 → []


def test_envelope_retrieval_없으면_빈_list_채움(_reset_state) -> None:  # type: ignore[no-untyped-def]
    """META 시나리오에서 cited_pages 등이 빈 list 로 envelope 일관성 유지."""
    fake = _FakeOrchestrator(retrieval=None, intent=Intent.META_RECAP, strategy=None)
    _install_orchestrator(_reset_state, fake)
    client = TestClient(app)
    resp = client.post("/chat/v2", json={"question": "요약", "mode": "auto", "chat_history": []})
    body = resp.json()
    assert body["metadata"]["cited_pages"] == []
    assert body["metadata"]["source_pages"] == []
    assert body["metadata"]["source_pages_label"] == []
    assert body["metadata"]["suggested_followups"] == []
    assert body["metadata"]["tool_calls"] == []
    assert body["metadata"]["tool_call_count"] == 0
    assert body["metadata"]["subgraph"] is None


# ============================================================
# /chat/v2/stream — SSE 시나리오
# ============================================================
def test_chat_v2_stream_chunks_meta(_reset_state) -> None:  # type: ignore[no-untyped-def]
    """SSE — 답변 청크 + meta envelope + done 송출."""
    fake = _FakeOrchestrator(
        retrieval=RetrievalResult(
            documents=(),
            citations=(),
            metadata={"answer": "예정론은 영원한 작정", "pattern": "Hybrid RAG"},
        ),
        intent=Intent.NEW_QUESTION,
        strategy="hybrid",
    )
    _install_orchestrator(_reset_state, fake)
    client = TestClient(app)
    with client.stream(
        "POST", "/chat/v2/stream", json={"question": "예정론?", "mode": "auto", "chat_history": []}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("x-vercel-ai-ui-message-stream") == "v1"
        assert resp.headers.get("X-Trace-Id")
        body = resp.read().decode("utf-8")

    # text-delta 청크가 답변을 분할해 송출
    assert "text-delta" in body
    assert "예정론은" in body
    # meta event 포함 — pattern + intent + envelope 키
    assert '"event": "meta"' in body or "event: meta" in body
    assert "Hybrid RAG" in body  # pattern
    assert "new_question" in body  # intent
    # done 종료
    assert "[DONE]" in body


def test_chat_v2_stream_오케스트레이터_예외_error_event(_reset_state) -> None:  # type: ignore[no-untyped-def]
    """orchestrator 예외 시 error event + done 송출 (HTTP 500 아님)."""

    class _BadOrch:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated stream failure")

    _install_orchestrator(_reset_state, _BadOrch())
    client = TestClient(app)
    with client.stream(
        "POST", "/chat/v2/stream", json={"question": "?", "mode": "auto", "chat_history": []}
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode("utf-8")
    assert "error" in body
    assert "RuntimeError" in body
    assert "[DONE]" in body


def test_chat_v2_stream_라우트_등록() -> None:
    """openapi 에 /chat/v2/stream 등록 확인."""
    client = TestClient(app)
    resp = client.get("/openapi.json")
    paths = resp.json()["paths"]
    assert "/chat/v2/stream" in paths


# ============================================================
# chat_history → Conversation.turns 복원 (브라우저 보유 history 패턴)
# ============================================================
def test_chat_v2_chat_history_가_state_turns_로_복원(_reset_state) -> None:  # type: ignore[no-untyped-def]
    """클라이언트가 보낸 chat_history 가 ConversationState.conversation.turns 로 복원되어
    last_turn / META_RECAP 등의 노드 분기에 사용됨을 검증."""
    captured: list = []

    class _CaptureOrch:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured.append(state)
            from datetime import UTC, datetime as _dt

            from chatbot.domain.conversation import Message as _Msg
            from chatbot.domain.conversation import Turn as _Turn

            answer = _Msg(role="assistant", content="echo")
            return state.model_copy(
                update={
                    "conversation": state.conversation.append_turn(
                        _Turn(
                            user_message=state.pending_user_message,
                            intent=Intent.NEW_QUESTION,
                            answer=answer,
                            trace_id=state.trace_id,
                            elapsed_ms=1,
                            started_at=_dt.now(UTC),
                        )
                    ),
                    "pending_intent": Intent.NEW_QUESTION,
                    "pending_answer": answer,
                }
            )

    _install_orchestrator(_reset_state, _CaptureOrch())
    client = TestClient(app)
    resp = client.post(
        "/chat/v2",
        json={
            "question": "위 내용 요약",
            "chat_history": [
                {"role": "user", "content": "예정론?"},
                {"role": "assistant", "content": "예정론은 칼빈 신학의 핵심..."},
                {"role": "user", "content": "베자는?"},
                {"role": "assistant", "content": "베자는 칼빈의 후계자..."},
            ],
        },
    )
    assert resp.status_code == 200
    assert len(captured) == 1
    state = captured[0]
    assert len(state.conversation.turns) == 2  # 4 메시지 → 2 페어 → 2 Turn
    assert state.conversation.turns[0].user_message.content == "예정론?"
    assert state.conversation.turns[0].answer.content.startswith("예정론은")
    assert state.conversation.turns[1].user_message.content == "베자는?"
    assert state.conversation.last_turn is not None


def test_chat_v2_빈_chat_history_빈_turns(_reset_state) -> None:  # type: ignore[no-untyped-def]
    """chat_history 미전달 시 turns 빈 tuple — 첫 턴 동작 보존."""
    captured: list = []

    class _Orch:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured.append(state)
            from datetime import UTC, datetime as _dt

            from chatbot.domain.conversation import Message as _Msg
            from chatbot.domain.conversation import Turn as _Turn

            answer = _Msg(role="assistant", content="ok")
            return state.model_copy(
                update={
                    "conversation": state.conversation.append_turn(
                        _Turn(
                            user_message=state.pending_user_message,
                            intent=Intent.NEW_QUESTION,
                            answer=answer,
                            trace_id=state.trace_id,
                            elapsed_ms=0,
                            started_at=_dt.now(UTC),
                        )
                    ),
                    "pending_intent": Intent.NEW_QUESTION,
                    "pending_answer": answer,
                }
            )

    _install_orchestrator(_reset_state, _Orch())
    client = TestClient(app)
    resp = client.post("/chat/v2", json={"question": "처음", "chat_history": []})
    assert resp.status_code == 200
    assert captured[0].conversation.turns == ()
