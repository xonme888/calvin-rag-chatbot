"""프롬프트 템플릿 모듈 — strategy 가 generate stage 의 system 프롬프트로 주입.

규칙:
- 각 프롬프트는 ``{context}`` placeholder 를 반드시 포함한다.
- corpus 도메인별 가이드(예: 칼빈의 인용 분량 제한)는 corpus 어댑터의 SYSTEM_PROMPT 에.
  본 모듈은 *프롬프트 조립 헬퍼* 만 제공.
"""

from chatbot.infrastructure.prompts.hybrid_prompt import build_hybrid_prompt
from chatbot.infrastructure.prompts.vision_prompt import VISION_SYSTEM_PROMPT

__all__ = ["build_hybrid_prompt", "VISION_SYSTEM_PROMPT"]
