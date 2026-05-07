"""``/conversations`` — 사용자별 대화 목록·상세·삭제 (PR 15).

PR 13 의 SupabaseConversationStore 위에 RESTful 라우트 노출. 사이드바가 본 라우트로
서버 진실원천 사용 (PRD-002 §결정 4).

흐름:
- 인증 필수 (Authorization Bearer JWT). 미인증 시 401.
- store.list_for_user / load / delete 위임. RLS + .eq("user_id") 가 사용자 격리.
- 목록은 가벼운 ConversationSummary (사이드바 즉시 표시). 상세는 full Conversation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.middleware.rate_limiter import limiter
from chatbot.application.bootstrap import build_persistence_from_env
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@lru_cache(maxsize=1)
def _persistence() -> tuple[Any | None, Any]:
    """첫 호출 시 환경변수 → (Store, Identifier). chat_v2 와 동일 lru_cache."""
    return build_persistence_from_env()


def reset_persistence() -> None:
    """테스트용 — 캐시 초기화."""
    _persistence.cache_clear()


def _require_user_id(request: Request) -> tuple[Any, str]:
    """store + user_id 확보 — 둘 중 하나라도 없으면 401/503."""
    store, identifier = _persistence()
    if store is None:
        raise HTTPException(status_code=503, detail="영속화 미설정 (Supabase env 확인)")
    user_id = identifier.current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return store, user_id


@router.get("")
@limiter.limit("60/minute;1000/day")
async def list_conversations(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(None, description="ISO 8601. 이 시점 이전 대화만."),
) -> dict[str, Any]:
    """사용자의 대화 목록 — updated_at desc. 사이드바 첫 로딩에 사용."""
    store, user_id = _require_user_id(request)
    summaries = store.list_for_user(user_id, limit=limit, before=before)
    return {
        "items": [s.model_dump(mode="json") for s in summaries],
        "count": len(summaries),
    }


@router.get("/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str) -> dict[str, Any]:
    """대화 상세 — full Conversation. 사이드바에서 세션 클릭 시 본문 로드."""
    store, user_id = _require_user_id(request)
    conv = store.load(conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="대화 없음")
    return {"conversation": conv.model_dump(mode="json")}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(request: Request, conversation_id: str) -> None:
    """대화 삭제. silent no-op (다른 사용자 소유면 보안상 존재 노출 X)."""
    store, user_id = _require_user_id(request)
    store.delete(conversation_id, user_id=user_id)


# ============================================================
# 일회성 마이그레이션 (PR 15.3) — IndexedDB 익명 세션 → Supabase
# ============================================================
class MigrationRequest(BaseModel):
    """클라이언트가 보내는 익명 세션 배열. ChatSession (web) 의 부분집합."""

    conversations: list[dict[str, Any]]


@router.post("/migrate")
@limiter.limit("10/hour")
async def migrate_anonymous_sessions(
    request: Request, payload: MigrationRequest
) -> dict[str, Any]:
    """IndexedDB 의 익명 ChatSession[] → Supabase 일괄 upsert.

    각 ChatSession 의 messages 를 user/assistant 페어로 묶어 가짜 Turn 시퀀스 복원.
    부분 실패 식별: ``skipped_ids`` 반환 — 클라이언트가 해당 항목만 IndexedDB 에
    잔존시켜 데이터 소실을 방지한다 (audit M1).
    rate limit 10/hour — 부분 실패 retry 1~2회 여유.
    """
    store, user_id = _require_user_id(request)
    saved = 0
    skipped_ids: list[str] = []
    now = datetime.now(UTC)

    for raw in payload.conversations:
        raw_id_orig = str(raw.get("id") or "")
        try:
            raw_id = raw_id_orig
            try:
                uuid.UUID(raw_id)
                conv_id = raw_id
            except (ValueError, AttributeError):
                conv_id = str(uuid.uuid4())

            turns: list[Turn] = []
            pending_user: dict[str, Any] | None = None
            for msg in raw.get("messages") or []:
                if msg.get("role") == "user":
                    pending_user = msg
                    continue
                if msg.get("role") == "assistant" and pending_user is not None:
                    turns.append(
                        Turn(
                            user_message=Message(
                                role="user",
                                content=str(pending_user.get("content") or ""),
                            ),
                            intent=Intent.NEW_QUESTION,
                            answer=Message(
                                role="assistant", content=str(msg.get("content") or "")
                            ),
                            trace_id="migrated",
                            elapsed_ms=0,
                            started_at=now,
                        )
                    )
                    pending_user = None
            if not turns:
                skipped_ids.append(raw_id_orig)
                continue
            created_at_raw = raw.get("createdAt")
            created_at = (
                datetime.fromtimestamp(created_at_raw / 1000, tz=UTC)
                if isinstance(created_at_raw, (int, float))
                else now
            )
            conv = Conversation(id=conv_id, turns=tuple(turns), created_at=created_at)
            store.save(conv, user_id=user_id)
            saved += 1
        except Exception as e:  # noqa: BLE001 — 손상된 단건은 skip, 전체 작업은 계속
            logger.warning(
                "migrate skip",
                extra={"raw_id": raw_id_orig, "err": f"{type(e).__name__}: {e}"},
            )
            skipped_ids.append(raw_id_orig)
    return {"saved": saved, "skipped": len(skipped_ids), "skipped_ids": skipped_ids}
