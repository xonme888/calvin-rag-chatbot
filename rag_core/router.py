"""사용자 질문 → 적합 RAG 모드 라우팅.

목적: 사용자에게 모드 선택 부담을 지우지 않으면서 Hybrid/Agentic/KG 의 강점을
자동 활용한다. 1차 구현은 키워드 휴리스틱 (LLM 호출 0). 추후 cheap LLM 분류로
업그레이드 가능 — 인터페이스 ``route_question(q) -> Mode`` 만 유지하면 된다.

분류 기준 (한국어 칼빈 신학 도메인):
- KG: "관계", "영향", "어떤 인물" 등 인물/개념 관계 질의
- Agentic: "최신", "오늘", "비교", "검색" 등 외부 도구가 필요한 질의
- Hybrid: 그 외 일반 본문 인용 질의 (디폴트)
"""

from __future__ import annotations

from typing import Literal

Mode = Literal["hybrid", "agentic", "kg"]


# 도메인 특화 키워드 — 칼빈/기독교 강요 챗봇용
_KG_HINTS: tuple[str, ...] = (
    "관계", "영향", "사이",
    "어떤 인물", "누가", "그래프", "연결",
    "네트워크", "계보",
)
# 주: "관련" 은 일반어로 빈번하게 등장 (예: "오늘 칼빈 관련 최신") — KG 힌트에서 제외

_AGENTIC_HINTS: tuple[str, ...] = (
    "최신", "오늘", "최근", "현재",
    "비교", "차이", "다른",  # "다른가/다른지/다른가요" 류 비교 의문문
    "검색", "찾아", "조회",
)


def route_question(question: str) -> Mode:
    """질문 한 줄을 보고 적합 모드를 결정한다.

    매칭 우선순위: KG > Agentic > Hybrid (디폴트).
    KG 가 가장 좁고, Hybrid 가 가장 넓다.
    """
    q = question.strip()
    if any(h in q for h in _KG_HINTS):
        return "kg"
    if any(h in q for h in _AGENTIC_HINTS):
        return "agentic"
    return "hybrid"
