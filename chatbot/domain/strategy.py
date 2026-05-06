"""검색 전략(RetrievalStrategy) — 구 '모드' 의 추상.

기존 hybrid/agentic/kg/vision 은 *Retriever 와 Tool 을 조합한 레시피*다. 그 자체로
새로운 검색 알고리즘이 아니다. Strategy 는:

- ``supports(request)`` : 이 전략이 요청을 처리할 만한지 (예: KG 는 그래프 의도일 때만 True)
- ``run(request)``      : Retriever/Tool 을 호출해 RetrievalResult 를 만든다

이 분리 덕에:
- 새 모드 = Strategy 1개 추가 (기존 Retriever/Tool 재사용)
- 새 검색기 = Retriever 1개 추가 (Strategy 들이 자동 활용 가능)
- 새 도구 = Tool 1개 추가 (Agentic Strategy 가 자동 인지)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult


@runtime_checkable
class RetrievalStrategy(Protocol):
    """검색 전략 1개. 1개 또는 여러 Retriever/Tool 을 조립해 RetrievalResult 생성.

    구현체는 *조립 책임만* 가진다 — 검색 알고리즘 자체는 Retriever 에, 도구 호출은
    Tool 에 위임. Strategy 가 200줄을 넘으면 책임이 새고 있다는 신호.
    """

    name: str
    label: str
    """UI 노출용 라벨 (예: 'Hybrid', 'Knowledge Graph')."""

    def is_available(self) -> tuple[bool, str | None]:
        """전략 자체의 가용성. 의존하는 Retriever/Tool 이 모두 가용해야 True."""
        ...

    def supports(self, request: RetrievalRequest) -> bool:
        """이 전략이 요청을 처리할 만한지의 사전판단.

        라우터가 후보 전략들 중 supports=True 인 것 중에서 선택한다. 모든 전략이
        False 를 반환하면 디폴트(보통 hybrid) 로 폴백.
        """
        ...

    def run(self, request: RetrievalRequest) -> RetrievalResult: ...


@runtime_checkable
class StrategyRegistry(Protocol):
    """전략 카탈로그. 라우터·UI 가 사용."""

    def register(self, strategy: RetrievalStrategy) -> None: ...

    def all(self) -> list[RetrievalStrategy]: ...

    def get(self, name: str) -> RetrievalStrategy:
        """없으면 KeyError."""
        ...

    def available_for(self, request: RetrievalRequest) -> list[RetrievalStrategy]:
        """is_available + supports 를 모두 만족하는 후보들."""
        ...
