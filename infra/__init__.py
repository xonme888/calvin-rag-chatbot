"""Calvin RAG Chatbot - 인프라 어댑터.

환경변수, 파일 로더, 인덱스 캐싱 등 외부 시스템과의 경계.
"""

from infra.document_loader import (
    CALVIN_PDF_PATH,
    DATA_DIR,
    load_calvin,
    load_pdf,
    load_text_file,
)
from infra.env_loader import load_env
from infra.index_cache import (
    INDEX_DIR,
    build_or_load_faiss,
    clear_cache,
    has_cache,
    make_cache_key,
)

__all__ = [
    "CALVIN_PDF_PATH",
    "DATA_DIR",
    "INDEX_DIR",
    "build_or_load_faiss",
    "clear_cache",
    "has_cache",
    "load_calvin",
    "load_env",
    "load_pdf",
    "load_text_file",
    "make_cache_key",
]
