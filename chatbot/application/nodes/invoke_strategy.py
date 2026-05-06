"""invoke_strategy 노드 — 선택된 strategy.run() 호출.

pending_strategy 가 None 이면 패스스루 — compose_answer 가 retrieval_result=None 으로 답변.
"""

from __future__ import annotations

from chatbot.application.nodes._helpers import to_retrieval_request
from chatbot.domain.state import ConversationState
from chatbot.domain.strategy import StrategyRegistry


def invoke_strategy(
    state: ConversationState,
    *,
    registry: StrategyRegistry,
) -> ConversationState:
    """state.pending_retrieval 을 RetrievalResult 로 채운다."""
    if state.pending_strategy is None:
        return state
    strategy = registry.get(state.pending_strategy)
    result = strategy.run(to_retrieval_request(state))
    return state.model_copy(update={"pending_retrieval": result})
