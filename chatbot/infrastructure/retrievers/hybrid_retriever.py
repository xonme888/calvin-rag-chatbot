"""BM25 + Dense → RRF 합성 어댑터.

도메인 Retriever 두 개를 받아 *합성만* 한다. 각 retriever 의 알고리즘은 그것들의
관심사 — 본 어댑터는 *Reciprocal Rank Fusion* 만 책임진다.

기존 ``rag_core/retriever.py:HybridRetriever.reciprocal_rank_fusion`` (line 141-171)
의 수식·동작과 동일. ``hash(content)`` 기반 dedup 도 동일하게 보존.
"""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest, Retriever


class HybridRetriever:
    """두 retriever 결과를 RRF 로 결합."""

    name: str = "hybrid"

    def __init__(
        self,
        bm25: Retriever,
        dense: Retriever,
        *,
        dense_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> None:
        if not 0.0 <= dense_weight <= 1.0:
            raise ValueError(f"dense_weight 는 0.0~1.0 범위여야 합니다: {dense_weight}")
        self._bm25 = bm25
        self._dense = dense
        self._dense_weight = dense_weight
        self._rrf_k = rrf_k

    @property
    def dense_weight(self) -> float:
        return self._dense_weight

    @dense_weight.setter
    def dense_weight(self, value: float) -> None:
        """런타임 가중치 조정 — 시연·실험에서 dense_weight 변경 슬라이더용.

        기존 ``HybridRAG.config.dense_weight`` 가 같은 책임을 가졌다. 본 setter 는
        새 retriever 인스턴스 생성 비용을 피하기 위해 mutable.
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"dense_weight 는 0.0~1.0 범위여야 합니다: {value}")
        self._dense_weight = value

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        _, _, fused = self.retrieve_split(request)
        return fused[: request.top_k]

    def retrieve_split(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[DocumentRef], list[DocumentRef], list[DocumentRef]]:
        """검색 결과를 (bm25, dense, fused) 3종으로 반환.

        v1의 ``retrieve_split``와 동일한 디버그 메타(bm25_count, dense_count, rrf_top_scores)
        복원을 위해 strategy 계층에서 사용한다.
        """
        bm25_results = self._bm25.retrieve(request)
        dense_results = self._dense.retrieve(request)
        fused = self._reciprocal_rank_fusion(bm25_results, dense_results)
        return bm25_results, dense_results, fused

    def _reciprocal_rank_fusion(
        self,
        bm25: list[DocumentRef],
        dense: list[DocumentRef],
    ) -> list[DocumentRef]:
        """RRF: score(d) = Σ weight_i / (k + rank_i(d)).

        점수 스케일 정규화 불필요 — 순위만 사용. 같은 본문 dedup 은 chunk_id 기준.
        """
        bm25_weight = 1.0 - self._dense_weight
        dense_weight = self._dense_weight
        rrf_k = self._rrf_k

        scores: dict[str, float] = {}
        ref_map: dict[str, DocumentRef] = {}

        for rank, ref in enumerate(bm25, start=1):
            scores[ref.chunk_id] = scores.get(ref.chunk_id, 0.0) + bm25_weight / (rrf_k + rank)
            ref_map[ref.chunk_id] = ref

        for rank, ref in enumerate(dense, start=1):
            scores[ref.chunk_id] = scores.get(ref.chunk_id, 0.0) + dense_weight / (rrf_k + rank)
            # bm25 가 같은 chunk 를 먼저 봤으면 그쪽이 score 가 더 정확 — 단, content/metadata 는 동일.
            ref_map.setdefault(ref.chunk_id, ref)

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [ref_map[cid].model_copy(update={"score": scores[cid]}) for cid in sorted_ids]
