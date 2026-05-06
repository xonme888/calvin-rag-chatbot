"""ToolRegistry / StrategyRegistry / CorpusRegistry 의 in-memory 구현.

각 registry 는 *런타임 카탈로그* 로, 등록된 도구·전략·corpus 를 이름으로 조회한다.
새 도구·전략·corpus 추가 = registry.register() 한 줄.

본 모듈은 도메인 Protocol 만 의존 — LangChain/외부 SDK import 0.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chatbot.domain.tools import Tool, ToolRegistry

if TYPE_CHECKING:  # 순환 import 방지 — Strategy/Corpus 는 domain 에서 import
    from chatbot.domain.corpus import Corpus
    from chatbot.domain.retrieval import RetrievalRequest
    from chatbot.domain.strategy import RetrievalStrategy


@dataclass(frozen=True)
class ToolPolicy:
    """도구별 운영 정책 — PRD-001 (rag_core/tools/policy.py) 의 어휘를 보존.

    InMemoryToolRegistry 가 본 정책을 함께 보유한다 — 도구 자체 (domain.Tool) 는 정책을
    모르고, *registry 가* 호출 직전 enforce 한다 (timeout/role/token cap).

    현 phase 의 한계: registry 는 정책을 *보유만* 한다. timeout/token_cap 의 실제 enforce 는
    PR 4 (오케스트레이터 wiring) 의 호출 wrapper 에서 추가된다. role 필터는 ``enabled_for``
    에 이미 enforce 되어 있다.
    """

    name: str
    timeout_seconds: float = 10.0
    per_call_token_cap: int = 4000
    required_role: str = "free"
    description_safe: bool = True


_ROLE_RANK: dict[str, int] = {"free": 0, "paid": 1, "admin": 2}


def role_meets(user_role: str, required: str) -> bool:
    """user_role 이 required 이상이면 True. PRD-001 동작과 동일."""
    return _ROLE_RANK.get(user_role, 0) >= _ROLE_RANK.get(required, 0)


@dataclass
class _ToolEntry:
    tool: Tool
    policy: ToolPolicy


class InMemoryToolRegistry:
    """domain.ToolRegistry 의 in-memory 구현 + ToolPolicy 메타 보유.

    PRD-001 의 ``ALLOWED_TOOLS`` 환경변수 allowlist + ``MCP_SERVERS`` 통합 시 합류 지점도
    여기 — list_tools() 가 외부 MCPClient 결과를 register 로 흡수하는 흐름.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _ToolEntry] = {}

    def register(self, tool: Tool, policy: ToolPolicy | None = None) -> None:
        """같은 name 으로 중복 호출 시 덮어쓴다 (테스트 편의).

        policy.name 과 tool.schema.name 이 다르면 tool 이름으로 강제 정정.
        """
        name = tool.schema.name
        if policy is None:
            policy = ToolPolicy(name=name)
        elif policy.name != name:
            policy = ToolPolicy(
                name=name,
                timeout_seconds=policy.timeout_seconds,
                per_call_token_cap=policy.per_call_token_cap,
                required_role=policy.required_role,
                description_safe=policy.description_safe,
            )
        self._entries[name] = _ToolEntry(tool=tool, policy=policy)

    def all(self) -> list[Tool]:
        return [e.tool for e in self._entries.values()]

    def get(self, name: str) -> Tool:
        return self._entries[name].tool

    def policy(self, name: str) -> ToolPolicy:
        """이름으로 정책 조회. 없으면 KeyError."""
        return self._entries[name].policy

    def available(self) -> list[Tool]:
        """is_available()[0] 이 True 인 도구만."""
        return [e.tool for e in self._entries.values() if e.tool.is_available()[0]]

    def enabled_for(self, user_role: str = "free") -> list[Tool]:
        """ALLOWED_TOOLS allowlist + role 필터를 통과한 *가용* 도구.

        PRD-001 의 enabled_tools(user_role) 와 동작 동일. 단, BaseTool 이 아닌 domain.Tool 반환.
        """
        allow = _allowlist_from_env()
        out: list[Tool] = []
        for entry in self._entries.values():
            if allow is not None and entry.tool.schema.name not in allow:
                continue
            if not role_meets(user_role, entry.policy.required_role):
                continue
            ok, _ = entry.tool.is_available()
            if not ok:
                continue
            out.append(entry.tool)
        return out

    def reset(self) -> None:
        """테스트용 — 등록 초기화."""
        self._entries.clear()


def _allowlist_from_env() -> set[str] | None:
    raw = os.getenv("ALLOWED_TOOLS", "").strip()
    if not raw:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


# Protocol 만족 검증 — 정적 type checker 가 InMemoryToolRegistry 를 ToolRegistry 로 인식.
_: type[ToolRegistry] = InMemoryToolRegistry  # type: ignore[type-abstract]


# ============================================================
# Strategy / Corpus registry
# ============================================================
@dataclass
class InMemoryStrategyRegistry:
    """domain.StrategyRegistry 의 in-memory 구현."""

    _strategies: dict[str, "RetrievalStrategy"] = field(default_factory=dict)

    def register(self, strategy: "RetrievalStrategy") -> None:
        self._strategies[strategy.name] = strategy

    def all(self) -> list["RetrievalStrategy"]:
        return list(self._strategies.values())

    def get(self, name: str) -> "RetrievalStrategy":
        return self._strategies[name]

    def available_for(self, request: "RetrievalRequest") -> list["RetrievalStrategy"]:
        return [s for s in self._strategies.values() if s.is_available()[0] and s.supports(request)]


@dataclass
class InMemoryCorpusRegistry:
    """corpus 등록·조회. 새 도메인(어거스틴 등) 추가 진입점."""

    _corpora: dict[str, "Corpus"] = field(default_factory=dict)

    def register(self, corpus: "Corpus") -> None:
        self._corpora[corpus.id] = corpus

    def all(self) -> list["Corpus"]:
        return list(self._corpora.values())

    def get(self, corpus_id: str) -> "Corpus":
        return self._corpora[corpus_id]
