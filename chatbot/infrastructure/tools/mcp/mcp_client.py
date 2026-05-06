"""MCP 클라이언트 stub — 환경변수 allowlist 기반 빈 도구 목록 반환.

PRD-001 의 ``rag_core/tools/mcp_adapter.py`` 와 의도가 같다 — 인터페이스만 안정화하고
실제 MCP 통신은 langchain-mcp-adapters 도입 시 채운다.

본 stub 은:
- ``MCP_SERVERS`` 환경변수에 URL 이 있으면 *경고 로그만* 남기고 빈 list 반환.
- 인터페이스가 ``MCPClient`` Protocol (chatbot.domain.tools) 만족.
- AgenticStrategy 가 list_tools() 를 호출해도 부팅 중단 없이 0개로 합류.

도입 시점에는 본 파일에 *어댑터 구현* 만 추가. agentic_strategy/registry 측 변경 0.
"""

from __future__ import annotations

import logging
import os
import re

from chatbot.domain.tools import Tool

logger = logging.getLogger(__name__)


# rag_core/tools/mcp_adapter.py:34-39 와 동일한 prompt injection 패턴.
# 본 파일에서 sanitize 가 발동되는 시점은 *실 어댑터* 도입 후이지만, 패턴 정의는
# stub 단계부터 두어 도구 description 검증 책임을 본 모듈에 *집중* 시킨다.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore (?:the )?previous instructions?", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),
)


def _allowed_servers() -> list[str]:
    raw = os.getenv("MCP_SERVERS", "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def sanitize_description(text: str) -> str:
    """MCP 도구 description 의 prompt injection 1차 필터. 의심 패턴 → [REMOVED]."""
    cleaned = text
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[REMOVED]", cleaned)
    return cleaned[:600]


class EnvAllowlistMCPClient:
    """``MCP_SERVERS`` 환경변수 allowlist 만 보는 stub 구현.

    실 MCP 통신은 미구현 — list_tools() 가 항상 빈 list 반환. 부팅 중단 없이 합류.
    """

    name: str = "env_allowlist_mcp"

    def is_available(self) -> tuple[bool, str | None]:
        urls = _allowed_servers()
        if not urls:
            return (False, "MCP_SERVERS 환경변수 미설정")
        return (True, None)

    def list_tools(self) -> list[Tool]:
        urls = _allowed_servers()
        if not urls:
            return []
        logger.info("MCP servers configured but stub — 0 tools registered. urls=%s", urls)
        # TODO: langchain-mcp-adapters.MultiServerMCPClient 도입 시:
        #   for url in urls:
        #       for mcp_tool in await fetch(url):
        #           tools.append(_convert(mcp_tool))
        return []
