"""KG 엔티티 정규화 — alias 통합 + 노이즈 노드 필터.

LLMGraphTransformer는 같은 인물을 한/영 두 가지로 추출하는 경향이 있다
(예: "Augustine" vs "어거스틴"). 이를 그대로 시각화하면 그래프에 같은 인물이
두 번 나타나며 관계도 분산된다.

이 모듈은 **명시 사전 기반 alias 통합** 만 수행 — 의미가 비슷해 보이는 다른
개념을 자동 통합하지 않는다 (의미 손실 위험). 인물명만 안전하게 통합한다.

또 1자 노드, 16진수 hash ID 같은 노이즈 패턴을 제거한다.
"""

from __future__ import annotations

import re

from rag_core.kg.port import GraphEdge, GraphNode, SubgraphData

# ====================================================================
# Alias 사전 — 명시적으로 같다고 확신할 수 있는 항목만
# ====================================================================
# 인물명 영문 → 한글 정규화. 단순 매칭 외에는 자동 통합하지 않음.
ENTITY_ALIASES: dict[str, str] = {
    # 어거스틴
    "Augustine": "어거스틴",
    "St. Augustine": "어거스틴",
    "Saint Augustine": "어거스틴",
    "St Augustine": "어거스틴",
    # 펠라기우스
    "Pelagius": "펠라기우스",
    # 루터
    "Luther": "루터",
    "Martin Luther": "루터",
    # 칼빈
    "Calvin": "칼빈",
    "John Calvin": "칼빈",
    # 아퀴나스
    "Aquinas": "아퀴나스",
    "Thomas Aquinas": "아퀴나스",
    # 츠빙글리
    "Zwingli": "츠빙글리",
    "Ulrich Zwingli": "츠빙글리",
    # 세르베투스 (반삼위일체로 칼빈에게 비판받음)
    "Servetus": "세르베투스",
    "Michael Servetus": "세르베투스",
    # 아리우스 (이단으로 분류, 삼위일체 논쟁)
    "Arius": "아리우스",
}


# ====================================================================
# 노이즈 패턴 — 시각화에서 제외
# ====================================================================
# Adapter Cypher에서 size(n.id) >= 2 로 1차 필터하지만, 정규화 후 한 번 더 검증.
_HASH_ID_PATTERN = re.compile(r"^[a-f0-9]{20,}$", re.IGNORECASE)
_DIGITS_OR_SYMBOL_ONLY = re.compile(r"^[\.\,\d\s\-\(\)]+$")


def normalize_entity_id(raw_id: str) -> str:
    """엔티티 id 정규화 — alias 사전에 있으면 통합, 없으면 strip만."""
    cleaned = raw_id.strip()
    return ENTITY_ALIASES.get(cleaned, cleaned)


def is_noise_entity(entity_id: str) -> bool:
    """노이즈 엔티티 식별 (1자, hash, 숫자만 등)."""
    if len(entity_id) < 2:
        return True
    if _HASH_ID_PATTERN.match(entity_id):
        return True
    if _DIGITS_OR_SYMBOL_ONLY.match(entity_id):
        return True
    return False


def normalize_subgraph(subgraph: SubgraphData) -> SubgraphData:
    """SubgraphData 후처리 — alias 통합 + 노이즈 제거 + 엣지 dedup + self-loop 제거.

    Args:
        subgraph: 원본 부분 그래프.

    Returns:
        정규화된 부분 그래프. 같은 정규화 id로 매핑되는 노드들은 하나로 합쳐지고,
        그들 사이의 엣지는 (source, target, label) 기준 dedup.
    """
    nodes_by_id: dict[str, GraphNode] = {}
    id_remap: dict[str, str] = {}

    for node in subgraph.nodes:
        if is_noise_entity(node.id):
            continue
        new_id = normalize_entity_id(node.id)
        id_remap[node.id] = new_id
        # 같은 정규화 id로 합쳐질 때, 첫 등장 노드의 type/properties 보존
        if new_id not in nodes_by_id:
            nodes_by_id[new_id] = GraphNode(
                id=new_id,
                label=new_id,
                type=node.type,
                properties=node.properties,
            )

    new_edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in subgraph.edges:
        new_src = id_remap.get(edge.source)
        new_tgt = id_remap.get(edge.target)
        if not new_src or not new_tgt:
            continue
        if new_src == new_tgt:  # self-loop 제거
            continue
        key = (new_src, new_tgt, edge.label)
        if key in seen:
            continue
        seen.add(key)
        new_edges.append(
            GraphEdge(
                source=new_src,
                target=new_tgt,
                label=edge.label,
                properties=edge.properties,
            )
        )

    return SubgraphData(nodes=list(nodes_by_id.values()), edges=new_edges)
