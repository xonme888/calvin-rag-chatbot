"""서버측 입력 검증 모음. 클라이언트 검증의 *2차 방어선*.

PRD-001 의 vision 게이팅 후속 — 클라이언트 (web/components/AttachmentInput.tsx) 만으로는
*악의적 우회* 가능하므로 본 레이어가 마지막 차단선.
"""

from chatbot.infrastructure.validation.attachment_validator import (
    AttachmentValidationError,
    AttachmentValidator,
)

__all__ = ["AttachmentValidator", "AttachmentValidationError"]
