"""말뭉치(Corpus) 도메인 — 새 책·도메인 추가의 추상.

설계 의도:
- 칼빈 강요 한 권에 묶이지 않는다. 어거스틴 고백록·바빙크 교의학 등 새 도메인은
  ``KnowledgeSource`` 1개 추가 + ``Corpus`` 등록만으로 합류해야 한다.
- 인용(Citation) 은 항상 ``corpus_id`` + ``source_id`` 를 들고 다닌다 — UI 가 원천을
  표시하고 권리표기·라이선스 검증을 분리할 수 있도록.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSource(BaseModel):
    """1개 원천(책·문서·웹). 한 Corpus 가 여러 source 를 가질 수 있다."""

    model_config = ConfigDict(frozen=True)

    id: str
    """corpus 내 고유. 예: 'institutes_v1', 'augustine_confessions_book01'."""

    kind: Literal["pdf", "epub", "html", "markdown", "plaintext"]
    uri: str
    """파일 경로 또는 URL. 인덱싱 파이프라인의 Loader 가 해석한다."""

    title: str
    author: str | None = None
    language: str = "ko"
    license: str | None = None
    """저작권 표기 — UI/감사 로그에서 노출. None 이면 '미상'."""

    metadata: dict[str, str] = Field(default_factory=dict)
    """source 특화 메타 (출판사, 판본, ISBN 등). UI 가 부가 정보로 노출."""


class Corpus(BaseModel):
    """말뭉치 — 동일 도메인 검색을 공유하는 source 들의 묶음.

    예: '칼빈-신학' Corpus 는 강요·기도서·로마서 주석을 source 로 가질 수 있다.
    검색 인덱스는 corpus 단위로 분리하는 것을 권장 (cross-corpus 검색 시 명시적 요청).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    sources: tuple[KnowledgeSource, ...]
    default_strategy: str | None = None
    """이 corpus 에 대한 기본 RetrievalStrategy 이름. None 이면 라우터가 결정."""


class DocumentRef(BaseModel):
    """검색 결과로 반환되는 문서 청크의 참조.

    실제 본문(content) 은 size 가 클 수 있어 별도 Store 에서 lazy load 가능.
    Citation 으로 표시되는 인용 정보의 원천이다.
    """

    model_config = ConfigDict(frozen=True)

    corpus_id: str
    source_id: str
    chunk_id: str
    page: int | None = None
    """0-indexed. UI 표시 시 +1 (사용자 친화). PDF 외 source 는 None."""

    content: str
    score: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class Citation(BaseModel):
    """답변 문장에 붙는 인용 — UI 의 인용 칩·각주가 사용.

    DocumentRef 와 분리한 이유: Citation 은 *답변에 노출되는 표면 메타* 만 담는다.
    내부 score·전체 본문은 DocumentRef 에 둔다.
    """

    model_config = ConfigDict(frozen=True)

    corpus_id: str
    source_id: str
    page_label: str
    """사용자에게 보여줄 형식 (예: 'p.42', '1권 7장 §3'). source kind 별로 어댑터가 만든다."""

    snippet: str
    """답변 문장과 매칭된 짧은 발췌. 길어도 200자."""
