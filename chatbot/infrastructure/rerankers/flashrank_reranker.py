"""FlashRank cross-encoder 재랭커 + Lost-in-the-Middle 재배치 — Stage 어댑터.

기존 ``rag_core/reranker.py`` 의 동작과 동일하되, 입출력이 LangChain Document 가
아니라 ``DocumentRef`` 시퀀스다. 두 단계를 독립 Stage 로 노출 — strategy 가
``[Reranker → Reorder]`` 순으로 합성한다 (단일 책임 분리).

FlashRank 미설치 환경에선 ``FlashRankRerankerStage.is_available()`` 이 False 를
반환 — strategy 가 본 단계를 건너뛰고 LongContextReorder 만 적용 가능.
"""

from __future__ import annotations

from typing import TypedDict

from chatbot.domain.corpus import DocumentRef


class RerankInput(TypedDict):
    """flashrank stage 입력. query 와 documents 를 동시에 전달.

    Stage Protocol 의 단일-인자 ``run(input)`` 제약과 query 의 필요성을 *그대로 envelope* 로
    풀어낸 형태 — clone/with_query 트릭 없이 모델 인스턴스를 1개로 유지한다.
    """

    query: str
    documents: list[DocumentRef]


class LongContextReorderStage:
    """Lost-in-the-Middle 회피 재배치 — 점수 높은 ref 를 양 끝에, 낮은 것을 가운데.

    LLM 은 긴 컨텍스트의 양 끝(앞/뒤) 정보를 가장 잘 인식한다 (Liu et al., 2023).
    ``rag_core/reranker.py:reorder_long_context`` 와 동일 알고리즘.
    """

    name: str = "long_context_reorder"

    def run(self, input: list[DocumentRef]) -> list[DocumentRef]:
        front: list[DocumentRef] = []
        back: list[DocumentRef] = []
        for i, ref in enumerate(input):
            if i % 2 == 0:
                front.append(ref)
            else:
                back.insert(0, ref)
        return front + back


class FlashRankRerankerStage:
    """FlashRank 모델로 cross-encoder 재점수화. 점수 내림차순 정렬 후 top_k 컷.

    Lazy initialization — 첫 ``run()`` 호출 시 모델 로드. 이후 동일 인스턴스 재사용.
    """

    name: str = "flashrank_reranker"

    def __init__(
        self,
        *,
        model_name: str = "ms-marco-MultiBERT-L-12",
        top_k: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._top_k = top_k
        self._ranker: object | None = None

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import flashrank  # noqa: F401
        except ImportError:
            return (False, "flashrank 미설치 — uv pip install -e '.[rerank]'")
        return (True, None)

    def _ensure_loaded(self) -> None:
        if self._ranker is not None:
            return
        try:
            from flashrank import Ranker
        except ImportError as e:
            raise ImportError(
                "flashrank 가 설치되지 않았습니다. uv pip install -e '.[rerank]' 로 설치하세요."
            ) from e
        self._ranker = Ranker(model_name=self._model_name)

    def run(self, input: RerankInput) -> list[DocumentRef]:
        documents = input["documents"]
        if not documents:
            return []
        self._ensure_loaded()
        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": ref.content, "meta": {"chunk_id": ref.chunk_id}}
            for i, ref in enumerate(documents)
        ]
        request = RerankRequest(query=input["query"], passages=passages)
        results = self._ranker.rerank(request)  # type: ignore[union-attr]

        sorted_results = sorted(results, key=lambda r: r["score"], reverse=True)
        out: list[DocumentRef] = [
            documents[r["id"]].model_copy(update={"score": float(r["score"])})
            for r in sorted_results
        ]
        if self._top_k is not None:
            out = out[: self._top_k]
        return out
