"""인용 파서 — 답변 텍스트와 DocumentRef 를 도메인 Citation 으로 변환.

분리된 책임:
1. ``extract_cited_pages``  — 답변 텍스트의 ``[p.N]`` 패턴 추출 (1-indexed page list).
2. ``format_doc_with_meta`` — DocumentRef → ``[page N] 본문`` 형식 (LLM 입력용).
3. ``refs_to_citations``    — DocumentRef + 인용된 page 셋 → ``Citation`` 시퀀스.

기존 ``rag_core/hybrid.py:578-590`` (extract_cited_pages_from_text) +
``rag_core/hybrid.py:593-607`` (_format_doc_with_meta) 의 동작을 보존.
``rag_core/citation_label.py`` 의 권/장 라벨 변환을 page_label 로 통합.
"""

from __future__ import annotations

import re

from chatbot.domain.corpus import Citation, DocumentRef

_CITED_PAGE_PATTERN = re.compile(r"\[p\.(\d+)\]")


def extract_cited_pages(text: str) -> list[int]:
    """답변 텍스트에서 ``[p.N]`` 패턴을 추출 — 1-indexed page list.

    중복 제거 (LLM 이 같은 페이지를 여러 번 인용) + 등장 순서 보존.
    """
    seen: set[int] = set()
    out: list[int] = []
    for match in _CITED_PAGE_PATTERN.finditer(text):
        page = int(match.group(1))
        if page not in seen:
            seen.add(page)
            out.append(page)
    return out


def format_doc_with_meta(ref: DocumentRef) -> str:
    """DocumentRef → LLM 입력용 컨텍스트 문자열.

    PDF 청크 (page 있음) 는 ``[page N] 본문`` 으로 prepend (N 은 1-indexed).
    page 없음 + filename/source 메타 있음은 ``[source] 본문``.
    둘 다 없음은 본문만.

    기존 ``rag_core/hybrid.py:_format_doc_with_meta`` (line 593-607) 와 동일.
    page 가 PyMuPDFLoader 의 0-indexed 인 점도 동일 (+1 변환).
    """
    if ref.page is not None:
        return f"[page {ref.page + 1}] {ref.content}"
    src = ref.metadata.get("filename") or ref.metadata.get("source")
    if src:
        return f"[{src}] {ref.content}"
    return ref.content


def _page_label(ref: DocumentRef) -> str:
    """DocumentRef → 사용자 표시용 페이지 라벨.

    칼빈 corpus 의 5단원 매핑(rag_core/kg/section_filter)에 들어있으면 권/장 표기,
    아니면 단순 ``p.N`` (1-indexed). 본 모듈은 도메인 무지 — 매핑은 lazy import.
    """
    if ref.page is None:
        src = ref.metadata.get("filename") or ref.metadata.get("source")
        return src or ""

    one_indexed = ref.page + 1
    # 칼빈 corpus 일 때만 권/장 라벨 시도. 다른 corpus 는 단순 page.
    if ref.corpus_id == "calvin":
        from rag_core.citation_label import page_to_section_label

        return page_to_section_label(one_indexed)["display"]
    return f"p.{one_indexed}"


def refs_to_citations(
    refs: list[DocumentRef],
    *,
    cited_pages_one_indexed: list[int] | None = None,
    snippet_max: int = 200,
) -> list[Citation]:
    """DocumentRef → Citation. UI/감사용 표면 메타.

    cited_pages_one_indexed 가 주어지면 *답변에 실제 등장한 페이지* 의 ref 만 변환 —
    검색은 됐지만 답변에 인용되지 않은 ref 는 제외. None 이면 모든 ref 변환.

    같은 (corpus, source, page) 조합은 첫 등장만 포함 (LLM 이 같은 페이지를 여러 청크로
    인용하더라도 사용자 UI 의 인용 칩은 1개).
    """
    cited_set = set(cited_pages_one_indexed) if cited_pages_one_indexed is not None else None
    seen: set[tuple[str, str, int | None]] = set()
    out: list[Citation] = []

    for ref in refs:
        page_one = (ref.page + 1) if ref.page is not None else None
        if cited_set is not None and (page_one is None or page_one not in cited_set):
            continue
        key = (ref.corpus_id, ref.source_id, page_one)
        if key in seen:
            continue
        seen.add(key)
        snippet = ref.content if len(ref.content) <= snippet_max else ref.content[:snippet_max]
        out.append(
            Citation(
                corpus_id=ref.corpus_id,
                source_id=ref.source_id,
                page_label=_page_label(ref),
                snippet=snippet,
            )
        )
    return out
