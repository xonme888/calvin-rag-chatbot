"""사용자/IP 별 토큰 cap — 비용 폭주 방어.

설계:
- ``BudgetStore`` Protocol — 어댑터 swap 가능 (in-memory ↔ Redis ↔ Postgres)
- 키 형식: ``user_id`` (인증 후) 또는 ``ip:<addr>`` (인증 전)
- role 별 한도 (PRD-4): free/paid/admin
- 일별 자동 리셋 — store 가 TTL 24시간으로 보관

다중 워커 운영 시 Redis 필수 — in-memory 는 워커별 분리되어 cap 의미 상실.
환경변수 ``BUDGET_STORE=memory|redis`` 로 선택.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol


# role 별 일일 한도 (input + output 합산)
# 환경변수로 override 가능 — 기본값은 보수적
ROLE_DAILY_CAP: dict[str, int] = {
    "free": int(os.getenv("BUDGET_FREE_CAP", "10000")),
    "paid": int(os.getenv("BUDGET_PAID_CAP", "100000")),
    "admin": int(os.getenv("BUDGET_ADMIN_CAP", "10000000")),
}


@dataclass
class BudgetUsage:
    tokens: int
    cost_krw: float
    period_start: float  # epoch — 24h 마다 리셋

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.period_start >= 86400.0


class BudgetStore(Protocol):
    """키별 누적 사용량 저장소."""

    def get(self, key: str) -> BudgetUsage | None: ...
    def add(self, key: str, tokens: int, cost_krw: float) -> BudgetUsage: ...
    def reset(self, key: str) -> None: ...


class InMemoryBudgetStore:
    """단일 프로세스 메모리 — 다중 워커 시 Redis 로 swap 필요."""

    def __init__(self) -> None:
        self._data: dict[str, BudgetUsage] = {}

    def get(self, key: str) -> BudgetUsage | None:
        usage = self._data.get(key)
        if usage and usage.is_expired():
            del self._data[key]
            return None
        return usage

    def add(self, key: str, tokens: int, cost_krw: float) -> BudgetUsage:
        usage = self.get(key)
        if usage is None:
            usage = BudgetUsage(tokens=0, cost_krw=0.0, period_start=time.time())
            self._data[key] = usage
        usage.tokens += tokens
        usage.cost_krw += cost_krw
        return usage

    def reset(self, key: str) -> None:
        self._data.pop(key, None)


class RedisBudgetStore:
    """Redis backed — Upstash 또는 self-hosted. 실제 구현은 도입 시점에.

    환경변수: ``REDIS_URL``
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("REDIS_URL", "")
        self._fallback = InMemoryBudgetStore()
        # TODO: lazy import redis-py, connection pool

    def get(self, key: str) -> BudgetUsage | None:
        # TODO: HGETALL budget:{key} → BudgetUsage
        return self._fallback.get(key)

    def add(self, key: str, tokens: int, cost_krw: float) -> BudgetUsage:
        # TODO: pipelined HINCRBY + EXPIRE 86400
        return self._fallback.add(key, tokens, cost_krw)

    def reset(self, key: str) -> None:
        # TODO: DEL budget:{key}
        self._fallback.reset(key)


def _make_store_from_env() -> BudgetStore:
    name = os.getenv("BUDGET_STORE", "memory").lower()
    if name == "redis":
        return RedisBudgetStore()
    return InMemoryBudgetStore()


_store: BudgetStore = _make_store_from_env()


def configure_store(store: BudgetStore) -> None:
    """런타임 store 교체 (테스트/마이그레이션)."""
    global _store
    _store = store


def check_budget(key: str, role: str = "free") -> tuple[bool, BudgetUsage | None, int]:
    """현재 사용량이 role 한도 초과인가.

    Returns:
        (allowed, usage, cap) — allowed=False 시 호출측이 429 던짐
    """
    cap = ROLE_DAILY_CAP.get(role, ROLE_DAILY_CAP["free"])
    usage = _store.get(key)
    if usage is None:
        return True, None, cap
    return usage.tokens < cap, usage, cap


def record_usage(key: str, tokens_in: int, tokens_out: int, cost_krw: float) -> BudgetUsage:
    """LLM 호출 후 사용량 기록 — usage_tracker 와는 별도 (사용자 키 단위)."""
    return _store.add(key, tokens_in + tokens_out, cost_krw)


# 키 생성 헬퍼 — 인증 도입 전엔 ip 기반, 도입 후엔 user_id
def budget_key(user_id: str | None, ip: str) -> str:
    if user_id:
        return f"user:{user_id}"
    return f"ip:{ip}"
