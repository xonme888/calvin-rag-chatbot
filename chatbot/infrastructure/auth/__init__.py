"""인증 어댑터 — domain.UserIdentifier 구현.

Supabase Auth + 익명 fallback. 새 IdP (Cloudflare Access 등) 추가 시 본 디렉토리에 어댑터 1개.
"""

from chatbot.infrastructure.auth.anonymous import AnonymousUserIdentifier
from chatbot.infrastructure.auth.supabase_auth import SupabaseUserIdentifier

__all__ = ["SupabaseUserIdentifier", "AnonymousUserIdentifier"]
