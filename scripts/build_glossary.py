"""칼빈 강요 5단원 청크에서 글로서리 자동 추출.

이미 구축된 자산 재활용:
- ``build_calvin_rag()`` 의 청크 (PDF 재로드 X)
- ``filter_chunks_by_sections(DEFAULT_CALVIN_SECTIONS)`` — 5단원 필터
- 각 청크의 ``metadata.page`` 로 정확한 페이지 매핑

흐름:
1. Hybrid RAG 빌드 (인덱스 캐시 활용 — 재인덱싱 없음)
2. 5단원 청크만 추출
3. 단원별로 청크 텍스트 합쳐 LLM 호출 (gpt-4o-mini, structured output)
4. 단원당 핵심 용어 6~12개 + 정의 + 대표 페이지
5. data/glossary/calvin.json 출력 (덮어쓰기 또는 병합)

비용 추정:
- 단원당 입력 ~30K 토큰 + 출력 ~3K 토큰
- gpt-4o-mini: 단원당 ~$0.01 = 5단원 ~$0.05 ≈ ₩75

사용:
    python scripts/build_glossary.py [--out PATH] [--merge]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# 프로젝트 루트 sys.path 보강
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field as PydanticField

from rag_core.calvin_builder import build_calvin_rag
from rag_core.hybrid import get_config
from rag_core.kg.section_filter import (
    DEFAULT_CALVIN_SECTIONS,
    CalvinSection,
    filter_chunks_by_sections,
)

_DEFAULT_OUT = _PROJECT_ROOT / "data" / "glossary" / "calvin.json"


# ====================================================================
# Structured output 스키마
# ====================================================================
class _GlossaryItem(PydanticBaseModel):
    term: str = PydanticField(description="핵심 용어 (한국어 명사형, 2~10자)")
    aliases: list[str] = PydanticField(
        default_factory=list,
        description="동의어/영문/이형. 0~3개. 예: predestination, 예정 교리.",
    )
    definition: str = PydanticField(
        description="60~140자 한국어 정의. 환각 금지 — 본문에 근거.",
    )


class _SectionGlossary(PydanticBaseModel):
    items: list[_GlossaryItem] = PydanticField(
        default_factory=list,
        description="이 단원의 핵심 신학 용어 6~12개.",
    )


# ====================================================================
# Prompt
# ====================================================================
_SYSTEM = """당신은 칼빈 신학 학습 도우미의 글로서리 큐레이터입니다.
주어진 칼빈 강요 본문 발췌를 보고 그 단원의 핵심 신학 용어 6~12개를 추출하세요.

규칙:
- 인물명 (예: 어거스틴, 펠라기우스) 과 핵심 교리 (예: 예정론, 이신칭의) 우선
- 너무 일반적인 단어 (하나님, 믿음 등 단독) 는 제외
- 정의는 본문 근거로만 60~140자 — 추측·외부 지식 금지
- aliases 는 0~3개 — 동의어/영문/이형만
- 한 용어가 단원에 등장하는 핵심 개념이어야 함
"""

_HUMAN = """## 단원: {label}
{description}

## 본문 발췌 (페이지 {page_start}~{page_end})
{context}

