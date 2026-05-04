"""FastAPI Depends 헬퍼 — RAG 인스턴스 캐시 + 가드.

LRU 캐시 기반 lazy 빌더. Streamlit ``@st.cache_resource`` 와 동일 사상.

운영 단계에선 ``app.state`` + lifespan 으로 startup 시 미리 빌드 가능 (Step 6 배포).
시연/개발 단계에선 lazy 가 booting 빠름.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from infra.usage_tracker import SessionStats
from rag_core.agentic import AgenticRAG
from rag_core.calvin_builder import build_calvin_rag
from rag_core.guardrail import (
    GuardrailDirection,
    get_input_guardrail,
    get_output_guardrail,
)
from rag_core.hybrid import HybridRAG
from rag_core.mode_registry import ModeEntry, register


@lru_cache(maxsize=1)
def get_hybrid_rag() -> HybridRAG:
    """HybridRAG — 첫 호출 시 PDF 로드 + 인덱스 캐시 적용."""
    return build_calvin_rag()


@lru_cache(maxsize=1)
def get_agentic_rag() -> AgenticRAG:
    """AgenticRAG — Hybrid 컴포지션."""
    return AgenticRAG(hybrid_rag=get_hybrid_rag())


@lru_cache(maxsize=1)
def get_vision_rag() -> Any:
    """VisionRAG — 사용자 이미지 첨부 처리. lazy."""
    from rag_core.vision_rag import VisionRAG

    return VisionRAG()


@lru_cache(maxsize=1)
def get_kg_rag_or_none() -> Any | None:
    """KG RAG — Neo4j 가용 + 그래프 인덱싱 됐을 때만 인스턴스. 아니면 None."""
    try:
        from rag_core.kg.factory import get_kg_adapter
        from rag_core.kg.pipeline import KnowledgeGraphRAG
    except ImportError:
        return None

    try:
        adapter = get_kg_adapter()
        if not adapter.health_check():
            return None
        if adapter.stats().get("nodes", 0) == 0:
            return None
    except Exception:  # noqa: BLE001
        return None

    return KnowledgeGraphRAG(kg_adapter=adapter, hybrid_rag=get_hybrid_rag())


@lru_cache(maxsize=1)
def get_session_stats() -> SessionStats:
    """프로세스 단위 누적 통계 — Streamlit `session_state` 와 다른 위치이지만 같은 역할.

    운영 환경에선 다중 워커이면 외부 스토어(Redis 등)로 이전 필요 (Phase 3).
    """
    return SessionStats()


# ====================================================================
# 가드 Depends
# ====================================================================
def check_input_guard(text: str) -> tuple[bool, str | None, str | None]:
    """입력 가드 체크 — (allow, reason, sanitized) 반환."""
    decision = get_input_guardrail().check(text, GuardrailDirection.INPUT)
    return decision.allow, decision.reason, decision.sanitized


def check_output_guard(text: str) -> tuple[bool, str | None, str | None]:
    """출력 가드 체크 — (allow, reason, sanitized) 반환."""
    decision = get_output_guardrail().check(text, GuardrailDirection.OUTPUT)
    return decision.allow, decision.reason, decision.sanitized


def reset_dependency_cache() -> None:
    """테스트에서 RAG 인스턴스/통계 초기화."""
    get_hybrid_rag.cache_clear()
    get_agentic_rag.cache_clear()
    get_kg_rag_or_none.cache_clear()
    get_vision_rag.cache_clear()
    get_session_stats.cache_clear()


# ====================================================================
# Mode Registry 등록 — 새 모드 추가 = 여기에 register(...) 한 번
# ====================================================================
def _kg_health() -> tuple[bool, str | None]:
    """KG 가용성 — Neo4j 연결 + 그래프 인덱싱 상태."""
    if get_kg_rag_or_none() is None:
        return False, "Neo4j 미연결 또는 그래프 비어 있음"
    return True, None


def _kg_factory() -> Any:
    """KG 인스턴스 — health 통과 보장된 시점에 호출."""
    inst = get_kg_rag_or_none()
    if inst is None:
        # health() 와 호출 사이에 상태가 바뀐 경우만 도달
        raise RuntimeError("KG 어댑터 가용성 변경 — Neo4j 연결 확인")
    return inst


# factory/health 는 lambda 로 lazy lookup — monkeypatch 가능
# (테스트가 api.dependencies.get_hybrid_rag 등을 setattr 해도 registry 가 새 함수 호출)
register(
    ModeEntry(
        name="hybrid",
        label="Hybrid (BM25+Dense+RRF)",
        tracker_mode="Hybrid",
        factory=lambda: get_hybrid_rag(),
        sse_capable=True,
    )
)
register(
    ModeEntry(
        name="agentic",
        label="Agentic (create_agent)",
        tracker_mode="Agentic",
        factory=lambda: get_agentic_rag(),
        sse_capable=False,
    )
)
register(
    ModeEntry(
        name="kg",
        label="Knowledge Graph (Neo4j+Cypher)",
        tracker_mode="Knowledge Graph",
        factory=_kg_factory,
        sse_capable=False,
        health=_kg_health,
    )
)
register(
    ModeEntry(
        name="vision",
        label="Vision (이미지 첨부)",
        tracker_mode="Vision",
        factory=lambda: get_vision_rag(),
        sse_capable=False,
    )
)
