"""IntentClassifier 구체 — 휴리스틱 우선 + LLM fallback.

흐름:
1. 메타 트리거 키워드 (요약/정리/위/방금/그러면 등) 매칭 → META_RECAP / META_REFERENCE 즉시 결정.
2. 인사말·고마움 패턴 → SMALLTALK.
3. 대명사·생략 후속 (그/저/이/그러면/그것은 등) → FOLLOWUP.
4. 그 외 + 직전 턴 없음 → NEW_QUESTION.
5. 모호한 경우(env flag 활성 시) cheap LLM 분류기 fallback.

PRD-006 §5 결정 1 의 휴리스틱 → LLM fallback 절충안.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from chatbot.application._protocols import IntentClassifier
from chatbot.domain.conversation import Message, Turn
from chatbot.domain.intent import Intent

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


# ============================================================
# 키워드 사전 — 본 모듈에서만 사용. ImmutableMapping 으로 두지 않음 (Python frozenset).
# ============================================================
_META_RECAP_HINTS: frozenset[str] = frozenset(
    {
        # 직접 명령
        "요약",
        "정리",
        "추려",
        # 위치 지시
        "위 내용",
        "위에서",
        "이전 내용",
        # 시간 지시
        "지금까지",
        "방금까지",
        "여태",
        # 대화 자체를 가리키는 표현 — 사용자가 "우리 무슨 대화를 한 것 같아" 류 질문 시
        "무슨 대화",
        "어떤 대화",
        "무엇을 물어",
        "무엇을 말",
        "무슨 이야기",
        "어떤 이야기",
        "물어봤",
        "물어본",
        "내가 뭐",
        "우리 뭐",
        # 자기 회고
        "내가 한 질문",
        "내 질문",
    }
)
_META_REFERENCE_HINTS: frozenset[str] = frozenset(
    {
        "방금 그",
        "방금 본",
        "그 그래프",
        "그 인용",
        "그 페이지",
        "그 답변",
        "아까 그",
        "조금 전에 본",
        "이전 답변",
    }
)
_FOLLOWUP_HINTS: frozenset[str] = frozenset(
    {"그러면", "그러므로", "그래서", "그 사람", "그것은", "그게 뭐", "그리고"}
)
_SMALLTALK_HINTS: frozenset[str] = frozenset(
    {"안녕", "고마워", "감사합니다", "잘 부탁", "수고", "반가워"}
)


class HeuristicIntentClassifier:
    """휴리스틱 only. LLM 호출 0 — 가장 빠른 분류기. 테스트·시연 디폴트."""

    def classify(self, *, message: Message, last_turn: Turn | None) -> Intent:
        text = message.content.strip()
        if _matches_any(text, _META_REFERENCE_HINTS):
            return Intent.META_REFERENCE
        if _matches_any(text, _META_RECAP_HINTS):
            return Intent.META_RECAP
        if _matches_any(text, _SMALLTALK_HINTS):
            return Intent.SMALLTALK
        if last_turn is not None and _matches_any(text, _FOLLOWUP_HINTS):
            return Intent.FOLLOWUP
        return Intent.NEW_QUESTION


class HeuristicWithLLMFallbackClassifier:
    """휴리스틱 → 모호 시 LLM 분류기 fallback.

    *모호*: 본 분류기는 *항상 휴리스틱 결과를 사용*. LLM fallback 은 *히트 키워드 0개* +
    NEW_QUESTION 디폴트 + ``CHATBOT_INTENT_LLM=true`` 환경변수 일 때만.
    """

    name: str = "intent_llm"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._heuristic = HeuristicIntentClassifier()
        self._llm = llm

    def classify(self, *, message: Message, last_turn: Turn | None) -> Intent:
        heuristic = self._heuristic.classify(message=message, last_turn=last_turn)
        if not _llm_fallback_enabled() or heuristic != Intent.NEW_QUESTION:
            return heuristic
        # 모호 NEW_QUESTION 만 LLM 으로 정확도 보강. 실패 시 휴리스틱 결과 유지.
        llm_decision = _classify_with_llm(self._llm, message)
        return llm_decision or heuristic


def _matches_any(text: str, hints: frozenset[str]) -> bool:
    return any(h in text for h in hints)


def _llm_fallback_enabled() -> bool:
    return os.getenv("CHATBOT_INTENT_LLM", "").strip().lower() in ("1", "true", "yes")


def _classify_with_llm(llm: BaseChatModel, message: Message) -> Intent | None:
    """LLM 분류 — 실패 시 None. Pydantic 구조화 출력으로 정확한 enum 반환 보장."""
    from langchain_core.prompts import ChatPromptTemplate
    from pydantic import BaseModel, Field

    class _Decision(BaseModel):
        intent: str = Field(
            description="다음 중 하나: new_question, followup, meta_recap, meta_reference, smalltalk"
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "사용자 메시지의 의도를 다음 중 하나로 분류하세요: "
                "new_question (새 본문 질의), followup (대명사·생략 후속), "
                "meta_recap (요약·정리), meta_reference (방금 그래프/인용 재참조), smalltalk (인사·감사).",
            ),
            ("human", "{question}"),
        ]
    )
    try:
        result = (prompt | llm.with_structured_output(_Decision)).invoke(
            {"question": message.content}
        )
        return Intent(result.intent) if result and result.intent else None
    except Exception:  # noqa: BLE001
        return None


# Protocol 만족 검증 — 정적 타입 체커가 알아챌 수 있도록.
_: type[IntentClassifier] = HeuristicIntentClassifier  # type: ignore[type-abstract]
