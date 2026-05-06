---
status: draft
group: A
created: 2026-05-06
related_prd: docs/prd/draft/006-conversation-first-orchestrator.md
related_trd: docs/trd/draft/006-conversation-first-orchestrator.md, docs/trd/draft/001-tools-input-extension.md
---

# TRD-008: Agentic 모드 분해 + ToolRegistry 정합 (AgenticRAG → AgenticStrategy)

본 TRD 는 *두 작업의 합류점* 이다:

1. TRD-006 의 PR 2-B (Agentic 분해)
2. TRD-001 (도구/MCP 확장) 의 ToolRegistry 와 `chatbot/domain/tools.py:Tool` Protocol 의 정합

두 작업이 같은 코드(`rag_core/agentic.py`, `rag_core/tools/`) 를 동시에 만지므로 한 TRD 로 묶어 변경 충돌을 방지한다.

## 1. AS-IS 분석

### 1.1 AgenticRAG 의 책임 (rag_core/agentic.py, 437줄)

| 책임 | 라인 | 라인 수 |
|---|---|---|
| 도구 정의 & 등록 | 225-242 | 18 |
| 도구 호출 루프 (LangChain create_agent) | 246-250 | 5 |
| 도구 결과 파싱 (parse_agent_messages) | 47-78 | 32 |
| 메시지→스트림 이벤트 변환 | 81-115 | 35 |
| 동기 query() | 290-351 | 62 |
| 스트리밍 stream_steps() | 353-437 | 85 |
| LLM 캐시 추적 + 메타 집계 | 303-350, 417-437 | 산재 |

`__init__` (62줄) + `query` (148줄 — 가장 큰 메서드) + `stream_steps` (85줄) — 메서드 3개가 295줄 점유.

### 1.2 도구 시스템 — 두 곳에 흩어져 있음

| 위치 | 파일:라인 | 역할 |
|---|---|---|
| Tool 정의 | `agentic.py:254-284` `_make_search_tool` | langchain `@tool` 데코레이터 클로저, retriever 캡처 |
| Tool 등록 | `agentic.py:225` `register_tool(_make_search_tool())` | rag_core/tools/registry.py 호출 |
| Registry | `rag_core/tools/registry.py` (95줄) | name → BaseTool factory 매핑, role 필터 |
| 정책 | `rag_core/tools/policy.py` (37줄) | `ToolPolicy(name, timeout_s, max_tokens, allowed_roles)` |

PRD-001 의 결정사항: ToolRegistry + ToolPolicy + MCP 어댑터. 이미 일부 인프라 (`rag_core/tools/registry.py`) 가 깔려 있다.

### 1.3 chatbot/domain/tools.py 와의 시그니처 충돌

| 항목 | rag_core/tools (PRD-001) | chatbot/domain/tools.py | 충돌 |
|---|---|---|---|
| Tool 타입 | `langchain_core.tools.BaseTool` | `Tool` Protocol (Pydantic 호환) | ✗ |
| 호출 시그니처 | `tool.invoke({"query": ...})` (langchain 규약) | `tool.invoke(arguments: dict)` | ✓ 호환 |
| 메타 | `ToolPolicy(name, timeout_s, ...)` | `ToolSchema(name, description, parameters)` | ⚠️ 이름·필드 다름 |
| MCP | `register_tool()` 무조건 등록 (stub) | `MCPClient.list_tools()` Protocol | ✗ 다름 |
| 가용성 | `entry.policy + role_meets()` | `Tool.is_available() -> tuple[bool, str|None]` | ✓ 통합 가능 |

이 충돌은 *언어와 시그니처의 차이* 보다 **추상의 차이** 다 — PRD-001 은 langchain 종속을 받아들였고, 본 TRD 는 도메인을 langchain-무지로 유지하려 한다.

### 1.4 AgenticRAG 의 핵심 위험

| 위험 | 라인 | 영향 |
|---|---|---|
| `AIMessage.tool_calls` 스키마 변경 | 68-69 | 즉시 파싱 실패 |
| `_format_doc_with_meta` 직렬화 실패 | 282 | 도구 결과 깨지면 agent 루프 중단 |
| BaseTool ↔ domain.Tool 타입 불일치 | 242 (enabled_tools) | 런타임 오류 (LLM 이 호출 못함) |
| 메시지 중복 감지 (`seen_msg_ids`) | 393-396 | 같은 메시지 반복 yield |

## 2. TO-BE 설계

### 2.1 합의된 추상 (정합점)

**도메인 (`chatbot/domain/tools.py`) 가 유일한 진실원천**. langchain 의존은 어댑터 레이어로 격리.

