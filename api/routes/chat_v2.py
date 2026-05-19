"""``/chat/v2`` (sync) + ``/chat/v2/stream`` (SSE) — 대화 우선 오케스트레이터 라우트.

기존 ``/chat/sync`` / ``/chat/stream`` 과 *공존* — 본 라우트는 chatbot 패키지의 LangGraph
orchestrator 를 사용. 응답 envelope 은 기존과 호환되되 ``intent`` / ``standalone_question`` /
``selected_strategy`` 메타가 추가된다.

envelope 변환 헬퍼는 ``_chat_v2_envelope`` 모듈에 분리 — 본 파일은 *라우팅 + 트레이스* 에 집중.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.dependencies import (
    build_usage_tracker,
    check_input_guard,
    check_output_guard,
    get_hybrid_rag,
    get_session_stats,
)
from api.middleware.rate_limiter import limiter
from api.middleware.token_budget import (
    check_token_budget,
    check_user_budget,
    record_user_budget_usage,
)
from api.routes._chat_v2_envelope import to_response, to_state
from api.schemas import ChatRequest, ChatSyncResponse
from chatbot.application.bootstrap import (
    build_default_orchestrator,
    build_persistence_from_env,
    build_turn_artifact_store_from_env,
)
from chatbot.infrastructure.persistence.turn_artifact_builder import build_turn_artifact
from infra.observability import (
    new_trace_id,
    set_current_trace_id,
    trace_event,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from chatbot.domain.persistence import ConversationStore, TurnArtifactStore, UserIdentifier

router = APIRouter(prefix="/chat", tags=["chat-v2"])
_SAFE_STREAM_ERROR_MESSAGE = "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
_SAFE_OUTPUT_BLOCKED_MESSAGE = "안전 정책으로 인해 응답을 제공할 수 없습니다."


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


@lru_cache(maxsize=1)
def _artifact_store() -> TurnArtifactStore | None:
    """턴 아티팩트 저장소. 미설정 시 None."""
    return build_turn_artifact_store_from_env()


@lru_cache(maxsize=1)
def _artifact_index_version() -> str:
    """아티팩트 저장 시 index version 태깅."""
    return os.getenv("RAG_INDEX_VERSION", "").strip() or "unknown"


def reset_orchestrator() -> None:
    """테스트용 — 캐시 초기화."""
    _orchestrator.cache_clear()
    _persistence.cache_clear()
    _artifact_store.cache_clear()
    _artifact_index_version.cache_clear()


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
    store, identifier = _persistence()
    artifact_store = _artifact_store()
    index_version = _artifact_index_version()
    user_id = identifier.current_user_id(request)
    client_ip = _client_ip(request)

    stats = get_session_stats()
    check_token_budget(stats)
    check_user_budget(user_id=user_id, ip=client_ip)
    safe_req = _apply_input_guard(req)

    trace_id = new_trace_id()
    set_current_trace_id(trace_id)
    trace_event(
        "request.start",
        endpoint="/chat/v2",
        question_preview=safe_req.question[:120],
        client_mode=safe_req.mode,
        attachment_count=len(safe_req.attachments),
        user_id=user_id,
        conversation_id=safe_req.conversation_id,
    )

    state = to_state(req=safe_req, trace_id=trace_id, store=store, user_id=user_id)
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
        background.add_task(
            _save_conversation_and_artifact_safe,
            store,
            artifact_store,
            result,
            user_id,
            index_version,
        )
    response = to_response(result=result, elapsed=elapsed, trace_id=trace_id)
    response = _apply_output_guard(response)
    _record_usage_and_budget(
        question=safe_req.question,
        answer=response.answer,
        user_id=user_id,
        client_ip=client_ip,
        routed_mode=str(response.metadata.get("selected_strategy") or "orchestrator"),
    )
    return response


def _save_conversation_and_artifact_safe(
    store: ConversationStore,
    artifact_store: TurnArtifactStore | None,
    result: Any,
    user_id: str,
    index_version: str,
) -> None:
    """orchestrator 결과의 conversation + turn artifact 영속화."""
    import logging as _lg

    try:
        conv = (
            result.conversation if hasattr(result, "conversation") else result.get("conversation")
        )
        retrieval = (
            result.pending_retrieval
            if hasattr(result, "pending_retrieval")
            else result.get("pending_retrieval")
        )
        if conv is not None:
            store.save(conv, user_id=user_id)
        if (
            artifact_store is not None
            and conv is not None
            and retrieval is not None
            and len(conv.turns) > 0
        ):
            turn_index = len(conv.turns) - 1
            turn = conv.turns[turn_index]
            if turn.retrieval_result_ref is not None:
                artifact = build_turn_artifact(
                    conversation_id=conv.id,
                    turn_index=turn_index,
                    turn=turn,
                    retrieval=retrieval,
                    index_version=index_version,
                )
                artifact_store.save_if_absent(artifact, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        _lg.getLogger(__name__).warning("conversation/artifact save 실패: %s", e)


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
    store, identifier = _persistence()
    artifact_store = _artifact_store()
    index_version = _artifact_index_version()
    user_id = identifier.current_user_id(request)
    client_ip = _client_ip(request)

    # sync / stream 경로 모두 동일한 budget 안전망을 적용.
    stats = get_session_stats()
    check_token_budget(stats)
    check_user_budget(user_id=user_id, ip=client_ip)
    safe_req = _apply_input_guard(req)

    trace_id = new_trace_id()
    set_current_trace_id(trace_id)
    trace_event(
        "request.start",
        endpoint="/chat/v2/stream",
        question_preview=safe_req.question[:120],
        client_mode=safe_req.mode,
        attachment_count=len(safe_req.attachments),
        user_id=user_id,
        conversation_id=safe_req.conversation_id,
    )
    return EventSourceResponse(
        _stream_events(
            req=safe_req,
            trace_id=trace_id,
            store=store,
            artifact_store=artifact_store,
            index_version=index_version,
            user_id=user_id,
            client_ip=client_ip,
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
    artifact_store: TurnArtifactStore | None = None,
    index_version: str = "unknown",
    user_id: str | None = None,
    client_ip: str = "unknown",
    background: BackgroundTasks | None = None,
) -> Any:
    """orchestrator 실행을 SSE로 송출.

    우선순위:
    1. LangGraph ``stream_mode=messages`` 지원 시 실제 LLM 델타 스트리밍
    2. 미지원/테스트 더블이면 기존 sync replay fallback
    """
    state = to_state(req=req, trace_id=trace_id, store=store, user_id=user_id)
    orchestrator = _orchestrator()
    start = time.time()
    result: Any | None = None
    emitted_delta = False
    streamed_text = ""
    stream_guard_blocked = False

    try:
        if callable(getattr(orchestrator, "stream", None)):
            holder: dict[str, Any] = {}
            async for delta in _iter_graph_message_deltas(
                orchestrator=orchestrator,
                state=state,
                holder=holder,
            ):
                if stream_guard_blocked:
                    continue
                candidate = streamed_text + delta
                allow, _reason, sanitized = check_output_guard(candidate)
                if not allow:
                    stream_guard_blocked = True
                    continue
                next_text = sanitized if sanitized is not None else candidate
                if not next_text.startswith(streamed_text):
                    next_text = candidate
                emit_delta = next_text[len(streamed_text) :]
                streamed_text = next_text
                if not emit_delta:
                    continue
                emitted_delta = True
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "text-delta", "delta": emit_delta},
                        ensure_ascii=False,
                    ),
                }
            if holder.get("error") is not None:
                raise holder["error"]
            result = holder.get("result")
        else:
            result = await asyncio.to_thread(orchestrator.invoke, state)
    except Exception:  # noqa: BLE001
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "error": {
                        "code": "ORCHESTRATOR_ERROR",
                        "message": _SAFE_STREAM_ERROR_MESSAGE,
                    }
                },
                ensure_ascii=False,
            ),
        }
        yield {"event": "done", "data": "[DONE]"}
        return
    if result is None:
        try:
            result = await asyncio.to_thread(orchestrator.invoke, state)
        except Exception:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": {
                            "code": "ORCHESTRATOR_ERROR",
                            "message": _SAFE_STREAM_ERROR_MESSAGE,
                        }
                    },
                    ensure_ascii=False,
                ),
            }
            yield {"event": "done", "data": "[DONE]"}
            return

    # SSE 시작 후 — 응답 청크 전에 background save 예약 (latency 영향 0)
    if store is not None and user_id and background is not None:
        background.add_task(
            _save_conversation_and_artifact_safe,
            store,
            artifact_store,
            result,
            user_id,
            index_version,
        )

    elapsed = time.time() - start
    response = to_response(result=result, elapsed=elapsed, trace_id=trace_id)
    response = _apply_output_guard(response)
    _record_usage_and_budget(
        question=req.question,
        answer=response.answer,
        user_id=user_id,
        client_ip=client_ip,
        routed_mode=str(response.metadata.get("selected_strategy") or "orchestrator"),
    )

    # 실제 token stream이 하나도 없었던 경로(비지원 모델/테스트 더블)는 기존 replay 폴백.
    if not emitted_delta:
        for delta in _token_deltas(response.answer):
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "text-delta", "delta": delta},
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


async def _iter_graph_message_deltas(
    *,
    orchestrator: Any,
    state: Any,
    holder: dict[str, Any],
) -> Any:
    """LangGraph stream worker를 백그라운드 스레드로 실행하고 delta를 비동기 전달."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    holder["result"] = None
    holder["error"] = None

    def _worker() -> None:
        final_state = None
        try:
            for event in orchestrator.stream(
                state,
                stream_mode=["messages", "values"],
            ):
                mode, payload = _split_stream_event(event)
                if mode == "values":
                    final_state = payload
                    continue
                if mode != "messages":
                    continue
                token, metadata = _split_message_payload(payload)
                if not _is_user_visible_node(metadata):
                    continue
                text = _chunk_to_text(token)
                if text:
                    loop.call_soon_threadsafe(queue.put_nowait, ("delta", text))
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc
        finally:
            holder["result"] = final_state
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        kind, payload = await queue.get()
        if kind == "done":
            break
        if kind == "delta":
            yield str(payload)


