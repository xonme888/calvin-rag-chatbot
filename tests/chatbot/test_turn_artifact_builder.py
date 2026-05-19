"""turn_artifact_builder 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

from chatbot.domain.conversation import Message, Turn
from chatbot.domain.corpus import Citation, DocumentRef
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import GraphEdge, GraphNode, RetrievalResult, Subgraph, ToolCallRecord
from chatbot.domain.turn_artifact import make_retrieval_result_ref
from chatbot.infrastructure.persistence.turn_artifact_builder import build_turn_artifact


def test_make_retrieval_result_ref_결정적():
    assert make_retrieval_result_ref("conv-1", 3) == "art:conv-1:3"


def test_build_turn_artifact_요약_생성():
    turn = Turn(
        user_message=Message(role="user", content="질문"),
        intent=Intent.NEW_QUESTION,
        standalone_question="재작성 질문",
        selected_strategy="kg",
        retrieval_result_ref="art:conv-1:0",
        answer=Message(role="assistant", content="답"),
        trace_id="t",
        elapsed_ms=12,
        started_at=datetime.now(UTC),
    )
    retrieval = RetrievalResult(
        documents=(
            DocumentRef(
                corpus_id="calvin",
                source_id="institutes_v1",
                chunk_id="chunk-a",
                page=4,
                content="가나다라마바사아자차카타파하",
                score=0.88,
            ),
        ),
        citations=(
            Citation(
                corpus_id="calvin",
                source_id="institutes_v1",
                page_label="p.5",
                snippet="가나다",
            ),
        ),
        subgraph=Subgraph(
            nodes=(
                GraphNode(id="n1", label="칼빈"),
                GraphNode(id="n2", label="베자"),
            ),
            edges=(GraphEdge(source="n1", target="n2", label="영향"),),
        ),
        tool_calls=(
            ToolCallRecord(
                tool_name="search_documents",
                arguments={"q": "예정론"},
                result_preview="ok",
                elapsed_ms=3,
            ),
        ),
        metadata={"pattern": "kg", "graph_node_count": "2", "graph_edge_count": "1"},
    )

    artifact = build_turn_artifact(
        conversation_id="conv-1",
        turn_index=0,
        turn=turn,
        retrieval=retrieval,
        index_version="idx-v1",
    )
    assert artifact.retrieval_result_ref == "art:conv-1:0"
    assert artifact.selected_strategy == "kg"
    assert artifact.pattern == "kg"
    assert artifact.index_version == "idx-v1"
    assert artifact.citations[0].page == 5
    assert artifact.documents[0].page == 5
    assert artifact.documents[0].chunk_ref == "chunk-a"
    assert artifact.tool_call_count == 1
    assert artifact.tool_names == ("search_documents",)
    assert artifact.graph is not None
    assert artifact.graph.graph_node_count == 2
    assert artifact.graph.graph_edge_count == 1
