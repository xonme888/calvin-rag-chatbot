"""오케스트레이터 부트스트랩 — registry 조립 + env 토글 (KG_ENABLED 등)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

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


def build_persistence_from_env() -> tuple[Any | None, Any]:
    """환경변수 → (ConversationStore | None, UserIdentifier).

    SUPABASE_URL + SUPABASE_SERVICE_KEY 모두 있으면 Supabase 어댑터 빌드.
    AUTH_ENABLED=false 또는 환경변수 미설정 시 (None, AnonymousUserIdentifier) — 익명 모드.

    chat_v2 라우트의 ``_persistence()`` lru_cache 가 본 함수를 1회 호출해 컴포넌트 보유.
    """
    import logging as _lg

    from chatbot.infrastructure.auth import AnonymousUserIdentifier

    _logger = _lg.getLogger(__name__)

    if _flag_disabled("AUTH_ENABLED"):
        _logger.warning("Persistence disabled — AUTH_ENABLED=false")
        return (None, AnonymousUserIdentifier())

    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not service_key:
        _logger.warning(
            "Persistence not configured — SUPABASE_URL/SUPABASE_SERVICE_KEY 미설정. 익명 모드."
        )
        return (None, AnonymousUserIdentifier())

    try:
        from supabase import create_client

        from chatbot.infrastructure.auth import SupabaseUserIdentifier
        from chatbot.infrastructure.persistence import SupabaseConversationStore
    except ImportError as e:
        _logger.warning("Persistence import 실패 (supabase 미설치): %s", e)
        return (None, AnonymousUserIdentifier())

    try:
        client = create_client(url, service_key)
    except Exception as e:  # noqa: BLE001
        _logger.warning("Supabase client 생성 실패: %s", e)
        return (None, AnonymousUserIdentifier())

    store = SupabaseConversationStore(client=client)
    identifier = SupabaseUserIdentifier(client=client)
    _logger.warning("Persistence registered (Supabase)")
    return (store, identifier)


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
    if _flag_disabled("AGENTIC_ENABLED"):
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
    if _flag_disabled("KG_ENABLED"):
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

    import logging as _lg

    _logger = _lg.getLogger(__name__)
    try:
        port = get_kg_adapter()
    except Exception as e:  # noqa: BLE001 — Neo4j 미연결 등 시 등록 스킵
        _logger.warning("KG strategy not registered (Neo4j 연결 실패): %s", e)
        return
    # 기존 api/dependencies.py:get_kg_rag_or_none 와 동등 — health + 그래프 비어있음 가드.
    try:
        if not port.health_check():
            _logger.warning("KG strategy not registered (Neo4j health_check 실패)")
            return
        nodes = port.stats().get("nodes", 0)
        if nodes == 0:
            _logger.warning("KG strategy not registered (그래프 비어 있음 — 인덱싱 필요)")
            return
    except Exception as e:  # noqa: BLE001
        _logger.warning("KG strategy not registered (stats 예외): %s", e)
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
    # warning 레벨로 격상 — 운영 root logger 의 INFO 차단 환경에서도 가시성 보장.
    _logger.warning("KG strategy registered (nodes=%d)", nodes)


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
    """opt-in 게이트 — 환경변수가 명시적으로 truthy 일 때만 True."""
    return os.getenv(env, "").strip().lower() in ("1", "true", "yes")


def _flag_disabled(env: str) -> bool:
    """opt-out 게이트 — 환경변수가 명시적으로 falsy 일 때만 True.

    미설정/truthy 는 *자동 활성화* — 기존 ``api/dependencies.get_kg_rag_or_none`` /
    ``get_agentic_rag`` 의 동작과 동등 (Neo4j/도구 가용 시 자동 등록).
    """
    return os.getenv(env, "").strip().lower() in ("0", "false", "no")
