"""OpenAIModerationAdapter 단위 테스트 — Mock OpenAI client (실 API 호출 0).

검증:
- Port 계약 만족
- flagged=False → allow
- flagged=True → block + 카테고리 추출
- 외부 API 예외 → fail-open (allow=True + guard_error metadata)
- 카테고리/스코어 dict 변환 (pydantic v2 model_dump 호환)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr

from rag_core.guardrail.openai_moderation_adapter import OpenAIModerationAdapter
from rag_core.guardrail.port import GuardrailDirection, GuardrailPort


def _moderation_response(
    flagged: bool,
    categories: dict[str, bool] | None = None,
    scores: dict[str, float] | None = None,
) -> Any:
    """OpenAI Moderation API 응답 형태의 Mock 객체."""
    cats_dict = categories or {}
    scores_dict = scores or {}

    cats_obj = SimpleNamespace(**cats_dict)
    cats_obj.model_dump = lambda: dict(cats_dict)

    scores_obj = SimpleNamespace(**scores_dict)
    scores_obj.model_dump = lambda: dict(scores_dict)

    result = SimpleNamespace(
        flagged=flagged,
        categories=cats_obj,
        category_scores=scores_obj,
    )
    return SimpleNamespace(results=[result])


def _adapter_with_mock_client(client: Any) -> OpenAIModerationAdapter:
    adapter = OpenAIModerationAdapter(api_key=SecretStr("sk-test"))
    adapter._client = client  # bypass lazy init
    return adapter


# ====================================================================
# Port 계약
# ====================================================================
def test_adapter_satisfies_port() -> None:
    adapter = OpenAIModerationAdapter(api_key=SecretStr("sk-test"))
    assert isinstance(adapter, GuardrailPort)


# ====================================================================
# 정상 응답
# ====================================================================
def test_passes_clean_input() -> None:
    class MockClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                return _moderation_response(flagged=False, scores={"hate": 0.001})

    adapter = _adapter_with_mock_client(MockClient())
    d = adapter.check("정상 신학 질문", GuardrailDirection.INPUT)
    assert d.allow
    assert d.metadata["flagged"] is False
    assert d.metadata["scores"]["hate"] == 0.001


def test_blocks_flagged_with_categories() -> None:
    class MockClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                return _moderation_response(
                    flagged=True,
                    categories={"hate": True, "violence": False, "sexual": False},
                )

    adapter = _adapter_with_mock_client(MockClient())
    d = adapter.check("악의적 텍스트", GuardrailDirection.INPUT)
    assert d.allow is False
    assert "hate" in (d.reason or "")
    assert d.metadata["flagged_categories"] == ["hate"]


def test_blocks_flagged_multiple_categories() -> None:
    class MockClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                return _moderation_response(
                    flagged=True,
                    categories={"hate": True, "violence": True},
                )

    adapter = _adapter_with_mock_client(MockClient())
    d = adapter.check("text", GuardrailDirection.OUTPUT)
    assert d.allow is False
    assert set(d.metadata["flagged_categories"]) == {"hate", "violence"}


# ====================================================================
# Fail-open (외부 API 예외)
# ====================================================================
def test_fail_open_on_api_error() -> None:
    """API 호출 실패 시 allow=True + guard_error metadata."""

    class FailingClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                raise RuntimeError("network down")

    adapter = _adapter_with_mock_client(FailingClient())
    d = adapter.check("text", GuardrailDirection.INPUT)
    assert d.allow is True  # fail-open
    assert "guard_error" in d.metadata
    assert "RuntimeError" in d.metadata["guard_error"]
    assert d.metadata["fail_mode"] == "open"


def test_fail_open_on_timeout() -> None:
    class TimeoutClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                raise TimeoutError("API timeout")

    adapter = _adapter_with_mock_client(TimeoutClient())
    d = adapter.check("text", GuardrailDirection.OUTPUT)
    assert d.allow
    assert "TimeoutError" in d.metadata["guard_error"]


# ====================================================================
# 카테고리/스코어 추출 (pydantic 호환)
# ====================================================================
def test_extracts_scores_for_audit_log() -> None:
    class MockClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                return _moderation_response(
                    flagged=False,
                    scores={"hate": 0.05, "violence": 0.02, "sexual": 0.001},
                )

    adapter = _adapter_with_mock_client(MockClient())
    d = adapter.check("text", GuardrailDirection.INPUT)
    assert d.metadata["scores"]["hate"] == 0.05
    assert d.metadata["scores"]["violence"] == 0.02
    assert d.metadata["direction"] == "input"


def test_handles_empty_categories_safely() -> None:
    """flagged=True 인데 categories 가 비어 있어도 예외 없음."""

    class MockClient:
        class moderations:
            @staticmethod
            def create(model: str, input: str) -> Any:
                return _moderation_response(flagged=True, categories={})

    adapter = _adapter_with_mock_client(MockClient())
    d = adapter.check("text", GuardrailDirection.INPUT)
    assert d.allow is False
    assert d.metadata["flagged_categories"] == []
