"""InMemoryToolRegistry + ToolPolicy + role_meets 테스트.

PRD-001 의 ALLOWED_TOOLS / role 필터 동작을 보존했는지 검증.
"""

from __future__ import annotations

from typing import Any

import pytest

from chatbot.application.registries import (
    InMemoryCorpusRegistry,
    InMemoryStrategyRegistry,
    InMemoryToolRegistry,
    ToolPolicy,
    role_meets,
)
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.domain.tools import ToolResult, ToolSchema
from chatbot.infrastructure.corpora.calvin_institutes import CALVIN_CORPUS


# ============================================================
# role_meets
# ============================================================
def test_role_meets_위계():
    assert role_meets("admin", "free") is True
    assert role_meets("admin", "paid") is True
    assert role_meets("paid", "free") is True
    assert role_meets("free", "paid") is False
    assert role_meets("free", "admin") is False


def test_role_meets_미등록_role_안전():
    assert role_meets("unknown", "free") is True  # 둘 다 0 으로 fallback


# ============================================================
# Tool helpers
# ============================================================
class _Tool:
    def __init__(self, name: str, available: bool = True) -> None:
        self.schema = ToolSchema(name=name, description="t")
        self._available = available

    def is_available(self) -> tuple[bool, str | None]:
        return (self._available, None if self._available else "비활성")

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=str(arguments))


# ============================================================
# InMemoryToolRegistry
# ============================================================
def test_registry_등록_조회():
    reg = InMemoryToolRegistry()
    t = _Tool("echo")
    reg.register(t, ToolPolicy(name="echo", timeout_seconds=15.0))
    assert reg.get("echo") is t
    assert reg.policy("echo").timeout_seconds == 15.0


def test_registry_get_미존재_KeyError():
    reg = InMemoryToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_registry_policy_name_불일치_정정():
    """policy.name 이 tool 이름과 다르면 tool 이름으로 강제 정정 (PRD-001 동작)."""
    reg = InMemoryToolRegistry()
    reg.register(
        _Tool("echo"),
        ToolPolicy(name="wrong", timeout_seconds=5.0, required_role="paid"),
    )
    pol = reg.policy("echo")
    assert pol.name == "echo"
    assert pol.required_role == "paid"  # 다른 필드 보존


def test_registry_같은_이름_덮어쓰기():
    reg = InMemoryToolRegistry()
    reg.register(_Tool("echo"))
    new_tool = _Tool("echo")
    reg.register(new_tool)
    assert reg.get("echo") is new_tool


def test_registry_available_unavailable_제외():
    reg = InMemoryToolRegistry()
    reg.register(_Tool("ok"))
    reg.register(_Tool("bad", available=False))
    avail = reg.available()
    assert {t.schema.name for t in avail} == {"ok"}


def test_registry_enabled_for_role_필터():
    reg = InMemoryToolRegistry()
    reg.register(_Tool("free_tool"), ToolPolicy(name="free_tool", required_role="free"))
    reg.register(_Tool("paid_tool"), ToolPolicy(name="paid_tool", required_role="paid"))
    free_names = {t.schema.name for t in reg.enabled_for("free")}
    assert free_names == {"free_tool"}
    admin_names = {t.schema.name for t in reg.enabled_for("admin")}
    assert admin_names == {"free_tool", "paid_tool"}


def test_registry_enabled_for_allowlist_env(monkeypatch):
    reg = InMemoryToolRegistry()
    reg.register(_Tool("a"))
    reg.register(_Tool("b"))
    monkeypatch.setenv("ALLOWED_TOOLS", "a")
    names = {t.schema.name for t in reg.enabled_for("admin")}
    assert names == {"a"}


def test_registry_reset():
    reg = InMemoryToolRegistry()
    reg.register(_Tool("a"))
    reg.reset()
    assert reg.all() == []


# ============================================================
# InMemoryStrategyRegistry
# ============================================================
class _Strategy:
    def __init__(self, name: str, available: bool = True, supports_v: bool = True) -> None:
        self.name = name
        self.label = name.title()
        self._available = available
        self._supports = supports_v

    def is_available(self) -> tuple[bool, str | None]:
        return (self._available, None)

    def supports(self, request: RetrievalRequest) -> bool:
        return self._supports

    def run(self, request):  # type: ignore[no-untyped-def]
        ...


def test_strategy_registry_available_for_필터():
    sr = InMemoryStrategyRegistry()
    sr.register(_Strategy("hybrid"))
    sr.register(_Strategy("kg", available=False))
    sr.register(_Strategy("vision", supports_v=False))
    candidates = sr.available_for(RetrievalRequest(standalone_question="?"))
    names = {s.name for s in candidates}
    assert names == {"hybrid"}


def test_strategy_registry_get():
    sr = InMemoryStrategyRegistry()
    s = _Strategy("hybrid")
    sr.register(s)
    assert sr.get("hybrid") is s


# ============================================================
# InMemoryCorpusRegistry
# ============================================================
def test_corpus_registry_등록_조회():
    cr = InMemoryCorpusRegistry()
    cr.register(CALVIN_CORPUS)
    assert cr.get("calvin") is CALVIN_CORPUS
    assert cr.all() == [CALVIN_CORPUS]
