"""mode_dispatcher 단위 테스트 (Mock RAG, LLM/DB 호출 0회).

검증 포인트:
- 3 모드 동시 호출 시 입력 순서로 결과 반환
- ThreadPoolExecutor 병렬 실행 (직렬 시간 < 합산 시간)
- KG가 None이면 2 모드만 호출
- 한 모드 실패 시 다른 모드는 계속, error로 보고
- callbacks_per_mode가 모드별로 정확히 주입
"""

from __future__ import annotations

import time
from typing import Any

from rag_core.mode_dispatcher import ModeResult, compare_all_modes


class _MockRAG:
    """RAG 인터페이스만 충족하는 Mock — query() 만 구현."""

    def __init__(self, name: str, latency_sec: float = 0.05, fail: bool = False) -> None:
        self.name = name
        self.latency_sec = latency_sec
        self.fail = fail
        self.captured_callbacks: list[Any] | None = None

    def query(self, question: str, callbacks: list[Any] | None = None) -> dict[str, Any]:
        self.captured_callbacks = callbacks
        if self.fail:
            raise RuntimeError(f"{self.name} mocked failure")
        time.sleep(self.latency_sec)
        return {
            "final_answer": f"answer from {self.name}: {question}",
            "source_documents": [f"src-{self.name}-1"],
            "metadata": {"pattern": self.name, "elapsed_seconds": self.latency_sec},
        }


def test_compare_returns_three_results_in_input_order() -> None:
    h = _MockRAG("Hybrid")
    a = _MockRAG("Agentic")
    k = _MockRAG("Knowledge Graph")
    results = compare_all_modes("Q", hybrid=h, agentic=a, kg=k)

    assert len(results) == 3
    assert [r.mode_name for r in results] == ["Hybrid", "Agentic", "Knowledge Graph"]
    assert all(r.error is None for r in results)
    assert all(r.answer.startswith("answer from") for r in results)


def test_compare_runs_in_parallel() -> None:
    """3 모드 각각 0.3초 sleep — 병렬 시 ~0.3초, 직렬 시 ~0.9초."""
    h = _MockRAG("Hybrid", latency_sec=0.3)
    a = _MockRAG("Agentic", latency_sec=0.3)
    k = _MockRAG("Knowledge Graph", latency_sec=0.3)

    start = time.time()
    results = compare_all_modes("Q", hybrid=h, agentic=a, kg=k)
    elapsed = time.time() - start

    assert len(results) == 3
    # 병렬이면 0.3 ~ 0.5초. 직렬이면 0.9초+. 0.7초 미만이면 병렬 OK.
    assert elapsed < 0.7, f"병렬 실행이 의심됨: {elapsed:.2f}초 (직렬 시간 ~0.9초)"


def test_compare_skips_kg_when_none() -> None:
    h = _MockRAG("Hybrid")
    a = _MockRAG("Agentic")
    results = compare_all_modes("Q", hybrid=h, agentic=a, kg=None)

    assert len(results) == 2
    assert {r.mode_name for r in results} == {"Hybrid", "Agentic"}


def test_compare_skips_agentic_and_kg_when_none() -> None:
    """Hybrid만 있어도 동작 (graceful degradation)."""
    h = _MockRAG("Hybrid")
    results = compare_all_modes("Q", hybrid=h, agentic=None, kg=None)

    assert len(results) == 1
    assert results[0].mode_name == "Hybrid"


def test_compare_isolates_one_mode_failure() -> None:
    """Agentic 실패해도 Hybrid/KG 결과는 정상 반환."""
    h = _MockRAG("Hybrid")
    a = _MockRAG("Agentic", fail=True)
    k = _MockRAG("Knowledge Graph")

    results = compare_all_modes("Q", hybrid=h, agentic=a, kg=k)

    assert len(results) == 3
    by_name = {r.mode_name: r for r in results}
    assert by_name["Hybrid"].error is None
    assert by_name["Agentic"].error is not None
    assert "RuntimeError" in by_name["Agentic"].error
    assert by_name["Knowledge Graph"].error is None


def test_compare_injects_callbacks_per_mode() -> None:
    """callbacks_per_mode가 정확한 모드에만 전달된다."""
    h = _MockRAG("Hybrid")
    a = _MockRAG("Agentic")
    cb_h = ["hybrid_callback"]
    cb_a = ["agentic_callback"]
    compare_all_modes(
        "Q",
        hybrid=h,
        agentic=a,
        kg=None,
        callbacks_per_mode={"Hybrid": cb_h, "Agentic": cb_a},
    )

    assert h.captured_callbacks == cb_h
    assert a.captured_callbacks == cb_a


def test_mode_result_dataclass_defaults() -> None:
    r = ModeResult(mode_name="Test")
    assert r.answer == ""
    assert r.metadata == {}
    assert r.source_documents == []
    assert r.elapsed == 0.0
    assert r.error is None
