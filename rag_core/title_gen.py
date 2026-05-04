"""세션 자동 제목 — 답변 종료 후 cheap LLM 으로 짧은 제목 생성.

목적: deriveTitle (앞 30자 truncate) 의 한계 보강 — 사용자 인지 가시성.
호출 시점: 클라이언트가 첫 답변 종료 후 1회 (`POST /api/title`).

설계:
- structured output 으로 안전 폴백 — 실패 시 빈 문자열 반환
- 답변 본문 1000자만 사용 (토큰 절약)
- 길이 제한 6~30자, 끝 마침표/물음표 제거
"""

from __future__ import annotations

import logging
from typing import Final

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


_TITLE_SYSTEM: Final = """당신은 칼빈 신학 챗봇의 대화 세션에 짧은 제목을 붙이는 어시스턴트입니다.

규칙:
- 한국어, 6~30자, 명사형 또는 짧은 어구
- 마침표/물음표/느낌표 금지
- "에 대한 질문", "답변" 같은 군더더기 금지
- 핵심 개념·인물·교리 단어 위주
- 예: "예정론의 정의", "어거스틴과 칼빈의 영향", "성례론 비교"
"""


class _TitleSchema(BaseModel):
    title: str = Field(default="", description="6~30자 한국어 제목")


_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _TITLE_SYSTEM),
        (
            "human",
            "## 사용자 질문\n{question}\n\n## 답변\n{answer}\n\n"
            "위 대화를 한 줄 제목으로 요약하세요.",
        ),
    ]
)


def generate_title(
    question: str,
    answer: str,
    llm: BaseChatModel,
    *,
    max_len: int = 30,
) -> str:
    """답변 종료 후 짧은 세션 제목 생성. 실패 시 빈 문자열."""
    if not question.strip() or not answer.strip():
        return ""
    try:
        chain = _PROMPT | llm.with_structured_output(_TitleSchema)
        result = chain.invoke({"question": question, "answer": answer[:1000]})
        if not isinstance(result, _TitleSchema):
            return ""
        title = result.title.strip().rstrip(".?!")
        return title[:max_len]
    except Exception as e:
        logger.warning("자동 제목 생성 실패 — 빈 문자열 반환: %s", e)
        return ""
