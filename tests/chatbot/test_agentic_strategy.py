"""AgenticStrategy 합성 테스트 — Fake LLM 으로 LLM 호출 0회 보장.

create_agent 가 *그래프 빌드만* 즉시 수행하고 invoke 는 LLM 호출이 필요하므로,
본 테스트는 _build_result / supports / is_available 등 *순수* 메서드만 검증.
실제 invoke 회귀는 Phase 2 audit 의 회귀 테스트가 별도로 다룬다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from chatbot.domain.conversation import Attachment
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.domain.tools import ToolResult, ToolSchema
from chatbot.infrastructure.parsers import AgentParseResult
from chatbot.infrastructure.strategies import AgenticStrategy, AgenticStrategyConfig


class _Echo:
    schema = ToolSchema(
        name="echo",
        description="echo back",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=f"echo:{arguments.get('x')}")


class _Unavail:
    schema = ToolSchema(name="unavail", description="b")

    def is_available(self) -> tuple[bool, str | None]:
        return (False, "미설정")

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="")


def _make_strategy(tools=None) -> AgenticStrategy:
    llm = FakeListChatModel(responses=["답변"])
    return AgenticStrategy(
        llm=llm,
        tools=tools or [_Echo()],
        config=AgenticStrategyConfig(),
    )


def test_agentic_name_label():
    s = _make_strategy()
    assert s.name == "agentic"
    assert s.label == "Agentic"


def test_agentic_is_available_모든_도구_가용():
    s = _make_strategy()
    assert s.is_available() == (True, None)


def test_agentic_is_available_도구_비활성_반영():
    s = _make_strategy(tools=[_Echo(), _Unavail()])
    ok, reason = s.is_available()
    assert ok is False
    assert "unavail" in (reason or "")


def test_agentic_supports_attachments_거부():
    s = _make_strategy()
    assert s.supports(RetrievalRequest(standalone_question="?")) is True
    req_att = RetrievalRequest(
        standalone_question="?",
        attachments=(Attachment(kind="image_url", value="http://x"),),
    )
    assert s.supports(req_att) is False


def test_agentic_build_result_envelope():
    s = _make_strategy()
    parsed = AgentParseResult(
        final_answer="예정론은 [p.1]",
        tool_calls=[{"tool": "search_documents", "args": {"query": "예정론"}}],
        source_documents=["[page 1] 본문"],
    )
    result = s._build_result(parsed=parsed, elapsed_ms=42)
    assert result.metadata["pattern"] == "Agentic RAG"
    assert result.metadata["answer"] == "예정론은 [p.1]"
    assert result.metadata["tool_call_count"] == "1"
    assert result.metadata["elapsed_ms"] == "42"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "search_documents"
    assert len(result.documents) == 1
    assert result.documents[0].chunk_id == "agentic_tool_output:0"
    assert result.documents[0].page is None


def test_agentic_build_result_도구호출_0개():
    s = _make_strategy()
    parsed = AgentParseResult(final_answer="직접 답변", tool_calls=[], source_documents=[])
    result = s._build_result(parsed=parsed, elapsed_ms=10)
    assert result.tool_calls == ()
    assert result.documents == ()
    assert result.metadata["tool_call_count"] == "0"
