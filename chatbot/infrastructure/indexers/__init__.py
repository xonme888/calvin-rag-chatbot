"""인덱서 어댑터 — domain.GraphIndexer 구현.

각 indexer 는 *한 추출 알고리즘* 만 책임진다 (예: LLMGraphTransformer 기반 추출,
규칙 기반 추출 등). 새 indexer = 본 디렉토리에 1개 파일 + StrategyConfig 갱신.
"""

from chatbot.infrastructure.indexers.llm_graph_indexer import LLMGraphIndexer

__all__ = ["LLMGraphIndexer"]