```
chatbot/domain/tools.py (PR 1 — 머지됨)
       │ Tool Protocol (langchain 무지)
       │
       ▼
chatbot/infrastructure/tools/
  ├── _adapters/
  │    ├── langchain_to_domain.py     BaseTool → Tool 어댑터 (PRD-001 자산 흡수)
  │    └── domain_to_langchain.py     Tool → BaseTool 어댑터 (Agentic create_agent 가 사용)
  ├── search/
  │    └── search_documents.py        domain.Tool 구현 (검색 도구)
  ├── mcp/
  │    └── mcp_client.py              MCPClient + list_tools() → domain.Tool 시퀀스
  └── domain/                         도메인 특화 도구 (예: 칼빈 사전)
```

PRD-001 의 `rag_core/tools/policy.py` 는 *유지* 하되, ToolPolicy 가 도메인 `Tool` 어댑터의 *부가 메타데이터* 로 흡수된다 — `Tool` 자체는 schema/is_available/invoke 만 알고, policy 는 ToolRegistry 가 기억한다.

### 2.2 신규/이전 모듈

```
chatbot/infrastructure/
├── strategies/
│   └── agentic_strategy.py            RetrievalStrategy 어댑터
├── tools/
│   ├── _adapters/
│   │   ├── langchain_to_domain.py     [신규]
│   │   └── domain_to_langchain.py     [신규]
│   ├── search/
│   │   └── search_documents.py        [이전: agentic.py:254-284 의 _make_search_tool]
│   ├── mcp/
│   │   └── mcp_client.py              [신규]
│   └── policy.py                      [이전: rag_core/tools/policy.py]
├── parsers/
│   └── agent_message_parser.py        [이전: agentic.py:47-115]
└── registries.py                      ToolRegistry 구현 (PRD-001 자산 흡수)
```

### 2.3 책임 매핑

| 기존 (rag_core/agentic.py) | 새 위치 | 비고 |
|---|---|---|
| `_make_search_tool` (254-284) | `infrastructure/tools/search/search_documents.py` | langchain `@tool` 제거, domain.Tool 직접 구현 |
| `parse_agent_messages` (47-78) | `infrastructure/parsers/agent_message_parser.py` | 단독 테스트 가능 |
| `message_to_stream_events` (81-115) | `infrastructure/parsers/agent_message_parser.py` | 동일 모듈에 묶음 |
| `__init__` (220-282) 의 LLM/agent 빌드 | `agentic_strategy.py` `__init__` (~30줄) | LangChain 의존 격리 |
| `query` (290-351) | `agentic_strategy.run()` (~50줄) | parse_agent_messages 호출 위임 |
| `stream_steps` (353-437) | `agentic_strategy.run_stream()` (TRD-006 PR 4 이후) | 본 TRD 는 sync 만 |

### 2.4 인터페이스 (Python sketch)

```python
# chatbot/infrastructure/tools/search/search_documents.py
class SearchDocumentsTool:
    schema = ToolSchema(
        name="search_documents",
        description="칼빈 강요 본문에서 질문에 가까운 청크를 검색.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
    )

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        docs = self._retriever.retrieve(
            RetrievalRequest(standalone_question=arguments["query"], top_k=arguments.get("k", 6))
        )
        return ToolResult(
            content=_format_docs(docs),
            metadata={"doc_count": str(len(docs))},
        )


# chatbot/infrastructure/tools/_adapters/domain_to_langchain.py
def to_langchain_tool(tool: Tool) -> BaseTool:
    """domain.Tool → langchain BaseTool. create_agent 가 받을 수 있도록."""
    @langchain_tool(name=tool.schema.name, description=tool.schema.description)
    def _wrapper(**kwargs) -> str:
        result = tool.invoke(kwargs)
        if result.is_error:
            raise RuntimeError(result.content)
        return result.content
    return _wrapper


# chatbot/infrastructure/strategies/agentic_strategy.py
class AgenticStrategy:
    name = "agentic"
    label = "Agentic"

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        tools: list[Tool],                          # domain.Tool — langchain 무지
        system_prompt: str,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._lc_tools = [to_langchain_tool(t) for t in tools]
        self._agent = create_agent(self._llm, self._lc_tools, system_prompt=system_prompt)

    def is_available(self) -> tuple[bool, str | None]:
        unavailable = [t.schema.name for t in self._tools if not t.is_available()[0]]
        if unavailable:
            return (False, f"도구 비활성: {unavailable}")
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        return not request.attachments  # 첨부는 vision

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        """create_agent 호출 → AgentMessageParser 로 변환 → RetrievalResult."""
        # 30~50줄 이내
```

### 2.5 ToolRegistry 정합 (PRD-001 합류)

PRD-001 의 `rag_core/tools/registry.py` 는 `chatbot/application/registries.py` 의 `InMemoryToolRegistry` 로 *대체 흡수*. PRD-001 이 정의한 ToolPolicy 는 registry 메타로 보존:

