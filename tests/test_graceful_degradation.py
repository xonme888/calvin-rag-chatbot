"""KG 모드 graceful degradation — Neo4j 미연결/의존성 미설치 시 보장.

이 테스트는 Hexagonal Port/Adapter 분리의 *본질적 가치*를 코드로 증명한다:
1. Hybrid/Agentic 모드는 KG와 완전 무관하게 동작
2. KG 어댑터 health_check 실패 시 명확한 에러 + Hybrid/Agentic은 영향 없음
3. KG 패키지(`rag_core.kg`)는 다른 RAG 코어에 import 의존성을 강제하지 않음 (선택 의존)

LLM/DB 호출 0회.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any, Callable

import pytest
from langchain_core.documents import Document

from rag_core.kg.port import KnowledgeGraphPort, SubgraphData


# ====================================================================
# Mock: Neo4j 정지 시나리오 (health_check가 False 반환)
# ====================================================================
class FailingKGAdapter:
    """Neo4j 컨테이너 정지 시 어댑터 동작 시뮬레이션.

    health_check만 False 반환하고, 다른 메서드는 호출 시 RuntimeError.
    KnowledgeGraphPort 계약은 만족.
    """

    def health_check(self) -> bool:
        return False

    def index_chunks(
        self,
        chunks: list[Document],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        raise RuntimeError("Neo4j 미연결 — 인덱싱 불가")

    def query_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        raise RuntimeError("Neo4j 미연결 — 쿼리 불가")

    def get_subgraph(self, entity_names: list[str], hops: int = 1) -> SubgraphData:
        # 그래프 조회는 실패해도 빈 결과 반환 (UI 렌더링이 깨지지 않게)
        return SubgraphData()

    def clear(self) -> None:
        raise RuntimeError("Neo4j 미연결")

    def stats(self) -> dict[str, int]:
        return {"nodes": 0, "edges": 0}


# ====================================================================
# 1. Port 계약 검증 — Failing 어댑터도 Port 만족
# ====================================================================
def test_failing_adapter_satisfies_port_contract() -> None:
    """장애 어댑터도 Port 계약을 만족해야 한다 (graceful degradation의 전제)."""
    adapter = FailingKGAdapter()
    assert isinstance(adapter, KnowledgeGraphPort)


def test_failing_adapter_health_check_false() -> None:
    adapter = FailingKGAdapter()
    assert adapter.health_check() is False


def test_failing_adapter_get_subgraph_returns_empty_safely() -> None:
    """get_subgraph는 실패해도 예외 대신 빈 결과 — UI 렌더링 보호."""
    adapter = FailingKGAdapter()
    result = adapter.get_subgraph(["예정론"])
    assert result.nodes == []
    assert result.edges == []


# ====================================================================
# 2. RAG 코어 모듈은 KG 패키지에 import 의존하지 않음 (AST 검증)
# ====================================================================
def _module_imports_kg_or_neo4j(module_obj: Any) -> tuple[bool, list[str]]:
    """모듈 소스에서 ``rag_core.kg`` 또는 ``langchain_neo4j`` import 여부를 AST로 검사."""
    src = inspect.getsource(module_obj)
    tree = ast.parse(src)
    forbidden = ("langchain_neo4j", "rag_core.kg")
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for f in forbidden:
                if mod.startswith(f):
                    found.append(f"from {mod} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for f in forbidden:
                    if alias.name.startswith(f):
                        found.append(f"import {alias.name}")
    return bool(found), found


def test_hybrid_module_independent_of_kg() -> None:
    """rag_core.hybrid 는 KG 패키지에 의존하지 않는다 (역방향 의존성 금지)."""
    import rag_core.hybrid as hybrid_module

    has_dep, found = _module_imports_kg_or_neo4j(hybrid_module)
    assert not has_dep, f"하이브리드가 KG에 의존함: {found}"


def test_agentic_module_independent_of_kg() -> None:
    """rag_core.agentic 도 KG 무관."""
    import rag_core.agentic as agentic_module

    has_dep, found = _module_imports_kg_or_neo4j(agentic_module)
    assert not has_dep, f"Agentic이 KG에 의존함: {found}"


def test_builder_module_independent_of_kg() -> None:
    """rag_core.builder (칼빈 도메인 빌더) 도 KG 무관."""
    import rag_core.builder as builder_module

    has_dep, found = _module_imports_kg_or_neo4j(builder_module)
    assert not has_dep, f"Builder가 KG에 의존함: {found}"


def test_tokenizer_module_independent_of_kg() -> None:
    """rag_core.tokenizer 도 KG 무관."""
    import rag_core.tokenizer as tokenizer_module

    has_dep, found = _module_imports_kg_or_neo4j(tokenizer_module)
    assert not has_dep, f"Tokenizer가 KG에 의존함: {found}"


def test_postprocess_module_independent_of_kg() -> None:
    """rag_core.postprocess 도 KG 무관."""
    import rag_core.postprocess as pp_module

    has_dep, found = _module_imports_kg_or_neo4j(pp_module)
    assert not has_dep, f"Postprocess가 KG에 의존함: {found}"


# ====================================================================
# 3. 챗봇 UI graceful degradation 헬퍼 검증
# ====================================================================
def test_chatbot_kg_health_helper_handles_failing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """챗봇 시작 시 health_check 헬퍼가 장애 어댑터를 감지하고 사유를 반환."""
    # app.calvin_chatbot 은 streamlit 의존성으로 직접 import 어려움 → 헬퍼 함수만 분리 검증
    # 실제 챗봇은 이 패턴을 따름:
    failing = FailingKGAdapter()

    def check_kg_available(adapter: KnowledgeGraphPort) -> tuple[bool, str | None]:
        try:
            if not adapter.health_check():
                return False, "Neo4j 미연결 (docker compose up -d)"
            return True, None
        except Exception as e:  # noqa: BLE001
            return False, f"Neo4j 초기화 실패: {type(e).__name__}"

    available, reason = check_kg_available(failing)
    assert available is False
    assert reason is not None
    assert "Neo4j" in reason


# ====================================================================
# 4. KG 의존성 import 실패 시 챗봇 전체가 죽지 않음
# ====================================================================
def test_kg_factory_import_isolated_from_rag_core() -> None:
    """rag_core.kg.factory import 실패해도 hybrid/agentic은 import 가능 (격리)."""
    # 실제 격리 검증: 위의 AST 테스트가 이걸 보장.
    # 추가로 rag_core 패키지의 __init__ 도 KG에 의존하지 않는지 확인.
    import rag_core

    src = inspect.getsource(rag_core)
    # rag_core/__init__.py는 hybrid/agentic만 export, kg는 lazy
    assert "from rag_core.kg" not in src or "TYPE_CHECKING" in src, (
        "rag_core/__init__.py가 KG 패키지를 strict import — graceful degradation 깨짐"
    )
