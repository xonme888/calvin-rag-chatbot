"""턴 단위 Retrieval 아티팩트 도메인 모델.

목적:
- Conversation.turns 는 가볍게 유지.
- RAG/KG 근거는 별도 아티팩트로 저장해 reopen 시 복원.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def make_retrieval_result_ref(conversation_id: str, turn_index: int) -> str:
    """결정적 아티팩트 키.

    형식: ``art:{conversation_id}:{turn_index}``
    """
    return f"art:{conversation_id}:{turn_index}"


class CitationSummary(BaseModel):
    """인용 요약 — 페이지/라벨/소스만 보존."""

    model_config = ConfigDict(frozen=True)

    page: int | None = None
    page_label: str
    source: str


class DocumentSummary(BaseModel):
    """문서 요약 — 원문 대신 식별자/짧은 미리보기만 보존."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    page: int | None = None
    chunk_ref: str
    score: float | None = None
    preview: str


class GraphSummary(BaseModel):
    """KG 요약 — 카운트 + 상위 노드/엣지 텍스트."""

    model_config = ConfigDict(frozen=True)

    graph_node_count: int = 0
    graph_edge_count: int = 0
    top_nodes: tuple[str, ...] = ()
    top_edges: tuple[str, ...] = ()


class TurnArtifact(BaseModel):
    """대화 reopen 용 턴 단위 근거 스냅샷."""

    model_config = ConfigDict(frozen=True)

    retrieval_result_ref: str
    conversation_id: str
    turn_index: int = Field(ge=0)
    pattern: str | None = None
    selected_strategy: str | None = None
    standalone_question: str | None = None
    index_version: str = "unknown"
    citations: tuple[CitationSummary, ...] = ()
    documents: tuple[DocumentSummary, ...] = ()
    graph: GraphSummary | None = None
    tool_call_count: int = Field(default=0, ge=0)
    tool_names: tuple[str, ...] = ()
    created_at: datetime
