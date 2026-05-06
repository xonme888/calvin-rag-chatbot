"""HybridStrategy 합성 테스트 — Self-RAG 루프 / 메타 envelope / supports.

LLM 호출 0회. Fake stage 들의 호출 횟수와 결과 envelope 만 검증한다.
"""

from __future__ import annotations

from chatbot.domain.conversation import Attachment
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult
from chatbot.infrastructure.stages import (
    GenerateOutput,
    GradeResult,
    RetrieveStage,
)
from chatbot.infrastructure.strategies import (
    HybridStrategy,
    HybridStrategyConfig,
)
from tests.chatbot.fakes import (
    FakeGenerateStage,
    FakeGradeStage,
    FakeRetriever,
    FakeRewriteStage,
    make_ref,
)


def _strategy(*, gen_outputs, grade_results=None, max_retries=1, self_rag=False):
    refs = [
        make_ref(page=0, content="예정론 본문"),
        make_ref(page=2, content="베자 본문"),
        make_ref(page=4, content="멜란히톤 본문"),
    ]
    retriever = FakeRetriever(refs)
    return (
        retriever,
        HybridStrategy(
            retriever=retriever,
            retrieve_stage=RetrieveStage(retriever),
            generate_stage=FakeGenerateStage(gen_outputs),
            grade_stage=FakeGradeStage(grade_results or []) if self_rag else None,
            rewrite_stage=FakeRewriteStage() if self_rag else None,
            config=HybridStrategyConfig(
                top_k=3,
                self_rag_enabled=self_rag,
                max_self_rag_retries=max_retries,
            ),
        ),
    )


def test_hybrid_정상_경로_envelope():
    _, strategy = _strategy(
        gen_outputs=[
            GenerateOutput(answer="예정론은 [p.1] 본문 [p.5]", cited_pages=[1, 5], confidence=0.85)
        ]
    )
    result = strategy.run(RetrievalRequest(standalone_question="예정론?"))
    assert isinstance(result, RetrievalResult)
    assert len(result.documents) == 3
    assert result.metadata["pattern"] == "Hybrid RAG"
    # cited_pages 는 json.dumps 로 직렬화 — 리스트 경계 보존
    import json as _json

    assert _json.loads(result.metadata["cited_pages"]) == [1, 5]
    assert result.metadata["is_grounded"] == "True"
    assert result.metadata["self_rag_retries"] == "0"
    assert "elapsed_ms" in result.metadata
    # citations 가 cited_pages 만 (1, 5) 노출
    labels = [c.page_label for c in result.citations]
    assert any("p.1" in label for label in labels)
    assert any("p.5" in label for label in labels)


def test_supports_attachments_있으면_False():
    _, strategy = _strategy(
        gen_outputs=[GenerateOutput(answer="x", cited_pages=[], confidence=0.5)]
    )
    assert strategy.supports(RetrievalRequest(standalone_question="?")) is True
    req_att = RetrievalRequest(
        standalone_question="?",
        attachments=(Attachment(kind="image_url", value="http://x"),),
    )
    assert strategy.supports(req_att) is False


def test_is_available_항상_True():
    _, strategy = _strategy(
        gen_outputs=[GenerateOutput(answer="x", cited_pages=[], confidence=0.5)]
    )
    ok, reason = strategy.is_available()
    assert ok is True and reason is None


def test_self_rag_재시도_1회_후_성공():
    _, strategy = _strategy(
        gen_outputs=[
            GenerateOutput(answer="answer1", cited_pages=[1], confidence=0.5),
            GenerateOutput(answer="answer2", cited_pages=[2], confidence=0.7),
        ],
        grade_results=[
            GradeResult(is_grounded=False, reason="부족"),
            GradeResult(is_grounded=True, reason="OK"),
        ],
        max_retries=2,
        self_rag=True,
    )
    result = strategy.run(RetrievalRequest(standalone_question="원본"))
    assert result.metadata["is_grounded"] == "True"
    assert result.metadata["self_rag_retries"] == "1"
    assert "answer2" in result.metadata["answer"]


def test_self_rag_max_retries_도달_실패_보존():
    _, strategy = _strategy(
        gen_outputs=[
            GenerateOutput(answer=f"ans{i}", cited_pages=[1], confidence=0.5) for i in range(5)
        ],
        grade_results=[GradeResult(is_grounded=False, reason="부족") for _ in range(5)],
        max_retries=2,
        self_rag=True,
    )
    result = strategy.run(RetrievalRequest(standalone_question="원본"))
    assert result.metadata["is_grounded"] == "False"
    assert result.metadata["self_rag_retries"] == "2"


def test_set_dense_weight_pass_through():
    """HybridRetriever 의 dense_weight setter 가 strategy 통해 호출됨."""
    from chatbot.infrastructure.retrievers import HybridRetriever
    from chatbot.infrastructure.retrievers._converters import to_document_ref

    class _Stub:
        name = "stub"

        def retrieve(self, req):  # type: ignore[no-untyped-def]
            return [
                to_document_ref(
                    content="x", metadata={"page": 0, "source_id": "s", "corpus_id": "c"}
                )
            ]

    hybrid_retriever = HybridRetriever(_Stub(), _Stub(), dense_weight=0.5)
    strategy = HybridStrategy(
        retriever=hybrid_retriever,
        retrieve_stage=RetrieveStage(hybrid_retriever),
        generate_stage=FakeGenerateStage(
            [GenerateOutput(answer="x", cited_pages=[], confidence=0.5)]
        ),
        config=HybridStrategyConfig(top_k=3),
    )
    strategy.set_dense_weight(0.8)
    assert hybrid_retriever.dense_weight == 0.8
