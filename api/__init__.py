"""Calvin RAG Chatbot — FastAPI 백엔드.

Phase 2 마이그레이션 (`docs/me/010`) 산출물.

Hexagonal Port/Adapter 자산 재사용:
- ``rag_core/`` (HybridRAG / AgenticRAG / KnowledgeGraphRAG / GuardrailPort 등)
- ``infra/`` (env / document_loader / index_cache / usage_tracker)

Streamlit (`app/`) 과 공존하며, D+8 시점에 Streamlit 폐기 예정.
"""
