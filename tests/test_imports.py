"""모든 도메인 모듈 strict import 회귀 테스트.

배경: Phase 0 rename에서 ``rag_core/kg/pipeline.py`` 의 lazy import 한 줄이
누락된 채 commit 되었는데, 다른 어떤 테스트도 ``pipeline`` 을 직접 import 하지 않아
검증되지 않았다. Streamlit 실행 시점에야 ``ModuleNotFoundError`` 가 발생.

대책: 이 테스트가 모든 도메인 모듈을 *명시적으로* import 한다. 누군가 모듈을
rename 하거나 import 경로를 바꿔도 이 테스트가 즉시 잡는다.

원칙: lazy import 가 있는 모듈도 반드시 strict import 검증 대상 추가.
"""

from __future__ import annotations

import importlib

import pytest

# 도메인 모듈 — 모두 외부 LLM/DB 호출 없이 import 가능해야 한다.
_MODULES_TO_IMPORT: tuple[str, ...] = (
    # rag_core 도메인
    "rag_core",
    "rag_core.hybrid",
    "rag_core.agentic",
    "rag_core.calvin_builder",
    "rag_core.tokenizer",
    "rag_core.reranker",
    "rag_core.retriever",
    "rag_core.mode_dispatcher",
    # rag_core.guardrail 서브패키지
    "rag_core.guardrail",
    "rag_core.guardrail.port",
    "rag_core.guardrail.length_guard",
    "rag_core.guardrail.keyword_guard",
    "rag_core.guardrail.openai_moderation_adapter",
    "rag_core.guardrail.chain",
    "rag_core.guardrail.factory",
    # rag_core.kg 서브패키지
    "rag_core.kg",
    "rag_core.kg.port",
    "rag_core.kg.config",
    "rag_core.kg.factory",
    "rag_core.kg.neo4j_adapter",
    "rag_core.kg.section_filter",
    "rag_core.kg.entity_normalizer",
    "rag_core.kg.graph_renderer",
    "rag_core.kg.pipeline",
    # infra
    "infra",
    "infra.env_loader",
    "infra.document_loader",
    "infra.index_cache",
    "infra.usage_tracker",
)


@pytest.mark.parametrize("module_name", _MODULES_TO_IMPORT)
def test_module_imports_without_error(module_name: str) -> None:
    """모듈 strict import 검증 — rename/이동 시 회귀 차단."""
    importlib.import_module(module_name)


def test_pipeline_lazy_imports_resolve() -> None:
    """KnowledgeGraphRAG가 의존하는 lazy import도 모듈 로드 시점에 검증된다."""
    from rag_core.kg import pipeline

    # pipeline 모듈 안에서 import 한 항목들이 정상 노출되는지 확인
    assert hasattr(pipeline, "KnowledgeGraphRAG")
    assert hasattr(pipeline, "filter_chunks_by_sections")
    assert hasattr(pipeline, "DEFAULT_CALVIN_SECTIONS")
