"""BaseTool ↔ domain.Tool 양방향 어댑터 테스트."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from chatbot.domain.tools import ToolResult, ToolSchema
from chatbot.infrastructure.tools import basetool_to_domain_tool, domain_tool_to_basetool


# ============================================================
# domain → langchain
# ============================================================
class _Search:
    schema = ToolSchema(
        name="search_documents",
        description="본문 검색",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "k": {"type": "integer", "description": "청크 수", "default": 5},
            },
            "required": ["query"],
        },
    )

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=f"q={arguments.get('query')} k={arguments.get('k')}")


def test_domain_to_langchain_다중_인자_정상():
    bt = domain_tool_to_basetool(_Search())
    assert bt.name == "search_documents"
    out = bt.invoke({"query": "예정론", "k": 3})
    assert out == "q=예정론 k=3"


def test_domain_to_langchain_default_적용():
    bt = domain_tool_to_basetool(_Search())
    out = bt.invoke({"query": "예정론"})
    assert out == "q=예정론 k=5"  # k default


class _Fail:
    schema = ToolSchema(
        name="fail",
        description="b",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="실패함", is_error=True)


def test_domain_to_langchain_is_error_RuntimeError_변환():
    bt = domain_tool_to_basetool(_Fail())
    with pytest.raises(RuntimeError, match="실패함"):
        bt.invoke({"x": "y"})


class _Bare:
    schema = ToolSchema(name="bare", description="no args")

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="ok")


def test_domain_to_langchain_빈_parameters():
    """parameters 가 비면 args_schema=None — 인자 없는 wrapper."""
    bt = domain_tool_to_basetool(_Bare())
    assert bt.invoke({}) == "ok"


# ============================================================
# langchain → domain
# ============================================================
def test_langchain_to_domain_정상():
    def _double(n: int) -> str:
        return str(n * 2)

    base = StructuredTool.from_function(func=_double, name="double", description="double")
    domain_tool = basetool_to_domain_tool(base)
    assert domain_tool.schema.name == "double"
    result = domain_tool.invoke({"n": 5})
    assert result.content == "10"
    assert result.is_error is False


def test_langchain_to_domain_호출실패는_is_error():
    def _boom(x: str) -> str:
        raise ValueError(f"boom:{x}")

    base = StructuredTool.from_function(func=_boom, name="boom", description="b")
    domain_tool = basetool_to_domain_tool(base)
    result = domain_tool.invoke({"x": "hi"})
    assert result.is_error is True
    assert "ValueError" in result.content


def test_langchain_to_domain_is_available_항상_True():
    def _x(y: str) -> str:
        return y

    base = StructuredTool.from_function(func=_x, name="x", description="x")
    domain_tool = basetool_to_domain_tool(base)
    ok, reason = domain_tool.is_available()
    assert ok is True and reason is None
