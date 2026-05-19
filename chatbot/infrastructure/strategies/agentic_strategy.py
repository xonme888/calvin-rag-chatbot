"""Agentic 검색 전략 — Tool 시퀀스 + LangChain create_agent 조립.

기존 ``rag_core/agentic.py:AgenticRAG`` 를 책임 분해한 결과의 *조립 책임* 만 본 파일이
가진다. 메시지 파싱은 ``parsers.agent_message_parser``, 도구는 ``tools/*``,
도구 ↔ BaseTool 변환은 ``tools/_adapters/`` 에 위임.

설계 원칙:
- domain.RetrievalStrategy 단일 시그니처 (RetrievalRequest → RetrievalResult).
- 도구는 *생성자 주입* (domain.Tool 시퀀스). create_agent 호출 직전에 BaseTool 로 어댑팅.
- 본 파일 < 200줄, run() < 60줄.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from chatbot.domain.corpus import Citation, DocumentRef
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult
from chatbot.domain.tools import Tool
from chatbot.infrastructure.parsers import (
    AgentParseResult,
    parse_messages,
    parsed_to_tool_calls,
)
from chatbot.infrastructure.strategies._config import AgenticStrategyConfig
from chatbot.infrastructure.tools import domain_tool_to_basetool
from infra.llm_cache import cache_delta, cache_snapshot

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class AgenticStrategy:
    """create_agent 위에 도메인 envelope 을 입힌 RetrievalStrategy.

    LLM 이 ReAct 패턴으로 도구 사용 여부/시점/쿼리를 자율 결정한다.
    """

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        tools: list[Tool],
        config: AgenticStrategyConfig,
    ) -> None:
        from langchain.agents import create_agent

        self._llm = llm
        self._tools = tools
        self._config = config
        self._lc_tools = [domain_tool_to_basetool(t) for t in tools]
        self._agent = create_agent(
            model=self._llm,
            tools=self._lc_tools,
            system_prompt=self._config.system_prompt,
        )

    @property
    def name(self) -> str:
        return "agentic"

    @property
    def label(self) -> str:
        return self._config.label

    def is_available(self) -> tuple[bool, str | None]:
        """모든 도구가 가용해야 True. 1개라도 비활성이면 부분 비활성으로 라벨 노출."""
        unavailable = [t.schema.name for t in self._tools if not t.is_available()[0]]
        if unavailable:
            return (False, f"도구 비활성: {','.join(unavailable)}")
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        """첨부가 있으면 vision 으로 양보."""
        return not request.attachments

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()
        cache_start = cache_snapshot()
        input_state: dict[str, Any] = {
            "messages": [HumanMessage(content=request.standalone_question)]
        }
        run_config: dict[str, Any] = {"recursion_limit": self._config.recursion_limit}

        final_state: dict[str, Any] = self._agent.invoke(input_state, config=run_config)
        parsed = parse_messages(final_state.get("messages", []))
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return self._build_result(
            parsed=parsed,
            elapsed_ms=elapsed_ms,
            question=request.standalone_question,
            cache_meta=cache_delta(cache_start),
        )

    def _build_result(
        self,
        *,
        parsed: AgentParseResult,
        elapsed_ms: int,
        question: str,
        cache_meta: dict[str, Any],
    ) -> RetrievalResult:
        """AgentParseResult → RetrievalResult.

        Agentic 은 본문 검색 결과가 *도구 응답 텍스트* 라서 DocumentRef 로 곧장 환원하기 어렵다.
        검색 도구가 [page N] prefix 를 부여한 문자열 시퀀스 (parsed.source_documents) 만 보존 —
        Citation 변환은 chat 라우트가 ``cited_pages_from_text`` 로 별도 처리.
        """
        documents = self._tool_outputs_to_refs(parsed.source_documents)
        tool_calls = parsed_to_tool_calls(parsed, elapsed_ms_per_call=0)
        citations: tuple[Citation, ...] = ()
        from rag_core.followup import generate_followups

        followups = generate_followups(question, parsed.final_answer, self._llm)
        metadata: dict[str, str] = {
            "pattern": self._config.pattern_name,
            "elapsed_ms": str(elapsed_ms),
            "answer": parsed.final_answer,
            "tool_call_count": str(len(parsed.tool_calls)),
            "model": str(getattr(self._llm, "model_name", "unknown")),
            "suggested_followups": json.dumps(followups, ensure_ascii=False),
        }
        metadata.update({k: str(v) for k, v in cache_meta.items()})
        return RetrievalResult(
            documents=tuple(documents),
            citations=citations,
            tool_calls=tool_calls,
            metadata=metadata,
        )

    def _tool_outputs_to_refs(self, outputs: list[str]) -> list[DocumentRef]:
        """검색 도구 응답 텍스트 시퀀스를 DocumentRef 로 *얕게* 변환.

        Agentic 은 청크 단위 score/page 를 보존하지 않으므로, 도구 응답 *각 문자열* 을
        DocumentRef 1개로 흡수 — page=None, score=None. cited_pages 는 LLM 답변 텍스트의
        ``[p.N]`` 패턴을 호출자가 별도 추출.
        """
        return [
            DocumentRef(
                corpus_id="",
                source_id="",
                chunk_id=f"agentic_tool_output:{i}",
                page=None,
                content=output,
            )
            for i, output in enumerate(outputs)
        ]
