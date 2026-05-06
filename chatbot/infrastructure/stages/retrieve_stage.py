"""검색 단계 — domain.Retriever 를 Stage 로 래핑.

Stage Protocol 의 ``run(input) -> output`` 시그니처에 retriever 의 ``retrieve(request)``
를 그대로 매핑한다. 책임이 단 한 줄이라 별도 클래스를 둘 필요가 약간 모호하지만,
파이프라인의 *구성 단위* 가 모두 Stage 인 일관성이 디버깅·trace 시 가치가 있다.
"""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest, Retriever


class RetrieveStage:
    """RetrievalRequest → list[DocumentRef]. 내부 retriever 1개에 위임."""

    name: str = "retrieve"

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def run(self, input: RetrievalRequest) -> list[DocumentRef]:
        return self._retriever.retrieve(input)
