"""의도(Intent) — 노드 분기의 원천.

오케스트레이터의 첫 노드 ``classify_intent`` 가 결정한다. 의도는 *다음에 어떤 작업을
해야 하는가* 의 결정이므로, 의도가 추가되면 노드 분기도 추가된다 (e.g. CLARIFICATION).
"""

from __future__ import annotations

from enum import StrEnum


class Intent(StrEnum):
    """대화 턴의 의도 분류.

    분류 우선순위(앞이 우선):
    1. SMALLTALK — 도구·검색 모두 불필요
    2. META_REFERENCE — 직전 턴의 메타(서브그래프/인용) 재사용
    3. META_RECAP — 직전 N개 턴의 요약·정리. RAG 우회.
    4. FOLLOWUP — 대명사·생략을 가진 후속 질문. rewrite 필요.
    5. NEW_QUESTION — 그 외 (디폴트)
    """

    NEW_QUESTION = "new_question"
    FOLLOWUP = "followup"
    META_RECAP = "meta_recap"
    META_REFERENCE = "meta_reference"
    SMALLTALK = "smalltalk"

    @property
    def needs_retrieval(self) -> bool:
        """검색·도구 호출 단계로 진행할지 여부. 노드 분기에 사용."""
        return self in (Intent.NEW_QUESTION, Intent.FOLLOWUP)

    @property
    def needs_rewrite(self) -> bool:
        """질문을 standalone 으로 재구성해야 할지 여부."""
        return self == Intent.FOLLOWUP
