"""select_strategy 노드 — supports() 통과 후보들 중 1개 선택.

Intent.needs_retrieval=False 인 경우는 LangGraph 의 조건 엣지가 본 노드를 *건너뛴다*.
본 노드는 needs_retrieval=True 일 때만 호출됨을 가정 — 입력 가드 없음.
"""

from __future__ import annotations

from chatbot.application._protocols import StrategyRouter
from chatbot.application.nodes._helpers import to_retrieval_request
from chatbot.domain.retrieval import RetrievalResult
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
    request = to_retrieval_request(state)
    candidates = registry.available_for(request)
    if not candidates:
        return _with_no_strategy(
            state,
            reason="처리 가능한 전략이 없습니다. 모드 설정 또는 첨부 형식을 확인해주세요.",
            mode_override=state.requested_mode if state.requested_mode != "auto" else None,
        )

    if state.requested_mode != "auto":
        by_name = {s.name: s for s in candidates}
        forced = by_name.get(state.requested_mode)
        if forced is None:
            return _with_no_strategy(
                state,
                reason=(
                    f"요청한 모드 '{state.requested_mode}' 를 현재 사용할 수 없습니다. "
                    "다른 모드로 재시도해주세요."
                ),
                mode_override=state.requested_mode,
            )
        return state.model_copy(update={"pending_strategy": forced.name})

    selected = router.choose(
        candidates=candidates,
        standalone_question=state.pending_standalone or state.pending_user_message.content,
        last_turn=state.conversation.last_turn,
        previous_mode=state.previous_mode,
    )
    if selected is None:
        return _with_no_strategy(
            state,
            reason="적절한 전략을 선택하지 못했습니다. 질문을 구체화해 다시 시도해주세요.",
            mode_override=None,
        )
    return state.model_copy(update={"pending_strategy": selected.name})


def _with_no_strategy(
    state: ConversationState,
    *,
    reason: str,
    mode_override: str | None,
) -> ConversationState:
    """전략 미선택 시 안내용 RetrievalResult 를 주입해 fallback 응답을 사용자 친화적으로 만든다."""
    retrieval = RetrievalResult(
        documents=(),
        citations=(),
        metadata={
            "answer": reason,
            "error_code": "NO_STRATEGY_AVAILABLE",
            "strategy_reason": reason,
            "mode_override": mode_override or "",
        },
    )
    return state.model_copy(update={"pending_strategy": None, "pending_retrieval": retrieval})
