"""칼빈 corpus 어댑터 테스트.

기존 `rag_core/calvin_builder.py:69-73` 의 캐시 키와 동일성을 검증 — 분해 작업이
인덱스 캐시를 무효화하지 않게.
"""

from __future__ import annotations

from chatbot.infrastructure.corpora.calvin_institutes import (
    CALVIN_CORPUS,
    CALVIN_INSTITUTES_SOURCE,
    SYSTEM_PROMPT,
    cache_key_parts,
)


def test_corpus_불변성():
    assert CALVIN_INSTITUTES_SOURCE.id == "institutes_v1"
    assert CALVIN_INSTITUTES_SOURCE.kind == "pdf"
    assert CALVIN_CORPUS.id == "calvin"
    assert CALVIN_CORPUS.sources == (CALVIN_INSTITUTES_SOURCE,)
    assert CALVIN_CORPUS.default_strategy == "hybrid"


def test_system_prompt_context_플레이스홀더_보존():
    assert "{context}" in SYSTEM_PROMPT, "generate stage 가 본문 주입 시 사용"


def test_cache_key_parts_레거시_동등성():
    """기존 build_calvin_rag 의 make_cache_key 인자 형식과 동일."""
    from infra.index_cache import make_cache_key

    expected = make_cache_key("calvin", "chunk500", "overlap50")
    assert make_cache_key(*cache_key_parts(500, 50)) == expected
    # 다른 파라미터에서도 prefix 가 'calvin' 으로 시작
    parts = cache_key_parts(800, 100)
    assert parts == ("calvin", "chunk800", "overlap100")
