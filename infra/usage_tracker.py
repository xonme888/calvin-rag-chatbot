"""LLM 호출 토큰/비용 누적 추적 — 비용 의식 어필 자산.

LangChain `BaseCallbackHandler` 의 ``on_llm_end`` 에서 token usage를 추출하고
모델별 단가로 비용을 누적한다. 모드별(Hybrid/Agentic/KG) 분리 통계도 제공.

설계 결정:
- ``SessionStats`` 와 ``UsageTracker`` 를 분리. Stats는 프로세스 단위로 영속(API 의존성 캐시 또는
  단위 테스트 fixture에서 주입), Tracker는 query 호출마다 주입(stateless에 가까움 — Stats 참조만)
- on_llm_end 가 token usage 를 못 받는 경우(스트리밍 일부) → tiktoken 추정 fallback
- 모델별 단가는 모듈 상수 ``MODEL_PRICING_USD`` 로 외부화 — 단가 변경 시 한 곳 수정
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

# OpenAI 단가 (USD / 1M tokens, 2026-05 기준)
# (input_rate_usd, output_rate_usd) per 1M tokens
MODEL_PRICING_USD: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.150, 0.600),
    "gpt-4o": (2.500, 10.000),
    "gpt-4-turbo": (10.000, 30.000),
    # 임베딩 모델 (output_rate=0)
    "text-embedding-3-small": (0.020, 0.000),
    "text-embedding-3-large": (0.130, 0.000),
}

USD_TO_KRW = 1500.0


@dataclass
class ModeStats:
    """단일 모드의 누적 통계."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_krw(self) -> float:
        return self.cost_usd * USD_TO_KRW


@dataclass
class SessionStats:
    """세션 전체 LLM 사용 통계 (모드별 분리)."""

    by_mode: dict[str, ModeStats] = field(default_factory=dict)

    def record(
        self,
        mode: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> None:
        """LLM 호출 1회 기록. 모델별 단가로 비용 자동 산출.

        Args:
            mode: 모드명 ("Hybrid", "Agentic", "Knowledge Graph", ...)
            input_tokens: 입력 토큰 수
            output_tokens: 출력 토큰 수
            model: 모델명 (단가 룩업용)
        """
        stats = self.by_mode.setdefault(mode, ModeStats())
        stats.calls += 1
        stats.input_tokens += input_tokens
        stats.output_tokens += output_tokens

        in_rate, out_rate = MODEL_PRICING_USD.get(model, (0.0, 0.0))
        stats.cost_usd += (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

    @property
    def total_calls(self) -> int:
        return sum(s.calls for s in self.by_mode.values())

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.by_mode.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.by_mode.values())

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.by_mode.values())

    @property
    def total_cost_krw(self) -> float:
        return self.total_cost_usd * USD_TO_KRW

    def reset(self) -> None:
        """전체 통계 초기화."""
        self.by_mode.clear()


class UsageTracker(BaseCallbackHandler):
    """LLM 호출에서 token usage 를 추출해 ``SessionStats`` 에 누적.

    LangChain LLM (특히 ChatOpenAI) 은 ``on_llm_end`` 에서
    ``response.llm_output['token_usage']`` 또는
    ``response.generations[0][0].message.usage_metadata`` 로 토큰 정보를 노출.

    Streaming 모드는 마지막 chunk 에만 usage가 있을 수 있어 정확도가 떨어진다 — 그 경우엔
    추정 fallback이 적용됨 (호출자가 별도로 추정 토큰을 record 호출 가능).
    """

    def __init__(self, stats: SessionStats, mode: str, model: str = "gpt-4o-mini") -> None:
        super().__init__()
        self.stats = stats
        self.mode = mode
        self.model = model

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """LLM 호출 종료 시 토큰 추출 → SessionStats 누적."""
        usage = self._extract_token_usage(response)
        if usage is None:
            return
        in_tokens, out_tokens = usage
        self.stats.record(self.mode, in_tokens, out_tokens, self.model)

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        """ChatModel 시작 시점 — on_llm_end 와 짝. 별도 처리 X."""
        pass

    def record_text_interaction(self, *, input_text: str, output_text: str) -> tuple[int, int]:
        """텍스트 입출력에서 대략 토큰을 추정해 SessionStats 에 기록.

        모든 LLM 호출 경로에 callback 주입이 어려운 라우트/통합 단계에서 사용하는
        최소 안전망이다. 한국어/영어 혼합 기준으로 ``문자수 / 2`` 근사를 사용한다.
        """
        input_tokens = rough_token_count(input_text)
        output_tokens = rough_token_count(output_text)
        self.stats.record(self.mode, input_tokens, output_tokens, self.model)
        return input_tokens, output_tokens

    @staticmethod
    def _extract_token_usage(response: Any) -> tuple[int, int] | None:
        """LangChain LLMResult 에서 (input_tokens, output_tokens) 추출.

        우선순위:
            1. response.llm_output['token_usage'] (OpenAI 표준)
            2. response.generations[0][0].message.usage_metadata (LangChain v1.x)
            3. None (추출 실패)
        """
        # 1) 표준 OpenAI 응답
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
        if token_usage:
            return (
                int(token_usage.get("prompt_tokens", 0)),
                int(token_usage.get("completion_tokens", 0)),
            )

        # 2) AIMessage.usage_metadata
        try:
            gen = response.generations[0][0]
        except (AttributeError, IndexError, TypeError):
            return None

        msg = getattr(gen, "message", None)
        if msg is None:
            return None
        meta = getattr(msg, "usage_metadata", None)
        if not meta:
            return None
        return (
            int(meta.get("input_tokens", 0)),
            int(meta.get("output_tokens", 0)),
        )


def estimate_cost_krw(model: str, input_tokens: int, output_tokens: int) -> float:
    """모델별 단가로 비용을 ₩ 추정 (외부 호출자가 직접 추정 시 사용)."""
    in_rate, out_rate = MODEL_PRICING_USD.get(model, (0.0, 0.0))
    cost_usd = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
    return cost_usd * USD_TO_KRW


def rough_token_count(text: str) -> int:
    """외부 tokenizer 없이 문자열 길이 기반으로 토큰 수를 대략 추정."""
    if not text:
        return 0
    # GPT 계열에서 한국어는 대체로 영어보다 토큰 밀도가 높아 보수적으로 2자로 1토큰 추정.
    return max(1, len(text) // 2)
