"""도구 패키지 — Agentic 모드의 LangChain tool 모음.

설계:
- ``registry`` 가 단일 진실 소스 (이름 → BaseTool + ToolPolicy)
- 새 도구 추가 = ``register_tool()`` 한 번 + 이 파일에서 import
- MCP 서버는 ``mcp_adapter`` 가 등록 시점에 BaseTool 로 변환

allowlist (PRD-1 §6 보강):
- 환경변수 ``ALLOWED_TOOLS=name1,name2`` (미설정 시 모든 등록 도구 활성)
- 환경변수 ``MCP_SERVERS=url1,url2`` (allowlist 외 MCP 서버 거부)
"""

from __future__ import annotations

from rag_core.tools.policy import ToolPolicy
from rag_core.tools.registry import (
    all_tools,
    enabled_tools,
    get_tool,
    register_tool,
    reset_registry,
)

__all__ = [
    "ToolPolicy",
    "all_tools",
    "enabled_tools",
    "get_tool",
    "register_tool",
    "reset_registry",
]
