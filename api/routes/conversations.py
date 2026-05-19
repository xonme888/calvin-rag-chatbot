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
import os
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.middleware.rate_limiter import limiter
from chatbot.application.bootstrap import (
    build_persistence_from_env,
    build_turn_artifact_store_from_env,
)
from chatbot.domain.conversation import Conversation, Message, Turn
from chatbot.domain.intent import Intent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@lru_cache(maxsize=1)
def _persistence() -> tuple[Any | None, Any]:
    """첫 호출 시 환경변수 → (Store, Identifier). chat_v2 와 동일 lru_cache."""
    return build_persistence_from_env()


@lru_cache(maxsize=1)
def _artifact_store() -> Any | None:
    """턴 아티팩트 저장소. 미설정 시 None."""
    return build_turn_artifact_store_from_env()


@lru_cache(maxsize=1)
def _artifact_index_version() -> str:
    """현재 서버 인덱스 버전."""
    return os.getenv("RAG_INDEX_VERSION", "").strip() or "unknown"


@lru_cache(maxsize=1)
def _artifact_ttl_days() -> int:
    """아티팩트 stale 판정 TTL 일수."""
    raw = os.getenv("RAG_ARTIFACT_TTL_DAYS", "").strip()
    try:
        ttl = int(raw) if raw else 7
    except ValueError:
        ttl = 7
    return max(1, ttl)


def reset_persistence() -> None:
    """테스트용 — 캐시 초기화."""
    _persistence.cache_clear()
    _artifact_store.cache_clear()
    _artifact_index_version.cache_clear()
    _artifact_ttl_days.cache_clear()


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


@router.get("/{conversation_id}/turns/{turn_index}/artifact")
async def get_turn_artifact(
    request: Request,
    conversation_id: str,
    turn_index: int,
) -> dict[str, Any]:
    """턴별 retrieval 아티팩트 조회 + stale 판정 + 재검색 힌트."""
    store, user_id = _require_user_id(request)
    artifact_store = _artifact_store()
    if artifact_store is None:
        raise HTTPException(status_code=503, detail="아티팩트 영속화 미설정")

    conv = store.load(conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="대화 없음")
    if turn_index < 0 or turn_index >= len(conv.turns):
        raise HTTPException(status_code=404, detail="턴 없음")

    turn = conv.turns[turn_index]
    if turn.retrieval_result_ref is None:
        raise HTTPException(status_code=404, detail="해당 턴에 retrieval 아티팩트 없음")

    artifact = artifact_store.load_by_turn(conversation_id, turn_index, user_id=user_id)
    if artifact is None:
        artifact = artifact_store.load_by_ref(turn.retrieval_result_ref, user_id=user_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="아티팩트 없음")

    current_index_version = _artifact_index_version()
    ttl_days = _artifact_ttl_days()
    stale_reasons = _stale_reasons(
        artifact_index_version=str(artifact.index_version or "unknown"),
        current_index_version=current_index_version,
        created_at=artifact.created_at,
        ttl_days=ttl_days,
    )
    return {
        "artifact": artifact.model_dump(mode="json"),
        "freshness": {
            "is_stale": bool(stale_reasons),
            "artifact_index_version": artifact.index_version,
            "current_index_version": current_index_version,
            "ttl_days": ttl_days,
        },
        "stale_reasons": stale_reasons,
        "requery_hint": {
            "question": turn.standalone_question or turn.user_message.content,
            "mode": turn.selected_strategy or "auto",
        },
        "notice": "최신 인덱스 재검색 결과는 과거 스냅샷과 다를 수 있습니다.",
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(request: Request, conversation_id: str) -> None:
    """대화 삭제. silent no-op (다른 사용자 소유면 보안상 존재 노출 X)."""
    store, user_id = _require_user_id(request)
    store.delete(conversation_id, user_id=user_id)


def _stale_reasons(
    *,
    artifact_index_version: str,
    current_index_version: str,
    created_at: datetime,
    ttl_days: int,
) -> list[str]:
    """index version/TTL 기반 stale 사유 계산."""
    reasons: list[str] = []
    if artifact_index_version != current_index_version:
        reasons.append("index_version_mismatch")
    created = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - created).total_seconds() / 86400.0
    if age_days > ttl_days:
        reasons.append("ttl_expired")
    return reasons


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
