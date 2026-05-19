"""LangGraph 의 StateSchema — 노드들이 공유하는 상태.

원칙:
- *진행 중* 인 턴의 중간 결정은 ``pending_*`` 으로 표기. 턴이 완료되면 ``Turn`` 으로
  freeze 되어 ``conversation.turns`` 에 append 된다.
- pending_* 필드는 노드 시퀀스가 전진하면서 채워진다 — 한 노드가 채우는 필드는 하나다
  (단일 책임). 다른 노드의 필드는 읽기만 한다.
- LangGraph 가 reducer 로 누적하므로 BaseModel 은 *mutable* (Conversation 자체는 frozen).

의도(Intent) 별 노드 활성화:
| Intent              | rewrite | select | invoke | compose |
|---------------------|---------|--------|--------|---------|
| NEW_QUESTION        |    -    |   ✓    |   ✓    |    ✓    |
| FOLLOWUP            |    ✓    |   ✓    |   ✓    |    ✓    |
| META_RECAP          |    -    |   -    |   -    |    ✓    |
| META_REFERENCE      |    -    |   -    |   -    |    ✓    |
| SMALLTALK           |    -    |   -    |   -    |    ✓    |
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from chatbot.domain.conversation import Conversation, Message
from chatbot.domain.intent import Intent
from chatbot.domain.retrieval import RetrievalResult


class ConversationState(BaseModel):
    """오케스트레이터의 단일 상태 컨테이너.

    한 대화 1개 = 한 ConversationState 1개. 페이지 새로고침 후에도 LangGraph
    checkpointer 가 conversation.id 키로 복원한다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation: Conversation
    pending_user_message: Message
    """현재 처리 중인 입력 메시지. 노드 시퀀스 시작 시 set."""

    pending_intent: Intent | None = None
    pending_standalone: str | None = None
    pending_strategy: str | None = None
    """선택된 RetrievalStrategy.name. META/SMALLTALK 이면 None 유지."""

    pending_retrieval: RetrievalResult | None = None
    pending_answer: Message | None = None

    requested_mode: str = "auto"
    previous_mode: str | None = None
    requested_dense_weight: float = 0.5
    """요청 라우팅 힌트. select/invoke 노드가 전략 선택·가중치 조정에 사용."""

    trace_id: str
    started_at_ms: int = Field(ge=0)
    """epoch ms — 턴 elapsed 계산용. compose_answer 노드가 사용."""

    errors: tuple[str, ...] = ()
    """노드 실행 중 누적된 오류 메시지. 회복 가능 오류는 여기 누적, 치명은 throw."""
