"""초대 코드 검증 라우트 — POST /invite/verify."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from infra.invite_codes import is_enforcement_enabled, verify_code

router = APIRouter(prefix="/invite", tags=["meta"])


class InviteVerifyRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class InviteVerifyResponse(BaseModel):
    ok: bool
    enforcement_enabled: bool


@router.post("/verify", response_model=InviteVerifyResponse)
async def verify_invite(req: InviteVerifyRequest) -> InviteVerifyResponse:
    """초대 코드 검증 — 200 ok, 401 invalid.

    검증 비활성 (환경변수 미설정) 시 어떤 코드든 ok=True 반환 (개발 모드).
    """
    enabled = is_enforcement_enabled()
    if not enabled:
        return InviteVerifyResponse(ok=True, enforcement_enabled=False)

    if verify_code(req.code):
        return InviteVerifyResponse(ok=True, enforcement_enabled=True)
    raise HTTPException(status_code=401, detail="유효하지 않은 초대 코드입니다.")


@router.get("/status", response_model=InviteVerifyResponse)
async def invite_status() -> InviteVerifyResponse:
    """초대 코드 검증이 활성인지 — 프론트가 첫 진입 시 호출.

    enforcement_enabled=False 면 InviteGate 자동 통과.
    """
    return InviteVerifyResponse(ok=True, enforcement_enabled=is_enforcement_enabled())
