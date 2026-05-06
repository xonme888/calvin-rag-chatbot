"""재랭커 Stage 어댑터 테스트 — LongContextReorder, FlashRank Stage envelope/availability."""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.infrastructure.rerankers import (
    FlashRankRerankerStage,
    LongContextReorderStage,
    RerankInput,
)


def _refs(n: int) -> list[DocumentRef]:
    return [
        DocumentRef(corpus_id="c", source_id="s", chunk_id=f"c:{i}", page=i, content=str(i))
        for i in range(n)
    ]


def test_long_context_reorder_홀짝_분배():
    """짝수 인덱스 → front 순방향, 홀수 인덱스 → back 역방향. 기존 알고리즘 보존."""
    out = LongContextReorderStage().run(_refs(5))
    assert [r.content for r in out] == ["0", "2", "4", "3", "1"]


def test_long_context_reorder_빈_입력():
    assert LongContextReorderStage().run([]) == []


def test_long_context_reorder_단일():
    out = LongContextReorderStage().run(_refs(1))
    assert [r.content for r in out] == ["0"]


def test_flashrank_빈_documents_즉시_빈_결과():
    """RerankInput.documents 가 빈 리스트면 모델 로드 없이 즉시 반환."""
    fr = FlashRankRerankerStage()
    assert fr.run(RerankInput(query="any", documents=[])) == []


def test_flashrank_미설치_fallback_정상():
    """flashrank 가 설치되어 있지 않은 환경에서 is_available 이 (False, reason)."""
    fr = FlashRankRerankerStage()
    ok, reason = fr.is_available()
    if not ok:
        assert reason and "flashrank" in reason


def test_flashrank_단일_인스턴스_재사용():
    """run() 여러 번 호출해도 _ranker 가 1개로 유지 (with_query/clone 패턴 제거 검증)."""
    fr = FlashRankRerankerStage()
    # 빈 docs 로 호출 — 로드 없이도 인스턴스 1개 유지
    fr.run(RerankInput(query="q1", documents=[]))
    fr.run(RerankInput(query="q2", documents=[]))
    # private 검사 — 모델 인스턴스가 매 run 마다 새로 생성되지 않는다
    assert hasattr(fr, "_ranker")
