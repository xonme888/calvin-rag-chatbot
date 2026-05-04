"""챗 라우트 — `/chat/sync` (동기 JSON), `/chat/stream` (SSE).

설계:
- 입력 가드 → mode 분기 호출 → 출력 가드 → 응답
- mode_dispatcher 처럼 ThreadPoolExecutor 동기 호출을 ``run_in_executor`` 로 async 래핑
- SSE 는 Vercel AI SDK Stream Protocol v1 호환 (`x-vercel-ai-ui-message-stream: v1`)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sse_starlette.sse import EventSourceResponse

from api.dependencies import (
    check_input_guard,
    check_output_guard,
    get_hybrid_rag,
    get_session_stats,
)
from api.middleware.audit_log import AuditRecord, log_chat
from api.middleware.rate_limiter import limiter
from api.middleware.token_budget import check_token_budget
from api.schemas import ChatMessage, ChatRequest, ChatSyncResponse
from infra.usage_tracker import UsageTracker
from rag_core.mode_registry import get as get_mode_entry
from rag_core.router import route_question

router = APIRouter(prefix="/chat", tags=["chat"])

_MODEL = "gpt-4o-mini"


def _client_ip(request: Request) -> str:
    """X-Forwarded-For (CF/proxy) 우선, fallback은 직접 IP."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _resolve_mode(req: ChatRequest) -> tuple[ChatRequest, bool]:
    """req.mode 가 'auto' 면 라우터로 결정된 모드로 갈아끼우고 반환.

    Returns:
        (resolved_req, was_auto) — was_auto 는 응답 metadata 의 auto_routed 표기에 사용.
    """
    if req.mode == "auto":
        routed = route_question(req.question)
        return req.model_copy(update={"mode": routed}), True
    return req, False


def _to_langchain_history(messages: list[ChatMessage]) -> list[BaseMessage]:
    history: list[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        else:
            history.append(AIMessage(content=m.content))
    return history


def _invoke_sync(req: ChatRequest) -> dict[str, Any]:
    """모드별 동기 RAG 호출 — ThreadPool 안에서 실행될 함수.

    Registry 에서 ModeEntry 를 조회하고 health → factory → query 순으로 호출한다.
    Hybrid 만 chat_history/dense_weight 인자가 추가로 필요해 분기 1곳만 남음.
    """
    stats = get_session_stats()

    try:
        entry = get_mode_entry(req.mode)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 모드: {req.mode}")

    available, reason = entry.health()
    if not available:
        raise HTTPException(
            status_code=503,
            detail=f"{entry.label} 비활성화 — {reason or '사유 미상'}",
        )

    rag = entry.factory()
    tracker = UsageTracker(stats, mode=entry.tracker_mode, model=_MODEL)

    # hybrid 만 chat_history/dense_weight 옵션 지원 — capability 차이
    if req.mode == "hybrid":
        rag.config.dense_weight = req.dense_weight
        history = _to_langchain_history(req.chat_history)
        return rag.query(req.question, chat_history=history, callbacks=[tracker])
    return rag.query(req.question, callbacks=[tracker])


@router.post("/sync", response_model=ChatSyncResponse)
@limiter.limit("10/minute;200/day")
async def chat_sync(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
) -> ChatSyncResponse:
    """동기 응답. 디버깅 + Phase B 가드 풀 패스용.

    흐름: rate limit (slowapi) → token budget → 입력 가드 → mode 호출 → 출력 가드 →
          audit log 비동기 기록 → 응답
    """
    ip = _client_ip(request)
    stats = get_session_stats()

    # 0. Token budget cap (누적치)
    check_token_budget(stats)

    # 0.5. mode='auto' 라우팅 — 사용자에게 모드 노출 X (구현 디테일 캡슐화)
    req, was_auto = _resolve_mode(req)

    # 1. 입력 가드
    in_allow, in_reason, in_sanitized = check_input_guard(req.question)
    if not in_allow:
        background.add_task(
            log_chat,
            AuditRecord(
                ip=ip,
                mode=req.mode,
                question=req.question,
                guard_action="input_blocked",
                guard_reason=in_reason,
            ),
        )
        raise HTTPException(status_code=400, detail=f"입력 차단: {in_reason}")
    if in_sanitized is not None:
        req = req.model_copy(update={"question": in_sanitized})

    # 2. 동기 RAG 호출을 async 래핑 (ThreadPool)
    start = time.time()
    try:
        result = await asyncio.to_thread(_invoke_sync, req)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"RAG 호출 실패: {type(e).__name__}") from e
    elapsed = time.time() - start

    answer = result.get("final_answer", "")
    source_documents = result.get("source_documents", [])
    metadata = result.get("metadata", {})
    # 라우팅 결과를 항상 metadata 에 노출 — UI 가 "(자동: Hybrid)" 표시 가능
    metadata = {**metadata, "routed_mode": req.mode, "auto_routed": was_auto}

    # 3. 출력 가드
    guard_action = "allow"
    guard_reason: str | None = None
    out_allow, out_reason, out_sanitized = check_output_guard(answer)
    if not out_allow:
        guard_action = "output_blocked"
        guard_reason = out_reason
        answer = "답변이 정책에 의해 필터링되었습니다."
        metadata = {**metadata, "guard_blocked": True, "guard_reason": out_reason}
        source_documents = []
    elif out_sanitized is not None:
        guard_action = "sanitized"
        guard_reason = out_reason
        answer = out_sanitized
        metadata = {**metadata, "guard_sanitized": True, "guard_reason": out_reason}

    # 4. Audit log 비동기 기록
    mode_stats = stats.by_mode.get(_mode_key(req.mode))
    background.add_task(
        log_chat,
        AuditRecord(
            ip=ip,
            mode=req.mode,
            question=req.question,
            answer_preview=answer[:200],
            tokens_in=mode_stats.input_tokens if mode_stats else 0,
            tokens_out=mode_stats.output_tokens if mode_stats else 0,
            cost_krw=mode_stats.cost_krw if mode_stats else 0.0,
            guard_action=guard_action,
            guard_reason=guard_reason,
            elapsed_seconds=elapsed,
        ),
    )

    return ChatSyncResponse(
        answer=answer,
        source_documents=source_documents,
        metadata=metadata,
        elapsed_seconds=elapsed,
    )


