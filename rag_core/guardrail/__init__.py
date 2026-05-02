"""LLM 가드레일 서브패키지.

Hexagonal Port/Adapter (KG/Retriever 와 같은 사상):
- ``port.GuardrailPort``: 도메인 인터페이스
- ``length_guard.LengthGuard``: 자체 (입력 길이)
- ``keyword_guard.KeywordGuard``: 자체 (출력 정규식 — API key/시스템 프롬프트)
- ``openai_moderation_adapter.OpenAIModerationAdapter``: OpenAI Moderation API 어댑터
- ``chain.CompositeGuardrail``: 체인 (첫 block 단락, sanitize 누적)
- ``factory.get_input_guardrail / get_output_guardrail``: 환경 기반 빌더

향후 Kanana Safeguard 등 어댑터를 추가해도 도메인/RAG/챗봇 코드 변경 0.
"""

from rag_core.guardrail.chain import CompositeGuardrail
from rag_core.guardrail.factory import (
    get_input_guardrail,
    get_output_guardrail,
    reset_cache,
)
from rag_core.guardrail.keyword_guard import KeywordGuard
from rag_core.guardrail.length_guard import LengthGuard
from rag_core.guardrail.port import (
    GuardrailDecision,
    GuardrailDirection,
    GuardrailPort,
)

__all__ = [
    "CompositeGuardrail",
    "GuardrailDecision",
    "GuardrailDirection",
    "GuardrailPort",
    "KeywordGuard",
    "LengthGuard",
    "get_input_guardrail",
    "get_output_guardrail",
    "reset_cache",
]
