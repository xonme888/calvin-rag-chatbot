"""Retriever 어댑터 테스트 — BM25, Dense, Hybrid(RRF), 변환기."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.retrievers import (
    BM25Retriever,
    HybridRetriever,
    to_document_ref,
)
from chatbot.infrastructure.retrievers._converters import _stable_chunk_id


# ============================================================
# _converters
# ============================================================
def test_stable_chunk_id_결정성():
    a = _stable_chunk_id("src", 0, "본문")
    b = _stable_chunk_id("src", 0, "본문")
    assert a == b
    assert _stable_chunk_id("src", 0, "다른본문") != a


def test_to_document_ref_기본_매핑():
    ref = to_document_ref(
        content="본문",
        metadata={"page": 5, "source_id": "s1", "corpus_id": "c1", "extra": "x"},
        score=0.7,
    )
    assert ref.corpus_id == "c1"
    assert ref.source_id == "s1"
    assert ref.page == 5
    assert ref.score == 0.7
    assert ref.metadata["extra"] == "x"
    assert ref.chunk_id.startswith("s1:p5:")


def test_to_document_ref_default_사용():
    ref = to_document_ref(
        content="x",
        metadata={"page": 0},
        default_corpus_id="cal",
        default_source_id="ins",
    )
    assert ref.corpus_id == "cal"
    assert ref.source_id == "ins"


# ============================================================
# BM25Retriever
# ============================================================
def _calvin_chunks() -> list[Document]:
    return [
        Document(
            page_content="예정론 칼빈 신학",
            metadata={"page": 0, "source_id": "institutes_v1", "corpus_id": "calvin"},
        ),
        Document(
            page_content="베자 후계자",
            metadata={"page": 1, "source_id": "institutes_v1", "corpus_id": "calvin"},
        ),
        Document(
            page_content="멜란히톤 루터파",
            metadata={"page": 2, "source_id": "institutes_v1", "corpus_id": "calvin"},
        ),
    ]


def test_bm25_정상_검색():
    bm25 = BM25Retriever(
        _calvin_chunks(), default_corpus_id="calvin", default_source_id="institutes_v1"
    )
    refs = bm25.retrieve(RetrievalRequest(standalone_question="예정론 칼빈", top_k=2))
    assert len(refs) >= 1
    assert refs[0].corpus_id == "calvin"
    assert refs[0].chunk_id.startswith("institutes_v1:p0:")


def test_bm25_corpus_id_필터_제외():
    bm25 = BM25Retriever(
        _calvin_chunks(), default_corpus_id="calvin", default_source_id="institutes_v1"
    )
    refs = bm25.retrieve(
        RetrievalRequest(standalone_question="예정론 칼빈", top_k=5, corpus_ids=("augustine",))
    )
    assert refs == []


# ============================================================
# HybridRetriever (RRF)
# ============================================================
class _StubRetriever:
    name = "stub"

    def __init__(self, refs):  # type: ignore[no-untyped-def]
        self._refs = list(refs)

    def retrieve(self, request):  # type: ignore[no-untyped-def]
        return list(self._refs)


def test_rrf_중복_chunk_가_가장_높은_점수():
    """두 retriever 모두 같은 ref 를 반환하면 RRF 점수가 합쳐져 1위가 된다."""
    ref_a = to_document_ref(content="A", metadata={"page": 0, "source_id": "s", "corpus_id": "c"})
    ref_b = to_document_ref(content="B", metadata={"page": 1, "source_id": "s", "corpus_id": "c"})
    ref_c = to_document_ref(content="C", metadata={"page": 2, "source_id": "s", "corpus_id": "c"})

    hybrid = HybridRetriever(
        _StubRetriever([ref_a, ref_b]),
        _StubRetriever([ref_b, ref_c]),
        dense_weight=0.5,
    )
    fused = hybrid.retrieve(RetrievalRequest(standalone_question="?", top_k=10))
    assert len(fused) == 3
    assert fused[0].chunk_id == ref_b.chunk_id


def test_rrf_top_k_컷():
    ref_a = to_document_ref(content="A", metadata={"page": 0, "source_id": "s", "corpus_id": "c"})
    ref_b = to_document_ref(content="B", metadata={"page": 1, "source_id": "s", "corpus_id": "c"})
    hybrid = HybridRetriever(_StubRetriever([ref_a, ref_b]), _StubRetriever([ref_a]))
    out = hybrid.retrieve(RetrievalRequest(standalone_question="?", top_k=1))
    assert len(out) == 1


def test_rrf_dense_weight_경계값():
    hybrid = HybridRetriever(_StubRetriever([]), _StubRetriever([]), dense_weight=0.0)
    hybrid.dense_weight = 1.0  # 경계 허용
    with pytest.raises(ValueError):
        hybrid.dense_weight = 1.5
    with pytest.raises(ValueError):
        hybrid.dense_weight = -0.1


def test_hybrid_생성자_dense_weight_가드():
    with pytest.raises(ValueError):
        HybridRetriever(_StubRetriever([]), _StubRetriever([]), dense_weight=2.0)
