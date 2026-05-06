"""``/chat/v2`` (sync) + ``/chat/v2/stream`` (SSE) — 대화 우선 오케스트레이터 라우트.

기존 ``/chat/sync`` / ``/chat/stream`` 과 *공존* — 본 라우트는 chatbot 패키지의 LangGraph
orchestrator 를 사용. 응답 envelope 은 기존과 호환되되 ``intent`` / ``standalone_question`` /
``selected_strategy`` 메타가 추가된다.

envelope 변환 헬퍼는 ``_chat_v2_envelope`` 모듈에 분리 — 본 파일은 *라우팅 + 트레이스* 에 집중.
"""

from __future__ import annotations

import asyncio
import json
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.dependencies import get_hybrid_rag, get_session_stats
from api.middleware.rate_limiter import limiter
from api.middleware.token_budget import check_token_budget
from api.routes._chat_v2_envelope import to_response, to_state
from api.schemas import ChatRequest, ChatSyncResponse
from chatbot.application.bootstrap import (
    build_default_orchestrator,
    build_persistence_from_env,
)
from infra.observability import (
    new_trace_id,
    set_current_trace_id,
    trace_event,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from chatbot.domain.persistence import ConversationStore, UserIdentifier

router = APIRouter(prefix="/chat", tags=["chat-v2"])


@lru_cache(maxsize=1)
def _orchestrator() -> CompiledStateGraph:
    """첫 호출 시 HybridRAG 부트스트랩 + LLM 의존성 조립 → orchestrator 반환."""
    hybrid_rag = get_hybrid_rag()
    return build_default_orchestrator(hybrid_rag=hybrid_rag, llm=hybrid_rag.llm)


@lru_cache(maxsize=1)
def _persistence() -> tuple[ConversationStore | None, UserIdentifier]:
    """첫 호출 시 환경변수 → (Supabase ConversationStore, UserIdentifier).

    AUTH_ENABLED=false 또는 SUPABASE_* 미설정 시 (None, AnonymousUserIdentifier).
    """
    return build_persistence_from_env()


def reset_orchestrator() -> None:
    """테스트용 — 캐시 초기화."""
    _orchestrator.cache_clear()
    _persistence.cache_clear()


@router.post("/v2", response_model=ChatSyncResponse)
@limiter.limit("10/minute;200/day")
async def chat_v2(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
) -> ChatSyncResponse:
    """대화 우선 오케스트레이터 라우트.

    - chat_history 가 *모든 모드* 에 일관되게 적용 (기존 /chat/sync 의 분기 제거).
    - Intent / standalone_question / selected_strategy 가 metadata 에 노출.
    - 첨부 자동 라우팅 (vision strategy.supports() 가 분기).
    """
    stats = get_session_stats()
    check_token_budget(stats)

    trace_id = new_trace_id()
    set_current_trace_id(trace_id)
    store, identifier = _persistence()
    user_id = identifier.current_user_id(request)
    trace_event(
        "request.start",
        endpoint="/chat/v2",
        question_preview=req.question[:120],
        client_mode=req.mode,
        attachment_count=len(req.attachments),
        user_id=user_id,
        conversation_id=req.conversation_id,
    )

    state = to_state(req=req, trace_id=trace_id, store=store, user_id=user_id)
    start = time.time()
    try:
        result = _orchestrator().invoke(state)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"오케스트레이터 실행 실패: {type(e).__name__}"
        ) from e
    elapsed = time.time() - start

    # 응답 후 background save — 응답 latency 영향 0 (PRD-002 §성공지표 ≤ 100ms 가정).
    if store is not None and user_id:
        background.add_task(_save_conversation_safe, store, result, user_id)
    return to_response(result=result, elapsed=elapsed, trace_id=trace_id)


def _save_conversation_safe(
    store: ConversationStore,
    result: Any,
    user_id: str,
) -> None:
    """orchestrator 결과의 conversation 을 영속화 — 실패 시 trace 만, 부팅 실패 X."""
    import logging as _lg

    try:
        conv = (
            result.conversation if hasattr(result, "conversation") else result.get("conversation")
        )
        if conv is not None:
            store.save(conv, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        _lg.getLogger(__name__).warning("conversation save 실패: %s", e)


# ============================================================
# /chat/v2/stream — SSE (Vercel AI SDK Stream Protocol v1)
# ============================================================
@router.post("/v2/stream")
@limiter.limit("10/minute;200/day")
async def chat_v2_stream(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
) -> EventSourceResponse:
    """orchestrator 호출 후 답변을 청크 단위로 SSE 송출 + meta envelope 1회 emit.

    토큰 단위 스트리밍은 LLM 의 stream_query 가 필요 — 본 라우트는 *답변 청크 분할 SSE*
    (기존 ``_stream_sync_replay`` 와 동일 패턴). 메타는 ``/chat/v2`` 와 동일 envelope.
    """
    trace_id = new_trace_id()
    set_current_trace_id(trace_id)
    store, identifier = _persistence()
    user_id = identifier.current_user_id(request)
    trace_event(
        "request.start",
        endpoint="/chat/v2/stream",
        question_preview=req.question[:120],
        client_mode=req.mode,
        attachment_count=len(req.attachments),
        user_id=user_id,
        conversation_id=req.conversation_id,
    )
    return EventSourceResponse(
        _stream_events(
            req=req,
            trace_id=trace_id,
            store=store,
            user_id=user_id,
            background=background,
        ),
        headers={
            "X-Accel-Buffering": "no",
            "x-vercel-ai-ui-message-stream": "v1",
            "X-Trace-Id": trace_id,
        },
    )


async def _stream_events(
    *,
    req: ChatRequest,
    trace_id: str,
    store: ConversationStore | None = None,
    user_id: str | None = None,
    background: BackgroundTasks | None = None,
) -> Any:
    """orchestrator.invoke 를 ThreadPool 로 감싸 SSE 청크 + meta + done 이벤트 송출."""
    state = to_state(req=req, trace_id=trace_id, store=store, user_id=user_id)
    start = time.time()
    try:
        result = await asyncio.to_thread(_orchestrator().invoke, state)
    except Exception as e:  # noqa: BLE001
        yield {
            "event": "error",
            "data": json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False),
        }
        yield {"event": "done", "data": "[DONE]"}
        return

    # SSE 시작 후 — 응답 청크 전에 background save 예약 (latency 영향 0)
    if store is not None and user_id and background is not None:
        background.add_task(_save_conversation_safe, store, result, user_id)

    elapsed = time.time() - start
    response = to_response(result=result, elapsed=elapsed, trace_id=trace_id)

    chunk_size = 16
    for i in range(0, len(response.answer), chunk_size):
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "text-delta", "delta": response.answer[i : i + chunk_size]},
                ensure_ascii=False,
            ),
        }
        await asyncio.sleep(0)

    meta_payload = {
        **response.metadata,
        "answer_full": response.answer,
        "elapsed_seconds": response.elapsed_seconds,
        "source_documents": response.source_documents,
    }
    yield {
        "event": "meta",
        "data": json.dumps(meta_payload, ensure_ascii=False, default=str),
    }
    yield {"event": "done", "data": "[DONE]"}
