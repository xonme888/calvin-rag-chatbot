"""3 모드 동시 호출 dispatcher.

같은 질문을 Hybrid / Agentic / KG 에 병렬로 투입해 답변/메타/그래프를 나란히 비교.
ThreadPoolExecutor 로 응답 시간 = max(3 모드) 가 되도록 한다.

설계 결정:
- 모드별 RAG 인스턴스는 외부에서 주입 (테스트 용이성 + caching 위치 분리)
- KG는 ``None``이면 자동 생략 — graceful degradation
- 한 모드 실패 시 다른 모드는 계속 — `ModeResult.error`로 보고
- LangChain callbacks는 모드별 다르게 주입 가능 (UsageTracker 등)
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# 모드 표시 순서 (UI column 정렬용)
_MODE_ORDER: dict[str, int] = {
    "Hybrid": 0,
    "Agentic": 1,
    "Knowledge Graph": 2,
}


@dataclass
class ModeResult:
    """단일 모드 호출 결과."""

    mode_name: str
    answer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source_documents: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    error: str | None = None


def compare_all_modes(
    question: str,
    hybrid: Any,
    agentic: Any | None = None,
    kg: Any | None = None,
    callbacks_per_mode: dict[str, list[Any]] | None = None,
    timeout: float = 60.0,
) -> list[ModeResult]:
    """3 모드 동시 호출. 입력 순서(Hybrid → Agentic → KG)로 결과 반환.

    Args:
        question: 사용자 질문
        hybrid: HybridRAG 인스턴스. 필수.
        agentic: AgenticRAG 인스턴스. None이면 호출 안 함.
        kg: KnowledgeGraphRAG 인스턴스. None이면 호출 안 함.
        callbacks_per_mode: ``{"Hybrid": [tracker], "Agentic": [...], ...}``. 없으면 callbacks 미주입.
        timeout: 모드별 최대 대기 시간 (초). 초과 시 error로 보고.

    Returns:
        ``ModeResult`` 리스트. 한 모드 실패해도 다른 모드는 계속 — error 필드로 보고.
    """
    callbacks_per_mode = callbacks_per_mode or {}

    targets: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("Hybrid", lambda: hybrid.query(question, callbacks=callbacks_per_mode.get("Hybrid"))),
    ]
    if agentic is not None:
        targets.append(
            (
                "Agentic",
                lambda: agentic.query(question, callbacks=callbacks_per_mode.get("Agentic")),
            )
        )
    if kg is not None:
        targets.append(
            (
                "Knowledge Graph",
                lambda: kg.query(question, callbacks=callbacks_per_mode.get("Knowledge Graph")),
            )
        )

    results: list[ModeResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as exe:
        future_to_name: dict[concurrent.futures.Future, str] = {}
        starts: dict[str, float] = {}
        for name, fn in targets:
            starts[name] = time.time()
            future_to_name[exe.submit(fn)] = name

        for future in concurrent.futures.as_completed(future_to_name, timeout=timeout):
            name = future_to_name[future]
            elapsed = time.time() - starts[name]
            try:
                raw = future.result()
                results.append(
                    ModeResult(
                        mode_name=name,
                        answer=raw.get("final_answer", ""),
                        metadata=raw.get("metadata", {}),
                        source_documents=raw.get("source_documents", []),
                        elapsed=raw.get("metadata", {}).get("elapsed_seconds", elapsed),
                    )
                )
            except Exception as e:  # noqa: BLE001
                results.append(
                    ModeResult(
                        mode_name=name,
                        elapsed=elapsed,
                        error=f"{type(e).__name__}: {e}",
                    )
                )

    # 입력 순서로 정렬 (Hybrid → Agentic → KG)
    results.sort(key=lambda r: _MODE_ORDER.get(r.mode_name, 99))
    return results
