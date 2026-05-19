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
from infra.llm_cache import cache_delta, cache_snapshot

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
        cache_start = cache_snapshot()
        self._apply_dense_weight_override(request)
        request = request.model_copy(update={"top_k": self._config.top_k})

        documents, debug_meta = self._retrieve_with_debug(request)
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
            debug_meta=debug_meta,
            cache_meta=cache_delta(cache_start),
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
        debug_meta: dict[str, str],
        cache_meta: dict[str, str | int | float | bool],
        elapsed_ms: int,
    ) -> RetrievalResult:
        citations = refs_to_citations(documents, cited_pages_one_indexed=cited_pages)
        metadata = {
            "pattern": self._config.pattern_name,
            "elapsed_ms": str(elapsed_ms),
            "confidence": f"{confidence:.4f}",
            "cited_pages": json.dumps(cited_pages),
            "is_grounded": str(outcome.is_grounded),
            "grade_reason": outcome.grade_reason,
            "self_rag_retries": str(outcome.retries),
            "self_rag_attempts": str(outcome.retries + 1),
            "answer": answer,
            "suggested_followups": json.dumps(followups, ensure_ascii=False),
            **debug_meta,
        }
        if outcome.rewritten_question:
            metadata["rewritten_question"] = outcome.rewritten_question
        metadata.update({k: str(v) for k, v in cache_meta.items()})
        return RetrievalResult(
            documents=tuple(documents),
            citations=tuple(citations),
            metadata=metadata,
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

    def _apply_dense_weight_override(self, request: RetrievalRequest) -> None:
        """request metadata_filter 의 dense_weight를 런타임 가중치로 반영."""
        raw = request.metadata_filter.get("dense_weight", "").strip()
        if not raw:
            return
        try:
            value = float(raw)
        except ValueError:
            return
        if 0.0 <= value <= 1.0:
            self.set_dense_weight(value)

    def _retrieve_with_debug(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[DocumentRef], dict[str, str]]:
        """검색 결과와 v1 호환 디버그 메타를 함께 반환."""
        splitter = getattr(self._retriever, "retrieve_split", None)
        if callable(splitter):
            bm25_results, dense_results, fused = splitter(request)
            top_docs = fused[: request.top_k]
            rrf_scores = [round(float(d.score or 0.0), 4) for d in top_docs[:5]]
            return top_docs, {
                "bm25_count": str(len(bm25_results)),
                "dense_count": str(len(dense_results)),
                "rrf_top_scores": json.dumps(rrf_scores),
                "dense_weight": f"{getattr(self._retriever, 'dense_weight', 0.5):.4f}",
            }
        docs = self._retrieve.run(request)
        return docs, {
            "bm25_count": "",
            "dense_count": "",
            "rrf_top_scores": json.dumps([]),
            "dense_weight": f"{getattr(self._retriever, 'dense_weight', 0.5):.4f}",
        }
