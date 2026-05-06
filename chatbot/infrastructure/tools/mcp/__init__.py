"""MCP (Model Context Protocol) 클라이언트 어댑터.

도메인 ``MCPClient`` Protocol 의 구현. ``list_tools()`` 가 동적으로 외부 서버에서
도구 목록을 받아 domain.Tool 시퀀스로 노출한다.

본 모듈은 *stub* 으로 시작 — 환경변수 ``MCP_SERVERS`` allowlist 만 보고 실제 통신은
``langchain-mcp-adapters`` 도입 시 채운다 (PRD-001 후속). 인터페이스는 안정.
"""

from chatbot.infrastructure.tools.mcp.mcp_client import EnvAllowlistMCPClient

__all__ = ["EnvAllowlistMCPClient"]
