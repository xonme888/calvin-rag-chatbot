"""도구 Registry — 이름 → (BaseTool, ToolPolicy) 매핑.

새 도구 추가 절차:
1. BaseTool 인스턴스 생성 (langchain ``@tool`` 데코레이터 또는 직접)
2. ``register_tool(tool, ToolPolicy(...))`` 호출
3. agentic.py 가 ``enabled_tools(role)`` 로 자동 노출

allowlist 우선순위:
- 환경변수 ``ALLOWED_TOOLS=...`` 미설정 → 모든 등록 도구 활성
- 설정됨 → 해당 이름만 활성 (미등록 이름 무시)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

from langchain_core.tools import BaseTool

from rag_core.tools.policy import ToolPolicy, role_meets


@dataclass
class _ToolEntry:
    tool: BaseTool
    policy: ToolPolicy


_REGISTRY: dict[str, _ToolEntry] = {}


def register_tool(tool: BaseTool, policy: ToolPolicy | None = None) -> None:
    """도구 등록. 같은 name 으로 중복 호출 시 덮어쓴다 (테스트 편의).

    policy 미지정 시 도구 이름으로 default ToolPolicy 사용.
    """
    name = tool.name
    if policy is None:
        policy = ToolPolicy(name=name)
    elif policy.name != name:
        # name 불일치 시 도구 이름으로 정정
        policy = ToolPolicy(
            name=name,
            timeout_seconds=policy.timeout_seconds,
            per_call_token_cap=policy.per_call_token_cap,
            required_role=policy.required_role,
            description_safe=policy.description_safe,
        )
    _REGISTRY[name] = _ToolEntry(tool=tool, policy=policy)


def get_tool(name: str) -> _ToolEntry:
    """이름으로 조회. 없으면 KeyError."""
    return _REGISTRY[name]


def all_tools() -> list[BaseTool]:
    """등록된 모든 도구 (allowlist 미적용)."""
    return [e.tool for e in _REGISTRY.values()]


def _allowlist() -> set[str] | None:
    raw = os.getenv("ALLOWED_TOOLS", "").strip()
    if not raw:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


def enabled_tools(user_role: str = "free") -> list[BaseTool]:
    """allowlist + role 통과한 도구만.

    - allowlist 미설정 → 모든 등록 도구 후보
    - role 통과: ``role_meets(user_role, policy.required_role)``
    """
    allow = _allowlist()
    out: list[BaseTool] = []
    for entry in _REGISTRY.values():
        if allow is not None and entry.tool.name not in allow:
            continue
        if not role_meets(user_role, entry.policy.required_role):
            continue
        out.append(entry.tool)
    return out


def iter_entries() -> Iterator[tuple[BaseTool, ToolPolicy]]:
    for entry in _REGISTRY.values():
        yield entry.tool, entry.policy


def reset_registry() -> None:
    """테스트용 — 등록 초기화."""
    _REGISTRY.clear()
