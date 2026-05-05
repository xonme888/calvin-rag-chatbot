"""infra/usage_tracker 단위 테스트 (LLM 호출 0회).

LangChain LLMResult 의 두 가지 형식(llm_output dict vs AIMessage.usage_metadata)
모두 처리되는지 검증.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from infra.usage_tracker import (
    MODEL_PRICING_USD,
    USD_TO_KRW,
    SessionStats,
    UsageTracker,
    estimate_cost_krw,
)


# ====================================================================
# SessionStats / ModeStats
# ====================================================================
def test_session_stats_records_call_and_computes_cost() -> None:
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=1000, output_tokens=200, model="gpt-4o-mini")

    mode = stats.by_mode["Hybrid"]
    assert mode.calls == 1
    assert mode.input_tokens == 1000
    assert mode.output_tokens == 200

    # gpt-4o-mini: input $0.150, output $0.600 per 1M tokens
    expected_usd = (1000 * 0.150 + 200 * 0.600) / 1_000_000
    assert mode.cost_usd == pytest.approx(expected_usd, rel=1e-9)
    assert mode.cost_krw == pytest.approx(expected_usd * USD_TO_KRW, rel=1e-9)


def test_session_stats_separates_modes() -> None:
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=100, output_tokens=50, model="gpt-4o-mini")
    stats.record(mode="Agentic", input_tokens=200, output_tokens=80, model="gpt-4o-mini")
    stats.record(mode="Hybrid", input_tokens=150, output_tokens=70, model="gpt-4o-mini")

    assert stats.by_mode["Hybrid"].calls == 2
    assert stats.by_mode["Agentic"].calls == 1
    assert stats.total_calls == 3
    assert stats.total_input_tokens == 450
    assert stats.total_output_tokens == 200


def test_session_stats_reset() -> None:
    stats = SessionStats()
    stats.record("Hybrid", 100, 50, "gpt-4o-mini")
    assert stats.total_calls == 1
    stats.reset()
    assert stats.total_calls == 0
    assert stats.total_cost_usd == 0.0


def test_unknown_model_zero_cost() -> None:
    """단가 사전에 없는 모델은 비용 0 (call/token만 카운트)."""
    stats = SessionStats()
    stats.record(mode="Hybrid", input_tokens=1000, output_tokens=200, model="unknown-model")
    assert stats.by_mode["Hybrid"].calls == 1
    assert stats.by_mode["Hybrid"].cost_usd == 0.0
    assert stats.by_mode["Hybrid"].input_tokens == 1000


def test_estimate_cost_helper() -> None:
    krw = estimate_cost_krw("gpt-4o-mini", 1_000_000, 0)  # 입력 1M tokens = $0.15
    assert krw == pytest.approx(0.150 * USD_TO_KRW, rel=1e-9)


# ====================================================================
# UsageTracker._extract_token_usage — 두 형식 모두 처리
# ====================================================================
def _make_response_with_llm_output(prompt_tokens: int, completion_tokens: int) -> Any:
    """OpenAI 표준 형식의 Mock LLMResult."""
    return SimpleNamespace(
        llm_output={
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        },
        generations=[],
    )


def _make_response_with_usage_metadata(input_tokens: int, output_tokens: int) -> Any:
    """LangChain v1.x AIMessage.usage_metadata 형식."""
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens},
        content="...",
    )
    gen = SimpleNamespace(message=msg, text="...")
    return SimpleNamespace(llm_output=None, generations=[[gen]])


def test_extract_from_llm_output_token_usage() -> None:
    response = _make_response_with_llm_output(1234, 567)
    result = UsageTracker._extract_token_usage(response)
    assert result == (1234, 567)


def test_extract_from_aimessage_usage_metadata() -> None:
    response = _make_response_with_usage_metadata(100, 50)
    result = UsageTracker._extract_token_usage(response)
    assert result == (100, 50)


def test_extract_returns_none_when_no_usage() -> None:
    response = SimpleNamespace(llm_output={}, generations=[])
    assert UsageTracker._extract_token_usage(response) is None


def test_tracker_on_llm_end_accumulates_in_stats() -> None:
    stats = SessionStats()
    tracker = UsageTracker(stats, mode="Hybrid", model="gpt-4o-mini")

    response = _make_response_with_llm_output(prompt_tokens=2000, completion_tokens=300)
    tracker.on_llm_end(response)

    assert stats.total_calls == 1
    assert stats.by_mode["Hybrid"].input_tokens == 2000
    assert stats.by_mode["Hybrid"].output_tokens == 300
    expected_usd = (2000 * 0.150 + 300 * 0.600) / 1_000_000
    assert stats.total_cost_usd == pytest.approx(expected_usd, rel=1e-9)


def test_tracker_safe_on_missing_usage() -> None:
    """token_usage 없는 응답에도 예외 발생하지 않음."""
    stats = SessionStats()
    tracker = UsageTracker(stats, mode="Hybrid", model="gpt-4o-mini")

    response = SimpleNamespace(llm_output={}, generations=[])
    tracker.on_llm_end(response)  # raises가 없어야 함
    assert stats.total_calls == 0  # 누적 안 됨


# ====================================================================
# 단가 사전 sanity
# ====================================================================
def test_pricing_dict_includes_default_model() -> None:
    """현재 챗봇 기본 모델(gpt-4o-mini)이 단가 사전에 등록되어 있다."""
    assert "gpt-4o-mini" in MODEL_PRICING_USD
    in_rate, out_rate = MODEL_PRICING_USD["gpt-4o-mini"]
    assert in_rate > 0 and out_rate > 0
    assert out_rate > in_rate, "출력이 입력보다 비싸야 (LLM 단가 일반 패턴)"