def _split_stream_event(event: Any) -> tuple[str, Any]:
    """stream_mode 다중 설정 시 (mode, payload) 튜플을 표준화."""
    if isinstance(event, tuple) and len(event) == 2 and isinstance(event[0], str):
        return event[0], event[1]
    return "values", event


def _split_message_payload(payload: Any) -> tuple[Any, dict[str, Any]]:
    """messages payload (token, metadata) 표준화."""
    if isinstance(payload, tuple) and len(payload) == 2:
        token, metadata = payload
        if isinstance(metadata, dict):
            return token, metadata
        return token, {}
    return payload, {}


def _is_user_visible_node(metadata: dict[str, Any]) -> bool:
    """내부 분류/재작성 노드는 제외하고 사용자 답변 경로만 스트림."""
    node = str(metadata.get("langgraph_node") or "")
    if not node:
        return True
    return node in {"invoke", "compose"}


def _chunk_to_text(chunk: Any) -> str:
    """LLM 메시지 청크에서 사용자 표시용 텍스트만 추출."""
    if chunk is None:
        return ""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _client_ip(request: Request) -> str:
    """요청의 사용자 IP. 프록시 환경에서는 X-Forwarded-For 우선."""
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _apply_input_guard(req: ChatRequest) -> ChatRequest:
    """입력 가드 적용. 차단 시 400."""
    allow, reason, sanitized = check_input_guard(req.question)
    if not allow:
        raise HTTPException(status_code=400, detail=reason or "입력 정책 위반")
    if sanitized is None:
        return req
    return req.model_copy(update={"question": sanitized})


