"""SupabaseConversationStore 단위 테스트 — Fake Supabase Client 로 SDK 호출 검증.

실제 Supabase 통합 테스트는 testcontainers 또는 운영 환경의 ``test_supabase_integration.py``
가 별도로 다룬다. 본 모듈은:
- save 가 upsert 호출, user_id/state/title 페이로드 정확히 전송
- load 가 .eq("id").eq("user_id") 두 필터 모두 적용 (RLS 추가 방어선)
- list_for_user 가 updated_at desc + limit + before 처리
- delete 가 silent no-op (다른 user_id 시도 시 RLS 가 0건 매칭)

LLM 호출 0. supabase 패키지의 *호출 시그니처* 만 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent
from chatbot.infrastructure.persistence import SupabaseConversationStore


# ============================================================
# Fake Supabase Client — fluent API 시뮬레이션
# ============================================================
class _FakeQuery:
    """Supabase fluent query — table.select.eq.eq.execute 체인."""

    def __init__(self, recorder: dict[str, Any], rows: list[dict] | None = None) -> None:
        self._recorder = recorder
        self._rows = rows or []
        self._filters: list[tuple[str, str, Any]] = []
        self._limit_val: int | None = None
        self._order: tuple[str, bool] | None = None

    def select(self, *_args: str) -> _FakeQuery:
        return self

    def eq(self, col: str, val: Any) -> _FakeQuery:
        self._filters.append(("eq", col, val))
        self._recorder.setdefault("filters", []).append(("eq", col, val))
        return self

    def lt(self, col: str, val: Any) -> _FakeQuery:
        self._filters.append(("lt", col, val))
        self._recorder.setdefault("filters", []).append(("lt", col, val))
        return self

    def order(self, col: str, *, desc: bool = False) -> _FakeQuery:
        self._order = (col, desc)
        self._recorder["order"] = (col, desc)
        return self

    def limit(self, n: int) -> _FakeQuery:
        self._limit_val = n
        self._recorder["limit"] = n
        return self

    def execute(self) -> Any:
        # 필터 조건에 맞는 rows 만 반환 (단순 시뮬)
        out = []
        for row in self._rows:
            if all(_match_filter(row, f) for f in self._filters):
                out.append(row)
        if self._limit_val is not None:
            out = out[: self._limit_val]
        return _FakeResponse(out)


def _match_filter(row: dict, f: tuple[str, str, Any]) -> bool:
    op, col, val = f
    if op == "eq":
        return row.get(col) == val
    if op == "lt":
        return row.get(col) is not None and row[col] < val
    return True


class _FakeResponse:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeUpsert:
    def __init__(self, recorder: dict[str, Any], payload: dict) -> None:
        recorder.setdefault("upserts", []).append(payload)

    def execute(self) -> Any:
        return _FakeResponse([])


class _FakeDelete:
    def __init__(self, recorder: dict[str, Any]) -> None:
        self._recorder = recorder
        self._filters: list[tuple[str, Any]] = []

    def eq(self, col: str, val: Any) -> _FakeDelete:
        self._filters.append((col, val))
        self._recorder.setdefault("delete_filters", []).append((col, val))
        return self

    def execute(self) -> Any:
        return _FakeResponse([])


class _FakeTable:
    def __init__(self, recorder: dict[str, Any], rows: list[dict] | None = None) -> None:
        self._recorder = recorder
        self._rows = rows or []

    def select(self, *cols: str) -> _FakeQuery:
        self._recorder["select"] = cols
        return _FakeQuery(self._recorder, self._rows)

    def upsert(self, payload: dict) -> _FakeUpsert:
        return _FakeUpsert(self._recorder, payload)

    def delete(self) -> _FakeDelete:
        return _FakeDelete(self._recorder)


class _FakeClient:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.recorder: dict[str, Any] = {}
        self._rows = rows or []

    def table(self, name: str) -> _FakeTable:
        self.recorder["table"] = name
        return _FakeTable(self.recorder, self._rows)


# ============================================================
# 헬퍼
# ============================================================
def _make_conversation(*, id_: str = "c1", q: str = "Q", a: str = "A") -> Conversation:
    return Conversation(
        id=id_,
        turns=(
            Turn(
                user_message=Message(role="user", content=q),
                intent=Intent.NEW_QUESTION,
                answer=Message(role="assistant", content=a),
                trace_id="t",
                elapsed_ms=1,
                started_at=datetime.now(UTC),
            ),
        ),
        created_at=datetime.now(UTC),
    )


# ============================================================
# save
# ============================================================
def test_save_upsert_payload_정확():
    client = _FakeClient()
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    store.save(_make_conversation(q="예정론?", a="예정론은..."), user_id="user-uuid-1")

    upserts = client.recorder["upserts"]
    assert len(upserts) == 1
    payload = upserts[0]
    assert payload["id"] == "c1"
    assert payload["user_id"] == "user-uuid-1"
    assert payload["title"] == "예정론?"  # 첫 user_message 의 첫 30자
    assert "state" in payload
    assert "turns" in payload["state"]
    assert client.recorder["table"] == "conversations"


def test_save_빈_turns_title_None():
    client = _FakeClient()
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    conv = Conversation(id="c1", created_at=datetime.now(UTC))
    store.save(conv, user_id="u1")
    assert client.recorder["upserts"][0]["title"] is None


def test_save_긴_질문_30자_컷():
    long_q = "긴" * 100
    client = _FakeClient()
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    store.save(_make_conversation(q=long_q), user_id="u1")
    assert len(client.recorder["upserts"][0]["title"]) == 30


# ============================================================
# load
# ============================================================
def test_load_본인_데이터_복원():
    conv = _make_conversation(q="Q", a="A")
    rows = [{"id": "c1", "user_id": "user-uuid-1", "state": conv.model_dump(mode="json")}]
    client = _FakeClient(rows=rows)
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]

    loaded = store.load("c1", user_id="user-uuid-1")
    assert loaded is not None
    assert loaded.id == "c1"
    assert len(loaded.turns) == 1
    assert loaded.turns[0].user_message.content == "Q"
    # eq 필터 두 개 모두 적용됐는지 (id + user_id)
    filters = client.recorder["filters"]
    assert ("eq", "id", "c1") in filters
    assert ("eq", "user_id", "user-uuid-1") in filters


def test_load_미존재_None():
    client = _FakeClient(rows=[])
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    assert store.load("missing", user_id="u1") is None


def test_load_RLS_시뮬_다른_사용자_차단():
    """RLS 가 user_id 미일치 row 를 차단 → 어댑터의 .eq("user_id") 가 0건 매칭."""
    conv = _make_conversation()
    rows = [{"state": conv.model_dump(mode="json"), "user_id": "u1", "id": "c1"}]
    client = _FakeClient(rows=rows)
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    # u2 로 조회 → 필터에서 0건 매칭 (시뮬)
    assert store.load("c1", user_id="u2") is None


# ============================================================
# list_for_user
# ============================================================
def test_list_user_id_필터_및_정렬():
    rows = [
        {
            "id": "c1",
            "title": "T1",
            "updated_at": "2026-05-06T10:00:00+00:00",
            "state": {"turns": [{}, {}]},
            "user_id": "u1",
        },
        {
            "id": "c2",
            "title": "T2",
            "updated_at": "2026-05-06T11:00:00+00:00",
            "state": {"turns": [{}]},
            "user_id": "u1",
        },
    ]
    client = _FakeClient(rows=rows)
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    summaries = store.list_for_user("u1")
    assert len(summaries) == 2
    assert {s.id for s in summaries} == {"c1", "c2"}
    assert client.recorder["order"] == ("updated_at", True)
    # turn_count 가 state.turns 길이로 계산
    assert {s.turn_count for s in summaries} == {1, 2}


def test_list_limit_적용():
    client = _FakeClient(rows=[])
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    store.list_for_user("u1", limit=10)
    assert client.recorder["limit"] == 10


def test_list_before_커서_lt_필터():
    cutoff = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    client = _FakeClient(rows=[])
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    store.list_for_user("u1", before=cutoff)
    filters = client.recorder["filters"]
    assert any(f[0] == "lt" and f[1] == "updated_at" for f in filters)


# ============================================================
# delete
# ============================================================
def test_delete_filters():
    client = _FakeClient()
    store = SupabaseConversationStore(client=client)  # type: ignore[arg-type]
    store.delete("c1", user_id="u1")
    delete_filters = client.recorder["delete_filters"]
    assert ("id", "c1") in delete_filters
    assert ("user_id", "u1") in delete_filters
