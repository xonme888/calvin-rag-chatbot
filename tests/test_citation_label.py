"""citation_label + cited_pages 후처리 단위 테스트 (LLM/네트워크 호출 0)."""

from __future__ import annotations

from rag_core.citation_label import labels_for_pages, page_to_section_label
from rag_core.hybrid import extract_cited_pages_from_text


# ====================================================================
# page_to_section_label
# ====================================================================
def test_page_in_section_returns_full_label() -> None:
    """3권 21장 (예정론) page 778~786 안의 페이지."""
    label = page_to_section_label(780)
    assert label["page"] == 780
    assert label["book"] == 3
    assert label["chapter"] == 21
    assert label["section_slug"] == "3-21"
    assert label["section_label"] == "예정론(서론)"
    assert label["display"] == "p.780 (3권 21장)"


def test_page_in_first_section() -> None:
    """1권 13장 (삼위일체) p.136~169."""
    label = page_to_section_label(150)
    assert label["book"] == 1
    assert label["chapter"] == 13
    assert "1권 13장" in label["display"]


def test_page_outside_sections_returns_page_only() -> None:
    """5단원 외 페이지는 라벨 없이 page 만."""
    label = page_to_section_label(50)
    assert label["page"] == 50
    assert label["section_slug"] is None
    assert label["section_label"] is None
    assert label["book"] is None
    assert label["display"] == "p.50"


def test_page_at_section_boundary() -> None:
    """경계값 — 섹션 시작/끝 page 포함."""
    # 3권 21장 page_start=778
    assert page_to_section_label(778)["section_slug"] == "3-21"
    # page_end=786 도 포함
    assert page_to_section_label(786)["section_slug"] == "3-21"
    # 787 은 외 (다음 섹션 시작 전)
    assert page_to_section_label(787)["section_slug"] is None


# ====================================================================
# labels_for_pages — 0-indexed → 1-indexed 변환
# ====================================================================
def test_labels_for_pages_handles_none() -> None:
    """페이지 메타가 None 인 항목은 그대로 None."""
    result = labels_for_pages([None, 779, None])  # 779 (0-indexed) → 780 (1-indexed)
    assert result[0] is None
    assert result[1] is not None
    assert result[1]["page"] == 780  # 0-indexed 779 → 1-indexed 780
    assert result[1]["section_slug"] == "3-21"
    assert result[2] is None


def test_labels_for_pages_outside_section() -> None:
    """0-indexed 49 → 1-indexed 50 → 5단원 외."""
    result = labels_for_pages([49])
    assert result[0]["display"] == "p.50"


# ====================================================================
# extract_cited_pages_from_text — Hybrid stream 후처리 정규식
# ====================================================================
def test_extract_simple_inline_citation() -> None:
    """답변 안 [p.124] 마커가 cited_pages 로 추출된다."""
    text = "칼빈은 예정론을 강조했다 [p.780]. 이는 어거스틴 영향 [p.169]."
    assert extract_cited_pages_from_text(text) == [780, 169]


def test_extract_dedupes_repeated_pages() -> None:
    """같은 페이지 여러 번 인용 — 등장 순서 보존하며 중복 제거."""
    text = "[p.780] foo [p.169] bar [p.780] baz"
    assert extract_cited_pages_from_text(text) == [780, 169]


def test_extract_no_citation_returns_empty() -> None:
    text = "칼빈은 예정론을 강조했다."
    assert extract_cited_pages_from_text(text) == []


def test_extract_ignores_unrelated_brackets() -> None:
    """일반 [N] 또는 [page N] 패턴은 무시 ([p.N] 만 매칭)."""
    text = "참고 [1] 또는 [page 124] 또는 [p.124] 그리고 [P.999]"
    # [P.999] 는 대문자라 매칭 안 됨 (정규식 case-sensitive)
    assert extract_cited_pages_from_text(text) == [124]


def test_extract_multiple_in_sentence() -> None:
    text = "예정론 [p.780][p.781][p.782] 세 페이지 모두 핵심"
    assert extract_cited_pages_from_text(text) == [780, 781, 782]
