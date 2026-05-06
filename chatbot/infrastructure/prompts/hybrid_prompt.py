"""Hybrid generate stage 의 ChatPromptTemplate 빌더.

기존 ``rag_core/hybrid.py:193-199`` 와 동일 — system + chat_history placeholder
+ human(question). chat_history 가 비어도 에러 없이 단일 턴으로 동작.

본 모듈은 corpus 별 system 프롬프트(SYSTEM_PROMPT) 를 그대로 받는다 — 어떤 도메인의
가이드인지는 corpus 어댑터가 결정한다.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


def build_hybrid_prompt(system_prompt: str) -> ChatPromptTemplate:
    """system_prompt + chat_history + human 의 템플릿 반환.

    system_prompt 는 ``{context}`` placeholder 를 포함해야 한다 — generate stage 가
    검색 결과 본문을 주입한다. 검증은 caller 책임.
    """
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{question}"),
        ]
    )
