"""LangChain Document ↔ domain.DocumentRef 변환.

규칙:
- chunk_id 는 ``{source_id}:p{page}:{stable_hash}`` 로 결정성 보장.
  같은 본문은 같은 ID — RRF 매칭과 인용 중복 제거에 사용.
- corpus_id/source_id 는 chunk.metadata 에서 읽는다 — 인덱싱 시점에 박아 둔다.
- page 는 PyMuPDFLoader 가 0-indexed 로 저장한다는 사실을 그대로 유지.
  사용자 표시 시점(citation_parser) 에 +1 변환.
"""

from __future__ import annotations

import hashlib
from typing import Any

from chatbot.domain.corpus import DocumentRef


def _stable_chunk_id(source_id: str, page: int | None, content: str) -> str:
    """결정성 chunk ID — 같은 (source, page, content) 는 항상 같은 ID."""
    digest = hashlib.sha1(content.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    page_part = f"p{page}" if page is not None else "p?"
    return f"{source_id}:{page_part}:{digest}"


def _coerce_metadata(meta: dict[str, Any]) -> dict[str, str]:
    """모든 값을 str 로 강제 — DocumentRef.metadata 의 타입 계약."""
    return {k: str(v) for k, v in meta.items() if v is not None}


def to_document_ref(
    *,
    content: str,
    metadata: dict[str, Any],
    score: float | None = None,
    default_corpus_id: str | None = None,
    default_source_id: str | None = None,
) -> DocumentRef:
    """LangChain Document → DocumentRef.

    metadata 에 corpus_id/source_id 가 없으면 default_* 를 사용. 둘 다 없으면 빈 문자열.
    page 는 metadata['page'] (PyMuPDFLoader 의 0-indexed 그대로) 를 보존.
    """
    corpus_id = str(metadata.get("corpus_id") or default_corpus_id or "")
    source_id = str(metadata.get("source_id") or default_source_id or "")
    page_raw = metadata.get("page")
    page = int(page_raw) if isinstance(page_raw, (int, float)) else None

    return DocumentRef(
        corpus_id=corpus_id,
        source_id=source_id,
        chunk_id=_stable_chunk_id(source_id, page, content),
        page=page,
        content=content,
        score=score,
        metadata=_coerce_metadata(metadata),
    )
