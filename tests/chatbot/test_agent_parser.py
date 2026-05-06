"""Agent message parser 테스트 — parse_messages, message_to_events, parsed_to_tool_calls."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chatbot.domain.retrieval import ToolCallRecord
from chatbot.infrastructure.parsers import (
    AgentParseResult,
    message_to_events,
    parse_messages,
    parsed_to_tool_calls,
)


# ============================================================
# parse_messages
# ============================================================
def _typical_messages() -> list:
    return [
        HumanMessage(content="예정론?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "search_documents", "args": {"query": "예정론"}, "id": "tc1"}],
        ),
        ToolMessage(
            content="[page 1] 본문\n\n---\n\n[page 2] 본문2",
            tool_call_id="tc1",
            name="search_documents",
        ),
        AIMessage(content="예정론은 [p.1]"),
    ]


def test_parse_messages_정상():
    result = parse_messages(_typical_messages())
    assert result.final_answer == "예정론은 [p.1]"
    assert result.tool_calls == [{"tool": "search_documents", "args": {"query": "예정론"}}]
    assert result.source_documents == ["[page 1] 본문\n\n---\n\n[page 2] 본문2"]


def test_parse_messages_역방향_마지막_답변():
    """tool 호출 후 답변이 여러 개라면 *마지막* AIMessage 가 final_answer."""
    msgs = [AIMessage(content="첫번째"), AIMessage(content="두번째")]
    assert parse_messages(msgs).final_answer == "두번째"


def test_parse_messages_빈_AIMessage_무시():
    """tool_calls 만 있는 빈 content AIMessage 는 final_answer 후보 아님."""
    msgs = [
        AIMessage(content="실답변"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "i"}]),
    ]
    # 마지막 AIMessage 가 빈 content → 그 이전 비-empty 답변
    assert parse_messages(msgs).final_answer == "실답변"


def test_parse_messages_빈_입력():
    result = parse_messages([])
    assert result == AgentParseResult()


# ============================================================
# message_to_events
# ============================================================
def test_message_to_events_thinking():
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "search_documents", "args": {"query": "예정론"}, "id": "tc1"}],
    )
    events = list(message_to_events(msg))
    assert len(events) == 1
    assert events[0]["type"] == "thinking"
    assert events[0]["tool"] == "search_documents"
    assert events[0]["details"] == 'query="예정론"'


def test_message_to_events_tool_result():
    msg = ToolMessage(
        content="[page 1] 본문\n\n---\n\n[page 2] 본문2",
        tool_call_id="tc1",
        name="search_documents",
    )
    events = list(message_to_events(msg))
    assert events[0]["type"] == "tool_result"
    assert "2개 청크" in events[0]["message"]
    assert events[0]["source_doc"] == msg.content


def test_message_to_events_answer():
    msg = AIMessage(content="답변 본문")
    events = list(message_to_events(msg))
    assert events == [{"type": "answer", "content": "답변 본문"}]


def test_message_to_events_빈_AIMessage_이벤트_없음():
    assert list(message_to_events(AIMessage(content=""))) == []


def test_message_to_events_HumanMessage_무시():
    assert list(message_to_events(HumanMessage(content="질문"))) == []


# ============================================================
# parsed_to_tool_calls
# ============================================================
def test_parsed_to_tool_calls_타입_변환():
    parsed = AgentParseResult(
        final_answer="x",
        tool_calls=[
            {"tool": "search_documents", "args": {"query": "예정론", "k": 5}},
        ],
    )
    records = parsed_to_tool_calls(parsed, elapsed_ms_per_call=10)
    assert len(records) == 1
    assert isinstance(records[0], ToolCallRecord)
    assert records[0].tool_name == "search_documents"
    assert records[0].arguments == {"query": "예정론", "k": "5"}
    assert records[0].elapsed_ms == 10


def test_parsed_to_tool_calls_빈_args_지원():
    parsed = AgentParseResult(
        final_answer="x",
        tool_calls=[{"tool": "x", "args": None}],  # type: ignore[dict-item]
    )
    records = parsed_to_tool_calls(parsed)
    assert records[0].arguments == {}
