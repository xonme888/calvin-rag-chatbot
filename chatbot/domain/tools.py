"""도구(Tool) 도메인 — Retriever 와 분리된 외부 호출 추상.

Retriever 는 corpus 안에서 검색만 하고, Tool 은 그 외 모든 외부 호출(웹 검색,
계산기, 도메인 API, MCP 서버 등) 을 담당한다. 분리 이유:

- Retriever 의 출력은 항상 ``DocumentRef`` (인용 가능). Tool 은 임의 텍스트.
- Tool 은 의도(arguments schema) 가 있어야 LLM 이 선택 가능. Retriever 는 시그니처 통일.
- MCP 서버는 다중 도구를 노출 — 하나의 MCP 클라이언트가 여러 Tool 을 등록할 수 있다.

새 외부 통합을 추가할 때 이 Protocol 만 만족하면 ToolRegistry 에 합류한다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ToolSchema(BaseModel):
    """Tool 의 자기-기술. LLM 이 도구 선택할 때 prompt 에 주입한다.

    parameters 는 JSON Schema (dict). pydantic 모델 직렬화로 채우는 것을 권장.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Tool 호출의 표준 결과.

    content 는 LLM 이 다음 단계로 흘려보낼 텍스트. metadata 는 감사·UI 용.
    is_error 가 True 이면 LLM 이 도구 호출 실패를 인지하고 다른 시도를 할 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    """외부 도구 1개. MCP 도구·웹 검색·계산기 모두 동일 Protocol.

    구현 시 단일 책임 유지: 한 Tool = 한 동작. "검색+요약" 같은 합성은
    오케스트레이터/Strategy 가 한다.
    """

    schema: ToolSchema

    def is_available(self) -> tuple[bool, str | None]:
        """가용성 확인. (False, reason) 이면 등록되지만 호출 시 503."""
        ...

    def invoke(self, arguments: dict[str, Any]) -> ToolResult: ...


@runtime_checkable
class MCPClient(Protocol):
    """MCP 서버 어댑터. 한 클라이언트가 여러 Tool 을 노출할 수 있다.

    MCPClient 자체는 Tool 이 아니다 — list_tools() 로 Tool 인스턴스들을 만들어 등록한다.
    이 분리 덕에 ToolRegistry 는 MCP 인지 도메인 도구인지 신경 쓰지 않는다.
    """

    name: str

    def is_available(self) -> tuple[bool, str | None]: ...

    def list_tools(self) -> list[Tool]: ...


@runtime_checkable
class ToolRegistry(Protocol):
    """런타임 도구 카탈로그. 등록·조회·필터링.

    Strategy(특히 Agentic) 가 사용할 도구 목록을 여기서 가져온다.
    """

    def register(self, tool: Tool) -> None: ...

    def all(self) -> list[Tool]: ...

    def get(self, name: str) -> Tool:
        """없으면 KeyError."""
        ...

    def available(self) -> list[Tool]:
        """is_available()[0] 이 True 인 것만."""
        ...
