"""LangGraph 오케스트레이터 — 노드 5개 와이어링 + 조건부 엣지.

흐름:
    START → classify_intent
                ├── needs_rewrite ──▶ rewrite_question ──┐
                ├── needs_retrieval ──────────────────────┼──▶ select_strategy ──▶ invoke_strategy ──▶ compose_answer ──▶ END
                └── META/SMALLTALK ──────────────────────────────────────────────────────────────────▶ compose_answer ──▶ END

본 모듈은 *그래프 빌더* 책임만. 노드 동작은 chatbot.application.nodes/, 의존성 구체 구현은
infrastructure/ 또는 application 외부에서 주입.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from chatbot.application._protocols import (
    AnswerComposer,
    IntentClassifier,
    QueryRewriter,
    StrategyRouter,
)
from chatbot.application.nodes import (
    classify_intent,
    compose_answer,
    invoke_strategy,
    rewrite_question,
    select_strategy,
)
from chatbot.domain.state import ConversationState
from chatbot.domain.strategy import StrategyRegistry

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def build_orchestrator(
    *,
    classifier: IntentClassifier,
    rewriter: QueryRewriter,
    strategies: StrategyRegistry,
    router: StrategyRouter,
    answerer: AnswerComposer,
) -> CompiledStateGraph:
    """노드 5개 + 조건부 엣지 와이어링 → CompiledStateGraph.

    in-memory 동작. checkpointer 는 PRD-002 합류 시 SQLite/Postgres 로 교체.
    """
    from langgraph.graph import END, START, StateGraph

    graph: StateGraph = StateGraph(ConversationState)

    graph.add_node("classify", partial(classify_intent, classifier=classifier))
    graph.add_node("rewrite", partial(rewrite_question, rewriter=rewriter))
    graph.add_node("select", partial(select_strategy, registry=strategies, router=router))
    graph.add_node("invoke", partial(invoke_strategy, registry=strategies))
    graph.add_node("compose", partial(compose_answer, answerer=answerer))

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"rewrite": "rewrite", "select": "select", "compose": "compose"},
    )
    graph.add_edge("rewrite", "select")
    graph.add_edge("select", "invoke")
    graph.add_edge("invoke", "compose")
    graph.add_edge("compose", END)
    return graph.compile()


def _route_after_classify(state: ConversationState) -> str:
    """Intent 별로 다음 노드 결정.

    - FOLLOWUP                 → rewrite (대명사 재구성 필요)
    - NEW_QUESTION             → select (재구성 불필요, 바로 strategy 선택)
    - META_RECAP / META_REFERENCE / SMALLTALK → compose (RAG 우회)
    """
    intent = state.pending_intent
    if intent is None:
        return "compose"  # 안전 폴백 — classify 실패 시 chitchat 대응
    if intent.needs_rewrite:
        return "rewrite"
    if intent.needs_retrieval:
        return "select"
    return "compose"
