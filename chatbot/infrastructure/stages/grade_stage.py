"""Self-RAG 근거도 평가 단계 — 답변이 본문으로 뒷받침되는지 LLM 으로 판단.

기존 ``rag_core/hybrid.py:_grade_node`` (line 315-351) 와 동일 동작.
구조화 스키마 ``GroundednessGrade`` (rag_core/hybrid.py:113-117) 재사용.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from chatbot.domain.corpus import DocumentRef
from chatbot.infrastructure.parsers import format_doc_with_meta

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


_GRADER_SYSTEM = (
    "당신은 답변의 본문 근거를 검증하는 전문가입니다. "
    "주어진 본문에 답변이 충분히 뒷받침되는지 판단하세요.\n\n"
    "## 본문:\n{context}\n\n"
    "## 답변:\n{answer}\n\n"
    "## 판단 기준:\n"
    "- 답변의 핵심 주장이 본문에 명시되어 있으면 grounded=True\n"
    "- 답변이 본문에 없는 내용을 추가했거나 모순되면 grounded=False\n"
    "- 부분적으로만 뒷받침되면 grounded=False"
)


class GradeInput(TypedDict):
    """grade_stage 입력. answer 또는 documents 가 비어 있으면 즉시 False 로 판정."""

    answer: str
    documents: list[DocumentRef]


class GradeResult(TypedDict):
    is_grounded: bool
    reason: str


class GradeStage:
    """LLM 으로 근거도 평가. 답변/문서 누락 시 LLM 호출 없이 False 반환."""

    name: str = "grade"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._llm = llm

    def run(self, input: GradeInput) -> GradeResult:
        if not input["answer"] or not input["documents"]:
            return GradeResult(is_grounded=False, reason="답변 또는 문서 누락")

        from langchain_core.prompts import ChatPromptTemplate

        from rag_core.hybrid import GroundednessGrade

        context = "\n\n---\n\n".join(format_doc_with_meta(d) for d in input["documents"])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _GRADER_SYSTEM),
                ("human", "이 답변이 본문으로 뒷받침됩니까?"),
            ]
        )
        grader = self._llm.with_structured_output(GroundednessGrade)
        chain = prompt | grader
        grade: GroundednessGrade = chain.invoke({"context": context, "answer": input["answer"]})
        return GradeResult(is_grounded=bool(grade.is_grounded), reason=str(grade.reason))
