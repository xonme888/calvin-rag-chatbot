"""``/chat/v2`` 라우트의 envelope 변환 헬퍼 — 라우트 본문에서 분리.

도메인/오케스트레이터 결과 → ChatSyncResponse 변환만. 라우트 자체는 *오케스트레이터 호출*
+ 트레이스 기록에 집중.
"""

from __future__ import annotations

import json as _json
import time
from datetime import UTC, datetime
from typing import Any

from api.schemas import ChatRequest, ChatSyncResponse
from chatbot.domain.conversation import Attachment as DomainAttachment
from chatbot.domain.conversation import Conversation, Message
from chatbot.domain.state import ConversationState


def to_state(*, req: ChatRequest, trace_id: str) -> ConversationState:
    """ChatRequest → ConversationState. 매 호출 새 conversation (영속화는 PRD-002 합류 후)."""
    user_message = Message(
        role="user",
        content=req.question,
        attachments=tuple(_to_attachment(a) for a in req.attachments),
    )
    return ConversationState(
        conversation=Conversation(
            id=trace_id,
            turns=tuple(),
            created_at=datetime.now(UTC),
        ),
        pending_user_message=user_message,
        trace_id=trace_id,
        started_at_ms=int(time.time() * 1000),
    )


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
