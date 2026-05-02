"""검색 후처리.

- ``reorder_long_context``: Lost-in-the-Middle 회피용 재배치
- ``FlashRankReranker``: cross-encoder 기반 로컬 재랭커
- ``rerank_and_reorder``: 두 가지를 한 번에 적용

flashrank는 무거운 의존성이라 lazy import 한다. 미설치 환경에서도
모듈 import 자체는 성공하며, 실제 ``rerank()`` 호출 시점에만
명확한 ImportError 메시지를 발생시킨다.
"""

from __future__ import annotations

from langchain_core.documents import Document


def reorder_long_context(docs: list[Document]) -> list[Document]:
    """Lost-in-the-Middle 현상 회피를 위해 중요 문서를 양 끝에 배치한다.

    LLM은 긴 컨텍스트의 양 끝(앞/뒤)에 위치한 정보를 가장 잘 인식하고
    중간에 있는 정보는 놓치는 경향이 있다(Liu et al., 2023). 따라서
    점수 높은 문서를 앞/뒤로, 낮은 문서를 가운데로 배치한다.

    Args:
        docs: 점수 내림차순으로 정렬된 Document 리스트.

    Returns:
        재배치된 Document 리스트. 길이는 입력과 동일.
    """
    result_front: list[Document] = []
    result_back: list[Document] = []
    for i, doc in enumerate(docs):
        if i % 2 == 0:
            result_front.append(doc)
        else:
            result_back.insert(0, doc)
    return result_front + result_back


class FlashRankReranker:
    """FlashRank 기반 cross-encoder 재랭커.

    BM25 + Dense 검색 결과(또는 RRF 결과)를 받아 cross-encoder 모델로
    재점수화한다. 로컬 동작이라 API 비용이 없고, ms-marco 계열 경량 모델이라
    추론도 빠른 편.

    Lazy initialization: 첫 ``rerank()`` 호출 시점에 모델을 로드한다.
    """

    def __init__(self, model_name: str = "ms-marco-MultiBERT-L-12") -> None:
        """재랭커를 초기화한다 (모델 로드는 첫 호출까지 지연).

        Args:
            model_name: FlashRank 모델 이름. 기본은 다국어 지원 모델.
        """
        self.model_name = model_name
        self._ranker: object | None = None

    def _ensure_loaded(self) -> None:
        if self._ranker is not None:
            return
        try:
            from flashrank import Ranker
        except ImportError as e:
            raise ImportError(
                "flashrank가 설치되지 않았습니다. uv pip install -e '.[rerank]' 로 설치하세요."
            ) from e
        self._ranker = Ranker(model_name=self.model_name)

    def rerank(
        self,
        query: str,
        docs: list[Document],
        top_k: int | None = None,
    ) -> list[tuple[Document, float]]:
        """질의에 대해 문서를 cross-encoder로 재점수화한다.

        Args:
            query: 사용자 질의.
            docs: 재랭킹 대상 Document 리스트. 빈 리스트면 즉시 빈 결과 반환.
            top_k: 상위 N개만 반환. None이면 전체.

        Returns:
            (Document, rerank_score) 튜플 리스트. 점수 내림차순 정렬.
        """
        if not docs:
            return []

        self._ensure_loaded()

        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": doc.page_content, "meta": doc.metadata} for i, doc in enumerate(docs)
        ]
        request = RerankRequest(query=query, passages=passages)
        results = self._ranker.rerank(request)  # type: ignore[union-attr]

        by_id = {i: doc for i, doc in enumerate(docs)}
        sorted_results = sorted(results, key=lambda r: r["score"], reverse=True)

        out: list[tuple[Document, float]] = [
            (by_id[r["id"]], float(r["score"])) for r in sorted_results
        ]
        if top_k is not None:
            out = out[:top_k]
        return out


def rerank_and_reorder(
    query: str,
    docs: list[Document],
    reranker: FlashRankReranker | None = None,
    top_k: int = 5,
) -> list[Document]:
    """rerank → top_k 추출 → long-context reorder 를 한 번에 적용한다.

    Args:
        query: 사용자 질의.
        docs: 입력 Document 리스트 (보통 RRF/하이브리드 검색 결과).
        reranker: 재사용할 ``FlashRankReranker``. None 이면 새로 생성하며,
            반복 호출 시 모델 로드 비용을 줄이려면 외부에서 한 번 생성해 전달.
        top_k: 최종 반환 개수.

    Returns:
        재랭크 + 재배치된 Document 리스트 (길이 ≤ ``top_k``).
    """
    if not docs:
        return []

    ranker = reranker if reranker is not None else FlashRankReranker()
    reranked = ranker.rerank(query, docs, top_k=top_k)
    top_docs = [doc for doc, _score in reranked]
    return reorder_long_context(top_docs)
