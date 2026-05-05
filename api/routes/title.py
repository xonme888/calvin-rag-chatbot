"""세션 자동 제목 생성 — POST /title.

클라이언트가 첫 답변 종료 후 1회 호출. 비용 ~$0.0001/회 (gpt-4o-mini).
실패 시 빈 문자열 반환 — 클라이언트는 deriveTitle 폴백.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.dependencies import get_hybrid_rag
from api.middleware.rate_limiter import limiter
from rag_core.title_gen import generate_title

router = APIRouter(tags=["meta"])


class TitleRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)


class TitleResponse(BaseModel):
    title: str


@router.post("/title", response_model=TitleResponse)
@limiter.limit("30/minute;500/day")
async def generate_session_title(request: Request, req: TitleRequest) -> TitleResponse:
    """질문+답변 → 6~30자 한국어 제목. 실패 시 빈 문자열."""
    llm = get_hybrid_rag().llm
    # 동기 LLM 호출을 ThreadPool 로 비차단 변환
    title = await asyncio.to_thread(generate_title, req.question, req.answer, llm)
    return TitleResponse(title=title)
