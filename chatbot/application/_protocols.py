"""Application 노드의 외부 의존성 Protocol — 테스트 시 Fake 주입.

각 노드는 *state + 의존성 → state* 의 순수 함수에 가깝다. 외부 의존(LLM 분류기,
LLM 재작성기, 라우터 결정 함수, 답변 합성기) 은 본 Protocol 들로 추상화되어 있다.

infrastructure 레이어가 *구체 구현* 을 제공한다:
- LLM 기반 IntentClassifier  → infrastructure/intent_llm.py (PR 3.4 이후)
- LLM 기반 QueryRewriter      → infrastructure/rewriter_llm.py
- StrategyRouter              → 휴리스틱(우선) 또는 LLM 기반 (라우터 정확도 ↑)
- AnswerComposer              → strategy 결과 또는 history 만으로 답변 합성

본 phase 는 Protocol 만 정의 — 실 구현은 PR 3.4 이후 합류.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chatbot.domain.conversation import Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult
from chatbot.domain.strategy import RetrievalStrategy


@runtime_checkable
class IntentClassifier(Protocol):
    """사용자 메시지 + 직전 턴 메타 → Intent.

    전형적 구현:
    - 휴리스틱 우선 (메타 트리거: "요약/정리/위/방금/그러면" 등) — 빠름·LLM 호출 0
    - 모호 시 LLM 분류기 fallback (gpt-4o-mini, ~₩0.5/호출)

    PRD-006 §5 결정 1 의 절충안 (휴리스틱 → LLM fallback).
    """

    def classify(
        self,
        message: Message,
        last_turn: Turn | None,
    ) -> Intent: ...


@runtime_checkable
class QueryRewriter(Protocol):
    """후속 질문 (대명사·생략) → standalone question.

    Intent.FOLLOWUP 일 때만 호출. 다른 Intent 는 본 Protocol 에 도달하지 않는다.
    구현은 LLM 1회 호출 — chat_history 와 함께 LLM 에게 *자기-완결 질문* 재구성을 요청.
    """

    def rewrite(
        self,
        message: Message,
        history: tuple[Message, ...],
    ) -> str: ...


@runtime_checkable
class StrategyRouter(Protocol):
    """후보 strategy 들 중 1개 선택. supports() 통과 후의 *2차 결정*.

    구현은 휴리스틱 (키워드 매칭) 또는 cheap LLM 분류 — registry.available_for() 가
    이미 1개로 좁혀준다면 단순 첫 번째 선택. 여러 후보면 라우터가 결정.
    """

    def choose(
        self,
        candidates: list[RetrievalStrategy],
        standalone_question: str,
        last_turn: Turn | None,
    ) -> RetrievalStrategy | None: ...


@runtime_checkable
class AnswerComposer(Protocol):
    """최종 Message 합성. 두 경로:

    1. retrieval 있음 (NEW/FOLLOWUP) — RetrievalResult.metadata.answer 를 그대로 또는 가공.
    2. retrieval 없음 (META/SMALLTALK) — chat_history + last_turn 메타로 LLM 답변 합성.

    본 Protocol 자체는 두 경로를 *내부에서* 구분 — 노드는 단일 호출만.
    """

    def compose(
        self,
        *,
        intent: Intent,
        user_message: Message,
        history: tuple[Message, ...],
        last_turn: Turn | None,
        retrieval_result: RetrievalResult | None,
    ) -> Message: ...
