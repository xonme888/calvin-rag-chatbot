"""답변 직후 후속 질문 3개를 생성하는 보조 헬퍼.

사용자가 직전 답변을 읽은 뒤 자연스럽게 이어갈 수 있는 한국어 후속 질문 3개를
짧은 LLM 호출로 만든다. 주 답변에 영향을 주지 않으며, 호출 실패 시 빈 리스트를
반환해 안전하게 폴백한다.

UX 목적: "다음에 뭘 물어야 할지 모르는" articulation barrier 제거 — 신학 도메인
친숙도가 낮은 사용자가 첫 답변에서 다음 단계로 진입하기 쉽게 만든다.
"""

from __future__ import annotations

import logging
from typing import Final

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


_FOLLOWUP_SYSTEM: Final = """당신은 칼빈 신학 학습 도우미의 후속 질문 추천기입니다.
사용자가 직전 답변을 읽은 직후 자연스럽게 이어 물어볼 수 있는 한국어 질문 3개를 생성하세요.

규칙:
- 직전 답변의 핵심 개념/인물/관계를 한 단계 깊이 파고드는 질문
- 한국어, 한 줄, 의문문 형식 (12~30자 권장)
- 너무 일반적이지 않고, 칼빈/기독교 강요 도메인 안에서 답할 수 있는 것
- 직전 질문과 너무 유사한 문장은 피한다
"""


class _Followups(BaseModel):
    """후속 질문 3개를 담는 structured output 스키마."""

    questions: list[str] = Field(
        default_factory=list,
        description="후속 질문 정확히 3개. 각 항목은 한국어 한 줄 의문문.",
    )


_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _FOLLOWUP_SYSTEM),
        (
            "human",
            "## 사용자 직전 질문\n{question}\n\n## 직전 답변\n{answer}\n\n"
            "위 답변을 읽은 사용자가 자연스럽게 이어 물어볼 후속 질문 3개를 출력하세요.",
        ),
    ]
)


def generate_followups(
    question: str,
    answer: str,
    llm: BaseChatModel,
    *,
    max_count: int = 3,
) -> list[str]:
    """답변 직후 후속 질문 N개를 생성한다 (기본 3).

    Args:
        question: 사용자의 직전 질문.
        answer: 챗봇의 직전 답변. 빈 문자열이면 곧바로 빈 리스트 반환.
        llm: 후속 질문 생성용 LLM (가급적 cheap 모델 권장).
        max_count: 반환 최대 개수.

    Returns:
        후속 질문 문자열 리스트 (실패 시 빈 리스트).
    """
    if not answer.strip():
        return []
    # answer 가 너무 길면 컨텍스트만 낭비 — 앞부분 2000자로 충분
    truncated_answer = answer[:2000]
    try:
        chain = _PROMPT | llm.with_structured_output(_Followups)
        result = chain.invoke({"question": question, "answer": truncated_answer})
        if not isinstance(result, _Followups):
            return []
        questions = [q.strip() for q in result.questions if q and q.strip()]
        return questions[:max_count]
    except Exception as e:
        # 주 답변에 영향 주지 않도록 안전 폴백
        logger.warning("follow-up 생성 실패 — 빈 리스트 반환: %s", e)
        return []
