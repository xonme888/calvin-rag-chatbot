"""KG 인덱싱용 청크 추출기.

칼빈 강요 PDF → 청크 분할 → 핵심 단원 page 범위로 필터링.

균형안 5단원(약 114p, ~510청크, ~₩175):
- 1권 13장 (삼위일체론)
- 2권 2장 (자유의지)
- 3권 11장 (이신칭의)
- 3권 21장 (예정론 서론)
- 4권 14장 (성례 총론)

자동 추출 시 +1 보정 적용 (이전 장 잔여 1페이지 침범 패턴 검증 완료).
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass(frozen=True)
class CalvinSection:
    """칼빈 강요의 한 단원 정의.

    page_start/page_end는 1-indexed (사람이 보는 페이지 번호).
    PDF의 metadata['page']는 0-indexed이므로 비교 시 +1 변환 필요.
    """

    book: int
    chapter: int
    label: str
    page_start: int  # 1-indexed, inclusive
    page_end: int    # 1-indexed, inclusive
    description: str = ""

    @property
    def slug(self) -> str:
        """식별용 짧은 키. 예: '1-13', '3-21'."""
        return f"{self.book}-{self.chapter}"

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1


# 균형안 5단원 (본문 검증 완료, +1 보정 반영).
# 이 정의를 환경별로 바꾸려면 KG_SECTION_PAGES env 또는 외부 JSON 주입을 추가.
DEFAULT_CALVIN_SECTIONS: tuple[CalvinSection, ...] = (
    CalvinSection(
        book=1, chapter=13, label="삼위일체론",
        page_start=136, page_end=169,
        description="한 본체 안의 삼위 — 성부, 성자, 성령의 동일 본질과 구별",
    ),
    CalvinSection(
        book=2, chapter=2, label="자유의지",
        page_start=246, page_end=272,
        description="타락한 인간의 자유의지 — 펠라기우스 비판, 어거스틴 계승",
    ),
    CalvinSection(
        book=3, chapter=11, label="이신칭의",
        page_start=618, page_end=640,
        description="믿음으로 의롭게 된다 — 칭의의 정의, 행위와의 관계",
    ),
    CalvinSection(
        book=3, chapter=21, label="예정론(서론)",
        page_start=778, page_end=786,
        description="예정 교리의 필요성과 위험 — 칼빈 신학의 정수",
    ),
    CalvinSection(
        book=4, chapter=14, label="성례(총론)",
        page_start=1060, page_end=1080,
        description="성례의 정의와 본질 — 보이는 말씀, 외형적 표징",
    ),
)


def filter_chunks_by_sections(
    chunks: list[Document],
    sections: tuple[CalvinSection, ...] = DEFAULT_CALVIN_SECTIONS,
) -> list[Document]:
    """청크 리스트에서 핵심 단원 page 범위에 속한 것만 반환한다.

    Document.metadata['page']는 PyMuPDFLoader가 0-indexed로 저장.
    1-indexed로 변환해 단원 page 범위와 비교.

    각 청크의 metadata에 ``section_slug`` (예: "3-21")와 ``section_label`` 추가.
    KG 노드의 출처 추적에 유용.

    Args:
        chunks: 전체 청크 리스트.
        sections: 필터링 기준이 되는 단원 정의.

    Returns:
        필터링된 청크 (메타데이터 보강).
    """
    filtered: list[Document] = []
    for chunk in chunks:
        page_0indexed = chunk.metadata.get("page")
        if page_0indexed is None:
            continue
        page_1indexed = page_0indexed + 1
        for section in sections:
            if section.page_start <= page_1indexed <= section.page_end:
                # 메타데이터 보강 (원본 dict는 변형하지 않음)
                new_metadata = {
                    **chunk.metadata,
                    "section_slug": section.slug,
                    "section_label": section.label,
                    "section_book": section.book,
                    "section_chapter": section.chapter,
                }
                filtered.append(
                    Document(page_content=chunk.page_content, metadata=new_metadata)
                )
                break
    return filtered


def estimate_cost(chunks: list[Document]) -> dict[str, float]:
    """LLMGraphTransformer 인덱싱 비용/시간 추정.

    가정 (gpt-4o-mini, 2026.05 기준):
        - input  ≈ 700 tokens / chunk @ $0.150/1M tokens
        - output ≈ 200 tokens / chunk @ $0.600/1M tokens
        - 처리 시간 ≈ 2초/chunk (rate limit 고려)
        - ₩1,500/$1

    Returns:
        {chunks, usd, krw, minutes}
    """
    n = len(chunks)
    cost_per_chunk_usd = (700 * 0.15 / 1_000_000) + (200 * 0.60 / 1_000_000)
    total_usd = n * cost_per_chunk_usd
    return {
        "chunks": n,
        "usd": round(total_usd, 4),
        "krw": round(total_usd * 1500, 1),
        "minutes": round(n * 2 / 60, 1),
    }
