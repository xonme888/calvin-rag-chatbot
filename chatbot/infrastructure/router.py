"""StrategyRouter 구체 — 키워드 휴리스틱.

기존 ``rag_core/router.py`` 의 키워드 사전 (_KG_HINTS, _AGENTIC_HINTS) 와 의도가 같다.
다른 점:
- 입력이 후보 strategy *시퀀스* + standalone_question. registry 가 이미 supports() 로 1차 필터.
- 본 라우터는 *후보 안에서* 키워드 매칭으로 1개 선택.
- 후보가 1개면 그대로. 매칭 0건이면 첫 후보 (디폴트, 보통 hybrid).

LLM 라우터로 교체하려면 본 모듈에 ``LLMStrategyRouter`` 추가 + bootstrap 갈아끼움.
"""

from __future__ import annotations

from chatbot.application._protocols import StrategyRouter
from chatbot.domain.conversation import Turn
from chatbot.domain.strategy import RetrievalStrategy

# rag_core/router.py:_KG_HINTS / _AGENTIC_HINTS 와 동일 어휘. "관련" 은 일반어라 제외.
_KG_KEYWORDS: frozenset[str] = frozenset(
    {"관계", "영향", "사이", "어떤 인물", "누가", "그래프", "연결", "네트워크", "계보"}
)
_AGENTIC_KEYWORDS: frozenset[str] = frozenset(
    {"검색", "찾아", "조회"}
)
_RECENCY_KEYWORDS: frozenset[str] = frozenset({"최신", "오늘", "최근", "현재"})


class KeywordStrategyRouter:
    """후보 시퀀스 안에서 키워드 매칭으로 1개 선택.

    매칭 우선순위: KG > Agentic > 첫 후보 (보통 hybrid).
    Vision 은 후보에 들어왔다는 것 자체가 attachments 가 있다는 뜻이라 *우선* 선택.
    """

    name: str = "keyword_router"

    def choose(
        self,
        *,
        candidates: list[RetrievalStrategy],
        standalone_question: str,
        last_turn: Turn | None,
        previous_mode: str | None = None,
    ) -> RetrievalStrategy | None:
        if not candidates:
            return None
        by_name = {s.name: s for s in candidates}

        # vision 후보 — supports() 가 attachments 로 분기했으므로 1순위.
        if "vision" in by_name:
            return by_name["vision"]

        # KG 키워드 매칭
        if "kg" in by_name and _matches_any(standalone_question, _KG_KEYWORDS):
            return by_name["kg"]

        # 최신성 키워드만 있는 질문은 agentic 강제 라우팅하지 않는다.
        if "hybrid" in by_name and _matches_any(standalone_question, _RECENCY_KEYWORDS):
            return by_name["hybrid"]

        # Agentic 키워드 매칭
        if "agentic" in by_name and _matches_any(standalone_question, _AGENTIC_KEYWORDS):
            return by_name["agentic"]

        # retry 힌트(previous_mode)가 있으면 같은 모드를 우선 피한다.
        if previous_mode and previous_mode in by_name and len(candidates) > 1:
            for preferred in ("hybrid", "kg", "agentic", "vision"):
                if preferred != previous_mode and preferred in by_name:
                    return by_name[preferred]
            for cand in candidates:
                if cand.name != previous_mode:
                    return cand

        # 디폴트: hybrid 우선, 없으면 첫 후보
        return by_name.get("hybrid", candidates[0])


def _matches_any(text: str, keywords: frozenset[str]) -> bool:
    return any(kw in text for kw in keywords)


_: type[StrategyRouter] = KeywordStrategyRouter  # type: ignore[type-abstract]
