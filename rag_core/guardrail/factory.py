"""가드 팩토리 — 환경변수 기반 인스턴스 빌더.

환경 토글:
- ``MODERATION_ENABLED=true`` (기본): OpenAI Moderation 추가 (API key 필요)
- ``MODERATION_ENABLED=false``: Length/Keyword 만 (테스트/로컬)

Phase 2에서 Kanana Safeguard 등을 추가하려면 이 팩토리만 수정.
RAG 본체 / 챗봇 코드는 변경 불필요 (Hexagonal 일관성).
"""

from __future__ import annotations

import os
from functools import lru_cache

from rag_core.guardrail.chain import CompositeGuardrail
from rag_core.guardrail.keyword_guard import KeywordGuard
from rag_core.guardrail.length_guard import LengthGuard
from rag_core.guardrail.port import GuardrailPort


def _moderation_enabled() -> bool:
    return os.getenv("MODERATION_ENABLED", "true").lower() in ("true", "1", "yes")


def _try_load_moderation() -> GuardrailPort | None:
    """OpenAI Moderation 어댑터를 시도. API key/패키지 없으면 None."""
    if not _moderation_enabled():
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-your"):
        return None
    try:
        from pydantic import SecretStr

        from rag_core.guardrail.openai_moderation_adapter import OpenAIModerationAdapter
    except ImportError:
        return None
    return OpenAIModerationAdapter(api_key=SecretStr(api_key))


@lru_cache(maxsize=1)
def get_input_guardrail() -> GuardrailPort:
    """입력 가드 — Length + (선택) OpenAI Moderation."""
    guards: list[GuardrailPort] = [LengthGuard(max_chars=2000)]
    moderation = _try_load_moderation()
    if moderation is not None:
        guards.append(moderation)
    return CompositeGuardrail(guards)


@lru_cache(maxsize=1)
def get_output_guardrail() -> GuardrailPort:
    """출력 가드 — Keyword(API key/시스템 프롬프트) + (선택) OpenAI Moderation."""
    guards: list[GuardrailPort] = [KeywordGuard()]
    moderation = _try_load_moderation()
    if moderation is not None:
        guards.append(moderation)
    return CompositeGuardrail(guards)


def reset_cache() -> None:
    """싱글톤 캐시 초기화 (테스트에서 환경 변경 시)."""
    get_input_guardrail.cache_clear()
    get_output_guardrail.cache_clear()
