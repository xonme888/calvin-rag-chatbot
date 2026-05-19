"""SupabaseTurnArtifactStore 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from chatbot.domain.turn_artifact import TurnArtifact
from chatbot.infrastructure.persistence.turn_artifact_store import SupabaseTurnArtifactStore


class _FakeResponse:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, recorder: dict[str, Any], rows: list[dict]) -> None:
        self._recorder = recorder
        self._rows = rows
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None

    def eq(self, col: str, val: Any) -> _FakeQuery:
        self._filters.append((col, val))
        self._recorder.setdefault("filters", []).append((col, val))
        return self

    def limit(self, n: int) -> _FakeQuery:
        self._limit = n
        return self

    def execute(self) -> _FakeResponse:
        rows = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResponse(rows)


class _FakeInsert:
    def __init__(self, recorder: dict[str, Any], payload: dict[str, Any]) -> None:
        recorder.setdefault("inserts", []).append(payload)

    def execute(self) -> _FakeResponse:
        return _FakeResponse([])


class _FakeTable:
    def __init__(self, recorder: dict[str, Any], rows: list[dict]) -> None:
        self._recorder = recorder
        self._rows = rows

    def select(self, *_cols: str) -> _FakeQuery:
        return _FakeQuery(self._recorder, self._rows)

    def insert(self, payload: dict[str, Any]) -> _FakeInsert:
        return _FakeInsert(self._recorder, payload)


class _FakeClient:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.recorder: dict[str, Any] = {}

    def table(self, name: str) -> _FakeTable:
        self.recorder["table"] = name
        return _FakeTable(self.recorder, self.rows)


def _artifact() -> TurnArtifact:
    return TurnArtifact(
        retrieval_result_ref="art:c1:0",
        conversation_id="c1",
        turn_index=0,
        pattern="hybrid",
        selected_strategy="hybrid",
        standalone_question="질문",
        index_version="idx-v1",
        created_at=datetime.now(UTC),
    )


def test_save_if_absent_insert():
    client = _FakeClient(rows=[])
    store = SupabaseTurnArtifactStore(client=client)  # type: ignore[arg-type]
    store.save_if_absent(_artifact(), user_id="u1")
    assert client.recorder["table"] == "conversation_turn_artifacts"
    assert len(client.recorder.get("inserts", [])) == 1


def test_save_if_absent_existing_skip():
    rows = [
        {
            "retrieval_result_ref": "art:c1:0",
            "conversation_id": "c1",
            "turn_index": 0,
            "pattern": "hybrid",
            "selected_strategy": "hybrid",
            "standalone_question": "질문",
            "index_version": "idx-v1",
            "payload": {},
            "created_at": datetime.now(UTC).isoformat(),
            "user_id": "u1",
        }
    ]
    client = _FakeClient(rows=rows)
    store = SupabaseTurnArtifactStore(client=client)  # type: ignore[arg-type]
    store.save_if_absent(_artifact(), user_id="u1")
    assert client.recorder.get("inserts", []) == []


def test_load_by_turn():
    rows = [
        {
            "retrieval_result_ref": "art:c1:0",
            "conversation_id": "c1",
            "turn_index": 0,
            "pattern": "kg",
            "selected_strategy": "kg",
            "standalone_question": "질문",
            "index_version": "idx-v2",
            "payload": {"tool_call_count": 1, "tool_names": ["search_documents"]},
            "created_at": datetime.now(UTC).isoformat(),
            "user_id": "u1",
        }
    ]
    client = _FakeClient(rows=rows)
    store = SupabaseTurnArtifactStore(client=client)  # type: ignore[arg-type]
    loaded = store.load_by_turn("c1", 0, user_id="u1")
    assert loaded is not None
    assert loaded.retrieval_result_ref == "art:c1:0"
    assert loaded.pattern == "kg"
    assert loaded.tool_call_count == 1
