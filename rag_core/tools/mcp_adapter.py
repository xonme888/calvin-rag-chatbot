"""MCP (Model Context Protocol) 서버 → LangChain BaseTool 어댑터 stub.

목적: MCP 표준을 따르는 외부 도구 서버를 LangChain ``create_agent`` 의 tool 로
연결. 실제 MCP 클라이언트 통합은 ``langchain-mcp-adapters`` 또는 자체 구현.

현 단계: **인터페이스만**. 외부 라이브러리 도입 시점에 ``_load_mcp_tools`` 본체
구현. 인터페이스 (allowlist + register_tool 호출 흐름) 는 안정.

보안 (시니어 리뷰 §5):
- 환경변수 ``MCP_SERVERS=url1,url2`` allowlist
- 도구 description 은 LLM 시스템 prompt 와 분리된 message 영역에서만 사용
- description 자체에 prompt injection 가능 — sanitize 후 등록
- 각 도구에 ToolPolicy(description_safe=False) 명시
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from rag_core.tools.policy import ToolPolicy
from rag_core.tools.registry import register_tool

logger = logging.getLogger(__name__)


def _allowed_servers() -> list[str]:
    raw = os.getenv("MCP_SERVERS", "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:the )?previous instructions?", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),  # ChatML 류 태그
)


def sanitize_description(text: str) -> str:
    """MCP 도구 description 의 prompt injection 패턴 제거.

    완전 방어가 아닌 1차 필터. 의심 패턴은 [REMOVED] 로 교체.
    """
    cleaned = text
    for p in _INJECTION_PATTERNS:
        cleaned = p.sub("[REMOVED]", cleaned)
    # 길이 제한 — 매우 긴 description 도 prompt 비용 + injection 표면
    return cleaned[:600]


def load_mcp_tools(server_urls: Iterable[str] | None = None) -> int:
    """MCP 서버에서 도구 목록을 받아 registry 에 등록.

    Args:
        server_urls: 명시 서버 목록. None 이면 환경변수 allowlist.

    Returns:
        등록된 도구 수.

    Note:
        현재 stub — 실제 MCP 클라이언트 호출은 외부 라이브러리 도입 시점에.
        일단 빈 list 반환해 agentic 부팅을 막지 않음.
    """
    urls = list(server_urls) if server_urls is not None else _allowed_servers()
    if not urls:
        return 0

    logger.info("MCP servers configured: %s — 어댑터 미구현, 0개 등록", urls)
    # TODO: langchain-mcp-adapters.MultiServerMCPClient 또는 자체 구현
    # for url in urls:
    #     client = MCPClient(url)
    #     for mcp_tool in client.list_tools():
    #         lc_tool = _convert(mcp_tool)
    #         register_tool(
    #             lc_tool,
    #             ToolPolicy(
    #                 name=lc_tool.name,
    #                 timeout_seconds=10.0,
    #                 required_role="paid",  # 외부 도구는 보수적
    #                 description_safe=False,
    #             ),
    #         )
    return 0


def _convert(mcp_tool):  # type: ignore[no-untyped-def]
    """MCP tool spec → LangChain BaseTool. 도입 시점에 구현."""
    raise NotImplementedError("MCP 어댑터는 langchain-mcp-adapters 도입 시 구현")
