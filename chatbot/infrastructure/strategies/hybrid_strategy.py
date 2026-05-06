"""Hybrid 검색 전략 — Retriever/Stage/Reranker 조립. RetrievalStrategy 구현."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TypeAlias

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest, RetrievalResult, Retriever
from chatbot.infrastructure.parsers import refs_to_citations
from chatbot.infrastructure.rerankers import (
    FlashRankRerankerStage,
    LongContextReorderStage,
    RerankInput,
)
from chatbot.infrastructure.stages import (
    GenerateInput,
    GenerateStage,
    GradeStage,
    RetrieveStage,
    RewriteStage,
)
from chatbot.infrastructure.strategies._config import HybridStrategyConfig
from chatbot.infrastructure.strategies._self_rag_loop import LoopOutcome, SelfRAGLoop

FollowupFn: TypeAlias = Callable[[str, str], list[str]]


class HybridStrategy:
    """Retriever + Reranker + Stage 조립. domain.RetrievalStrategy 구현."""

    def __init__(
        self,
        *,
        retriever: Retriever,
        retrieve_stage: RetrieveStage,
        generate_stage: GenerateStage,
        reranker: FlashRankRerankerStage | None = None,
        reorderer: LongContextReorderStage | None = None,
        grade_stage: GradeStage | None = None,
        rewrite_stage: RewriteStage | None = None,
        followup_fn: FollowupFn | None = None,
        config: HybridStrategyConfig,
    ) -> None:
        self._retriever = retriever
        self._retrieve = retrieve_stage
        self._generate = generate_stage
        self._reranker = reranker
        self._reorderer = reorderer or LongContextReorderStage()
        self._grade = grade_stage
        self._rewrite = rewrite_stage
        self._followup_fn = followup_fn
        self._config = config

    @property
    def name(self) -> str:
        return "hybrid"

    @property
    def label(self) -> str:
        return self._config.label

    def set_dense_weight(self, value: float) -> None:
        """런타임 dense_weight 조정 — HybridRetriever 의 setter 위임."""
        if hasattr(self._retriever, "dense_weight"):
            self._retriever.dense_weight = value  # type: ignore[attr-defined]

    def is_available(self) -> tuple[bool, str | None]:
        """LLM 호출 실패는 회로 차단기 책임. 본 메서드는 Strategy 자체의 가용성만."""
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        """첨부가 있으면 vision 으로 양보."""
        return not request.attachments

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        start = time.perf_counter()
        request = request.model_copy(update={"top_k": self._config.top_k})

        documents = self._retrieve.run(request)
        documents = self._maybe_rerank(query=request.standalone_question, documents=documents)

        gen_out = self._generate.run(
            GenerateInput(
                question=request.standalone_question,
                documents=documents,
                chat_history=list(request.chat_history),
            )
        )
        outcome = self._maybe_self_rag(
            question=request.standalone_question,
            documents=documents,
            answer=gen_out["answer"],
            request=request,
        )
        followups = (
            self._followup_fn(request.standalone_question, outcome.answer)
            if self._followup_fn
            else []
        )
        return self._build_result(
            documents=outcome.documents,
            answer=outcome.answer,
            cited_pages=gen_out["cited_pages"],
            confidence=gen_out["confidence"],
            outcome=outcome,
            followups=followups,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
        )

    def _build_result(
        self,
        *,
        documents: list[DocumentRef],
        answer: str,
        cited_pages: list[int],
        confidence: float,
        outcome: LoopOutcome,
        followups: list[str],
        elapsed_ms: int,
    ) -> RetrievalResult:
        citations = refs_to_citations(documents, cited_pages_one_indexed=cited_pages)
        return RetrievalResult(
            documents=tuple(documents),
            citations=tuple(citations),
            metadata={
                "pattern": self._config.pattern_name,
                "elapsed_ms": str(elapsed_ms),
                "confidence": f"{confidence:.4f}",
                "cited_pages": json.dumps(cited_pages),
                "is_grounded": str(outcome.is_grounded),
                "grade_reason": outcome.grade_reason,
                "self_rag_retries": str(outcome.retries),
                "answer": answer,
                "suggested_followups": json.dumps(followups, ensure_ascii=False),
            },
        )

    def _maybe_rerank(self, *, query: str, documents: list[DocumentRef]) -> list[DocumentRef]:
        if not self._config.reranker_enabled or not documents or self._reranker is None:
            return documents
        ok, _ = self._reranker.is_available()
        if not ok:
            return documents
        # 모델 인스턴스는 주입된 self._reranker 1개만 — RerankInput envelope 로 query 전달.
        # with_query/clone 패턴 제거(audit 권고 §3.2 반영) — 매 턴 모델 중복 로드 방지.
        reranked = self._reranker.run(RerankInput(query=query, documents=documents))
        if self._config.reranker_top_k:
            reranked = reranked[: self._config.reranker_top_k]
        return self._reorderer.run(reranked)

    def _maybe_self_rag(
        self,
        *,
        question: str,
        documents: list[DocumentRef],
        answer: str,
        request: RetrievalRequest,
    ) -> LoopOutcome:
        if not self._config.self_rag_enabled or self._grade is None or self._rewrite is None:
            return LoopOutcome(
                answer=answer,
                documents=documents,
                is_grounded=True,
                grade_reason="self_rag disabled",
                retries=0,
            )
        loop = SelfRAGLoop(
            grade=self._grade,
            rewrite=self._rewrite,
            retrieve=self._retrieve,
            generate=self._generate,
            max_retries=self._config.max_self_rag_retries,
        )
        return loop.run(
            question=question,
            documents=documents,
            answer=answer,
            request=request,
        )
