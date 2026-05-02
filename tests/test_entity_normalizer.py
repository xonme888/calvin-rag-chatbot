"""KG 엔티티 정규화 단위 테스트 (LLM/DB 호출 0회)."""

from __future__ import annotations

from rag_core.kg.entity_normalizer import (
    ENTITY_ALIASES,
    is_noise_entity,
    normalize_entity_id,
    normalize_subgraph,
)
from rag_core.kg.port import GraphEdge, GraphNode, SubgraphData


# ====================================================================
# normalize_entity_id
# ====================================================================
def test_alias_mapping_augustine_to_korean() -> None:
    assert normalize_entity_id("Augustine") == "어거스틴"
    assert normalize_entity_id("St. Augustine") == "어거스틴"


def test_alias_mapping_calvin() -> None:
    assert normalize_entity_id("Calvin") == "칼빈"
    assert normalize_entity_id("John Calvin") == "칼빈"


def test_korean_id_unchanged() -> None:
    """한글 인명은 alias 없이 그대로 — 의미 손실 방지."""
    assert normalize_entity_id("어거스틴") == "어거스틴"
    assert normalize_entity_id("칼빈") == "칼빈"


def test_strip_whitespace() -> None:
    assert normalize_entity_id("  Augustine  ") == "어거스틴"


def test_unknown_entity_returns_as_is() -> None:
    """사전에 없는 엔티티는 그대로 (자동 통합 금지)."""
    assert normalize_entity_id("예정론") == "예정론"
    assert normalize_entity_id("자유의지") == "자유의지"


# ====================================================================
# is_noise_entity
# ====================================================================
def test_noise_filter_one_char() -> None:
    assert is_noise_entity("그")
    assert is_noise_entity("이")
    assert is_noise_entity("a")


def test_noise_filter_hash_id() -> None:
    """LLMGraphTransformer가 가끔 만드는 16진수 hash 유사 노드."""
    assert is_noise_entity("61c7fcce7e942e277b5770daeb47bd")
    assert is_noise_entity("dbe714caac3d594b52d1784e67d606")


def test_noise_filter_digits_only() -> None:
    assert is_noise_entity("123")
    assert is_noise_entity("3.21")
    assert is_noise_entity("(1)")


def test_meaningful_entity_not_noise() -> None:
    assert not is_noise_entity("어거스틴")
    assert not is_noise_entity("예정론")
    assert not is_noise_entity("Augustine")
    assert not is_noise_entity("이신칭의")


# ====================================================================
# normalize_subgraph — alias 통합 + 엣지 dedup + self-loop 제거
# ====================================================================
def test_subgraph_alias_merges_duplicate_nodes() -> None:
    """Augustine과 어거스틴이 한 노드로 합쳐진다."""
    sg = SubgraphData(
        nodes=[
            GraphNode(id="Augustine", label="Augustine", type="Person"),
            GraphNode(id="어거스틴", label="어거스틴", type="Person"),
            GraphNode(id="예정론", label="예정론", type="Concept"),
        ],
        edges=[
            GraphEdge(source="Augustine", target="예정론", label="DEFINES"),
            GraphEdge(source="어거스틴", target="예정론", label="INFLUENCES"),
        ],
    )
    out = normalize_subgraph(sg)
    ids = {n.id for n in out.nodes}
    assert ids == {"어거스틴", "예정론"}
    # 엣지는 두 개 보존 (label이 다르므로)
    assert len(out.edges) == 2
    assert all(e.source == "어거스틴" for e in out.edges)


def test_subgraph_dedup_identical_edges() -> None:
    """source/target/label이 완전 동일하면 1개로 합침."""
    sg = SubgraphData(
        nodes=[
            GraphNode(id="Augustine", label="Augustine", type="Person"),
            GraphNode(id="어거스틴", label="어거스틴", type="Person"),
            GraphNode(id="예정론", label="예정론", type="Concept"),
        ],
        edges=[
            GraphEdge(source="Augustine", target="예정론", label="DEFINES"),
            GraphEdge(source="어거스틴", target="예정론", label="DEFINES"),  # 정규화 후 동일
        ],
    )
    out = normalize_subgraph(sg)
    assert len(out.edges) == 1


def test_subgraph_removes_noise_nodes_and_dependent_edges() -> None:
    """1자 노드와 그 노드를 참조하는 엣지가 모두 제거된다."""
    sg = SubgraphData(
        nodes=[
            GraphNode(id="그", label="그", type="Concept"),
            GraphNode(id="예정론", label="예정론", type="Concept"),
        ],
        edges=[GraphEdge(source="그", target="예정론", label="INFLUENCES")],
    )
    out = normalize_subgraph(sg)
    assert len(out.nodes) == 1
    assert out.nodes[0].id == "예정론"
    assert out.edges == []


def test_subgraph_removes_self_loops() -> None:
    """alias 후 self-loop가 생기면 제거 (Augustine → 어거스틴 두 노드를 연결한 엣지)."""
    sg = SubgraphData(
        nodes=[
            GraphNode(id="Augustine", label="Augustine", type="Person"),
            GraphNode(id="어거스틴", label="어거스틴", type="Person"),
        ],
        edges=[GraphEdge(source="Augustine", target="어거스틴", label="SAME_AS")],
    )
    out = normalize_subgraph(sg)
    assert len(out.nodes) == 1
    assert out.edges == []


def test_subgraph_empty_input_safe() -> None:
    out = normalize_subgraph(SubgraphData())
    assert out.nodes == []
    assert out.edges == []


def test_alias_dictionary_has_expected_persons() -> None:
    """주요 칼빈 신학 인물이 alias 사전에 등록되어 있다."""
    expected = {"Augustine", "Pelagius", "Luther", "Calvin", "Aquinas", "Zwingli"}
    assert expected.issubset(set(ENTITY_ALIASES.keys()))
