"""OpenAI Moderation API 어댑터.

omni-moderation-latest 사용 — 무료, 다국어(한국어 포함, 2024-09 +42% 개선),
~50~100ms 추가 latency.

설계:
- **Fail-open**: 외부 API 다운 시 서비스 죽이지 않게 ``allow=True`` 반환.
  단 ``metadata['guard_error']`` 에 사유 기록 → audit log 로 모니터링.
- 입력/출력 모두 같은 API 호출.
- categories: hate / hate/threatening / harassment / harassment/threatening /
  self-harm / sexual / sexual/minors / violence / violence/graphic 등.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from rag_core.guardrail.port import GuardrailDecision, GuardrailDirection


class OpenAIModerationAdapter:
    """OpenAI Moderation API 어댑터 — Hexagonal: Port 구현체."""

    name = "openai_moderation"

    def __init__(
        self,
        api_key: SecretStr,
        model: str = "omni-moderation-latest",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client: Any = None  # lazy

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ImportError(
                    "openai 패키지가 필요합니다. pyproject.toml 확인."
                ) from e
            self._client = OpenAI(api_key=self.api_key.get_secret_value())
        return self._client

    def check(self, text: str, direction: GuardrailDirection) -> GuardrailDecision:
        # 외부 API 호출은 try/except — fail-open 정책
        try:
            response = self._ensure_client().moderations.create(
                model=self.model, input=text
            )
            result = response.results[0]
        except Exception as e:  # noqa: BLE001
            # 가드 실패 = 서비스 죽이지 않음. 단 audit log 로 모니터링 가능
            return GuardrailDecision(
                allow=True,
                metadata={
                    "guard_error": f"{type(e).__name__}: {str(e)[:120]}",
                    "fail_mode": "open",
                },
            )

        flagged_categories = self._extract_flagged_categories(result)
        scores = self._extract_scores(result)

        if getattr(result, "flagged", False):
            return GuardrailDecision(
                allow=False,
                reason=(
                    "OpenAI Moderation 정책 위반 감지: "
                    f"{', '.join(flagged_categories) if flagged_categories else 'flagged'}"
                ),
                metadata={
                    "flagged_categories": flagged_categories,
                    "scores": scores,
                    "direction": direction.value,
                },
            )
        return GuardrailDecision(
            allow=True,
            metadata={
                "flagged": False,
                "scores": scores,
                "direction": direction.value,
            },
        )

    @staticmethod
    def _extract_flagged_categories(result: Any) -> list[str]:
        """OpenAI Moderation 결과에서 flagged=True 인 카테고리만 추출."""
        cats = getattr(result, "categories", None)
        if cats is None:
            return []
        # pydantic v2: model_dump / dict() 둘 다 시도
        if hasattr(cats, "model_dump"):
            cat_dict = cats.model_dump()
        elif hasattr(cats, "dict"):
            cat_dict = cats.dict()
        elif isinstance(cats, dict):
            cat_dict = cats
        else:
            return []
        return [k for k, v in cat_dict.items() if v]

    @staticmethod
    def _extract_scores(result: Any) -> dict[str, float]:
        """category_scores 추출 (audit log/임계 디버깅용)."""
        scores = getattr(result, "category_scores", None)
        if scores is None:
            return {}
        if hasattr(scores, "model_dump"):
            return scores.model_dump()
        if hasattr(scores, "dict"):
            return scores.dict()
        if isinstance(scores, dict):
            return dict(scores)
        return {}
