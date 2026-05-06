"""Self-RAG 질문 재작성 단계 — 검색 실패 후 검색 친화 형태로 질문 변환.

기존 ``rag_core/hybrid.py:_rewrite_node`` (line 353-385) 와 동일.
구조화 스키마 ``RewrittenQuery`` (rag_core/hybrid.py:120-125) 재사용.

주의: 본 단계는 *Self-RAG 루프 내부* 의 검색 친화 재작성이다 — 오케스트레이터 노드의
``rewrite_question`` (대명사 후속의 standalone 변환) 과 *역할이 다르다*. 이름이 비슷해도
입력/목적이 다르므로 strategy 안에서만 사용한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


_REWRITER_SYSTEM = (
    "다음 질문을 검색에 더 적합한 형태로 재작성하세요. "
    "동의어/구체적 용어/맥락 보강 등을 활용.\n\n"
    "원래 질문: {original}\n"
    "이전 검색 실패 이유: {reason}"
)


class RewriteInput(TypedDict):
    """rewrite_stage 입력."""

    original_question: str
    grade_reason: str


class RewriteStage:
    """검색 친화적으로 질문을 재작성. 출력은 새 질문 문자열 1개."""

    name: str = "rewrite"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._llm = llm

    def run(self, input: RewriteInput) -> str:
        from langchain_core.prompts import ChatPromptTemplate

        from rag_core.hybrid import RewrittenQuery

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _REWRITER_SYSTEM),
                ("human", "재작성된 질문은?"),
            ]
        )
        rewriter = self._llm.with_structured_output(RewrittenQuery)
        chain = prompt | rewriter
        result: RewrittenQuery = chain.invoke(
            {"original": input["original_question"], "reason": input["grade_reason"]}
        )
        return str(result.rewritten)
