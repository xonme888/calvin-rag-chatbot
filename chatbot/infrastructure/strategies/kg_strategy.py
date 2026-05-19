"""KG 검색 전략 — GraphStore + Stage 조립. RetrievalStrategy 구현.

기존 ``rag_core/kg/pipeline.py:KnowledgeGraphRAG`` 를 책임 분해한 결과의 *조립 책임* 만
본 파일이 갖는다. extract_entities / get_subgraph / normalize / text_retrieve / generate
가 각자의 단계로 분리되어 합성된다.

흐름:
1. ExtractEntitiesStage  — 질문 → entities + intent
2. GraphStore.get_subgraph — entities → Subgraph
3. NormalizeSubgraphStage — alias 통합·노이즈 제거
4. text_retriever         — 본문 검색 (Hybrid retriever 재사용)
5. _format_subgraph_for_llm — Subgraph → LLM 친화 텍스트
6. LLM 호출               — graph_text + chunk_text → 답변

본 파일 < 200줄, run() < 60줄 목표.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from chatbot.domain.corpus import Citation, DocumentRef
from chatbot.domain.graph import GraphStore
from chatbot.domain.retrieval import (
    RetrievalRequest,
    RetrievalResult,
    Retriever,
    Subgraph,
)
from chatbot.infrastructure.parsers import (
    extract_cited_pages,
    format_doc_with_meta,
    refs_to_citations,
)
from chatbot.infrastructure.stages import (
    ExtractEntitiesResult,
    ExtractEntitiesStage,
    NormalizeSubgraphStage,
    RetrieveStage,
)
from chatbot.infrastructure.strategies._config import KGStrategyConfig
from infra.llm_cache import cache_delta, cache_snapshot

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class KGStrategy:
    """KG 부분 그래프 + 본문 검색 결합. domain.RetrievalStrategy 구현."""

    def __init__(
        self,
        *,
        graph_store: GraphStore,
        text_retriever: Retriever,
        extract_stage: ExtractEntitiesStage,
        normalize_stage: NormalizeSubgraphStage,
        llm: BaseChatModel,
        config: KGStrategyConfig,
    ) -> None:
        self._graph_store = graph_store
        self._retrieve = RetrieveStage(text_retriever)
        self._extract = extract_stage
        self._normalize = normalize_stage
        self._llm = llm
        self._config = config

    @property
    def name(self) -> str:
        return "kg"

    @property
    def label(self) -> str:
        return self._config.label

    def is_available(self) -> tuple[bool, str | None]:
        """GraphStore health_check 결과 그대로 노출."""
        return self._graph_store.health_check()

    def supports(self, request: RetrievalRequest) -> bool:
        """첨부가 있으면 vision 으로 양보."""
        return not request.attachments

    def run(self, request: RetrievalRequest) -> RetrievalResult:
        from langchain_core.prompts import ChatPromptTemplate

        start = time.perf_counter()
        cache_start = cache_snapshot()
        request = request.model_copy(update={"top_k": self._config.top_k})

        extraction = self._extract.run(request.standalone_question)
        subgraph = self._fetch_subgraph(extraction["entities"])
        documents = self._retrieve.run(request)

        graph_text = _format_subgraph_for_llm(subgraph)
        chunk_text = "\n\n---\n\n".join(format_doc_with_meta(d) for d in documents)

        prompt = ChatPromptTemplate.from_messages(
            [("system", self._config.system_prompt), ("human", "{question}")]
        )
        response = (prompt | self._llm).invoke(
            {
                "question": request.standalone_question,
                "graph_text": graph_text,
                "chunk_text": chunk_text,
            }
        )
        answer = response.content if hasattr(response, "content") else str(response)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return self._build_result(
            documents=list(documents),
            answer=answer,
            extraction=extraction,
            subgraph=subgraph,
            question=request.standalone_question,
            cache_meta=cache_delta(cache_start),
            elapsed_ms=elapsed_ms,
        )

    def _fetch_subgraph(self, entities: list[str]) -> Subgraph:
        """엔티티 없으면 빈 Subgraph 반환 — Neo4j 호출 0."""
        if not entities:
            return Subgraph(nodes=(), edges=())
        raw = self._graph_store.get_subgraph(entities, hops=self._config.subgraph_hops)
        return self._normalize.run(raw)

    def _build_result(
        self,
        *,
        documents: list[DocumentRef],
        answer: str,
        extraction: ExtractEntitiesResult,
        subgraph: Subgraph,
        question: str,
        cache_meta: dict[str, object],
        elapsed_ms: int,
    ) -> RetrievalResult:
        cited_pages = extract_cited_pages(answer)
        citations: tuple[Citation, ...] = tuple(
            refs_to_citations(documents, cited_pages_one_indexed=cited_pages)
        )
        from rag_core.followup import generate_followups

        followups = generate_followups(question, answer, self._llm)
        metadata: dict[str, str] = {
            "pattern": self._config.pattern_name,
            "elapsed_ms": str(elapsed_ms),
            "answer": answer,
            "entities": ",".join(extraction["entities"]),
            "intent": extraction["intent"],
            "graph_node_count": str(len(subgraph.nodes)),
            "graph_edge_count": str(len(subgraph.edges)),
            "vector_count": str(len(documents)),
            "suggested_followups": json.dumps(followups, ensure_ascii=False),
        }
        metadata.update({k: str(v) for k, v in cache_meta.items()})
        return RetrievalResult(
            documents=tuple(documents),
            citations=citations,
            subgraph=subgraph,
            metadata=metadata,
        )


def _format_subgraph_for_llm(subgraph: Subgraph) -> str:
    """Subgraph → LLM 친화 텍스트. rag_core/kg/pipeline:_format_subgraph_for_llm 와 동일."""
    if not subgraph.edges:
        if subgraph.nodes:
            return "(그래프 노드: " + ", ".join(n.label for n in subgraph.nodes[:10]) + ")"
        return "(관련 그래프 관계 없음)"

    lines: list[str] = []
    label_by_id = {n.id: n.label for n in subgraph.nodes}
    for edge in subgraph.edges[:30]:
        src = label_by_id.get(edge.source, edge.source)
        dst = label_by_id.get(edge.target, edge.target)
        lines.append(f"- {src} --[{edge.label or 'RELATED_TO'}]--> {dst}")
    return "\n".join(lines)
