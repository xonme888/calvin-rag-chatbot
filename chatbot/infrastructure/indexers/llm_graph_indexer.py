"""LLMGraphTransformer 기반 GraphIndexer 어댑터.

본 phase 는 *얇은 위임* 으로 시작한다 — 기존 ``rag_core/kg/neo4j_adapter.Neo4jAdapter``
가 LLMGraphTransformer 호출과 그래프 적재를 *둘 다* 책임진다. 본 어댑터는:

1. ``estimate_cost`` — 기존 ``rag_core/kg/section_filter.estimate_cost`` 재사용 (LLM 호출 0).
2. ``index_into``    — store.index_chunks 위임 (실 LLM 호출은 store 내부에서).

향후 *변환 단계* 와 *적재 단계* 의 분리는 별도 PR — 본 phase 의 도메인 추상만 안정화.
다른 indexer (예: 규칙 기반 트리플 추출) 가 합류할 때 본 인터페이스가 그대로 쓰인다.
"""

from __future__ import annotations

from typing import Any

from chatbot.domain.graph import GraphStore
from chatbot.domain.indexing import Chunk


class LLMGraphIndexer:
    """LLMGraphTransformer 호출을 감싼 GraphIndexer.

    *변환 알고리즘 정의* (allowed_nodes/relationships) 는 store 어댑터(neo4j_adapter)
    내부에 보관되어 있다 — 본 indexer 는 비용 추정 + store 위임만.
    """

    name: str = "llm_graph_transformer"

    def estimate_cost(self, chunks: list[Chunk]) -> dict[str, float]:
        """기존 rag_core/kg/section_filter.estimate_cost 의 모델 가정 보존.

        gpt-4o-mini 기준: input 700 + output 200 토큰/청크. 처리 시간 2초/청크.
        ₩1,500/$1.
        """
        n = len(chunks)
        cost_per_chunk_usd = (700 * 0.15 / 1_000_000) + (200 * 0.60 / 1_000_000)
        total_usd = n * cost_per_chunk_usd
        return {
            "chunks": float(n),
            "usd": round(total_usd, 4),
            "krw": round(total_usd * 1500, 1),
            "minutes": round(n * 2 / 60, 1),
        }

    def index_into(
        self,
        chunks: list[Chunk],
        store: GraphStore,
        progress_callback: Any | None = None,
    ) -> int:
        """청크를 store 에 적재. LLM 호출은 store.index_chunks 가 내부적으로 발생.

        Returns:
            적재된 청크 수.
        """
        return store.index_chunks(chunks, progress_callback=progress_callback)
