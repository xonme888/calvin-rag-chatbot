"""익명 UserIdentifier — AUTH_ENABLED=false 또는 dev/시연 모드.

current_user_id() 가 항상 None — 영속화 어댑터가 None 받으면 *비저장* 또는 *익명 슬롯* 으로
처리. 본 어댑터는 *Auth 비활성* 명시 의도.
"""

from __future__ import annotations

from typing import Any


class AnonymousUserIdentifier:
    """항상 None 반환. dev/시연/AUTH_ENABLED=false 환경에서 사용."""

    name: str = "anonymous"

    def current_user_id(self, request: Any) -> str | None:
        return None
