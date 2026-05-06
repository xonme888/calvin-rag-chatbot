"""단원 범위 필터 단계 — Chunk 시퀀스에서 핵심 단원 page 범위만 통과.

기존 ``rag_core/kg/section_filter.filter_chunks_by_sections`` 의 알고리즘을 *재사용* 하되
입출력을 도메인 ``Chunk`` (chatbot/domain/indexing.py) 로 통일.

PyMuPDFLoader 가 ``page`` 를 0-indexed 로 저장하므로 +1 변환 후 1-indexed 범위와 비교.
필터 통과한 chunk 의 metadata 에 ``section_slug`` / ``section_label`` 보강.

칼빈 corpus 의 5단원 정의 (DEFAULT_CALVIN_SECTIONS) 는 corpus 도메인 데이터로 묶을 수 있다.
본 파일은 *알고리즘만* 노출 — 단원 정의는 인자로 받음.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbot.domain.indexing import Chunk


@dataclass(frozen=True)
class Section:
    """corpus 단원 1개. page_start/page_end 는 1-indexed inclusive."""

    book: int
    chapter: int
    label: str
    page_start: int
    page_end: int
    description: str = ""

    @property
    def slug(self) -> str:
        """식별용 짧은 키. 예: '1-13', '3-21'."""
        return f"{self.book}-{self.chapter}"

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1


# ============================================================
# 칼빈 강요 5단원 — rag_core/kg/section_filter.DEFAULT_CALVIN_SECTIONS 와 동일.
# 새 corpus 추가 시 본 모듈 외부에서 자체 sections tuple 정의.
# ============================================================
DEFAULT_CALVIN_SECTIONS: tuple[Section, ...] = (
    Section(
        book=1,
        chapter=13,
        label="삼위일체론",
        page_start=136,
        page_end=169,
        description="한 본체 안의 삼위 — 성부, 성자, 성령의 동일 본질과 구별",
    ),
    Section(
        book=2,
        chapter=2,
        label="자유의지",
        page_start=246,
        page_end=272,
        description="타락한 인간의 자유의지 — 펠라기우스 비판, 어거스틴 계승",
    ),
    Section(
        book=3,
        chapter=11,
        label="이신칭의",
        page_start=618,
        page_end=640,
        description="믿음으로 의롭게 된다 — 칭의의 정의, 행위와의 관계",
    ),
    Section(
        book=3,
        chapter=21,
        label="예정론(서론)",
        page_start=778,
        page_end=786,
        description="예정 교리의 필요성과 위험 — 칼빈 신학의 정수",
    ),
    Section(
        book=4,
        chapter=14,
        label="성례(총론)",
        page_start=1060,
        page_end=1080,
        description="성례의 정의와 본질 — 보이는 말씀, 외형적 표징",
    ),
)


class SectionFilterStage:
    """Chunk 시퀀스 → 단원 범위 통과 Chunk 시퀀스 (메타 보강)."""

    name: str = "section_filter"

    def __init__(self, sections: tuple[Section, ...] = DEFAULT_CALVIN_SECTIONS) -> None:
        self._sections = sections

    def run(self, input: list[Chunk]) -> list[Chunk]:
        out: list[Chunk] = []
        for chunk in input:
            page_0 = _parse_page(chunk.metadata.get("page"))
            if page_0 is None:
                continue
            page_1 = page_0 + 1
            for section in self._sections:
                if section.page_start <= page_1 <= section.page_end:
                    new_meta = {
                        **chunk.metadata,
                        "section_slug": section.slug,
                        "section_label": section.label,
                        "section_book": str(section.book),
                        "section_chapter": str(section.chapter),
                    }
                    out.append(Chunk(id=chunk.id, content=chunk.content, metadata=new_meta))
                    break
        return out


def _parse_page(raw: str | None) -> int | None:
    """metadata.page (str) → int. 변환 실패 시 None — 청크 제외."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
