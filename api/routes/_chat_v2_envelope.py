"""``/chat/v2`` 라우트의 envelope 변환 헬퍼 — 라우트 본문에서 분리.

도메인/오케스트레이터 결과 → ChatSyncResponse 변환만. 라우트 자체는 *오케스트레이터 호출*
+ 트레이스 기록에 집중.
"""

from __future__ import annotations

import json as _json
import time
from datetime import UTC, datetime
from typing import Any

from api.schemas import ChatMessage, ChatRequest, ChatSyncResponse
from chatbot.domain.conversation import Attachment as DomainAttachment
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent
from chatbot.domain.persistence import ConversationStore
from chatbot.domain.state import ConversationState


def to_state(
    *,
    req: ChatRequest,
    trace_id: str,
    store: ConversationStore | None = None,
    user_id: str | None = None,
) -> ConversationState:
    """ChatRequest → ConversationState.

    영속화 우선순위:
    1. ``store`` + ``user_id`` + ``req.conversation_id`` 모두 있고 store.load 가 conversation
       반환 → *Supabase 진실원천* 으로 turns 복원. PRD-002 §결정 4.
    2. 그 외 — ``req.chat_history`` 를 가짜 Turn 시퀀스로 복원 (PR 6 의 클라이언트-보유 history
       패턴). AUTH 비활성·익명·미설정 환경에서의 fallback.
    """
    user_message = Message(
        role="user",
        content=req.question,
        attachments=tuple(_to_attachment(a) for a in req.attachments),
    )
    conversation = _resolve_conversation(req=req, trace_id=trace_id, store=store, user_id=user_id)
    return ConversationState(
        conversation=conversation,
        pending_user_message=user_message,
        requested_mode=req.mode,
        previous_mode=req.previous_mode,
        requested_dense_weight=req.dense_weight,
        trace_id=trace_id,
        started_at_ms=int(time.time() * 1000),
    )


def _resolve_conversation(
    *,
    req: ChatRequest,
    trace_id: str,
    store: ConversationStore | None,
    user_id: str | None,
) -> Conversation:
    """영속화 진실원천 결정 — Supabase 우선, chat_history fallback."""
    if store is not None and user_id and req.conversation_id:
        loaded = store.load(req.conversation_id, user_id=user_id)
        if loaded is not None:
            return loaded
    # 새 conversation_id 또는 영속화 미설정 — chat_history 로 복원.
    # Supabase conversations.id 가 uuid 타입이라 trace_id (16자 hex) 사용 불가 — 새 uuid4 생성.
    import uuid as _uuid

    new_id = req.conversation_id or str(_uuid.uuid4())
    return Conversation(
        id=new_id,
        turns=_history_to_turns(req.chat_history, parent_trace_id=trace_id),
        created_at=datetime.now(UTC),
    )


def _history_to_turns(
    history: list[ChatMessage],
    *,
    parent_trace_id: str,
) -> tuple[Turn, ...]:
    """ChatMessage 시퀀스 → Turn 시퀀스. user → assistant 인접 페어 1개당 Turn 1개.

    메타 필드 (intent / selected_strategy / standalone_question 등) 는 placeholder —
    클라이언트가 *과거 메타*를 보내지 않기 때문. compose_answer 의 history_messages 헬퍼는
    user/assistant 본문만 사용하므로 답변 합성 정확도 영향 없음.
    """
    turns: list[Turn] = []
    now = datetime.now(UTC)
    pending_user: ChatMessage | None = None
    for msg in history:
        if msg.role == "user":
            pending_user = msg
            continue
        # assistant — 직전 user 와 페어. user 없으면 무시 (history 손상 케이스).
        if pending_user is None:
            continue
        turns.append(
            Turn(
                user_message=Message(role="user", content=pending_user.content),
                intent=Intent.NEW_QUESTION,
                standalone_question=None,
                selected_strategy=None,
                retrieval_result_ref=None,
                answer=Message(role="assistant", content=msg.content),
                trace_id=parent_trace_id,
                elapsed_ms=0,
                started_at=now,
            )
        )
        pending_user = None
    return tuple(turns)


def _to_attachment(att: Any) -> DomainAttachment:
    """api.schemas.Attachment → domain Attachment.

    api 측 data_url 만 전달 — domain 의 image_url kind 로 흡수 (validator 가 data:URL 도 허용).
    """
    data_url = getattr(att, "data_url", None) or (
        att.get("data_url") if isinstance(att, dict) else None
    )
    return DomainAttachment(kind="image_url", value=str(data_url or ""))


