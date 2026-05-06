"""테스트 공용 Fake 구현체 — 외부 LLM/검색 의존 없이 strategy 합성을 검증.

실제 LLM 호출이 필요한 회귀 테스트는 Phase 2 audit 가 별도로 다룬다.
"""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.stages import (
    GenerateInput,
    GenerateOutput,
    GenerateStage,
    GradeInput,
    GradeResult,
    GradeStage,
    RewriteInput,
    RewriteStage,
)


class FakeRetriever:
    """미리 정의된 ref 시퀀스를 반환. corpus_ids 필터는 무시 — 호출 패턴만 검증."""

    name: str = "fake"

    def __init__(self, refs: list[DocumentRef]) -> None:
        self.refs = list(refs)
        self.calls: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        self.calls.append(request)
        return list(self.refs[: request.top_k])


class FakeGenerateStage(GenerateStage):
    """LLM 호출 없이 미리 정의된 답변 시퀀스 반환."""

    def __init__(self, answers: list[GenerateOutput]) -> None:  # type: ignore[no-untyped-def]
        self._answers = list(answers)
        self.calls: list[GenerateInput] = []

    name: str = "generate"

    def run(self, input: GenerateInput) -> GenerateOutput:
        self.calls.append(input)
        if not self._answers:
            raise AssertionError("FakeGenerateStage answers 가 부족합니다.")
        return self._answers.pop(0)


class FakeGradeStage(GradeStage):
    def __init__(self, results: list[GradeResult]) -> None:  # type: ignore[no-untyped-def]
        self._results = list(results)
        self.calls: list[GradeInput] = []

    name: str = "grade"

    def run(self, input: GradeInput) -> GradeResult:
        self.calls.append(input)
        if not self._results:
            return GradeResult(is_grounded=True, reason="기본 통과")
        return self._results.pop(0)


class FakeRewriteStage(RewriteStage):
    def __init__(self, prefix: str = "재작성:") -> None:  # type: ignore[no-untyped-def]
        self._prefix = prefix
        self.calls: list[RewriteInput] = []

    name: str = "rewrite"

    def run(self, input: RewriteInput) -> str:
        self.calls.append(input)
        return f"{self._prefix}{input['original_question']}"


def make_ref(
    *,
    page: int,
    content: str,
    corpus_id: str = "calvin",
    source_id: str = "institutes_v1",
    chunk_id: str | None = None,
) -> DocumentRef:
    """DocumentRef 생성 헬퍼 — 테스트 가독성 향상."""
    return DocumentRef(
        corpus_id=corpus_id,
        source_id=source_id,
        chunk_id=chunk_id or f"{source_id}:p{page}:test",
        page=page,
        content=content,
    )
