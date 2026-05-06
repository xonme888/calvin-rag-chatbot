"""Conversation-first 챗봇 패키지.

설계 원칙:
- 대화 시스템(`chatbot/`)과 RAG 패턴 박물관(`rag_core/`)을 분리한다.
- 챗봇이 RAG 를 도구처럼 호출한다. 그 반대가 아니다.
- 도메인은 프레임워크 무지(Framework-agnostic) — 다른 레이어를 import 하지 않는다.

레이어:
- `chatbot.domain`        : 불변 모델 + Protocol (포트). 외부 의존성 0.
- `chatbot.application`   : 오케스트레이터 + 노드. 도메인만 의존.
- `chatbot.infrastructure`: 어댑터 (RAG 모드, MCP, LLM, Store, ...). 도메인 구현.
"""
