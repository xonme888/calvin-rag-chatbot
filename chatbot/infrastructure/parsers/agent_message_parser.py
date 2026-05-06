"""Agent 메시지 파서 — LangChain message 시퀀스 → 도메인 모델/이벤트.

기존 ``rag_core/agentic.py:47-115`` 의 두 함수 (``parse_agent_messages``,
``message_to_stream_events``) 를 흡수해 도메인 ``ToolCallRecord`` 로 변환한다.

분리된 책임:
1. ``parse_messages``       — 종료 후 messages → AgentParseResult (final_answer + tool_calls)
2. ``message_to_events``    — 단일 메시지 → 0개 이상의 stream 이벤트 (thinking/tool_result/answer)
3. ``parsed_to_tool_calls`` — AgentParseResult → tuple[ToolCallRecord, ...] (RetrievalResult 합류용)

LangChain 의존은 본 파일에만 — Strategy 는 본 파서를 호출하면 된다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from chatbot.domain.retrieval import ToolCallRecord


@dataclass
class AgentParseResult:
    """Agent 종료 messages 에서 추출한 평면 정보."""

    final_answer: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    """LLM 이 호출한 도구 시퀀스. 형식: ``{"tool": str, "args": dict}``."""

    source_documents: list[str] = field(default_factory=list)
    """``search_documents`` 도구가 반환한 본문 문자열 시퀀스."""


def parse_messages(messages: list[BaseMessage]) -> AgentParseResult:
    """``rag_core/agentic.py:47-78`` 와 동일 동작.

    - final_answer: messages 역방향에서 첫 AIMessage.content (tool_calls 없는 답변).
    - tool_calls: 모든 AIMessage 의 .tool_calls 합산.
    - source_documents: name=='search_documents' 인 ToolMessage 의 content.
    """
    final_answer = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, str) and content.strip():
                final_answer = content
                break

    tool_calls: list[dict[str, Any]] = []
    source_documents: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", None) or []:
                tool_calls.append({"tool": tc.get("name", ""), "args": tc.get("args", {})})
        if getattr(msg, "name", None) == "search_documents":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            source_documents.append(content)

    return AgentParseResult(
        final_answer=final_answer,
        tool_calls=tool_calls,
        source_documents=source_documents,
    )


def message_to_events(msg: BaseMessage) -> Iterator[dict[str, Any]]:
    """단일 메시지 → 0개 이상의 stream 이벤트.

    한 AIMessage 의 tool_calls 는 각각 ``thinking`` 으로 분리.
    답변 AIMessage 는 ``answer``. ``search_documents`` ToolMessage 는 ``tool_result``.

    ``rag_core/agentic.py:81-115`` 와 동일.
    """
    if isinstance(msg, AIMessage):
        msg_tool_calls = getattr(msg, "tool_calls", None) or []
        if msg_tool_calls:
            for tc in msg_tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {}) or {}
                yield {
                    "type": "thinking",
                    "tool": tool_name,
                    "args": tool_args,
                    "message": f"검색 도구 호출: {tool_name}",
                    "details": ", ".join(f'{k}="{v}"' for k, v in tool_args.items()),
                }
        elif msg.content:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content.strip():
                yield {"type": "answer", "content": content}
    elif getattr(msg, "name", None) == "search_documents":
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        n_chunks = content.count("---") + 1 if content else 0
        yield {
            "type": "tool_result",
            "message": f"{n_chunks}개 청크 검색 완료",
            "source_doc": content,
        }


def parsed_to_tool_calls(
    parsed: AgentParseResult,
    *,
    elapsed_ms_per_call: int = 0,
) -> tuple[ToolCallRecord, ...]:
    """AgentParseResult.tool_calls (dict) → tuple[ToolCallRecord, ...].

    elapsed_ms 는 호출 단위로 측정하지 않는 현 구조에선 0 으로 채운다 — 향후 timing 추가 시
    매개변수 하나로 일괄 부착.
    """
    return tuple(
        ToolCallRecord(
            tool_name=str(tc.get("tool", "")),
            arguments={k: str(v) for k, v in (tc.get("args") or {}).items()},
            result_preview="",  # 도구별 결과는 source_documents 에 별도 보존
            elapsed_ms=elapsed_ms_per_call,
        )
        for tc in parsed.tool_calls
    )
