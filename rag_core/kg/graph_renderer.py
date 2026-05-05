"""KG 시각화 — SubgraphData → streamlit-agraph/pyvis 입력 변환.

streamlit-agraph는 lazy import (.[kg] 미설치 시도 import 자체는 성공해야 함).
"""

from __future__ import annotations

from typing import Any

from rag_core.kg.port import GraphNode, SubgraphData

# 노드 타입별 색상 (시각적 구분용)
NODE_COLOR_BY_TYPE: dict[str, str] = {
    "Concept": "#4F46E5",  # 인디고 — 신학 개념
    "Person": "#DC2626",  # 빨강 — 인물 (어거스틴, 펠라기우스 등)
    "Doctrine": "#059669",  # 초록 — 교리
    "Event": "#D97706",  # 주황 — 사건
    "Document": "#6B7280",  # 회색 — 출처 (원본 청크)
    "Entity": "#3B82F6",  # 파랑 — 분류 미상 (fallback)
}

DEFAULT_NODE_COLOR = "#3B82F6"


def to_agraph_format(subgraph: SubgraphData) -> dict[str, Any]:
    """SubgraphData → streamlit-agraph가 받는 형식.

    streamlit-agraph 사용 예:
        from streamlit_agraph import agraph, Node, Edge, Config
        data = to_agraph_format(subgraph)
        agraph(nodes=data['nodes'], edges=data['edges'], config=Config(height=500))

    Returns:
        {nodes: list[Node], edges: list[Edge], summary: dict}
    """
    try:
        from streamlit_agraph import Edge, Node
    except ImportError as e:
        raise ImportError(
            "streamlit-agraph가 설치되지 않았습니다. uv pip install -e '.[kg]' 로 설치하세요."
        ) from e

    nodes = [
        Node(
            id=n.id,
            label=_truncate(n.label, 24),
            size=_node_size(n),
            color=NODE_COLOR_BY_TYPE.get(n.type, DEFAULT_NODE_COLOR),
            title=_node_tooltip(n),
        )
        for n in subgraph.nodes
    ]
    edges = [
        Edge(
            source=e.source,
            target=e.target,
            label=e.label,
            type="CURVE_SMOOTH",
        )
        for e in subgraph.edges
        if e.source and e.target
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "type_breakdown": _count_by_type(subgraph.nodes),
        },
    }


def _node_size(node: GraphNode) -> int:
    """노드 타입별 시각 크기."""
    if node.type in ("Person", "Doctrine"):
        return 25
    if node.type == "Concept":
        return 20
    return 15


def _node_tooltip(node: GraphNode) -> str:
    """마우스 hover 시 표시될 정보."""
    desc = node.properties.get("description", "")
    type_str = f"({node.type})" if node.type != "Entity" else ""
    return f"{node.label} {type_str}\n{desc}".strip()


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _count_by_type(nodes: list[GraphNode]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.type] = counts.get(n.type, 0) + 1
    return counts


def to_pyvis_html(subgraph: SubgraphData, height: str = "500px") -> str:
    """pyvis 사용 시 HTML 문자열 반환 (streamlit-agraph 대안).

    Streamlit `st.components.v1.html` 로 렌더링.

    Returns:
        pyvis가 생성한 인터랙티브 그래프 HTML.
    """
    try:
        from pyvis.network import Network
    except ImportError as e:
        raise ImportError(
            "pyvis가 설치되지 않았습니다. (kg 옵션 그룹은 streamlit-agraph 사용 권장)"
        ) from e

    net = Network(height=height, directed=True, notebook=False, cdn_resources="in_line")
    for n in subgraph.nodes:
        net.add_node(
            n.id,
            label=_truncate(n.label, 24),
            color=NODE_COLOR_BY_TYPE.get(n.type, DEFAULT_NODE_COLOR),
            title=_node_tooltip(n),
        )
    for e in subgraph.edges:
        if e.source and e.target:
            net.add_edge(e.source, e.target, label=e.label)
    return net.generate_html(notebook=False)
