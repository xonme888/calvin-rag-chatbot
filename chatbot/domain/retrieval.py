"""검색(Retrieval) 도메인 — Retriever, RetrievalRequest/Result, Subgraph.

설계 의도:
- Retriever 는 *검색* 만 한다. 도구 호출은 ``tools.Tool``, 조합 레시피는 ``strategy.RetrievalStrategy``.
  세 책임을 분리해 변경 반경을 최소화한다.
- 모든 Retriever 와 Strategy 는 동일한 RetrievalRequest 를 받는다 — 분기·시그니처 차이 제거.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from chatbot.domain.conversation import Attachment, Message
from chatbot.domain.corpus import Citation, DocumentRef


class RetrievalRequest(BaseModel):
    """모든 검색기·전략의 통일 입력.

    standalone_question 은 후속 질문이 rewrite 된 결과. NEW_QUESTION 이면 user 원문 그대로.
    chat_history 는 답변 합성 단계에서 사용 — Retriever 가 보지 않더라도 envelope 일관성을
    위해 함께 전달한다 (Strategy 가 history-aware retriever 를 조립하는 경우 사용).
    """

    model_config = ConfigDict(frozen=True)

    standalone_question: str
    chat_history: tuple[Message, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    corpus_ids: tuple[str, ...] | None = None
    """검색 대상 corpus 제한. None 이면 등록된 모든 corpus."""

    top_k: int = 8
    metadata_filter: dict[str, str] = Field(default_factory=dict)


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    type: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    label: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class Subgraph(BaseModel):
    """KG 검색 결과로 반환되는 부분 그래프. UI 의 시각화·후속 메타-참조 모두 사용."""

    model_config = ConfigDict(frozen=True)

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    metadata: dict[str, str] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """모든 검색기·전략의 통일 출력.

    documents 는 항상 채워지고, subgraph/tool_calls 는 옵션. compose_answer 노드는
    이 envelope 만 보면 어느 strategy 결과인지 신경 쓰지 않고 답변을 합성할 수 있다.
    """

    model_config = ConfigDict(frozen=True)

    documents: tuple[DocumentRef, ...]
    citations: tuple[Citation, ...]
    """답변에 노출 가능한 인용 형태로 변환된 표면 메타. documents 의 부분집합."""

    subgraph: Subgraph | None = None
    tool_calls: tuple["ToolCallRecord", ...] = ()
    """이 검색 동안 실행된 도구 호출 기록 (Agentic strategy 가 채움)."""

    metadata: dict[str, str] = Field(default_factory=dict)
    """전략·구현 특화 메타 (cache_hits, elapsed, confidence 등). 필수 키는 정해두지 않는다."""


class ToolCallRecord(BaseModel):
    """RetrievalResult 에 누적되는 도구 호출 기록 (감사·시연용).

    Tool 자체의 정의는 ``tools.py``. 여기엔 *호출 결과의 직렬화 가능 형태* 만 둔다.
    """

    model_config = ConfigDict(frozen=True)

    tool_name: str
    arguments: dict[str, str]
    result_preview: str
    """결과의 짧은 요약 (≤200자). 전체 결과는 별도 저장소에 두고 ID 로 참조해도 좋다."""

    elapsed_ms: int = Field(ge=0)


@runtime_checkable
class Retriever(Protocol):
    """검색기 1개 — BM25/Dense/Hybrid/Graph 등.

    Strategy 가 1개 또는 여러 Retriever 를 조립한다. Retriever 자체는 단일 책임:
    request → DocumentRef 시퀀스. citations 변환·subgraph 구성은 Strategy 책임.
    """

    name: str

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]: ...


# Pydantic forward ref 해소
RetrievalResult.model_rebuild()
