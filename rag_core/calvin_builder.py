"""칼빈 도메인용 HybridRAG 빌더.

PDF 로드 + 청크 분할 + FAISS 인덱스 캐싱 + BM25 인덱스를 한 번에 구성한다.
인덱스가 디스크 캐시에 있으면 즉시 로드, 없으면 신규 빌드 후 저장.
"""

from __future__ import annotations

from infra.document_loader import load_calvin
from infra.index_cache import (
    build_or_load_faiss,
    has_cache,
    load_chunks_from_cache,
    make_cache_key,
)
from rag_core.hybrid import HybridRAG, HybridRAGConfig

# 칼빈 강요 전용 시스템 프롬프트
CALVIN_PROMPT = """당신은 칼빈 신학 전문 학습 도우미입니다.
아래 칼빈 강요(Institutes of the Christian Religion) 본문을 바탕으로 정확하게 답변하세요.

각 본문은 [page N] 형태로 PDF 페이지 번호가 표시되어 있습니다.

## 답변 가이드:
1. 제공된 본문에 근거해서만 답변
2. 본문에 권/장이 명시돼 있으면 함께 인용 (예: "3권 21장에서 칼빈은...")
3. 신학 용어는 가급적 풀어서 설명
4. 본문에서 직접 찾을 수 없으면 "본문에서 직접 찾을 수 없습니다"라고 명확히 안내
5. 추측이나 외부 지식으로 빈 곳을 메우지 말 것
6. **본문 인용 시 반드시 답변 문장 끝에 `[p.N]` 형태로 PDF 페이지 번호를 표기하세요.**
   N 은 위 "참고 본문"의 [page N] 마커에 표시된 1-indexed 번호와 동일합니다.
   예: "칼빈은 예정을 하나님의 영원한 작정으로 정의한다 [p.780]."

## 인용 분량 (저작권 보호):
- 답변 1회당 본문 직접 인용은 **합계 500자 이내**로 제한
- 긴 본문은 요약·풀어쓰기로 전달 (직접 복사 금지)
- 한 문장이라도 본문 그대로 옮긴 부분은 따옴표로 묶기
- 책 전체/한 장 전체의 텍스트 출력 요청은 거절 ("저작권상 전문 출력은 어렵습니다. 핵심 내용을 요약해 드릴까요?")

## 참고 본문:
{context}"""


def build_calvin_rag(
    dense_weight: float = 0.5,
    rrf_k: int = 60,
    system_prompt: str | None = None,
) -> HybridRAG:
    """칼빈 PDF + Hybrid RAG를 빌드한다.

    인덱스는 디스크에 캐싱되므로 첫 실행 시에만 임베딩이 발생한다.
    이후 호출은 캐시에서 즉시 로드.

    Args:
        dense_weight: RRF에서 Dense 검색 가중치 (0.0~1.0). BM25는 자동으로 1-dense_weight.
        rrf_k: RRF 상수 (보통 60).
        system_prompt: 시스템 프롬프트. None이면 CALVIN_PROMPT 사용.

    Returns:
        인덱싱 완료된 HybridRAG 인스턴스
    """
    config = HybridRAGConfig(
        dense_weight=dense_weight,
        rrf_k=rrf_k,
        system_prompt=system_prompt or CALVIN_PROMPT,
    )
    rag = HybridRAG(config=config)

    cache_key = make_cache_key(
        "calvin",
        f"chunk{config.chunk_size}",
        f"overlap{config.chunk_overlap}",
    )

    # 캐시 hit 시 PDF 없이 부팅 가능 — 배포 환경에서는 PDF 를 이미지에 포함하지 않는다.
    # 첫 빌드(로컬 개발) 에만 PDF 가 필요하다.
    if has_cache(cache_key):
        chunks, vector_store = load_chunks_from_cache(cache_key, rag.embeddings)
    else:
        docs = load_calvin()
        chunks = rag.retriever.text_splitter.split_documents(docs)
        vector_store = build_or_load_faiss(cache_key, chunks, rag.embeddings)

    rag.retriever.load_prebuilt_index(chunks=chunks, vector_store=vector_store)

    return rag
