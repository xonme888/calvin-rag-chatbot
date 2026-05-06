"""엔티티 추출 단계 — 질문 → 핵심 엔티티 + 의도.

기존 ``rag_core/kg/pipeline.py:extract_entities`` (line 153-156) 의 동작과 동일.
구조화 스키마 ``EntityExtraction`` (rag_core/kg/pipeline.py:37-50) 재사용.

KGStrategy 가 본 단계의 결과를 받아 GraphStore.get_subgraph 와 generate_stage 에 전달.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


_EXTRACT_SYSTEM = (
    "사용자 질문에서 핵심 엔티티(인물명/신학 개념/교리)를 추출하고 "
    "질문 의도를 분류하세요. 엔티티는 짧은 명사형으로 정규화 "
    "(예: '예정론', '어거스틴', '이신칭의')."
)


class ExtractEntitiesResult(TypedDict):
    """엔티티 추출 결과 envelope."""

    entities: list[str]
    intent: str
    """'definition' / 'comparison' / 'influence' / 'general' 중 하나."""


class ExtractEntitiesStage:
    """LLM 구조화 출력으로 엔티티 + 의도 추출."""

    name: str = "extract_entities"

    def __init__(self, *, llm: BaseChatModel) -> None:
        self._llm = llm

    def run(self, input: str) -> ExtractEntitiesResult:
        from langchain_core.prompts import ChatPromptTemplate

        from rag_core.kg.pipeline import EntityExtraction

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _EXTRACT_SYSTEM),
                ("human", "{question}"),
            ]
        )
        chain = prompt | self._llm.with_structured_output(EntityExtraction)
        result: EntityExtraction = chain.invoke({"question": input})
        return ExtractEntitiesResult(
            entities=list(result.entities),
            intent=str(result.intent),
        )