def _mode_key(mode: str) -> str:
    """API mode 식별자 → SessionStats key — registry 의 tracker_mode 위임."""
    try:
        return get_mode_entry(mode).tracker_mode
    except KeyError:
        return mode


# ====================================================================
# SSE 스트리밍 — Vercel AI SDK Stream Protocol v1 호환
# ====================================================================
async def _stream_chat_events(req: ChatRequest, was_auto: bool = False):
    """async generator — Vercel AI SDK Data Stream Protocol 형식.

    포맷:
        data: {"type":"text-delta","delta":"..."}\n\n
        data: {"type":"text-delta","delta":"..."}\n\n
        ...
        data: [DONE]\n\n

    Hybrid 의 stream_query 는 동기 generator라 to_thread/run_in_executor 로 async 변환.
    Agentic/KG 는 sync 호출 결과를 텍스트 청크로 분할해 yield (스트리밍 흉내).
    """
    if req.mode == "hybrid":
        async for event in _stream_hybrid(req, was_auto):
            yield event
    else:
        # Agentic / KG 는 동기 호출 후 청크 단위 replay (간이 SSE)
        async for event in _stream_sync_replay(req, was_auto):
            yield event

    yield {"event": "done", "data": "[DONE]"}


async def _stream_hybrid(req: ChatRequest, was_auto: bool = False):
    """Hybrid stream_query 를 async 변환해 토큰 단위 SSE.

    Stream 종료 후 ``event: meta`` 1회 emit — cited_pages, source_pages_label,
    elapsed, confidence, tokens 등 메타데이터 클라이언트 전달.
    """
    hybrid = get_hybrid_rag()
    hybrid.config.dense_weight = req.dense_weight
    history = _to_langchain_history(req.chat_history)
    stats = get_session_stats()
    tracker = UsageTracker(stats, mode="Hybrid", model=_MODEL)

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def producer() -> None:
        try:
            for chunk in hybrid.stream_query(
                req.question, chat_history=history, callbacks=[tracker]
            ):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(asyncio.to_thread(producer))

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield {
            "event": "message",
            "data": json.dumps({"type": "text-delta", "delta": chunk}, ensure_ascii=False),
        }

    # Stream 종료 후 — _last_metadata 가 채워져 있으므로 meta 이벤트 1회 emit
    last_meta = hybrid._last_metadata or {}
    payload = _build_stream_meta_payload(
        req=req,
        was_auto=was_auto,
        result_metadata=last_meta,
        source_documents=last_meta.get("source_documents", []),
        stats=stats,
    )
    yield {
        "event": "meta",
        "data": json.dumps(payload, ensure_ascii=False, default=str),
    }


