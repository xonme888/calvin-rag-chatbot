"""select_strategy 노드 — supports() 통과 후보들 중 1개 선택.

Intent.needs_retrieval=False 인 경우는 LangGraph 의 조건 엣지가 본 노드를 *건너뛴다*.
본 노드는 needs_retrieval=True 일 때만 호출됨을 가정 — 입력 가드 없음.
"""

from __future__ import annotations

from chatbot.application._protocols import StrategyRouter
from chatbot.application.nodes._helpers import to_retrieval_request
from chatbot.domain.state import ConversationState
from chatbot.domain.strategy import StrategyRegistry


def select_strategy(
    state: ConversationState,
    *,
    registry: StrategyRegistry,
    router: StrategyRouter,
) -> ConversationState:
    """state.pending_strategy 에 선택된 strategy.name 을 채운다.

    후보가 0개면 None — 다음 노드(invoke_strategy) 가 패스스루.
    """
    candidates = registry.available_for(to_retrieval_request(state))
    if not candidates:
        return state.model_copy(update={"pending_strategy": None})
    selected = router.choose(
        candidates=candidates,
        standalone_question=state.pending_standalone or state.pending_user_message.content,
        last_turn=state.conversation.last_turn,
    )
    return state.model_copy(update={"pending_strategy": selected.name if selected else None})
