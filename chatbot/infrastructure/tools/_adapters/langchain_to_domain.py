"""LangChain BaseTool → domain.Tool 변환.

PRD-001 의 ``rag_core/tools/registry.py`` 가 등록하는 BaseTool 인스턴스 (예: 외부 MCP
어댑터, 외부 ``@tool`` 데코레이터) 를 도메인 Tool 로 흡수해 단일 시그니처로 관리하기 위함.

본 어댑터를 통해 만들어진 domain.Tool 의 invoke(arguments) 는 BaseTool.invoke(arguments)
를 호출하고 결과 문자열을 ToolResult.content 에 담아 반환한다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from chatbot.domain.tools import ToolResult, ToolSchema


class _LangChainToolAdapter:
    """BaseTool 을 도메인 Tool 인터페이스로 노출. 내부 사용 — 외부엔 함수만 공개."""

    def __init__(self, base: BaseTool) -> None:
        self._base = base
        self.schema = ToolSchema(
            name=base.name,
            description=base.description or "",
            parameters=_args_schema_dict(base),
        )

    def is_available(self) -> tuple[bool, str | None]:
        """BaseTool 자체엔 가용성 개념이 없음 — 항상 True 반환.

        실제 실패는 invoke 시 예외로 드러난다 (회로 차단기가 흡수).
        """
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            output = self._base.invoke(arguments)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)
        content = output if isinstance(output, str) else str(output)
        return ToolResult(content=content, metadata={})


def _args_schema_dict(base: BaseTool) -> dict[str, Any]:
    """BaseTool.args_schema (Pydantic 모델) → JSON Schema dict.

    LangChain 1.x 가 schema 노출 방식이 버전마다 다르므로 *얕은 추출* 만 시도하고
    실패 시 빈 dict (parameters 없음) 으로 폴백. ToolSchema.parameters 가 dict 라
    빈값이라도 호환.
    """
    args = getattr(base, "args_schema", None)
    if args is None:
        return {}
    schema_method = getattr(args, "model_json_schema", None) or getattr(args, "schema", None)
    if callable(schema_method):
        try:
            return dict(schema_method())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def basetool_to_domain_tool(base: BaseTool):  # type: ignore[no-untyped-def]
    """BaseTool → domain.Tool. 어댑터 인스턴스를 반환한다 — Tool Protocol 만족."""
    return _LangChainToolAdapter(base)