async def _stream_sync_replay(req: ChatRequest, was_auto: bool):
    """Agentic/KG: 동기 호출 후 답변을 청크 단위로 흘려보냄.

    Stream 종료 후 ``event: meta`` 1회 emit — Hybrid 와 동일 envelope 로
    subgraph/source/cited_pages/followups 등 메타를 잃지 않게 한다.
    """
    result = await asyncio.to_thread(_invoke_sync, req)
    answer = result.get("final_answer", "")

    # 간단 청크 분할 — 토큰 단위 정확도는 떨어지나 UX 충분
    chunk_size = 16
    for i in range(0, len(answer), chunk_size):
        chunk = answer[i : i + chunk_size]
        yield {
            "event": "message",
            "data": json.dumps({"type": "text-delta", "delta": chunk}, ensure_ascii=False),
        }
        await asyncio.sleep(0)

    payload = _build_stream_meta_payload(
        req=req,
        was_auto=was_auto,
        result_metadata=result.get("metadata", {}) or {},
        source_documents=result.get("source_documents", []),
        stats=get_session_stats(),
    )
    yield {
        "event": "meta",
        "data": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _build_stream_meta_payload(
    *,
    req: ChatRequest,
    was_auto: bool,
    result_metadata: dict[str, Any],
    source_documents: list[str],
    stats: Any,
) -> dict[str, Any]:
    """Hybrid/Agentic/KG 공통 SSE meta envelope.

    프론트는 이 한 형태만 보면 되도록 모든 모드의 metadata 키를 평탄화한다.
    값이 없으면 빈 배열/None 으로 채워 envelope 일관성 유지.
    """
    tracker_key = _mode_key(req.mode)
    mode_stats = stats.by_mode.get(tracker_key)
    return {
        "cited_pages": result_metadata.get("cited_pages", []),
        "source_documents": source_documents,
        "source_pages": result_metadata.get("source_pages", []),
        "source_pages_label": result_metadata.get("source_pages_label", []),
        "elapsed_seconds": result_metadata.get("elapsed_seconds"),
        "confidence": result_metadata.get("confidence"),
        "pattern": result_metadata.get("pattern", req.mode),
        "mode": req.mode,
        "routed_mode": req.mode,
        "auto_routed": was_auto,
        "subgraph": result_metadata.get("subgraph"),
        "tool_calls": result_metadata.get("tool_calls", []),
        "tool_call_count": result_metadata.get("tool_call_count"),
        "suggested_followups": result_metadata.get("suggested_followups", []),
        "tokens": {
            "input": mode_stats.input_tokens if mode_stats else 0,
            "output": mode_stats.output_tokens if mode_stats else 0,
        },
    }


@router.post("/stream")
@limiter.limit("10/minute;200/day")
async def chat_stream(
    request: Request,
    req: ChatRequest,
    background: BackgroundTasks,
) -> EventSourceResponse:
    """SSE 스트리밍. Vercel AI SDK `useChat` 호환 헤더 포함.

    출력 가드는 stream 종료 *후* audit 용 (cheap check 만 inline). 본격 출력 가드는 sync 권장.
    """
    ip = _client_ip(request)
    stats = get_session_stats()
    check_token_budget(stats)

    # mode='auto' 라우팅 — 사용자에게 모드 노출 X
    req, was_auto = _resolve_mode(req)

    # 입력 가드만 inline
    in_allow, in_reason, in_sanitized = check_input_guard(req.question)
    if not in_allow:
        background.add_task(
            log_chat,
            AuditRecord(
                ip=ip,
                mode=req.mode,
                question=req.question,
                guard_action="input_blocked",
                guard_reason=in_reason,
            ),
        )
        raise HTTPException(status_code=400, detail=f"입력 차단: {in_reason}")
    if in_sanitized is not None:
        req = req.model_copy(update={"question": in_sanitized})

    # stream 시작 — audit log 는 stream 종료 후 별도 (현재는 단순화 위해 시작 시 기록)
    background.add_task(
        log_chat,
        AuditRecord(
            ip=ip,
            mode=req.mode,
            question=req.question,
            guard_action="stream_started",
            elapsed_seconds=0.0,
        ),
    )

    return EventSourceResponse(
        _stream_chat_events(req, was_auto),
        headers={
            "X-Accel-Buffering": "no",  # nginx/CF 버퍼링 차단 (docs/me/010)
            "x-vercel-ai-ui-message-stream": "v1",  # Vercel AI SDK 호환
        },
    )