def to_response(*, result: Any, elapsed: float, trace_id: str) -> ChatSyncResponse:
    """LangGraph result (dict 또는 ConversationState) → ChatSyncResponse."""
    conv, retrieval, answer_msg = _unpack_result(result)
    last_turn = conv.turns[-1] if conv and conv.turns else None
    answer_text = (
        answer_msg.content if answer_msg else (last_turn.answer.content if last_turn else "")
    )
    metadata = _build_metadata(retrieval=retrieval, last_turn=last_turn, trace_id=trace_id)
    source_documents = [d.content for d in retrieval.documents] if retrieval is not None else []
    return ChatSyncResponse(
        answer=answer_text,
        source_documents=source_documents,
        metadata=metadata,
        elapsed_seconds=elapsed,
    )


def _unpack_result(result: Any) -> tuple[Any, Any, Any]:
    """LangGraph 가 dict 또는 ConversationState 둘 다 반환할 수 있어 둘 다 처리."""
    if isinstance(result, dict):
        return (
            result.get("conversation"),
            result.get("pending_retrieval"),
            result.get("pending_answer"),
        )
    return result.conversation, result.pending_retrieval, result.pending_answer


def _build_metadata(
    *,
    retrieval: Any,
    last_turn: Any,
    trace_id: str,
) -> dict[str, Any]:
    """기존 ``/chat/sync`` envelope 키 셋 + 신규 chatbot 메타.

    프론트 (web/lib/api.ts:ChatStreamMeta) 가 사용하는 키들을 모두 노출 — 두 라우트가 동일
    envelope 으로 처리 가능. retrieval=None 인 META/SMALLTALK 시나리오는 빈 list 로 채움.
    """
    metadata: dict[str, Any] = {
        "intent": last_turn.intent.value if last_turn else None,
        "standalone_question": last_turn.standalone_question if last_turn else None,
        "selected_strategy": last_turn.selected_strategy if last_turn else None,
        "routed_mode": last_turn.selected_strategy if last_turn else None,
        "auto_routed": bool(last_turn and last_turn.selected_strategy),
        "trace_id": trace_id,
    }
    if retrieval is None:
        metadata.update(
            cited_pages=[],
            source_pages=[],
            source_pages_label=[],
            suggested_followups=[],
            tool_calls=[],
            tool_call_count=0,
            subgraph=None,
            pattern=None,
        )
        return metadata

    metadata["pattern"] = retrieval.metadata.get("pattern")
    metadata["citations"] = [c.model_dump() for c in retrieval.citations]
    metadata["subgraph"] = (
        retrieval.subgraph.model_dump() if retrieval.subgraph is not None else None
    )
    metadata["cited_pages"] = _coerce_int_list(retrieval.metadata.get("cited_pages"))
    metadata["source_pages"] = [
        (d.page + 1) if d.page is not None else None for d in retrieval.documents
    ]
    metadata["source_pages_label"] = [c.page_label for c in retrieval.citations]
    metadata["suggested_followups"] = _coerce_str_list(
        retrieval.metadata.get("suggested_followups")
    )
    metadata["tool_calls"] = [
        {"tool_name": tc.tool_name, "arguments": dict(tc.arguments)} for tc in retrieval.tool_calls
    ]
    metadata["tool_call_count"] = len(retrieval.tool_calls)
    if retrieval.metadata.get("mode_override"):
        metadata["auto_routed"] = False
    for key in (
        "error_code",
        "strategy_reason",
        "mode_override",
        "auto_routed",
        "routed_mode",
    ):
        value = retrieval.metadata.get(key)
        if value not in (None, ""):
            metadata[key] = value
    return metadata


def _coerce_int_list(raw: Any) -> list[int]:
    """RetrievalResult.metadata 의 직렬화된 cited_pages (json/csv) → list[int]."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [int(p) for p in raw if p is not None]
    text = str(raw).strip()
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list):
            return [int(p) for p in parsed if p is not None]
    except (ValueError, TypeError):
        pass
    return [int(p) for p in text.split(",") if p.strip().isdigit()]


def _coerce_str_list(raw: Any) -> list[str]:
    """RetrievalResult.metadata 의 직렬화된 suggested_followups (json) → list[str]."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(s) for s in raw if s]
    try:
        parsed = _json.loads(str(raw))
        if isinstance(parsed, list):
            return [str(s) for s in parsed if s]
    except (ValueError, TypeError):
        pass
    return []
