"""KG 관련 stage 3개 테스트 — extract_entities (LLM 의존이라 import만), normalize_subgraph, section_filter."""

from __future__ import annotations

from chatbot.domain.indexing import Chunk
from chatbot.domain.retrieval import GraphEdge, GraphNode, Subgraph
from chatbot.infrastructure.stages import (
    DEFAULT_CALVIN_SECTIONS,
    ExtractEntitiesStage,
    NormalizeSubgraphStage,
    Section,
    SectionFilterStage,
)


# ============================================================
# NormalizeSubgraphStage
# ============================================================
def test_normalize_alias_통합():
    """Augustine + 어거스틴 → 어거스틴 1개 노드."""
    sg = Subgraph(
        nodes=(
            GraphNode(id="Augustine", label="Augustine"),
            GraphNode(id="어거스틴", label="어거스틴"),
        ),
        edges=(GraphEdge(source="Augustine", target="어거스틴", label="SAME"),),
    )
    out = NormalizeSubgraphStage().run(sg)
    assert {n.id for n in out.nodes} == {"어거스틴"}
    # self-loop (alias 통합 후) 제거
    assert len(out.edges) == 0


def test_normalize_노이즈_제거():
    sg = Subgraph(
        nodes=(
            GraphNode(id="a", label="a"),  # 1자
            GraphNode(id="abcdef0123456789abcd", label="hash"),  # hash
            GraphNode(id="123,456", label="nums"),  # 숫자만
            GraphNode(id="칼빈", label="칼빈"),
        ),
        edges=(),
    )
    out = NormalizeSubgraphStage().run(sg)
    assert {n.id for n in out.nodes} == {"칼빈"}


def test_normalize_엣지_dedup():
    """정규화 후 같은 (source, target, label) 엣지 1개만 유지."""
    sg = Subgraph(
        nodes=(
            GraphNode(id="Calvin", label="Calvin"),
            GraphNode(id="Augustine", label="Augustine"),
        ),
        edges=(
            GraphEdge(source="Augustine", target="Calvin", label="INFLUENCES"),
            GraphEdge(
                source="어거스틴", target="칼빈", label="INFLUENCES"
            ),  # 그러나 nodes 에 한국어가 없음
        ),
    )
    # 두 번째 엣지의 source/target 이 nodes 에 없으니 빠짐
    out = NormalizeSubgraphStage().run(sg)
    assert len(out.edges) == 1
    assert out.edges[0].source == "어거스틴"
    assert out.edges[0].target == "칼빈"


def test_normalize_self_loop_제거():
    sg = Subgraph(
        nodes=(GraphNode(id="x", label="x"),),
        edges=(GraphEdge(source="x", target="x", label="SELF"),),
    )
    out = NormalizeSubgraphStage().run(sg)
    assert out.edges == ()


# ============================================================
# SectionFilterStage
# ============================================================
def test_section_filter_단원_매칭():
    chunks = [
        Chunk(id="c:1", content="삼위일체 본문", metadata={"page": "139"}),  # 1권 13장
        Chunk(id="c:2", content="예정론 본문", metadata={"page": "779"}),  # 3권 21장
        Chunk(id="c:3", content="범위 밖", metadata={"page": "500"}),
    ]
    out = SectionFilterStage().run(chunks)
    assert len(out) == 2
    assert out[0].metadata["section_slug"] == "1-13"
    assert out[1].metadata["section_slug"] == "3-21"


def test_section_filter_page_없음_제외():
    chunks = [Chunk(id="c", content="x", metadata={})]
    assert SectionFilterStage().run(chunks) == []


def test_section_filter_page_str_타입_지원():
    """metadata.page 가 str 로 와도 int 변환."""
    chunks = [Chunk(id="c", content="x", metadata={"page": "139"})]
    out = SectionFilterStage().run(chunks)
    assert len(out) == 1


def test_section_filter_page_변환_실패_제외():
    chunks = [Chunk(id="c", content="x", metadata={"page": "abc"})]
    assert SectionFilterStage().run(chunks) == []


def test_section_filter_경계_시작():
    """page_0 = 135 → page_1 = 136 (1권 13장 시작)."""
    chunks = [Chunk(id="c", content="x", metadata={"page": "135"})]
    out = SectionFilterStage().run(chunks)
    assert len(out) == 1
    assert out[0].metadata["section_slug"] == "1-13"


def test_section_filter_경계_끝():
    """page_0 = 168 → page_1 = 169 (1권 13장 끝)."""
    chunks = [Chunk(id="c", content="x", metadata={"page": "168"})]
    out = SectionFilterStage().run(chunks)
    assert len(out) == 1


def test_section_filter_경계_밖():
    """page_0 = 169 → page_1 = 170 (1권 13장 끝 + 1)."""
    chunks = [Chunk(id="c", content="x", metadata={"page": "169"})]
    assert SectionFilterStage().run(chunks) == []


def test_section_filter_원본_metadata_보존():
    chunks = [
        Chunk(id="c", content="x", metadata={"page": "139", "extra": "preserved"}),
    ]
    out = SectionFilterStage().run(chunks)
    assert out[0].metadata["extra"] == "preserved"
    assert out[0].metadata["page"] == "139"


def test_section_slug():
    s = Section(book=3, chapter=21, label="x", page_start=1, page_end=2)
    assert s.slug == "3-21"
    assert s.page_count == 2


def test_default_calvin_sections_5개():
    assert len(DEFAULT_CALVIN_SECTIONS) == 5
    slugs = [s.slug for s in DEFAULT_CALVIN_SECTIONS]
    assert slugs == ["1-13", "2-2", "3-11", "3-21", "4-14"]


# ============================================================
# ExtractEntitiesStage — 인스턴스화만 (LLM 호출은 Phase 2 audit 회귀에서)
# ============================================================
def test_extract_entities_stage_인스턴스화():
    stage = ExtractEntitiesStage(llm=None)  # type: ignore[arg-type]
    assert stage.name == "extract_entities"
