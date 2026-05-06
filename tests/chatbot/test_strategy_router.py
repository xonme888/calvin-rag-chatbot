"""KeywordStrategyRouter 테스트."""

from __future__ import annotations

from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.router import KeywordStrategyRouter


class _S:
    def __init__(self, name: str) -> None:
        self.name = name
        self.label = name.title()

    def is_available(self) -> tuple[bool, str | None]:
        return (True, None)

    def supports(self, request: RetrievalRequest) -> bool:
        return True

    def run(self, request: RetrievalRequest):  # type: ignore[no-untyped-def]
        return None


def test_router_vision_후보_1순위():
    router = KeywordStrategyRouter()
    hybrid, vision = _S("hybrid"), _S("vision")
    result = router.choose(
        candidates=[hybrid, vision],
        standalone_question="이 도판은 무엇인가?",
        last_turn=None,
    )
    assert result is vision


def test_router_kg_키워드_매칭():
    router = KeywordStrategyRouter()
    hybrid, kg = _S("hybrid"), _S("kg")
    for keyword in ["관계", "영향", "그래프", "계보"]:
        result = router.choose(
            candidates=[hybrid, kg],
            standalone_question=f"칼빈과 베자의 {keyword}는?",
            last_turn=None,
        )
        assert result is kg, f"keyword={keyword} 가 KG 매칭 안 됨"


def test_router_agentic_키워드_매칭():
    router = KeywordStrategyRouter()
    hybrid, agentic = _S("hybrid"), _S("agentic")
    for keyword in ["최신", "오늘", "비교", "검색"]:
        result = router.choose(
            candidates=[hybrid, agentic],
            standalone_question=f"{keyword} 정보",
            last_turn=None,
        )
        assert result is agentic


def test_router_default_hybrid():
    router = KeywordStrategyRouter()
    hybrid, kg = _S("hybrid"), _S("kg")
    result = router.choose(
        candidates=[hybrid, kg],
        standalone_question="예정론은 무엇인가?",
        last_turn=None,
    )
    assert result is hybrid


def test_router_빈_후보_None():
    assert (
        KeywordStrategyRouter().choose(candidates=[], standalone_question="?", last_turn=None)
        is None
    )


def test_router_hybrid_없음_첫_후보():
    """hybrid 가 없으면 첫 후보 fallback."""
    router = KeywordStrategyRouter()
    agentic, kg = _S("agentic"), _S("kg")
    result = router.choose(
        candidates=[agentic, kg],
        standalone_question="예정론은?",  # 키워드 매칭 없음
        last_turn=None,
    )
    assert result is agentic  # 첫 후보


def test_router_vision_kg_같이_있어도_vision_우선():
    """attachments 가 있으면 vision 후보가 들어올 텐데, KG 키워드가 있어도 vision 1순위."""
    router = KeywordStrategyRouter()
    kg, vision = _S("kg"), _S("vision")
    result = router.choose(
        candidates=[kg, vision],
        standalone_question="이 도판의 인물 관계는?",
        last_turn=None,
    )
    assert result is vision