위 본문에서 핵심 신학 용어 6~12개를 추출하세요.
"""


# ====================================================================
# 핵심 로직
# ====================================================================
def _llm() -> ChatOpenAI:
    cfg = get_config()
    return ChatOpenAI(
        api_key=cfg.open_api_key,
        model="gpt-4o-mini",
        temperature=0,
    )


def _representative_page(chunks_for_term: list, term: str) -> tuple[int, str] | None:
    """용어가 가장 자주 등장한 청크의 페이지 + 단원 라벨 라벨링."""
    pages: Counter[int] = Counter()
    page_labels: dict[int, str] = {}
    for ch in chunks_for_term:
        if term in ch.page_content:
            page = ch.metadata.get("page")
            if page is None:
                continue
            page_1based = int(page) + 1
            pages[page_1based] += 1
            slug = ch.metadata.get("section_slug")
            label = ch.metadata.get("section_label")
            if slug and label:
                book, chap = slug.split("-")
                page_labels[page_1based] = f"p.{page_1based} ({book}권 {chap}장)"
            else:
                page_labels[page_1based] = f"p.{page_1based}"
    if not pages:
        return None
    top_page = pages.most_common(1)[0][0]
    return top_page, page_labels[top_page]


def _extract_section(
    section: CalvinSection,
    chunks: list,
    llm: ChatOpenAI,
    *,
    max_context_chars: int = 24000,
) -> list[dict]:
    """단원의 청크들을 하나로 합쳐 LLM 호출, 글로서리 항목 반환."""
    section_chunks = [c for c in chunks if c.metadata.get("section_slug") == section.slug]
    if not section_chunks:
        print(f"  [skip] {section.slug} {section.label} — 청크 0개", flush=True)
        return []

    # 청크 텍스트 합치기 — 너무 길면 truncate
    combined: list[str] = []
    total = 0
    for ch in section_chunks:
        snippet = f"[page {int(ch.metadata.get('page', 0)) + 1}]\n{ch.page_content.strip()}"
        if total + len(snippet) > max_context_chars:
            break
        combined.append(snippet)
        total += len(snippet)
    context = "\n\n---\n\n".join(combined)

    prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)])
    chain = prompt | llm.with_structured_output(_SectionGlossary)
    try:
        result = chain.invoke(
            {
                "label": section.label,
                "description": section.description,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "context": context,
            }
        )
    except Exception as e:  # noqa: BLE001
        print(f"  [error] {section.slug} {section.label} — {e}", flush=True)
        return []

    if not isinstance(result, _SectionGlossary):
        return []

    out: list[dict] = []
    for item in result.items:
        rep = _representative_page(section_chunks, item.term)
        sources = []
        if rep is not None:
            page, label = rep
            sources.append({"page": page, "label": label})
        out.append(
            {
                "term": item.term.strip(),
                "aliases": [a.strip() for a in item.aliases if a.strip()],
                "definition": item.definition.strip(),
                "sources": sources,
            }
        )
    print(
        f"  [done] {section.slug} {section.label} — {len(out)}개 추출",
        flush=True,
    )
    return out


def _merge_existing(out_path: Path, new_items: list[dict]) -> list[dict]:
    """기존 calvin.json 과 병합 — 같은 term 은 새 데이터로 갱신."""
    if not out_path.exists():
        return new_items
    try:
        existing = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return new_items
    by_term: dict[str, dict] = {item["term"]: item for item in existing if isinstance(item, dict)}
    for item in new_items:
        by_term[item["term"]] = item
    return list(by_term.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="칼빈 5단원에서 글로서리 자동 추출")
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="출력 JSON 경로")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="기존 파일과 병합 (term 중복 시 새 데이터로 갱신)",
    )
    args = parser.parse_args()

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("[1/3] Hybrid RAG 인덱스 로드 중 (캐시 활용)...", flush=True)
    rag = build_calvin_rag()

    print("[2/3] 5단원 청크 필터링...", flush=True)
    # retriever 의 chunks 직접 접근 (HybridRetriever 의 indexed chunks)
    raw_chunks = getattr(rag.retriever, "_chunks", None) or getattr(rag.retriever, "chunks", None)
    if raw_chunks is None:
        # fallback — PDF 재로드 후 split (캐시 미사용)
        from infra.document_loader import load_calvin

        raw_chunks = rag.retriever.text_splitter.split_documents(load_calvin())
    filtered = filter_chunks_by_sections(raw_chunks, DEFAULT_CALVIN_SECTIONS)
    print(f"  필터링 완료 — {len(filtered)} 청크 (전체 {len(raw_chunks)})", flush=True)

    print("[3/3] 단원별 LLM 호출 — gpt-4o-mini, structured output", flush=True)
    llm = _llm()
    all_items: list[dict] = []
    for section in DEFAULT_CALVIN_SECTIONS:
        items = _extract_section(section, filtered, llm)
        all_items.extend(items)

    if args.merge:
        all_items = _merge_existing(out_path, all_items)

    out_path.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n완료 — {len(all_items)}개 용어, {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
