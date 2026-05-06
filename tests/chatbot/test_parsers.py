"""인용 파서 테스트 — extract_cited_pages, format_doc_with_meta, refs_to_citations.

기존 ``rag_core/hybrid.py:578-607`` 의 동작 동등성을 검증한다.
"""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.infrastructure.parsers import (
    extract_cited_pages,
    format_doc_with_meta,
    refs_to_citations,
)


# ============================================================
# extract_cited_pages
# ============================================================
def test_extract_cited_pages_중복제거_순서보존():
    text = "칼빈은 [p.780] 정의했다. 베자는 [p.150] 강조했다 [p.780]."
    assert extract_cited_pages(text) == [780, 150]


def test_extract_cited_pages_없음():
    assert extract_cited_pages("페이지 인용이 없다") == []


def test_extract_cited_pages_유사패턴_무시():
    text = "[페이지 1] 본문 (page 2) [p.5]"
    assert extract_cited_pages(text) == [5]


# ============================================================
# format_doc_with_meta — 기존 hybrid.py:_format_doc_with_meta 와 동일
# ============================================================
def test_format_doc_with_meta_PDF_page_플러스1():
    ref = DocumentRef(
        corpus_id="calvin",
        source_id="institutes_v1",
        chunk_id="c:1",
        page=779,
        content="본문",
    )
    assert format_doc_with_meta(ref) == "[page 780] 본문"


def test_format_doc_with_meta_filename_fallback():
    ref = DocumentRef(
        corpus_id="c",
        source_id="s",
        chunk_id="c:1",
        page=None,
        content="Q&A",
        metadata={"filename": "faq.txt"},
    )
    assert format_doc_with_meta(ref) == "[faq.txt] Q&A"


def test_format_doc_with_meta_source_fallback():
    ref = DocumentRef(
        corpus_id="c",
        source_id="s",
        chunk_id="c:1",
        page=None,
        content="x",
        metadata={"source": "kb"},
    )
    assert format_doc_with_meta(ref) == "[kb] x"


def test_format_doc_with_meta_메타_없음_본문만():
    ref = DocumentRef(corpus_id="c", source_id="s", chunk_id="c:1", page=None, content="x")
    assert format_doc_with_meta(ref) == "x"


# ============================================================
# refs_to_citations
# ============================================================
def test_refs_to_citations_cited_pages_필터():
    refs = [
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:1",
            page=779,
            content="본문",
        ),
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:2",
            page=300,
            content="안 인용",
        ),
    ]
    out = refs_to_citations(refs, cited_pages_one_indexed=[780])
    assert len(out) == 1
    assert out[0].page_label.startswith("p.780")


def test_refs_to_citations_같은_page_dedup():
    refs = [
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:1",
            page=0,
            content="첫번째",
        ),
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:2",
            page=0,
            content="두번째",
        ),
    ]
    out = refs_to_citations(refs)
    assert len(out) == 1
    assert out[0].snippet == "첫번째"  # 첫 등장만


def test_refs_to_citations_snippet_길이_컷():
    long_content = "가" * 500
    ref = DocumentRef(
        corpus_id="calvin",
        source_id="institutes_v1",
        chunk_id="c:1",
        page=0,
        content=long_content,
    )
    out = refs_to_citations([ref], snippet_max=100)
    assert len(out[0].snippet) == 100


def test_refs_to_citations_other_corpus_단순_page_라벨():
    ref = DocumentRef(
        corpus_id="augustine",
        source_id="confessions",
        chunk_id="a:1",
        page=4,
        content="고백록",
    )
    out = refs_to_citations([ref])
    assert out[0].page_label == "p.5"


def test_refs_to_citations_calvin_section_매핑_시도():
    """칼빈 corpus 는 section_filter 매핑이 시도됨. 매칭 안 되면 단순 p.N."""
    ref = DocumentRef(
        corpus_id="calvin",
        source_id="institutes_v1",
        chunk_id="c:1",
        page=49,
        content="본문",
    )
    out = refs_to_citations([ref])
    # 5단원 매핑은 page 50(0-indexed 49) 이 어떤 단원인지에 따라 다르므로 prefix 만 검증
    assert out[0].page_label.startswith("p.50")
