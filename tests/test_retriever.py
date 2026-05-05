"""HybridRetriever / RetrieverPort 단위 테스트.

FakeEmbeddings 로 LLM/네트워크 호출 0회 검증.
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings

from rag_core.retriever import HybridRetriever, RetrieverPort


def _make_retriever() -> HybridRetriever:
    """FakeEmbeddings 기반 retriever — 외부 호출 0."""
    return HybridRetriever(
        embeddings=FakeEmbeddings(size=32),
        chunk_size=200,
        chunk_overlap=20,
        dense_weight=0.5,
        rrf_k=60,
    )


def test_hybrid_retriever_satisfies_port_contract() -> None:
    """HybridRetriever 가 RetrieverPort Protocol 을 만족."""
    r = _make_retriever()
    assert isinstance(r, RetrieverPort)


def test_index_documents_populates_indexes() -> None:
    r = _make_retriever()
    docs = [
        Document(page_content="칼빈은 예정론을 정의했다.", metadata={"page": 0}),
        Document(page_content="어거스틴이 영향을 주었다.", metadata={"page": 1}),
        Document(page_content="자유의지에 대한 논의.", metadata={"page": 2}),
    ]
    n = r.index_documents(docs)
    assert n >= 3
    assert r.vector_store is not None
    assert r.bm25_retriever is not None
    assert len(r.chunks) == n


def test_retrieve_returns_documents() -> None:
    r = _make_retriever()
    r.index_documents(
        [
            Document(page_content="예정론은 칼빈의 핵심 교리다.", metadata={"page": 0}),
            Document(page_content="삼위일체에 대한 논의.", metadata={"page": 1}),
            Document(page_content="자유의지 개념을 검토했다.", metadata={"page": 2}),
        ]
    )
    docs = r.retrieve("예정론", k=2)
    assert len(docs) <= 2
    assert all(isinstance(d, Document) for d in docs)


def test_retrieve_with_scores_returns_score_tuples() -> None:
    r = _make_retriever()
    r.index_documents([Document(page_content=f"문서 {i}", metadata={}) for i in range(5)])
    results = r.retrieve_with_scores("문서", k=3)
    assert len(results) <= 3
    for doc, score in results:
        assert isinstance(doc, Document)
        assert isinstance(score, float)


def test_retrieve_split_returns_three_lists() -> None:
    r = _make_retriever()
    r.index_documents([Document(page_content=f"문서 {i}", metadata={}) for i in range(5)])
    bm25, dense, fused = r.retrieve_split("문서", k=3)
    assert isinstance(bm25, list)
    assert isinstance(dense, list)
    assert isinstance(fused, list)
    # fused는 RRF 결과 — bm25/dense 합집합 이내
    fused_keys = {hash(d.page_content) for d, _ in fused}
    bm25_keys = {hash(d.page_content) for d, _ in bm25}
    dense_keys = {hash(d.page_content) for d, _ in dense}
    assert fused_keys.issubset(bm25_keys | dense_keys)


def test_reciprocal_rank_fusion_combines_ranks() -> None:
    """RRF 점수 = Σ weight_i / (k + rank_i). 동일 가중치라면 두 리스트 모두 1위인 doc이 가장 높다."""
    r = _make_retriever()
    a = Document(page_content="A", metadata={})
    b = Document(page_content="B", metadata={})
    c = Document(page_content="C", metadata={})

    bm25 = [(a, 10.0), (b, 5.0), (c, 1.0)]  # A 1위
    dense = [(a, 0.9), (b, 0.5), (c, 0.1)]  # A 1위
    fused = r.reciprocal_rank_fusion(bm25, dense)
    assert fused[0][0].page_content == "A"  # 양쪽 1위 → 최상위


def test_reciprocal_rank_fusion_handles_disjoint_results() -> None:
    """두 리스트에 겹치는 문서가 없어도 모두 결과에 포함."""
    r = _make_retriever()
    a = Document(page_content="A", metadata={})
    b = Document(page_content="B", metadata={})

    fused = r.reciprocal_rank_fusion([(a, 10.0)], [(b, 0.9)])
    contents = {d.page_content for d, _ in fused}
    assert contents == {"A", "B"}


def test_retrieve_raises_when_not_indexed() -> None:
    r = _make_retriever()
    try:
        r.retrieve("Q")
    except RuntimeError as e:
        assert "index_documents" in str(e)
    else:
        raise AssertionError("RuntimeError 발생해야 함")


def test_load_prebuilt_index_skips_embedding() -> None:
    """디스크 캐시 활용 시 외부에서 받은 vector_store를 그대로 사용."""
    r = _make_retriever()
    chunks = [Document(page_content=f"청크 {i}", metadata={"page": i}) for i in range(3)]

    # 다른 retriever에서 인덱스를 빌드한 척
    builder = _make_retriever()
    builder.index_documents(chunks)
    prebuilt_vs = builder.vector_store
    assert prebuilt_vs is not None

    # 캐시에서 로드하는 시나리오
    r.load_prebuilt_index(chunks=chunks, vector_store=prebuilt_vs)
    assert r.vector_store is prebuilt_vs
    assert r.bm25_retriever is not None
    assert len(r.chunks) == 3
