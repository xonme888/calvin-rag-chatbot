"""QueryRewriter 구체 — chat_history + 후속 질문 → standalone question.

LLM 1회 호출. 구조화 출력으로 *재구성된 질문 1줄* 만 추출 — 결과 텍스트가 LangChain
응답 메타와 섞이지 않도록.

Intent.FOLLOWUP 일 때만 호출됨을 가정 (rewrite_question 노드의 분기).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatbot.application._protocols import QueryRewriter
from chatbot.domain.conversation import Message

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


_REWRITER_SYSTEM = (
    "이전 대화 맥락을 고려해 사용자의 후속 질문을 *자기-완결 질문* 으로 재구성하세요. "
    "대명사(그/저/이) 와 생략을 채워, 단독으로 검색 가능한 한국어 한 문장으로 만드세요.\n\n"
    "규칙:\n"
    "- 원래 질문의 *의도* 를 보존. 새 정보를 추가하지 마세요.\n"
    "- 한 문장만 출력 (질문 부호 ?로 끝).\n"
    "- 이전 대화에서 언급된 핵심 명사를 활용해 대명사를 치환.\n"
)


class LLMQueryRewriter:
    """LLM 1회 호출로 standalone 질문 재구성."""

    name: str = "rewriter_llm"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._llm = llm

    def rewrite(self, *, message: Message, history: tuple[Message, ...]) -> str:
        """history 를 system 컨텍스트로, 메시지를 human 으로 — 구조화 출력으로 새 질문 추출."""
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, Field

        class _Rewritten(BaseModel):
            standalone_question: str = Field(description="자기-완결 한국어 질문 한 문장")

        history_text = _format_history(history)
        try:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", _REWRITER_SYSTEM + "\n\n## 이전 대화:\n{history}"),
                    ("human", "{question}"),
                ]
            )
            chain = prompt | self._llm.with_structured_output(_Rewritten)
            result = chain.invoke({"history": history_text, "question": message.content})
            text = (result.standalone_question or "").strip()
            return text or message.content
        except Exception:  # noqa: BLE001
            # 구조화 출력 실패 또는 LLM 호환 오류 시 원문 그대로 — 라우팅 정확도만 저하.
            return message.content


def _format_history(history: tuple[Message, ...]) -> str:
    """user/assistant 시퀀스 → '사용자: ... / 챗봇: ...' 텍스트.

    너무 길면 *최근 6개 메시지* (3턴) 만 — rewrite 컨텍스트 토큰 비용 절감.
    """
    lines: list[str] = []
    for m in history[-6:]:
        prefix = "사용자" if m.role == "user" else "챗봇"
        lines.append(f"{prefix}: {m.content}")
    return "\n".join(lines) if lines else "(이전 대화 없음)"


_: type[QueryRewriter] = LLMQueryRewriter  # type: ignore[type-abstract]
