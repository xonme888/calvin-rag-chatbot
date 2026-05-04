"""모드/도구별 회로 차단기 — 연속 실패 시 자동 차단 + 자동 회복.

상태:
- closed: 정상. 모든 호출 통과
- open: 차단. 호출 즉시 ``CircuitOpenError`` 발생, ``reset_timeout`` 후 half-open
- half-open: 시험 호출 1회 통과. 성공 시 closed, 실패 시 다시 open

설계:
- 글로벌 registry — name 으로 조회 (mode 이름 / 도구 이름)
- thread-safe 가 아님 (FastAPI async 단일 이벤트 루프 가정). 다중 워커 시
  Redis backed 으로 swap 가능 (인터페이스 유지)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """회로가 열려있어 호출 차단됨."""

    def __init__(self, name: str, opened_for_seconds: float) -> None:
        super().__init__(
            f"circuit '{name}' open ({opened_for_seconds:.0f}s 동안 차단)"
        )
        self.name = name


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    reset_timeout: float = 30.0  # 초

    state: State = State.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    opened_at: float | None = None

    def is_open(self) -> bool:
        """현재 차단 상태인가. open 이지만 reset_timeout 경과 시 half-open 으로 전이."""
        if self.state == State.OPEN:
            if self.opened_at is not None and time.time() - self.opened_at >= self.reset_timeout:
                self.state = State.HALF_OPEN
                return False
            return True
        return False

    def record_success(self) -> None:
        if self.state == State.HALF_OPEN:
            # 시험 호출 성공 → closed 복귀
            self.state = State.CLOSED
            self.failure_count = 0
            self.opened_at = None
        elif self.state == State.CLOSED:
            self.failure_count = 0
        self.success_count += 1

    def record_failure(self) -> None:
        self.last_failure_time = time.time()
        self.failure_count += 1
        if self.state == State.HALF_OPEN:
            # 시험 호출 실패 → 다시 open
            self.state = State.OPEN
            self.opened_at = time.time()
            return
        if self.failure_count >= self.failure_threshold:
            self.state = State.OPEN
            self.opened_at = time.time()

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """동기 함수 호출 — open 이면 즉시 차단, 아니면 호출 후 성공/실패 기록."""
        if self.is_open():
            raise CircuitOpenError(self.name, time.time() - (self.opened_at or 0))
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def status(self) -> dict[str, Any]:
        """현재 상태 dict — health/ready 또는 admin 디버그용."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "opened_at": self.opened_at,
        }


# ---- 글로벌 registry ----
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    reset_timeout: float = 30.0,
) -> CircuitBreaker:
    """이름으로 breaker 조회 — 없으면 생성. 첫 호출의 임계값을 보존."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
        )
    return _breakers[name]


def all_breakers() -> list[CircuitBreaker]:
    return list(_breakers.values())


def reset_all() -> None:
    """테스트용 — 모든 breaker 초기화."""
    _breakers.clear()