```python
# chatbot/application/registries.py
class InMemoryToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _ToolEntry] = {}

    def register(self, tool: Tool, *, policy: ToolPolicy | None = None) -> None: ...
    def all(self) -> list[Tool]: ...
    def get(self, name: str) -> Tool: ...
    def available(self) -> list[Tool]: ...
    def policy(self, name: str) -> ToolPolicy | None: ...
```

PRD-001 의 시나리오·결정·성공지표는 모두 보존. 변하는 것은 *Tool 의 시그니처가 langchain BaseTool 이 아니라 domain.Tool* 이라는 점뿐. 어댑터로 호환.

## 3. 마이그레이션 단계

| 단계 | 작업 | 검증 |
|---|---|---|
| 2-B.1 | `tools/_adapters/{langchain_to_domain,domain_to_langchain}.py` | 어댑터 단독 테스트 (Tool ↔ BaseTool 양방향) |
| 2-B.2 | `tools/search/search_documents.py` (도메인 Tool 구현) | 기존 `_make_search_tool` 와 동일 결과 (검색 결과 5건 비교) |
| 2-B.3 | `tools/mcp/mcp_client.py` (Protocol 어댑터, 본 TRD 는 stub OK) | list_tools() 가 빈 list 반환해도 OK — PRD-001 후속 |
| 2-B.4 | `parsers/agent_message_parser.py` (parse + stream events) | unit 테스트, 기존 parse_agent_messages 결과와 동일 |
| 2-B.5 | `application/registries.py:InMemoryToolRegistry` | PRD-001 의 ToolPolicy 통합, MCP allowlist 보존 |
| 2-B.6 | `strategies/agentic_strategy.py` 조립 | 기존 query() 와 동일 입력 30건 비교 (도구 호출 횟수·도구 인자 동일) |
| 2-B.7 | tests | 노드 단독 + 통합 |

본 TRD 의 작업은 PRD-001 의 *후속* 으로 이루어진다 — PRD-001 이 먼저 머지된 상태가 아니어도 본 TRD 는 진행 가능 (어댑터를 양방향으로 만들기 때문). PRD-001 의 코드가 머지되면 본 TRD 가 그것을 흡수.

## 4. 테스트 계획

### 4.1 단위

| 모듈 | 케이스 | Fake |
|---|---|---|
| SearchDocumentsTool | 정상 / k 인자 / retriever 빈 결과 / 도구 가용 false | FakeRetriever |
| domain_to_langchain | invoke 정상 / is_error → RuntimeError | FakeTool |
| langchain_to_domain | BaseTool.invoke → ToolResult 변환 | FakeBaseTool |
| AgentMessageParser | tool_calls 정상 / content only / ToolMessage 처리 | LangChain AIMessage 픽스처 |
| InMemoryToolRegistry | register / get / available / policy 조회 | - |
| AgenticStrategy.is_available | 모든 도구 가용 / 일부 비활성 | FakeTool |

### 4.2 통합

| 시나리오 | 검증 |
|---|---|
| 정상 검색 1회 | tool_calls 메타 동일, source_documents 동일 |
| 도구 호출 0회 (직접 답변) | answer 만 채워짐, tool_calls 빈 tuple |
| 외부 API 도구 timeout | InMemoryToolRegistry 의 ToolPolicy.timeout_s enforce → ToolResult(is_error=True) |
| MCP 도구 (stub) | list_tools() 빈 list — agent 가 등록된 다른 도구만 사용 |

### 4.3 회귀

기존 Agentic 응답 envelope 의 `tool_calls`, `tool_call_count`, `pattern` 키가 RetrievalResult.metadata 로 그대로 노출되어야 함. `chat.py:_build_stream_meta_payload` 가 이 키들을 사용 중.

## 5. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| BaseTool ↔ domain.Tool 어댑터의 인자 직렬화 mismatch | 도구가 호출되지 않음 | 양방향 어댑터 단독 테스트 + create_agent 호출 시 schema dump 확인 |
| ToolPolicy enforcement 위치 변경 | timeout 미적용 | InMemoryToolRegistry 의 invoke 래퍼에서 enforce (PRD-001 동작 보존) |
| LangChain 버전 업데이트로 AIMessage.tool_calls 형식 변경 | 파서 깨짐 | parser 단독 테스트가 회귀 잡음 |
| MCP 도입 미루기 | PRD-001 시나리오 1 미충족 | 본 TRD 는 stub 으로 placeholder 만, PRD-001 후속에서 채움 |

## 6. 후속

- MCP 클라이언트 실 구현 (PRD-001 후속).
- run_stream() — TRD-006 PR 4 이후 SSE 변환.
- 도구별 reasoning trace UI 블록 (PRD-001 결정 3) — 본 TRD 의 RetrievalResult.tool_calls 데이터 위에 프론트가 렌더.
