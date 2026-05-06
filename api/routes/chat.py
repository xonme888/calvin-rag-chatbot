"""챗 라우트 — `/chat/sync` (동기 JSON), `/chat/stream` (SSE).

**DEPRECATED (PR 6 Phase B)**: 본 모듈은 *얇은 wrapper* 다. 모든 라우트가 ``/chat/v2`` /
``/chat/v2/stream`` (chatbot 패키지의 LangGraph orchestrator) 으로 위임된다.
``mode`` 인자는 무시되고 orchestrator 가 자동 라우팅한다.

신규 클라이언트는 ``/chat/v2`` 직접 사용 권장. 일정·이전 가이드:
``docs/guides/legacy-route-deprecation.md``.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request

from api.routes.chat_v2 import chat_v2 as _v2_sync
from api.routes.chat_v2 import chat_v2_stream as _v2_stream
from api.schemas import ChatRequest, ChatSyncResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sync", response_model=ChatSyncResponse)
async def chat_sync(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
) -> ChatSyncResponse:
    """``/chat/v2`` 로 위임. 외부 envelope 동일 — 기존 클라이언트 영향 0.

    rate limiter / token budget / 입력 가드 등 미들웨어는 chat_v2 가 동일하게 적용.
    """
    return await _v2_sync(request=request, req=req, background=background)


@router.post("/stream")
async def chat_stream(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
):  # type: ignore[no-untyped-def]
    """``/chat/v2/stream`` 으로 위임. SSE envelope 동일."""
    return await _v2_stream(request=request, req=req, background=background)
