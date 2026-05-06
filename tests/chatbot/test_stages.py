"""Stage 어댑터 테스트 — LLM 의존 stage 는 답변 빈/문서 빈 fast-path 만.

LLM 호출이 필요한 정상 경로(generate/grade/rewrite) 는 Phase 2 audit 의 회귀 테스트가
별도로 다룬다 — 본 테스트에서는 인스턴스 가능성과 단락 평가만.
"""

from __future__ import annotations

from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.stages import (
    GradeInput,
    GradeStage,
    RetrieveStage,
)
from tests.chatbot.fakes import FakeRetriever, make_ref


def test_retrieve_stage_단순_위임():
    refs = [make_ref(page=0, content="본문0"), make_ref(page=1, content="본문1")]
    retriever = FakeRetriever(refs)
    stage = RetrieveStage(retriever)
    out = stage.run(RetrievalRequest(standalone_question="?", top_k=2))
    assert out == refs


def test_retrieve_stage_top_k_위임():
    refs = [make_ref(page=i, content=str(i)) for i in range(5)]
    stage = RetrieveStage(FakeRetriever(refs))
    out = stage.run(RetrievalRequest(standalone_question="?", top_k=2))
    assert len(out) == 2


def test_grade_stage_답변_빈_즉시_False_LLM_미호출():
    """answer 가 빈 문자열이면 LLM 호출 없이 즉시 not grounded 판정."""
    stage = GradeStage(llm=None)  # type: ignore[arg-type]
    result = stage.run(GradeInput(answer="", documents=[]))
    assert result["is_grounded"] is False
    assert "누락" in result["reason"]


def test_grade_stage_문서_빈_즉시_False():
    stage = GradeStage(llm=None)  # type: ignore[arg-type]
    result = stage.run(GradeInput(answer="answer", documents=[]))
    assert result["is_grounded"] is False
