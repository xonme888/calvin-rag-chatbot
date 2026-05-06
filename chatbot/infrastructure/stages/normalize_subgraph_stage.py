"""부분 그래프 정규화 단계 — alias 통합 + 노이즈 노드/엣지 제거.

기존 ``rag_core/kg/entity_normalizer.normalize_subgraph`` 의 알고리즘을 *재사용* 하되
입출력을 도메인 ``Subgraph`` (chatbot/domain/retrieval.py) 단일 형식으로 통일한다.

LLMGraphTransformer 가 같은 인물을 한/영 두 가지로 추출하는 경향 (예: "Augustine" vs
"어거스틴") 을 사전 기반으로 통합. 자동 임베딩 유사도 통합은 의미 손실 위험으로 미사용.
"""

from __future__ import annotations

import re

from chatbot.domain.retrieval import GraphEdge, GraphNode, Subgraph

# 인물명 영문 → 한글 정규화. 단순 매칭만 — 자동 통합 안 함.
# rag_core/kg/entity_normalizer.ENTITY_ALIASES 와 동일 사전.
_ENTITY_ALIASES: dict[str, str] = {
    "Augustine": "어거스틴",
    "St. Augustine": "어거스틴",
    "Saint Augustine": "어거스틴",
    "St Augustine": "어거스틴",
    "Pelagius": "펠라기우스",
    "Luther": "루터",
    "Martin Luther": "루터",
    "Calvin": "칼빈",
    "John Calvin": "칼빈",
    "Aquinas": "아퀴나스",
    "Thomas Aquinas": "아퀴나스",
    "Zwingli": "츠빙글리",
    "Ulrich Zwingli": "츠빙글리",
    "Servetus": "세르베투스",
    "Michael Servetus": "세르베투스",
    "Arius": "아리우스",
}

_HASH_ID_PATTERN = re.compile(r"^[a-f0-9]{20,}$", re.IGNORECASE)
_DIGITS_OR_SYMBOL_ONLY = re.compile(r"^[\.\,\d\s\-\(\)]+$")


def _normalize_id(raw: str) -> str:
    cleaned = raw.strip()
    return _ENTITY_ALIASES.get(cleaned, cleaned)


def _is_noise(entity_id: str) -> bool:
    """1자, hash, 숫자만 — 시각화 노이즈로 판정 (entity_normalizer 와 동일)."""
    if len(entity_id) < 2:
        return True
    if _HASH_ID_PATTERN.match(entity_id):
        return True
    if _DIGITS_OR_SYMBOL_ONLY.match(entity_id):
        return True
    return False


class NormalizeSubgraphStage:
    """Subgraph → 정규화 Subgraph. alias 통합·노이즈 제거·엣지 dedup·self-loop 제거."""

    name: str = "normalize_subgraph"

    def run(self, input: Subgraph) -> Subgraph:
        nodes_by_id: dict[str, GraphNode] = {}
        id_remap: dict[str, str] = {}

        for node in input.nodes:
            if _is_noise(node.id):
                continue
            new_id = _normalize_id(node.id)
            id_remap[node.id] = new_id
            if new_id not in nodes_by_id:
                nodes_by_id[new_id] = GraphNode(
                    id=new_id,
                    label=new_id,
                    type=node.type,
                    metadata=dict(node.metadata),
                )

        new_edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for edge in input.edges:
            new_src = id_remap.get(edge.source)
            new_tgt = id_remap.get(edge.target)
            if not new_src or not new_tgt:
                continue
            if new_src == new_tgt:
                continue
            edge_label = edge.label or ""
            key = (new_src, new_tgt, edge_label)
            if key in seen:
                continue
            seen.add(key)
            new_edges.append(
                GraphEdge(
                    source=new_src,
                    target=new_tgt,
                    label=edge.label,
                    metadata=dict(edge.metadata),
                )
            )

        return Subgraph(
            nodes=tuple(nodes_by_id.values()),
            edges=tuple(new_edges),
            metadata=dict(input.metadata),
        )
