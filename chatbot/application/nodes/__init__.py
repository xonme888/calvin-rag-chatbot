"""LangGraph 노드 함수 모음 — 모두 ``state -> state`` 시그니처.

각 노드는 *하나의 책임* 만 가진다. 다른 노드를 호출하지 않는다 (LangGraph 가 와이어링).
부수효과는 trace event 외 없음. 의존성은 ``functools.partial`` 또는 클로저로 주입.
"""

from chatbot.application.nodes.classify_intent import classify_intent
from chatbot.application.nodes.compose_answer import compose_answer
from chatbot.application.nodes.invoke_strategy import invoke_strategy
from chatbot.application.nodes.rewrite_question import rewrite_question
from chatbot.application.nodes.select_strategy import select_strategy

__all__ = [
    "classify_intent",
    "rewrite_question",
    "select_strategy",
    "invoke_strategy",
    "compose_answer",
]
