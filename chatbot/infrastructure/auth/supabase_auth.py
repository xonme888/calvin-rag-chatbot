"""SupabaseUserIdentifier — Authorization Bearer JWT → user_id.

설계:
- Supabase 가 발급한 JWT 의 ``sub`` claim 이 user uuid. 검증은 supabase Client 의
  ``auth.get_user(jwt)`` 가 자동 (Supabase 서버에 검증 요청, 실패 시 None).
- 호출 빈도가 매 요청마다라 *cheap* — 단순 JWT decode + JWKS 검증. supabase-py 가 처리.
- 검증 실패 / 토큰 없음 / 만료 시 None — 상위 라우트가 *익명 fallback* 또는 401 결정.

Authorization header 추출은 본 어댑터 책임. FastAPI Request 객체 직접 받음 — 도메인 의존성을
유지하되 FastAPI 호환.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client


class SupabaseUserIdentifier:
    """Authorization Bearer JWT → Supabase user uuid.

    Client 는 *anon key* 또는 *service_role key* 둘 다 OK — auth.get_user 는 JWT 자체를
    검증하므로 client key 는 무관.
    """

    name: str = "supabase"

    def __init__(self, *, client: Client) -> None:
        self._client = client

    def current_user_id(self, request: Any) -> str | None:
        token = _extract_bearer_token(request)
        if not token:
            return None
        try:
            response = self._client.auth.get_user(token)
        except Exception:  # noqa: BLE001 — 어떤 검증 실패도 None
            return None
        user = getattr(response, "user", None)
        if user is None:
            return None
        return str(getattr(user, "id", "")) or None


def _extract_bearer_token(request: Any) -> str | None:
    """``Authorization: Bearer <token>`` → token. 헤더 없거나 형식 다르면 None.

    FastAPI Request 또는 dict-like (testing) 양쪽 호환 — getattr fallback.
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    parts = str(auth).split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
