"""route_question 휴리스틱 단위 테스트."""

from __future__ import annotations

import pytest

from rag_core.router import route_question


@pytest.mark.parametrize(
    "question",
    [
        "어거스틴이 칼빈에게 미친 영향은?",
        "칼빈과 루터의 관계는 어떻게 되는가",
        "예정론과 자유의지 사이의 긴장",
        "어떤 인물이 칼빈 신학에 가장 중요한가",
        "예정론을 누가 처음 제기했는가",
    ],
)
def test_KG_힌트가_있으면_kg_모드(question: str):
    assert route_question(question) == "kg"


@pytest.mark.parametrize(
    "question",
    [
        "오늘 칼빈 관련 최신 논문이 있나",
        "최근 칼빈 신학 동향은 어떤가",
        "루터와 칼빈의 성례론을 비교해줘",
        "성령의 사역에 대한 두 진영의 차이",
        "위키에서 칼빈 신학을 검색해서 알려줘",
    ],
)
def test_Agentic_힌트가_있으면_agentic_모드(question: str):
    assert route_question(question) == "agentic"


@pytest.mark.parametrize(
    "question",
    [
        "예정론이란 무엇인가",
        "기독교 강요 1권의 핵심 주제",
        "이신칭의는 무엇이며 칼빈은 어떻게 설명하는가",
        "칼빈은 교회의 직제를 어떻게 보았는가",
    ],
)
def test_힌트가_없으면_hybrid_디폴트(question: str):
    assert route_question(question) == "hybrid"


def test_KG가_Agentic보다_우선():
    # KG 힌트 + Agentic 힌트 동시 — 우선순위 KG
    assert route_question("어거스틴과 칼빈의 관계를 비교해줘") == "kg"


def test_공백만_있으면_hybrid_폴백():
    assert route_question("   ") == "hybrid"
