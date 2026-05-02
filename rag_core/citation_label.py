"""페이지 → 권/장 라벨 매핑.

5단원 (`rag_core/kg/section_filter.DEFAULT_CALVIN_SECTIONS`) 에 속한 페이지는
"3권 21장" 같은 라벨을 부여하고, 외 페이지는 라벨 없이 page 번호만 반환한다.

시연 1일 컷 위주이므로 PDF 전체(4권 80장) 매핑은 제외 (`docs/me/011` 결정).
"""

from __future__ import annotations

from typing import TypedDict

from rag_core.kg.section_filter import DEFAULT_CALVIN_SECTIONS, CalvinSection


class CitationLabel(TypedDict):
    """단일 페이지의 인용 라벨.

    page 는 1-indexed (사람이 보는 페이지 번호). PyMuPDFLoader 의
    `metadata['page']` 는 0-indexed 이므로 호출 측에서 +1 변환 후 전달할 것.
    """

    page: int
    section_slug: str | None  # 예: "3-21". 5단원 외엔 None
    section_label: str | None  # 예: "예정론(서론)". 5단원 외엔 None
    book: int | None  # 예: 3. 5단원 외엔 None
    chapter: int | None  # 예: 21. 5단원 외엔 None
    display: str  # 예: "p.778 (3권 21장)" 또는 "p.50"


def _find_section(page: int) -> CalvinSection | None:
    """1-indexed 페이지 번호로 5단원 매칭. 없으면 None."""
    for section in DEFAULT_CALVIN_SECTIONS:
        if section.page_start <= page <= section.page_end:
            return section
    return None


def page_to_section_label(page: int) -> CitationLabel:
    """1-indexed 페이지 → 권/장 라벨 dict.

    Args:
        page: 1-indexed PDF 페이지 번호.

    Returns:
        ``CitationLabel`` — 5단원 매칭 시 라벨 채워짐, 외엔 page 만.
    """
    section = _find_section(page)
    if section is None:
        return CitationLabel(
            page=page,
            section_slug=None,
            section_label=None,
            book=None,
            chapter=None,
            display=f"p.{page}",
        )
    return CitationLabel(
        page=page,
        section_slug=section.slug,
        section_label=section.label,
        book=section.book,
        chapter=section.chapter,
        display=f"p.{page} ({section.book}권 {section.chapter}장)",
    )


def labels_for_pages(pages: list[int | None]) -> list[CitationLabel | None]:
    """Document 메타의 0-indexed page 리스트를 라벨 리스트로 변환.

    None 페이지(메타 누락)는 그대로 None 반환.
    """
    out: list[CitationLabel | None] = []
    for p in pages:
        if p is None:
            out.append(None)
        else:
            # PyMuPDFLoader: 0-indexed → 1-indexed
            out.append(page_to_section_label(p + 1))
    return out
