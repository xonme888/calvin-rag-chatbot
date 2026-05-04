"""API 요청/응답 Pydantic v2 스키마.

자바 매핑(`docs/me/010`): Pydantic = Spring DTO + Bean Validation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 모드 식별자 (외부 API 표기 — 클라이언트에서 사용)
ModeName = Literal["hybrid", "agentic", "kg", "vision"]
# 클라이언트가 보낼 수 있는 모드 — "auto" 는 백엔드 라우터가 결정
InputMode = Literal["auto", "hybrid", "agentic", "kg", "vision"]


class Attachment(BaseModel):
    """사용자 첨부물 — 1차는 이미지 (data URL 형식)."""

    type: Literal["image"] = Field(default="image")
    data_url: str = Field(
        min_length=1,
        max_length=10_000_000,  # ~10MB base64 (실제 이미지 ~7MB)
        description="data:image/jpeg;base64,... 형식 또는 https:// URL",
    )
    name: str | None = Field(default=None, description="파일명 (선택)")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ChatMessage(BaseModel):
    """대화 히스토리 메시지 (멀티턴용)."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """챗 요청 — 모든 엔드포인트 공통."""

    question: str = Field(min_length=1, max_length=2000, description="사용자 질문")
    mode: InputMode = Field(
        default="auto",
        description="RAG 모드 선택. 'auto' 면 백엔드 라우터가 결정.",
    )
    chat_history: list[ChatMessage] = Field(
        default_factory=list,
        description="이전 대화 메시지 (멀티턴, Hybrid 모드만 활용)",
    )
    dense_weight: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Hybrid 모드 RRF 가중치"
    )
    previous_mode: ModeName | None = Field(
        default=None,
        description="'다른 모드로 재시도' 시 직전 응답의 라우팅 모드. 라우터 진화 학습 시그널.",
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        description="첨부물 (이미지 등). 비어있지 않으면 router 가 vision 모드로 강제.",
    )


class ChatSyncResponse(BaseModel):
    """동기 챗 응답."""

    answer: str
    source_documents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: float


class ModeInfo(BaseModel):
    name: ModeName
    label: str
    available: bool
    reason: str | None = None


class ModesResponse(BaseModel):
    modes: list[ModeInfo]


class StatsResponse(BaseModel):
    """누적 사용 통계 — `infra/usage_tracker.SessionStats` 직렬화."""

    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_cost_krw: float
    by_mode: dict[str, dict[str, Any]]
