"""RetrievalStrategy 어댑터 — 구 '모드' 의 추상.

각 strategy 는 *조립 책임만* 가진다. 검색 알고리즘 자체는 Retriever, 도구 호출은 Tool,
재랭크는 rerankers/. 본 모듈의 strategy 가 이들을 합성해 RetrievalResult 를 만든다.

새 모드 = 본 디렉토리에 strategy 1개 추가 + StrategyRegistry 등록.
"""

from chatbot.infrastructure.strategies._config import (
    AgenticStrategyConfig,
    HybridStrategyConfig,
    KGStrategyConfig,
    VisionStrategyConfig,
)
from chatbot.infrastructure.strategies.agentic_strategy import AgenticStrategy
from chatbot.infrastructure.strategies.hybrid_strategy import HybridStrategy
from chatbot.infrastructure.strategies.kg_strategy import KGStrategy
from chatbot.infrastructure.strategies.vision_strategy import VisionStrategy

__all__ = [
    "HybridStrategy",
    "HybridStrategyConfig",
    "AgenticStrategy",
    "AgenticStrategyConfig",
    "KGStrategy",
    "KGStrategyConfig",
    "VisionStrategy",
    "VisionStrategyConfig",
]
