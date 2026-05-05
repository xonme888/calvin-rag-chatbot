"""FAISS 인덱스 디스크 캐싱.

칼빈 강요 같은 큰 데이터를 매번 임베딩하면 비용/시간 낭비.
첫 실행 시 디스크에 저장, 이후엔 즉시 로드.

인덱스 디렉토리는 환경변수 ``INDEX_DIR``로 override 가능.
미설정 시 이 repo의 ``indexes/``를 사용.
학습 repo와 캐시를 공유하려면 환경변수에 절대경로 지정.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

# 프로젝트 루트 (calvin-rag-chatbot/) 기준 인덱스 경로 fallback
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_index_dir() -> Path:
    """인덱스 디렉토리를 결정한다.

    우선순위:
        1. 환경변수 ``INDEX_DIR``
        2. 이 repo의 ``indexes/`` (fallback)
    """
    env_path = os.getenv("INDEX_DIR", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return PROJECT_ROOT / "indexes"


# 모듈 레벨 상수: import 시점에 한 번 결정
INDEX_DIR = _resolve_index_dir()


def make_cache_key(*parts: str) -> str:
    """캐시 키를 안전한 디렉토리명으로 변환한다.

    예: make_cache_key("calvin", "chunk500", "overlap50")
        → "calvin__chunk500__overlap50"
    """
    safe = "__".join(str(p) for p in parts)
    if len(safe) > 80:
        return hashlib.md5(safe.encode()).hexdigest()[:16]
    return safe


def cache_path(cache_key: str) -> Path:
    """캐시 디렉토리 경로를 반환한다."""
    return INDEX_DIR / cache_key


def has_cache(cache_key: str) -> bool:
    """캐시 존재 여부."""
    p = cache_path(cache_key)
    return p.exists() and (p / "index.faiss").exists()


def build_or_load_faiss(
    cache_key: str,
    chunks: list[Document],
    embeddings: Embeddings,
    rebuild: bool = False,
) -> FAISS:
    """FAISS 인덱스를 캐시에서 로드하거나 새로 빌드한다.

    Args:
        cache_key: 캐시 식별자 (chunk_size, overlap 등을 반영해 만들기를 권장)
        chunks: 빌드 시 사용할 청크 리스트
        embeddings: 빌드 시 사용할 임베딩 모델
        rebuild: True면 캐시 무시하고 강제 재빌드

    Returns:
        FAISS 벡터 저장소

    Notes:
        - allow_dangerous_deserialization=True 사용 (FAISS pickle 로드 필요)
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    target = cache_path(cache_key)

    if has_cache(cache_key) and not rebuild:
        print(f"캐시에서 인덱스 로드: {target}")
        return FAISS.load_local(
            str(target),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    print(f"인덱스 신규 빌드: {len(chunks)}개 청크 임베딩 중...")
    vector_store = FAISS.from_documents(chunks, embeddings)
    vector_store.save_local(str(target))
    print(f"인덱스 저장: {target}")
    return vector_store


def load_chunks_from_cache(
    cache_key: str,
    embeddings: Embeddings,
) -> tuple[list[Document], FAISS]:
    """캐시된 FAISS 인덱스를 로드해 chunks + vector_store 를 복원한다.

    PDF 없이 부팅 가능하게 만드는 핵심. FAISS docstore 가 청크 메타까지 보존하므로
    원본 문서를 다시 읽지 않고도 retriever 재구성에 필요한 정보가 모두 들어 있다.

    Args:
        cache_key: 캐시 식별자
        embeddings: vector_store 에 바인딩될 임베딩 모델

    Returns:
        (chunks, vector_store) 튜플. caller 가 BM25/Hybrid retriever 재구성에 사용.

    Raises:
        FileNotFoundError: 캐시가 존재하지 않을 때
    """
    if not has_cache(cache_key):
        raise FileNotFoundError(f"캐시 없음: {cache_path(cache_key)}")

    target = cache_path(cache_key)
    vector_store = FAISS.load_local(
        str(target),
        embeddings,
        allow_dangerous_deserialization=True,
    )
    # FAISS InMemoryDocstore — _dict 는 Document 객체 그대로 보존
    chunks = list(vector_store.docstore._dict.values())
    return chunks, vector_store


def clear_cache(cache_key: str) -> bool:
    """특정 캐시를 삭제한다.

    Returns:
        삭제했으면 True, 없었으면 False
    """
    target = cache_path(cache_key)
    if not target.exists():
        return False
    import shutil

    shutil.rmtree(target)
    return True
