"""AgenticRAG 의 메시지 파서 단위 테스트 (LLM/DB 호출 0회).

query() 와 stream_steps() 가 공유하는 메시지 파싱 책임을 분리한 헬퍼:
- parse_agent_messages(messages) -> AgentParseResult (query 용)
- message_to_stream_events(msg) -> Iterator[dict] (stream_steps 용)
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from rag_core.agentic import (
    AgentParseResult,
    message_to_stream_events,
    parse_agent_messages,
)


# ====================================================================
# parse_agent_messages
# ====================================================================
def test_parse_extracts_final_answer_from_last_aimessage_with_content() -> None:
    msgs = [
        HumanMessage(content="질문"),
        AIMessage(content="", tool_calls=[{"name": "search_documents", "args": {"query": "Q"}, "id": "1"}]),
        ToolMessage(content="검색 결과", name="search_documents", tool_call_id="1"),
        AIMessage(content="최종 답변입니다."),
    ]
    parsed = parse_agent_messages(msgs)
    assert parsed.final_answer == "최종 답변입니다."


def test_parse_collects_tool_calls() -> None:
    msgs = [
        AIMessage(content="", tool_calls=[
            {"name": "search_documents", "args": {"query": "예정론"}, "id": "1"},
            {"name": "search_documents", "args": {"query": "어거스틴"}, "id": "2"},
        ]),
    ]
    parsed = parse_agent_messages(msgs)
    assert len(parsed.tool_calls) == 2
    assert parsed.tool_calls[0]["tool"] == "search_documents"
    assert parsed.tool_calls[0]["args"] == {"query": "예정론"}


def test_parse_collects_search_documents_results() -> None:
    msgs = [
        ToolMessage(content="청크 1 본문", name="search_documents", tool_call_id="1"),
        ToolMessage(content="청크 2 본문", name="search_documents", tool_call_id="2"),
        ToolMessage(content="다른 도구 결과", name="other_tool", tool_call_id="3"),
    ]
    parsed = parse_agent_messages(msgs)
    assert parsed.source_documents == ["청크 1 본문", "청크 2 본문"]


def test_parse_empty_messages_returns_default() -> None:
    parsed = parse_agent_messages([])
    assert parsed == AgentParseResult()


def test_parse_skips_tool_only_aimessage_for_final_answer() -> None:
    """tool_calls만 있는 AIMessage(content 비어 있음)는 답변으로 잡지 않음."""
    msgs = [
        AIMessage(content="실제 답변"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]),
    ]
    parsed = parse_agent_messages(msgs)
    assert parsed.final_answer == "실제 답변"


# ====================================================================
# message_to_stream_events
# ====================================================================
def test_event_for_aimessage_with_tool_calls() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "search_documents", "args": {"query": "예정론", "k": 5}, "id": "1"}],
    )
    events = list(message_to_stream_events(msg))
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "thinking"
    assert e["tool"] == "search_documents"
    assert e["args"] == {"query": "예정론", "k": 5}
    assert "검색 도구 호출" in e["message"]


def test_event_for_aimessage_with_content_only() -> None:
    msg = AIMessage(content="답변 내용")
    events = list(message_to_stream_events(msg))
    assert events == [{"type": "answer", "content": "답변 내용"}]


def test_event_for_search_documents_tool_message() -> None:
    msg = ToolMessage(
        content="청크 1\n\n---\n\n청크 2\n\n---\n\n청크 3",
        name="search_documents",
        tool_call_id="1",
    )
    events = list(message_to_stream_events(msg))
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "tool_result"
    assert "3개 청크" in e["message"]
    assert e["source_doc"].startswith("청크 1")


def test_event_for_other_tool_message_is_skipped() -> None:
    """search_documents 외 도구는 stream 이벤트로 변환하지 않음."""
    msg = ToolMessage(content="다른 도구 출력", name="other_tool", tool_call_id="1")
    events = list(message_to_stream_events(msg))
    assert events == []


def test_event_for_humanmessage_is_skipped() -> None:
    events = list(message_to_stream_events(HumanMessage(content="질문")))
    assert events == []


def test_event_for_aimessage_with_multiple_tool_calls_yields_each() -> None:
    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_documents", "args": {"query": "A"}, "id": "1"},
            {"name": "search_documents", "args": {"query": "B"}, "id": "2"},
        ],
    )
    events = list(message_to_stream_events(msg))
    assert len(events) == 2
    assert all(e["type"] == "thinking" for e in events)
    assert {e["args"]["query"] for e in events} == {"A", "B"}
