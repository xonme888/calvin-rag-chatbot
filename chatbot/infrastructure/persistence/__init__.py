"""영속화 어댑터 — domain.ConversationStore 구현.

새 백엔드 추가는 본 디렉토리에 어댑터 1개 + bootstrap 등록.
"""

from chatbot.infrastructure.persistence.supabase_store import SupabaseConversationStore

__all__ = ["SupabaseConversationStore"]
