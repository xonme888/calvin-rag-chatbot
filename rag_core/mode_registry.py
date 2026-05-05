"""RAG 모드 Registry — 모드 정보를 한 곳에서 선언/조회한다.

목적: ``api/routes/chat.py`` 의 ``if req.mode == "hybrid": ... elif "agentic": ...``
분기를 제거하고, ``api/routes/health.py`` 의 모드 하드코딩 리스트도 제거한다.

새 모드 추가 비용:
1. RAG 클래스 작성 (기존 시그니처: ``query(question, callbacks=...) -> dict``)
2. ``register(ModeEntry(...))`` 한 번 호출

기존 모드별 차이 (예: hybrid 의 ``chat_history``/``dense_weight`` 인자) 는
``factory`` 가 만들어낸 인스턴스를 호출하는 측에서 capability 기반으로 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ModeEntry:
    """단일 모드 등록 엔트리."""

    name: str  # API 식별자 — "hybrid", "agentic", "kg" 등
    label: str  # UI 라벨 — "Hybrid (BM25+Dense+RRF)" 등
    tracker_mode: str  # UsageTracker 의 mode 이름 — "Hybrid" 등
    factory: Callable[[], Any]  # 싱글톤 인스턴스 반환 함수 (None 가능)
    sse_capable: bool = False  # SSE 토큰 스트리밍 지원 여부
    health: Callable[[], tuple[bool, Optional[str]]] = field(
        default_factory=lambda: lambda: (True, None)
    )
    """가용성 검사 — (available, reason). reason 은 비활성 시 사용자 안내."""


_REGISTRY: dict[str, ModeEntry] = {}


def register(entry: ModeEntry) -> None:
    """모드 등록. 중복 이름이면 덮어쓴다 (테스트 편의)."""
    _REGISTRY[entry.name] = entry


def get(name: str) -> ModeEntry:
    """이름으로 모드 조회. 없으면 KeyError."""
    return _REGISTRY[name]


def has(name: str) -> bool:
    return name in _REGISTRY


def all_entries() -> list[ModeEntry]:
    """등록된 모드 전체 — 등록 순서 보존."""
    return list(_REGISTRY.values())


def reset() -> None:
    """테스트용. 등록 초기화."""
    _REGISTRY.clear()
