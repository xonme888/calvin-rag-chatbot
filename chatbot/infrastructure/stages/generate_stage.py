"""답변 합성 단계 — LLM 구조화 출력으로 answer + cited_pages + confidence 추출.

기존 ``rag_core/hybrid.py:_generate_node`` (line 232-287) 의 책임을 분해:
- 컨텍스트 조립 (DocumentRef → ``[page N] 본문`` 문자열) → ``parsers.format_doc_with_meta``.
- 프롬프트 호출 (system + chat_history + human) → ``prompts.build_hybrid_prompt`` 결과 사용.
- 구조화 출력 — ``RAGResponse`` (rag_core/hybrid.py:93-110) 를 그대로 재사용.

본 Stage 자체는 LLM 호출 + 구조화 출력 ↔ GenerateOutput 변환만. 인용 라벨 / 후속질문 /
메타 누적은 *strategy* 가 책임진다 (단일 책임 분리).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from chatbot.domain.conversation import Message
from chatbot.domain.corpus import DocumentRef
from chatbot.infrastructure.parsers import format_doc_with_meta

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.language_models import BaseChatModel
    from langchain_core.prompts import ChatPromptTemplate


class GenerateInput(TypedDict):
    """generate_stage 의 입력 envelope."""

    question: str
    documents: list[DocumentRef]
    chat_history: list[Message]


class GenerateOutput(TypedDict):
    """generate_stage 의 출력 envelope. strategy 가 RetrievalResult 합성에 사용."""

    answer: str
    cited_pages: list[int]
    confidence: float


class GenerateStage:
    """LLM 구조화 출력으로 answer + cited_pages + confidence 추출.

    LLM 과 prompt 는 생성자 주입 — 테스트 시 FakeListLLM 으로 대체 가능.
    """

    name: str = "generate"

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        callbacks: list[BaseCallbackHandler] | None = None,
    ) -> None:
        self._llm = llm
        self._prompt = prompt
        self._callbacks = callbacks

    def run(self, input: GenerateInput) -> GenerateOutput:
        from rag_core.hybrid import RAGResponse

        context = "\n\n---\n\n".join(format_doc_with_meta(d) for d in input["documents"])
        chat_history_lc = _to_langchain_messages(input["chat_history"])

        structured_llm = self._llm.with_structured_output(RAGResponse)
        chain = self._prompt | structured_llm
        kwargs = {"callbacks": self._callbacks} if self._callbacks else {}
        response: RAGResponse = chain.invoke(
            {"context": context, "question": input["question"], "chat_history": chat_history_lc},
            **kwargs,
        )
        return GenerateOutput(
            answer=response.answer,
            cited_pages=list(response.cited_pages),
            confidence=float(response.confidence),
        )


def _to_langchain_messages(history: list[Message]):  # type: ignore[no-untyped-def]
    """domain.Message → LangChain BaseMessage. 본 헬퍼는 본 단계 안에서만 사용."""
    from langchain_core.messages import AIMessage, HumanMessage

    out = []
    for m in history:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        else:
            out.append(AIMessage(content=m.content))
    return out
