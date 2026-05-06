"""Vision 검색 전략 — 첨부 이미지 + 질문 → LLM 답변 (선택적 corpus 검색 통합).

기존 ``rag_core/vision_rag.py:VisionRAG.query`` 의 책임을:
- AttachmentValidator        — 서버측 검증
- PrepareImagePayloadStage   — Attachment → OpenAI multimodal payload
- (선택) text_retriever      — corpus 검색 결합 (env flag VISION_WITH_RETRIEVAL)
- LLM 호출                  — strategy 가 직접

으로 분해. supports() 가 첨부 *유무* 로 자연 분기 — _resolve_mode 의 명시 분기 제거 가능.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult, Retriever
from chatbot.infrastructure.parsers import format_doc_with_meta, refs_to_citations
from chatbot.infrastructure.prompts import VISION_SYSTEM_PROMPT
from chatbot.infrastructure.stages import (
    PrepareImagePayloadStage,
    RetrieveStage,
)
from chatbot.infrastructure.strategies._config import VisionStrategyConfig
from chatbot.infrastructure.validation import (
    AttachmentValidationError,
    AttachmentValidator,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class VisionStrategy:
    """첨부 이미지 분석 전략. domain.RetrievalStrategy 구현."""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        validator: AttachmentValidator,
        prepare_stage: PrepareImagePayloadStage,
        text_retriever: Retriever | None = None,
        config: VisionStrategyConfig,
    ) -> None:
        self._llm = llm
        self._validator = validator
        self._prepare = prepare_stage
        self._retrieve = RetrieveStage(text_retriever) if text_retriever is not None else None
        self._config = config

    @property
    def name(self) -> str:
        return "vision"

    @property
    def label(self) -> str:
        return self._config.label

    def is_available(self) -> tuple[bool, str | None]:
        flag = os.getenv(self._config.enabled_env_var, "").strip().lower()
        if flag not in ("1", "true", "yes"):
            return (False, f"{self._config.enabled_env_var} 환경변수 비활성")
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        """첨부가 있을 때만 True — vision 의 본질 조건."""
        return bool(request.attachments)

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        from langchain_core.messages import HumanMessage, SystemMessage

        start = time.perf_counter()

        # 1. 서버측 검증 — 실패 시 user-friendly 답변으로 변환
        try:
            self._validator.validate_all(list(request.attachments))
        except AttachmentValidationError as e:
            return self._error_result(reason=str(e), start=start)

        # 2. (선택) corpus 검색
        documents = self._maybe_retrieve(request)

        # 3. multimodal payload 조립
        payload = self._prepare.run((request.standalone_question, list(request.attachments)))

        # 4. system + (선택 context) + human(payload) → LLM
        system_text = VISION_SYSTEM_PROMPT
        if documents:
            chunk_text = "\n\n---\n\n".join(format_doc_with_meta(d) for d in documents)
            system_text = f"{VISION_SYSTEM_PROMPT}\n\n## 참고 본문 발췌:\n{chunk_text}"

        messages: list[Any] = [
            SystemMessage(content=system_text),
            HumanMessage(content=payload["parts"]),
        ]
        response = self._llm.invoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)
        return self._build_result(
            answer=answer if isinstance(answer, str) else str(answer),
            documents=documents,
            attachment_count=len(request.attachments),
            elapsed_ms=int((time.perf_counter() - start) * 1000),
        )

    def _maybe_retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        if self._retrieve is None:
            return []
        flag = os.getenv(self._config.with_retrieval_env_var, "").strip().lower()
        if flag not in ("1", "true", "yes"):
            return []
        adjusted = request.model_copy(update={"top_k": self._config.text_top_k})
        return self._retrieve.run(adjusted)

    def _build_result(
        self,
        *,
        answer: str,
        documents: list[DocumentRef],
        attachment_count: int,
        elapsed_ms: int,
    ) -> RetrievalResult:
        from chatbot.infrastructure.parsers import extract_cited_pages

        cited_pages = extract_cited_pages(answer)
        citations = (
            tuple(refs_to_citations(documents, cited_pages_one_indexed=cited_pages))
            if documents
            else ()
        )
        return RetrievalResult(
            documents=tuple(documents),
            citations=citations,
            metadata={
                "pattern": self._config.pattern_name,
                "elapsed_ms": str(elapsed_ms),
                "answer": answer,
                "attachment_count": str(attachment_count),
                "with_retrieval": "true" if documents else "false",
            },
        )

    def _error_result(self, *, reason: str, start: float) -> RetrievalResult:
        """첨부 검증 실패 시 사과 메시지 + 메타 표기. answer 는 사용자 안내."""
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return RetrievalResult(
            documents=(),
            citations=(),
            metadata={
                "pattern": self._config.pattern_name,
                "elapsed_ms": str(elapsed_ms),
                "answer": "첨부된 이미지를 처리할 수 없습니다. 형식이나 크기를 확인해주세요.",
                "attachment_count": "0",
                "validation_error": reason,
            },
        )
