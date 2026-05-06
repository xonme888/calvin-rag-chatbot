"""AnswerComposer 구체 — 두 경로:

1. retrieval 있음 (NEW/FOLLOWUP) — RetrievalResult.metadata['answer'] 그대로 또는 *얇게 가공*.
2. retrieval 없음 (META_*/SMALLTALK) — chat_history + last_turn 메타로 LLM 답변 합성.

설계 원칙:
- RetrievalResult.metadata['answer'] 가 있으면 그것을 *진실원천* 으로 신뢰. 본 composer 가
  답변을 *재합성* 하지 않는다 — strategy 가 이미 합성한 결과를 받아 Message 로만 변환.
- META 시나리오는 LLM 1회 호출 — 사용자가 "위 내용 요약" 등 요청 시 본 composer 가 직접 답변.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatbot.application._protocols import AnswerComposer
from chatbot.domain.conversation import Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


_META_RECAP_SYSTEM = (
    "사용자가 직전 대화 내용을 요약해달라고 요청했습니다. 이전 대화의 핵심을 한국어로 "
    "간결히 정리하세요. 새 정보를 만들지 말고, *이미 답한 내용* 만 다시 정리합니다.\n\n"
    "## 이전 대화:\n{history}"
)
_META_REFERENCE_SYSTEM = (
    "사용자가 직전 답변의 *특정 메타* (방금 그래프, 그 인용 페이지 등) 를 다시 요청했습니다. "
    "이전 답변에 포함되었던 메타를 그대로 다시 안내하세요. 새 검색은 하지 마세요.\n\n"
    "## 직전 답변:\n{last_answer}\n"
    "## 직전 메타 요약:\n{last_metadata}"
)
_SMALLTALK_SYSTEM = (
    "본 챗봇은 칼빈 신학에 한정된 답변만 가능합니다. 사용자의 인사·감사 메시지에 짧고 따뜻하게 응답한 후, "
    "칼빈 신학 관련 질문을 권유하세요. 한 문장 답변."
)


class HistoryAwareAnswerComposer:
    """retrieval 결과 우선 + META/SMALLTALK 만 LLM 호출."""

    name: str = "answer_composer"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._llm = llm

    def compose(
        self,
        *,
        intent: Intent,
        user_message: Message,
        history: tuple[Message, ...],
        last_turn: Turn | None,
        retrieval_result: RetrievalResult | None,
    ) -> Message:
        if retrieval_result is not None:
            return _from_retrieval(retrieval_result)
        if intent == Intent.META_RECAP:
            return self._compose_meta_recap(history)
        if intent == Intent.META_REFERENCE:
            return self._compose_meta_reference(last_turn)
        if intent == Intent.SMALLTALK:
            return self._compose_smalltalk(user_message)
        # 폴백 — 의도 분류기가 이상값을 보내도 안전 응답.
        return Message(role="assistant", content=_FALLBACK_TEXT)

    def _compose_meta_recap(self, history: tuple[Message, ...]) -> Message:
        text = _format_history_for_recap(history)
        return self._invoke_llm(
            _META_RECAP_SYSTEM, {"history": text}, fallback="이전 대화가 충분치 않습니다."
        )

    def _compose_meta_reference(self, last_turn: Turn | None) -> Message:
        if last_turn is None:
            return Message(role="assistant", content="이전 답변이 없어 다시 안내드릴 수 없습니다.")
        last_answer = last_turn.answer.content
        last_metadata = (
            f"전략: {last_turn.selected_strategy or '(없음)'}, 의도: {last_turn.intent.value}"
        )
        return self._invoke_llm(
            _META_REFERENCE_SYSTEM,
            {"last_answer": last_answer, "last_metadata": last_metadata},
            fallback=last_answer,
        )

    def _compose_smalltalk(self, user_message: Message) -> Message:
        return self._invoke_llm(
            _SMALLTALK_SYSTEM,
            {"question": user_message.content},
            fallback="칼빈 신학에 대한 질문을 도와드리겠습니다.",
        )

    def _invoke_llm(
        self,
        system_template: str,
        variables: dict[str, str],
        *,
        fallback: str,
    ) -> Message:
        from langchain_core.prompts import ChatPromptTemplate

        try:
            prompt = ChatPromptTemplate.from_messages(
                [("system", system_template), ("human", "{question}")]
            )
            payload = {**variables, "question": variables.get("question", "")}
            response = (prompt | self._llm).invoke(payload)
            text = (
                response.content
                if hasattr(response, "content") and isinstance(response.content, str)
                else str(response)
            )
            return Message(role="assistant", content=text or fallback)
        except Exception:  # noqa: BLE001
            return Message(role="assistant", content=fallback)


_FALLBACK_TEXT = "죄송합니다. 답변을 생성할 수 없습니다."


def _from_retrieval(result: RetrievalResult) -> Message:
    """RetrievalResult.metadata['answer'] 를 그대로 Message 로. 없으면 폴백."""
    answer = result.metadata.get("answer", "").strip()
    return Message(role="assistant", content=answer or _FALLBACK_TEXT)


def _format_history_for_recap(history: tuple[Message, ...]) -> str:
    """user/assistant 시퀀스 → '사용자: ... / 챗봇: ...' 텍스트. 최근 8개 메시지."""
    if not history:
        return "(이전 대화 없음)"
    lines: list[str] = []
    for m in history[-8:]:
        prefix = "사용자" if m.role == "user" else "챗봇"
        lines.append(f"{prefix}: {m.content}")
    return "\n".join(lines)


_: type[AnswerComposer] = HistoryAwareAnswerComposer  # type: ignore[type-abstract]
