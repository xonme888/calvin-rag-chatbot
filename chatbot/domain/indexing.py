"""인덱싱 파이프라인 — Loader → Splitter → Embedder → Store.

각 단계가 독립 Protocol. 구현체 교체는 *해당 단계 어댑터 1개* 만 손대면 끝난다.
- Loader 변경 (PDF → MCP 서버) : ``infrastructure/loaders/`` 에 새 어댑터 + corpus 메타에 kind 추가
- Splitter 변경 (재귀 → 의미론적): ``infrastructure/splitters/`` 새 어댑터
- Embedder 교체 (OpenAI → BGE)  : ``infrastructure/embedders/`` 새 어댑터
- Store 교체 (FAISS → Qdrant)   : ``infrastructure/stores/`` 새 어댑터

도메인은 시그니처만 정의한다. 어떤 파라미터도 frozen pydantic 모델로 주고받아 추적성 ↑.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from chatbot.domain.corpus import KnowledgeSource


class Document(BaseModel):
    """Loader 가 읽어들인 단위 — 책 1권/문서 1개가 보통 여러 Document 로 나온다 (페이지·섹션)."""

    model_config = ConfigDict(frozen=True)

    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    """원천 메타 (page, section, source_id 등). Splitter 가 chunk 에 전파."""


class Chunk(BaseModel):
    """Splitter 가 만든 검색 단위. 임베딩과 1:1 대응."""

    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    """corpus_id, source_id, page, parent_doc_id 를 최소한 포함해야 한다 (Citation 으로 환원 가능)."""


@runtime_checkable
class Loader(Protocol):
    """원천 → Document 시퀀스. PDF/EPUB/HTML/MCP 등 어댑터별로 구현."""

    @property
    def supports(self) -> tuple[str, ...]:
        """이 Loader 가 처리할 수 있는 KnowledgeSource.kind 목록 (예: ('pdf',))."""
        ...

    def load(self, source: KnowledgeSource) -> list[Document]: ...


@runtime_checkable
class Splitter(Protocol):
    """Document → Chunk. 청크 크기·overlap·전략(재귀/의미론) 별 구현."""

    name: str

    def split(self, documents: list[Document]) -> list[Chunk]: ...


@runtime_checkable
class Embedder(Protocol):
    """텍스트 → 벡터. OpenAI/BGE/HuggingFace 어댑터.

    배치 처리는 어댑터 내부 책임 — 도메인은 호출 계약만 본다.
    """

    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class Store(Protocol):
    """벡터 저장소. FAISS/Qdrant/PG 등.

    검색 시 metadata filter 를 받는다 — corpus_id 로 도메인 격리, source_id 로 책 단위 검색 가능.
    """

    name: str

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def search(
        self,
        query_embedding: list[float],
        k: int,
        filter: dict[str, str] | None = None,
    ) -> list[Chunk]: ...

    def delete(self, filter: dict[str, str]) -> int:
        """filter 매칭 chunk 삭제. 반환은 삭제 수. corpus 재인덱싱 시 사용."""
        ...