def _apply_output_guard(response: ChatSyncResponse) -> ChatSyncResponse:
    """출력 가드 적용. 차단 시 안전 메시지로 치환."""
    allow, reason, sanitized = check_output_guard(response.answer)
    if allow and sanitized is None:
        return response

    metadata = dict(response.metadata)
    if allow and sanitized is not None:
        metadata["guard_action"] = "sanitized"
        metadata["guard_reason"] = reason
        return response.model_copy(update={"answer": sanitized, "metadata": metadata})

    metadata["guard_action"] = "output_blocked"
    metadata["guard_reason"] = reason
    return response.model_copy(
        update={"answer": _SAFE_OUTPUT_BLOCKED_MESSAGE, "metadata": metadata}
    )


def _record_usage_and_budget(
    *,
    question: str,
    answer: str,
    user_id: str | None,
    client_ip: str,
    routed_mode: str,
) -> None:
    """요청 단위 사용량 통계/예산 누적."""
    model_name = _resolve_usage_model_name()
    tracker = build_usage_tracker(mode=routed_mode, model=model_name)
    tokens_in, tokens_out = tracker.record_text_interaction(
        input_text=question,
        output_text=answer,
    )
    record_user_budget_usage(
        user_id=user_id,
        ip=client_ip,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model_name,
    )


def _resolve_usage_model_name() -> str:
    """Usage 추정용 모델명.

    요청 경로에서 RAG lazy build를 트리거하지 않기 위해 환경변수 기반으로만 결정한다.
    """
    return os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"


def _token_deltas(answer: str) -> list[str]:
    """답변 문자열을 토큰 단위(delta)로 분할.

    LLM native streaming이 없는 경로에서도 UI는 token-like delta 흐름을 받는다.
    """
    if not answer:
        return [""]
    chunks = re.findall(r"\S+\s*|\n+", answer)
    return chunks if chunks else [answer]
