"""오케스트레이터 부트스트랩 — registry 조립 + env 토글 (KG_ENABLED 등)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from chatbot.application.orchestrator import build_orchestrator
from chatbot.application.registries import (
    InMemoryCorpusRegistry,
    InMemoryStrategyRegistry,
    InMemoryToolRegistry,
)
from chatbot.infrastructure.answer_composer import HistoryAwareAnswerComposer
from chatbot.infrastructure.corpora.calvin_institutes import (
    CALVIN_CORPUS,
    SYSTEM_PROMPT as CALVIN_PROMPT,
)
from chatbot.infrastructure.intent_llm import HeuristicWithLLMFallbackClassifier
from chatbot.infrastructure.parsers import format_doc_with_meta  # noqa: F401 — search_documents 가 사용
from chatbot.infrastructure.prompts import build_hybrid_prompt
from chatbot.infrastructure.retrievers import (
    BM25Retriever,
    DenseRetriever,
    HybridRetriever,
)
from chatbot.infrastructure.rewriter_llm import LLMQueryRewriter
from chatbot.infrastructure.router import KeywordStrategyRouter
from chatbot.infrastructure.stages import GenerateStage, RetrieveStage
from chatbot.infrastructure.strategies import (
    HybridStrategy,
    HybridStrategyConfig,
)
from chatbot.infrastructure.tools.search import SearchDocumentsTool

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

    from rag_core.hybrid import HybridRAG


def build_default_orchestrator(
    *,
    hybrid_rag: HybridRAG,
    llm: BaseChatModel,
) -> CompiledStateGraph:
    """HybridRAG + LLM 주입 → 4-strategy orchestrator. KG/Agentic 은 env flag 토글."""
    corpora = InMemoryCorpusRegistry()
    corpora.register(CALVIN_CORPUS)

    strategies = InMemoryStrategyRegistry()
    strategies.register(_build_hybrid_strategy(hybrid_rag=hybrid_rag, llm=llm))
    _maybe_register_agentic(strategies, hybrid_rag=hybrid_rag, llm=llm)
    _maybe_register_kg(strategies, hybrid_rag=hybrid_rag, llm=llm)
    _maybe_register_vision(strategies, hybrid_rag=hybrid_rag, llm=llm)

    tools = InMemoryToolRegistry()
    tools.register(SearchDocumentsTool(_build_hybrid_retriever(hybrid_rag)))

    classifier = HeuristicWithLLMFallbackClassifier(llm=llm)
    rewriter = LLMQueryRewriter(llm=llm)
    router = KeywordStrategyRouter()
    answerer = HistoryAwareAnswerComposer(llm=llm)

    return build_orchestrator(
        classifier=classifier,
        rewriter=rewriter,
        strategies=strategies,
        router=router,
        answerer=answerer,
    )


def _build_hybrid_strategy(*, hybrid_rag: HybridRAG, llm: BaseChatModel) -> HybridStrategy:
    """기존 HybridRAG 의 retriever/embeddings 를 *재사용* 해 4 strategy 가 같은 인덱스를 공유."""
    text_retriever = _build_hybrid_retriever(hybrid_rag)
    retrieve_stage = RetrieveStage(text_retriever)
    generate_stage = GenerateStage(
        llm=llm,
        prompt=build_hybrid_prompt(CALVIN_PROMPT),
    )
    return HybridStrategy(
        retriever=text_retriever,
        retrieve_stage=retrieve_stage,
        generate_stage=generate_stage,
        config=HybridStrategyConfig(top_k=hybrid_rag.config.top_k),
    )


def _build_hybrid_retriever(hybrid_rag: HybridRAG) -> HybridRetriever:
    """기존 HybridRAG.retriever 의 chunks/vector_store 를 도메인 어댑터로 감싼다."""
    legacy = hybrid_rag.retriever
    if legacy.chunks is None or legacy.vector_store is None:
        raise RuntimeError("HybridRAG 가 아직 인덱싱되지 않았습니다.")
    bm25 = BM25Retriever(
        list(legacy.chunks),
        default_corpus_id="calvin",
        default_source_id="institutes_v1",
    )
    dense = DenseRetriever(
        legacy.vector_store,
        default_corpus_id="calvin",
        default_source_id="institutes_v1",
    )
    return HybridRetriever(
        bm25,
        dense,
        dense_weight=hybrid_rag.config.dense_weight,
        rrf_k=hybrid_rag.config.rrf_k,
    )


def _maybe_register_agentic(
    registry: InMemoryStrategyRegistry,
    *,
    hybrid_rag: HybridRAG,
    llm: BaseChatModel,
) -> None:
    if not _flag_enabled("AGENTIC_ENABLED"):
        return
    from chatbot.infrastructure.strategies import AgenticStrategy, AgenticStrategyConfig

    text_retriever = _build_hybrid_retriever(hybrid_rag)
    registry.register(
        AgenticStrategy(
            llm=llm,
            tools=[SearchDocumentsTool(text_retriever)],
            config=AgenticStrategyConfig(),
        )
    )


def _maybe_register_kg(
    registry: InMemoryStrategyRegistry,
    *,
    hybrid_rag: HybridRAG,
    llm: BaseChatModel,
) -> None:
    if not _flag_enabled("KG_ENABLED"):
        return
    try:
        from rag_core.kg.factory import get_kg_adapter
    except ImportError as e:
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "KG strategy not registered (langchain-neo4j 미설치): %s", e
        )
        return
    from chatbot.infrastructure.stages import (
        ExtractEntitiesStage,
        NormalizeSubgraphStage,
    )
    from chatbot.infrastructure.stores import port_to_graph_store
    from chatbot.infrastructure.strategies import KGStrategy, KGStrategyConfig

    try:
        port = get_kg_adapter()
    except Exception as e:  # noqa: BLE001 — Neo4j 미연결 등 시 등록 스킵
        import logging as _lg

        _lg.getLogger(__name__).warning("KG strategy not registered (Neo4j 연결 실패): %s", e)
        return
    registry.register(
        KGStrategy(
            graph_store=port_to_graph_store(port),
            text_retriever=_build_hybrid_retriever(hybrid_rag),
            extract_stage=ExtractEntitiesStage(llm=llm),
            normalize_stage=NormalizeSubgraphStage(),
            llm=llm,
            config=KGStrategyConfig(),
        )
    )


def _maybe_register_vision(
    registry: InMemoryStrategyRegistry,
    *,
    hybrid_rag: HybridRAG,
    llm: BaseChatModel,
) -> None:
    """VISION_ENABLED 게이트는 strategy.is_available() 안에서 별도 — 본 함수는 등록만 항상."""
    from chatbot.infrastructure.stages import PrepareImagePayloadStage
    from chatbot.infrastructure.strategies import VisionStrategy, VisionStrategyConfig
    from chatbot.infrastructure.validation import AttachmentValidator

    registry.register(
        VisionStrategy(
            llm=llm,
            validator=AttachmentValidator(),
            prepare_stage=PrepareImagePayloadStage(),
            text_retriever=_build_hybrid_retriever(hybrid_rag),
            config=VisionStrategyConfig(),
        )
    )


def _flag_enabled(env: str) -> bool:
    return os.getenv(env, "").strip().lower() in ("1", "true", "yes")
