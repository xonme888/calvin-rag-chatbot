"""``search_documents`` — Retriever 를 LLM 도구로 노출하는 domain.Tool 구현.

기존 ``rag_core/agentic.py:_make_search_tool`` (line 254-284) 의 동작을 *재사용* 한다 —
검색 호출은 Retriever 에 위임하고, 결과 직렬화는 ``parsers.format_doc_with_meta`` 와
동일하게 ``[page N] 본문`` 형식.

도구 description / parameters 는 LLM 이 도구를 *언제* 호출할지 결정할 때 보는 *유일한*
컨텍스트다. 가이드성 한국어 description 을 명확히 둔다.
"""

from __future__ import annotations

from typing import Any

from chatbot.domain.retrieval import RetrievalRequest, Retriever
from chatbot.domain.tools import ToolResult, ToolSchema
from chatbot.infrastructure.parsers import format_doc_with_meta


class SearchDocumentsTool:
    """corpus 본문에서 query 를 검색해 [page N] prefix 본문 시퀀스를 반환한다."""

    schema = ToolSchema(
        name="search_documents",
        description=(
            "칼빈 강요(Institutes of the Christian Religion) 본문에서 관련 청크를 검색한다. "
            "검색 쿼리는 한국어 또는 영어. 검색 결과 형식: '[page N] 본문\\n\\n---\\n\\n[page M] ...'"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 쿼리 — 핵심 키워드 또는 자연어 질문",
                },
                "k": {
                    "type": "integer",
                    "description": "검색할 청크 수 (1~20 허용, 기본 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult(content="검색 쿼리가 비어 있습니다.", is_error=True)

        k_raw = arguments.get("k", 5)
        try:
            k = int(k_raw)
        except (TypeError, ValueError):
            k = 5
        k = max(1, min(k, 20))  # 도구 폭주 방지 — k 상한 20

        try:
            refs = self._retriever.retrieve(RetrievalRequest(standalone_question=query, top_k=k))
        except RuntimeError as e:
            return ToolResult(
                content=f"검색기가 초기화되지 않았습니다: {e}",
                is_error=True,
            )

        if not refs:
            return ToolResult(content="관련된 본문을 찾을 수 없습니다.")

        body = "\n\n---\n\n".join(format_doc_with_meta(r) for r in refs)
        return ToolResult(content=body, metadata={"doc_count": str(len(refs))})
