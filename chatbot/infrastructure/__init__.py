"""Infrastructure 레이어 — 도메인 Protocol 의 어댑터.

규칙:
- 도메인 의존성은 자유롭게 import 가능 (chatbot.domain.*).
- LangChain/FAISS/Neo4j 등 외부 SDK 의존은 본 레이어 안에서만.
- 어댑터는 *기존 rag_core 의 자산을 재사용* 한다 — 코드 중복 금지.
"""
