"""domain.Tool → LangChain BaseTool 변환.

create_agent 가 BaseTool 시퀀스를 받으므로, registry 가 보유한 도메인 Tool 들을
이 어댑터로 감싸 전달한다. 도메인은 LangChain 무지를 유지.

핵심 변환: domain.Tool.schema.parameters (JSON Schema dict) → Pydantic args_schema.
StructuredTool 이 args_schema 가 있어야 다중 인자(예: query, k) 를 인식하기 때문.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from chatbot.domain.tools import Tool

# JSON Schema 의 type 문자열 → Python 타입. 단순 매핑만 — 복합 (object/array) 은 dict/list.
_JSON_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def domain_tool_to_basetool(tool: Tool) -> BaseTool:
    """domain.Tool → LangChain StructuredTool. args_schema 자동 동적 생성.

    parameters 가 비어 있으면 args_schema 없이 단일 dict 인자만 받는 wrapper 생성 —
    이 경우 LLM 이 도구 호출 시 인자 추론을 못 할 수 있어, parameters 정의를 권장.
    """
    args_schema = _params_to_args_schema(tool)

    def _wrapper(**kwargs: Any) -> str:
        result = tool.invoke(kwargs)
        if result.is_error:
            raise RuntimeError(result.content)
        return result.content

    return StructuredTool.from_function(
        func=_wrapper,
        name=tool.schema.name,
        description=tool.schema.description,
        args_schema=args_schema,
    )


def _params_to_args_schema(tool: Tool) -> type[BaseModel] | None:
    """JSON Schema parameters → Pydantic 모델 class. 빈 schema 면 None."""
    parameters = tool.schema.parameters or {}
    properties = parameters.get("properties") or {}
    if not properties:
        return None
    required = set(parameters.get("required") or [])

    fields: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _JSON_TYPES.get(str(prop.get("type", "string")), str)
        description = prop.get("description")
        if name in required:
            fields[name] = (py_type, Field(..., description=description))
        else:
            default = prop.get("default", None)
            fields[name] = (py_type, Field(default=default, description=description))
    return create_model(f"{tool.schema.name}_Args", **fields)
