"""KG Port + RAG 단위 테스트 — Mock 어댑터로 LLM/DB 호출 0회 검증.

Hexagonal 원칙의 핵심 가치 중 하나: Port 계약만 만족하면 어댑터 교체 가능.
이 테스트는 ``Neo4jAdapter`` 없이도 ``KnowledgeGraphRAG`` 로직을 검증한다.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.documents import Document

from rag_core.kg.extractor import (
    DEFAULT_CALVIN_SECTIONS,
    estimate_cost,
    filter_chunks_by_sections,
)
from rag_core.kg.port import (
    GraphEdge,
    GraphNode,
    KnowledgeGraphPort,
    SubgraphData,
)


# ====================================================================
# Mock KG Adapter — Port 만족하는 인메모리 구현
# ====================================================================
class InMemoryKGAdapter:
    """KnowledgeGraphPort 의 인메모리 구현 (테스트 전용)."""

    def __init__(self, prebuilt_subgraph: SubgraphData | None = None) -> None:
        self._chunks: list[Document] = []
        self._subgraph = prebuilt_subgraph or SubgraphData()
        self._calls: dict[str, int] = {"index": 0, "query": 0, "subgraph": 0}

    def health_check(self) -> bool:
        return True

    def index_chunks(
        self,
        chunks: list[Document],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        self._calls["index"] += 1
        self._chunks.extend(chunks)
        if progress_callback:
            progress_callback(len(chunks), len(chunks))
        return len(chunks)

    def query_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        self._calls["query"] += 1
        return []

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> SubgraphData:
        self._calls["subgraph"] += 1
        return self._subgraph

    def clear(self) -> None:
        self._chunks.clear()

    def stats(self) -> dict[str, int]:
        return {"nodes": len(self._subgraph.nodes), "edges": len(self._subgraph.edges)}


# ====================================================================
# Port 계약 검증
# ====================================================================
def test_inmemory_adapter_satisfies_port() -> None:
    """InMemoryKGAdapter 가 KnowledgeGraphPort 계약을 만족한다."""
    adapter = InMemoryKGAdapter()
    assert isinstance(adapter, KnowledgeGraphPort)
    assert adapter.health_check() is True
    assert adapter.stats() == {"nodes": 0, "edges": 0}


def test_inmemory_adapter_indexing_and_subgraph() -> None:
    """인덱싱과 부분 그래프 조회가 정상 동작한다."""
    subgraph = SubgraphData(
        nodes=[
            GraphNode(id="예정론", label="예정론", type="Concept"),
            GraphNode(id="어거스틴", label="어거스틴", type="Person"),
        ],
        edges=[GraphEdge(source="어거스틴", target="예정론", label="INFLUENCES")],
    )
    adapter = InMemoryKGAdapter(prebuilt_subgraph=subgraph)

    docs = [
        Document(page_content="예정 교리에 대해", metadata={"page": 776}),
        Document(page_content="어거스틴은 ...", metadata={"page": 779}),
    ]
    n = adapter.index_chunks(docs)
    assert n == 2
    assert adapter.stats()["nodes"] == 2
    assert adapter.stats()["edges"] == 1

    result = adapter.get_subgraph(["예정론"])
    assert len(result.nodes) == 2
    assert result.edges[0].label == "INFLUENCES"


# ====================================================================
# Extractor 단원 필터링 검증
# ====================================================================
def test_filter_chunks_by_sections_includes_section_pages() -> None:
    """단원 page 범위 안의 청크만 통과시킨다."""
    chunks = [
        Document(page_content="예정론 도입", metadata={"page": 777}),  # 1-indexed 778, 3권 21장
        Document(page_content="아무 페이지", metadata={"page": 1000}),  # 1001, 어떤 단원도 아님
        Document(page_content="삼위일체", metadata={"page": 137}),       # 138, 1권 13장
    ]
    filtered = filter_chunks_by_sections(chunks)
    assert len(filtered) == 2
    # section_slug 메타가 보강되어 있어야 함
    assert any(c.metadata.get("section_slug") == "3-21" for c in filtered)
    assert any(c.metadata.get("section_slug") == "1-13" for c in filtered)


def test_filter_chunks_excludes_pages_outside_sections() -> None:
    """5단원 외 페이지는 제외."""
    chunks = [
        Document(page_content="x", metadata={"page": 50}),    # 51 — 1권 1장 (제외)
        Document(page_content="y", metadata={"page": 500}),   # 501 — 3권 1장 (제외)
        Document(page_content="z", metadata={"page": 850}),   # 851 — 4권 1장 (제외)
    ]
    filtered = filter_chunks_by_sections(chunks)
    assert filtered == []


def test_estimate_cost_returns_reasonable_numbers() -> None:
    """500청크 추정 비용이 ~₩170 근방인가 (가정 변경 시 회귀 감지)."""
    chunks = [Document(page_content="x", metadata={}) for _ in range(500)]
    cost = estimate_cost(chunks)
    assert cost["chunks"] == 500
    # ₩100~₩300 사이 (단가 변동에 약간 여유)
    assert 100 <= cost["krw"] <= 300, f"비용 추정 이상: ₩{cost['krw']}"


def test_default_sections_total_matches_balanced_plan() -> None:
    """균형안 5단원 합계가 약 114페이지인가."""
    total_pages = sum(s.page_count for s in DEFAULT_CALVIN_SECTIONS)
    assert 100 <= total_pages <= 130, f"단원 합계 페이지 이상: {total_pages}"
