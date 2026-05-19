"""Supabase TurnArtifactStore — 턴 단위 retrieval 스냅샷 저장/조회."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chatbot.domain.persistence import TurnArtifactStore
from chatbot.domain.turn_artifact import (
    CitationSummary,
    DocumentSummary,
    GraphSummary,
    TurnArtifact,
)

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "conversation_turn_artifacts"


class SupabaseTurnArtifactStore:
    """TurnArtifactStore 의 Supabase 구현.

    원칙:
    - immutable snapshot: 동일 retrieval_result_ref 가 이미 있으면 저장하지 않음.
    - 사용자 격리: RLS + user_id eq 필터 이중 방어.
    """

    name: str = "supabase_turn_artifact"

    def __init__(self, *, client: Client) -> None:
        self._client = client

    def save_if_absent(self, artifact: TurnArtifact, *, user_id: str) -> None:
        """아티팩트 최초 1회만 저장."""
        existing = self.load_by_ref(artifact.retrieval_result_ref, user_id=user_id)
        if existing is not None:
            return
        payload = {
            "citations": [c.model_dump(mode="json") for c in artifact.citations],
            "documents": [d.model_dump(mode="json") for d in artifact.documents],
            "graph": (
                artifact.graph.model_dump(mode="json") if artifact.graph is not None else None
            ),
            "tool_call_count": artifact.tool_call_count,
            "tool_names": list(artifact.tool_names),
        }
        self._client.table(_TABLE).insert(
            {
                "retrieval_result_ref": artifact.retrieval_result_ref,
                "conversation_id": artifact.conversation_id,
                "user_id": user_id,
                "turn_index": artifact.turn_index,
                "pattern": artifact.pattern,
                "selected_strategy": artifact.selected_strategy,
                "standalone_question": artifact.standalone_question,
                "index_version": artifact.index_version,
                "payload": payload,
                "created_at": artifact.created_at.isoformat(),
            }
        ).execute()

    def load_by_turn(
        self,
        conversation_id: str,
        turn_index: int,
        *,
        user_id: str,
    ) -> TurnArtifact | None:
        res = (
            self._client.table(_TABLE)
            .select(
                "retrieval_result_ref, conversation_id, turn_index, pattern, "
                "selected_strategy, standalone_question, index_version, payload, created_at"
            )
            .eq("conversation_id", conversation_id)
            .eq("turn_index", turn_index)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return _row_to_artifact(rows[0])

    def load_by_ref(self, retrieval_result_ref: str, *, user_id: str) -> TurnArtifact | None:
        res = (
            self._client.table(_TABLE)
            .select(
                "retrieval_result_ref, conversation_id, turn_index, pattern, "
                "selected_strategy, standalone_question, index_version, payload, created_at"
            )
            .eq("retrieval_result_ref", retrieval_result_ref)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        return _row_to_artifact(rows[0])


def _row_to_artifact(row: dict[str, Any]) -> TurnArtifact:
    """DB row → TurnArtifact."""
    payload = row.get("payload") or {}
    graph_raw = payload.get("graph")
    created_at_raw = row.get("created_at")
    created_at = (
        datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
        if created_at_raw
        else datetime.now(UTC)
    )
    return TurnArtifact(
        retrieval_result_ref=str(row["retrieval_result_ref"]),
        conversation_id=str(row["conversation_id"]),
        turn_index=int(row["turn_index"]),
        pattern=row.get("pattern"),
        selected_strategy=row.get("selected_strategy"),
        standalone_question=row.get("standalone_question"),
        index_version=str(row.get("index_version") or "unknown"),
        citations=tuple(CitationSummary.model_validate(c) for c in payload.get("citations") or []),
        documents=tuple(DocumentSummary.model_validate(d) for d in payload.get("documents") or []),
        graph=GraphSummary.model_validate(graph_raw) if graph_raw else None,
        tool_call_count=int(payload.get("tool_call_count") or 0),
        tool_names=tuple(str(n) for n in (payload.get("tool_names") or [])),
        created_at=created_at,
    )


_: type[TurnArtifactStore] = SupabaseTurnArtifactStore  # type: ignore[type-abstract]
