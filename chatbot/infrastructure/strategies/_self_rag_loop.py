"""Self-RAG 루프 — grade → rewrite → retrieve → generate 사이클을 격리.

본 헬퍼는 HybridStrategy 외부에서 직접 사용하지 않는다 (밑줄 prefix). max_retries 가
무한 루프 가드. 기존 ``rag_core/hybrid.py:_grade_router`` (387-393) 의 분기와 동등한
의미 — is_grounded 또는 retries ≥ max 에서 종료.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.stages import (
    GenerateInput,
    GenerateStage,
    GradeInput,
    GradeStage,
    RetrieveStage,
    RewriteInput,
    RewriteStage,
)


@dataclass
class LoopOutcome:
    """루프 종료 시 strategy 가 받는 결과 envelope."""

    answer: str
    documents: list[DocumentRef]
    is_grounded: bool
    grade_reason: str
    retries: int


@dataclass
class SelfRAGLoop:
    grade: GradeStage
    rewrite: RewriteStage
    retrieve: RetrieveStage
    generate: GenerateStage
    max_retries: int

    def run(
        self,
        *,
        question: str,
        documents: list[DocumentRef],
        answer: str,
        request: RetrievalRequest,
    ) -> LoopOutcome:
        """1 사이클: grade → (실패 + retries 남음) ? rewrite + retrieve + generate : 종료."""
        retries = 0
        while True:
            grade = self.grade.run(GradeInput(answer=answer, documents=documents))
            if grade["is_grounded"] or retries >= self.max_retries:
                return LoopOutcome(
                    answer=answer,
                    documents=documents,
                    is_grounded=grade["is_grounded"],
                    grade_reason=grade["reason"],
                    retries=retries,
                )
            retries += 1
            question, documents, answer = self._iterate(
                question=question,
                grade_reason=grade["reason"],
                request=request,
            )

    def _iterate(
        self,
        *,
        question: str,
        grade_reason: str,
        request: RetrievalRequest,
    ) -> tuple[str, list[DocumentRef], str]:
        """rewrite → 새 request 로 retrieve → generate. 한 사이클의 *부속 단계*."""
        new_question = self.rewrite.run(
            RewriteInput(original_question=question, grade_reason=grade_reason)
        )
        new_request = request.model_copy(update={"standalone_question": new_question})
        documents = self.retrieve.run(new_request)
        gen_out = self.generate.run(
            GenerateInput(
                question=new_question,
                documents=documents,
                chat_history=list(request.chat_history),
            )
        )
        return new_question, documents, gen_out["answer"]
