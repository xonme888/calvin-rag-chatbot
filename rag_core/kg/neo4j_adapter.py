"""Neo4j 어댑터 — KnowledgeGraphPort 구현 (langchain-neo4j 기반).

이 어댑터는 로컬 Docker와 Neo4j Aura를 동일 코드로 처리한다 (URI scheme 차이만 있음).
환경별 분기는 ``Neo4jConfig`` 가 담당.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.documents import Document

from rag_core.kg.config import Neo4jConfig
from rag_core.kg.port import GraphEdge, GraphNode, SubgraphData


class Neo4jAdapter:
    """KnowledgeGraphPort 의 Neo4j 구현.

    로컬/Aura 모두 동일 어댑터로 처리. langchain-neo4j(``Neo4jGraph``)를 통해
    Cypher 실행 + APOC 절차로 트리플 삽입.
    """

    def __init__(self, config: Neo4jConfig) -> None:
        """어댑터를 초기화한다.

        Args:
            config: Neo4j 연결 설정. URI/username/password는 ``.env``에서.

        Raises:
            ImportError: langchain-neo4j 미설치 시. ``uv pip install -e '.[kg]'``.
        """
        try:
            from langchain_neo4j import Neo4jGraph
        except ImportError as e:
            raise ImportError(
                "langchain-neo4j가 설치되지 않았습니다. uv pip install -e '.[kg]' 로 설치하세요."
            ) from e

        self.config = config
        self._graph = Neo4jGraph(
            url=config.uri,
            username=config.username,
            password=config.password.get_secret_value(),
            refresh_schema=False,  # 인덱싱 전엔 스키마 가져오기 무의미
        )

    # ================================================================
    # KnowledgeGraphPort 구현
    # ================================================================
    def health_check(self) -> bool:
        """간단한 Cypher로 연결 확인."""
        try:
            result = self._graph.query("RETURN 1 AS ok")
            return bool(result and result[0].get("ok") == 1)
        except Exception:
            return False

    def index_chunks(
        self,
        chunks: list[Document],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """청크에서 트리플을 추출해 Neo4j에 영속한다.

        LLMGraphTransformer는 청크당 LLM 1회 호출 — 비용/시간이 큰 부분.
        본 인덱싱 전 50청크 샘플로 스키마 검증 권장.

        Args:
            chunks: 인덱싱 대상 청크.
            progress_callback: 진행률 콜백 ``(current, total) -> None``.

        Returns:
            인덱싱된 청크 수.
        """
        try:
            from langchain_core.messages import SystemMessage
            from langchain_experimental.graph_transformers import LLMGraphTransformer
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise ImportError(
                "langchain-experimental 또는 langchain-openai가 필요합니다."
            ) from e

        llm = ChatOpenAI(
            model=self.config.openai_model,
            temperature=0,
            api_key=self.config.openai_api_key,
        )

        transformer = LLMGraphTransformer(
            llm=llm,
            allowed_nodes=["Concept", "Person", "Doctrine", "Event"],
            allowed_relationships=[
                "DEFINES", "OPPOSES", "INFLUENCES", "CITES",
                "RELATED_TO", "PART_OF", "CONTRADICTS",
            ],
            node_properties=["description"],
            relationship_properties=False,
        )

        total = len(chunks)
        indexed = 0

        # 청크 → GraphDocument 변환 (LLM 호출 발생)
        # 큰 배치는 메모리 부담 — 10청크 단위로 처리하며 콜백
        batch_size = 10
        for i in range(0, total, batch_size):
            batch = chunks[i : i + batch_size]
            graph_documents = transformer.convert_to_graph_documents(batch)
            self._graph.add_graph_documents(
                graph_documents,
                baseEntityLabel=True,  # 모든 노드에 ``__Entity__`` 라벨 추가
                include_source=True,    # 원본 청크도 노드로 보존 (출처 추적)
            )
            indexed += len(batch)
            if progress_callback:
                progress_callback(indexed, total)

        return indexed

    def query_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Cypher 쿼리 실행."""
        return self._graph.query(cypher, params=params or {})

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> SubgraphData:
        """엔티티 주변 N홉 부분 그래프 (시각화용).

        Document 노드(원본 청크)와 MENTIONS 관계는 시각화에서 제외.
        2자 미만 id(대명사 등 노이즈)도 제외.
        평면 형식 (s/o id + 라벨)으로 명시 RETURN — langchain-neo4j 의 dict 변환과 호환.
        """
        if not entity_names:
            return SubgraphData()

        cypher = """
            MATCH (n:__Entity__)-[r]-(m:__Entity__)
            WHERE any(name IN $names WHERE toLower(n.id) CONTAINS toLower(name))
              AND NOT n:Document AND NOT m:Document
              AND size(n.id) >= 2 AND size(m.id) >= 2
              AND type(r) <> 'MENTIONS'
            RETURN
                n.id AS s, labels(n) AS s_labels, coalesce(n.description, '') AS s_desc,
                m.id AS o, labels(m) AS o_labels, coalesce(m.description, '') AS o_desc,
                type(r) AS rel
            LIMIT 60
        """
        try:
            rows = self._graph.query(cypher, params={"names": entity_names})
        except Exception:
            return self._fallback_subgraph(entity_names, hops)

        if not rows:
            return SubgraphData()

        nodes_by_id: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        for row in rows:
            s_id = row["s"]
            o_id = row["o"]
            if s_id not in nodes_by_id:
                nodes_by_id[s_id] = GraphNode(
                    id=s_id, label=s_id,
                    type=Neo4jAdapter._pick_type(row.get("s_labels", [])),
                    properties={"description": row.get("s_desc", "")},
                )
            if o_id not in nodes_by_id:
                nodes_by_id[o_id] = GraphNode(
                    id=o_id, label=o_id,
                    type=Neo4jAdapter._pick_type(row.get("o_labels", [])),
                    properties={"description": row.get("o_desc", "")},
                )
            edges.append(GraphEdge(source=s_id, target=o_id, label=row["rel"]))

        # 정규화 후처리 — alias 통합(어거스틴/Augustine), 노이즈 제거, dedup
        from rag_core.kg.entity_normalizer import normalize_subgraph

        raw = SubgraphData(nodes=list(nodes_by_id.values()), edges=edges)
        normalized = normalize_subgraph(raw)

        # 시각화 부담 줄이려 노드 30개, 엣지 50개로 캡
        nodes = normalized.nodes[:30]
        valid_ids = {n.id for n in nodes}
        edges_capped = [
            e for e in normalized.edges if e.source in valid_ids and e.target in valid_ids
        ][:50]
        return SubgraphData(nodes=nodes, edges=edges_capped)

    def clear(self) -> None:
        """전체 노드/엣지 삭제 (재인덱싱 시)."""
        self._graph.query("MATCH (n) DETACH DELETE n")

    def stats(self) -> dict[str, int]:
        """노드/엣지 수 반환."""
        result = self._graph.query(
            "MATCH (n) WITH count(n) AS nodes "
            "MATCH ()-[r]->() RETURN nodes, count(r) AS edges"
        )
        if not result:
            return {"nodes": 0, "edges": 0}
        return {"nodes": result[0].get("nodes", 0), "edges": result[0].get("edges", 0)}

    # ================================================================
    # 내부 헬퍼
    # ================================================================
    def _fallback_subgraph(self, entity_names: list[str], hops: int) -> SubgraphData:
        """APOC 없이 N홉 부분 그래프 추출 (성능 ↓)."""
        cypher = f"""
            MATCH path = (n:__Entity__)-[*1..{hops}]-(m:__Entity__)
            WHERE any(name IN $names WHERE toLower(n.id) CONTAINS toLower(name))
            WITH collect(path) AS paths
            UNWIND paths AS p
            UNWIND nodes(p) AS node
            WITH collect(DISTINCT node) AS nodes, paths
            UNWIND paths AS p2
            UNWIND relationships(p2) AS rel
            RETURN nodes, collect(DISTINCT rel) AS relationships
        """
        try:
            result = self._graph.query(cypher, params={"names": entity_names})
        except Exception:
            return SubgraphData()
        if not result:
            return SubgraphData()
        row = result[0]
        nodes = [self._to_graph_node(n) for n in row.get("nodes", [])]
        edges = [self._to_graph_edge(r) for r in row.get("relationships", [])]
        return SubgraphData(nodes=nodes, edges=edges)

    @staticmethod
    def _pick_type(labels: list[str]) -> str:  # noqa: ARG004 (호환용)
        """노드 라벨 중 ``__Entity__`` 외 첫 라벨을 타입으로."""
        for lbl in labels:
            if lbl != "__Entity__":
                return lbl
        return "Entity"

    @staticmethod
    def _to_graph_node(node_dict: Any) -> GraphNode:
        """Neo4j 노드 dict → GraphNode."""
        if hasattr(node_dict, "__dict__"):
            data = dict(node_dict)
        else:
            data = node_dict if isinstance(node_dict, dict) else {}
        node_id = str(data.get("id") or data.get("name") or "")
        label = str(data.get("name") or data.get("id") or node_id)
        node_type = next(
            (lbl for lbl in (data.get("labels") or []) if lbl != "__Entity__"),
            "Entity",
        )
        return GraphNode(id=node_id, label=label, type=node_type, properties=data)

    @staticmethod
    def _to_graph_edge(rel_dict: Any) -> GraphEdge:
        """Neo4j relationship dict → GraphEdge."""
        if hasattr(rel_dict, "__dict__"):
            data = dict(rel_dict)
        else:
            data = rel_dict if isinstance(rel_dict, dict) else {}
        return GraphEdge(
            source=str(data.get("start_node_id") or data.get("source") or ""),
            target=str(data.get("end_node_id") or data.get("target") or ""),
            label=str(data.get("type") or data.get("label") or "RELATED_TO"),
            properties=data,
        )
