"""RetrievalResult + Turn → TurnArtifact 변환기."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC

from chatbot.domain.conversation import Turn
from chatbot.domain.retrieval import RetrievalResult
from chatbot.domain.turn_artifact import (
    CitationSummary,
    DocumentSummary,
    GraphSummary,
    TurnArtifact,
    make_retrieval_result_ref,
)

_P_DOT_PATTERN = re.compile(r"^p\.(\d+)$")


def build_turn_artifact(
    *,
    conversation_id: str,
    turn_index: int,
    turn: Turn,
    retrieval: RetrievalResult,
    index_version: str,
) -> TurnArtifact:
    """턴 완료 시점 retrieval 결과를 경량 스냅샷으로 축약."""
    retrieval_ref = turn.retrieval_result_ref or make_retrieval_result_ref(
        conversation_id, turn_index
    )
    source_to_page: dict[str, int] = {}
    doc_summaries: list[DocumentSummary] = []
    for doc in retrieval.documents:
        page_one = (doc.page + 1) if doc.page is not None else None
        if page_one is not None and doc.source_id not in source_to_page:
            source_to_page[doc.source_id] = page_one
        chunk_ref = doc.chunk_id.strip() or _content_hash(doc.content)
        preview = doc.content[:160]
        doc_summaries.append(
            DocumentSummary(
                source_id=doc.source_id,
                page=page_one,
                chunk_ref=chunk_ref,
                score=doc.score,
                preview=preview,
            )
        )

    citations: list[CitationSummary] = []
    for c in retrieval.citations:
        page = _parse_page_label(c.page_label) or source_to_page.get(c.source_id)
        citations.append(
            CitationSummary(
                page=page,
                page_label=c.page_label,
                source=c.source_id,
            )
        )

    graph_summary = _build_graph_summary(retrieval)
    tool_names = _dedup_tool_names([tc.tool_name for tc in retrieval.tool_calls])
    created_at = (
        turn.started_at
        if turn.started_at.tzinfo is not None
        else turn.started_at.replace(tzinfo=UTC)
    )
    return TurnArtifact(
        retrieval_result_ref=retrieval_ref,
        conversation_id=conversation_id,
        turn_index=turn_index,
        pattern=retrieval.metadata.get("pattern"),
        selected_strategy=turn.selected_strategy,
        standalone_question=turn.standalone_question,
        index_version=index_version,
        citations=tuple(citations),
        documents=tuple(doc_summaries),
        graph=graph_summary,
        tool_call_count=len(retrieval.tool_calls),
        tool_names=tuple(tool_names),
        created_at=created_at,
    )


def _parse_page_label(page_label: str) -> int | None:
    """``p.N`` 라벨 파싱. 권/장 표기는 문서 요약 page 폴백을 사용."""
    match = _P_DOT_PATTERN.match(page_label.strip())
    if not match:
        return None
    return int(match.group(1))


def _build_graph_summary(retrieval: RetrievalResult) -> GraphSummary | None:
    if retrieval.subgraph is None:
        return None
    subgraph = retrieval.subgraph
    node_count = int(retrieval.metadata.get("graph_node_count") or len(subgraph.nodes))
    edge_count = int(retrieval.metadata.get("graph_edge_count") or len(subgraph.edges))
    top_nodes = tuple(n.label for n in subgraph.nodes[:10])
    label_by_id = {n.id: n.label for n in subgraph.nodes}
    top_edges = tuple(
        f"{label_by_id.get(e.source, e.source)} -[{e.label or 'RELATED_TO'}]-> "
        f"{label_by_id.get(e.target, e.target)}"
        for e in subgraph.edges[:10]
    )
    return GraphSummary(
        graph_node_count=node_count,
        graph_edge_count=edge_count,
        top_nodes=top_nodes,
        top_edges=top_edges,
    )


def _dedup_tool_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
