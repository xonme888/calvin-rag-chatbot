"""검색 추상화 — RetrieverPort + HybridRetriever 구현.

배경: HybridRAG 안에 BM25+Dense+RRF 검색 인프라가 박혀 있었고, Agentic/KG가
HybridRAG 객체 통째를 받아 ``_reciprocal_rank_fusion`` 같은 비공개 메서드를
직접 호출 — 캡슐화 위반 4곳에서 같은 검색 로직이 복제됨.

이 모듈은 KG 백엔드 추상화(``KnowledgeGraphPort``)와 동일 사상으로 검색을 분리:
- ``RetrieverPort``: 도메인 인터페이스 (Protocol)
- ``HybridRetriever``: BM25+Dense+RRF 구현

향후 Dense-only, Graph-augmented retrieval 등 대안 구현을 추가할 때
``RetrieverPort`` 만 만족시키면 RAG 본체 코드는 무수정.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_core.tokenizer import BM25Retriever


@runtime_checkable
class RetrieverPort(Protocol):
    """검색 추상화 인터페이스. RAG 본체가 이 Port에만 의존."""

    def index_documents(self, documents: list[Document]) -> int:
        """문서를 청크로 나눠 인덱싱. 인덱싱된 청크 수 반환."""
        ...

    def retrieve(self, question: str, k: int = 5) -> list[Document]:
        """질문에 대한 top-k 문서 반환. 점수 없이 문서만."""
        ...

    def retrieve_with_scores(self, question: str, k: int = 5) -> list[tuple[Document, float]]:
        """top-k 문서 + 점수. 메타데이터/디버깅에 활용."""
        ...


class HybridRetriever:
    """BM25(키워드) + Dense(의미) + RRF 결합 검색.

    KG 백엔드 추상화와 대칭으로 검색 인프라를 RAG 본체에서 분리.
    HybridRAG/AgenticRAG/KnowledgeGraphRAG 가 모두 이 RetrieverPort 구현체를 공유.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        dense_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> None:
        """HybridRetriever 인스턴스를 생성.

        Args:
            embeddings: 벡터 임베딩 (OpenAIEmbeddings 등).
            chunk_size: 청크 분할 크기.
            chunk_overlap: 청크 간 겹침.
            dense_weight: RRF에서 Dense 가중치 (0~1). BM25는 1-dense_weight.
            rrf_k: RRF 상수 (보통 60).
        """
        self.embeddings = embeddings
        self.dense_weight = dense_weight
        self.rrf_k = rrf_k

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n---\n", "\n\n", "\n", ".", " "],
        )

        self.vector_store: FAISS | None = None
        self.bm25_retriever: BM25Retriever | None = None
        self.chunks: list[Document] = []

    # ================================================================
    # RetrieverPort 구현
    # ================================================================
    def index_documents(self, documents: list[Document]) -> int:
        """문서를 청크로 나눠 BM25 + FAISS 양쪽에 인덱싱."""
        chunks = self.text_splitter.split_documents(documents)
        self.chunks = chunks
        self.bm25_retriever = BM25Retriever(chunks)
        self.vector_store = FAISS.from_documents(chunks, self.embeddings)
        return len(chunks)

    def load_prebuilt_index(
        self,
        chunks: list[Document],
        vector_store: FAISS,
    ) -> None:
        """디스크 캐시에서 미리 빌드된 FAISS 인덱스를 적용한다.

        ``index_documents`` 가 매번 임베딩을 호출하는 반면, 이 메서드는 기존
        벡터 스토어를 그대로 받아 임베딩 비용을 0으로 만든다 (디스크 캐시 활용).
        BM25 인덱스는 메모리 기반이라 매번 다시 빌드.

        Args:
            chunks: 분할된 청크 (외부에서 ``text_splitter.split_documents()`` 로 분할)
            vector_store: 디스크 캐시에서 로드한 FAISS 인스턴스
        """
        self.chunks = chunks
        self.vector_store = vector_store
        self.bm25_retriever = BM25Retriever(chunks)

    def retrieve(self, question: str, k: int = 5) -> list[Document]:
        return [doc for doc, _ in self.retrieve_with_scores(question, k=k)]

    def retrieve_with_scores(self, question: str, k: int = 5) -> list[tuple[Document, float]]:
        _, _, fused = self.retrieve_split(question, k=k)
        return fused[:k]

    # ================================================================
    # 디버깅/메타데이터용 분리 결과 노출
    # ================================================================
    def retrieve_split(
        self, question: str, k: int = 5
    ) -> tuple[
        list[tuple[Document, float]],
        list[tuple[Document, float]],
        list[tuple[Document, float]],
    ]:
        """검색 결과를 (bm25, dense, fused) 3종으로 반환.

        RAG 메타데이터에 ``bm25_count``, ``rrf_top_scores`` 등을 노출하기 위함.
        """
        if self.vector_store is None or self.bm25_retriever is None:
            raise RuntimeError("먼저 index_documents()를 호출하세요.")

        bm25_results = self.bm25_retriever.search(question, k=k)
        dense_results = self.vector_store.similarity_search_with_score(question, k=k)
        fused = self.reciprocal_rank_fusion(bm25_results, dense_results)
        return bm25_results, dense_results, fused

    def reciprocal_rank_fusion(
        self,
        bm25_results: list[tuple[Document, float]],
        dense_results: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        """두 검색 결과를 RRF로 결합.

        score(d) = Σ weight_i / (k + rank_i(d))

        점수가 아닌 *순위* 만 사용하므로 스케일 정규화 불필요.
        Public 메서드 — Agentic/KG 등 외부에서도 사용 가능 (캡슐화 위반 해소).
        """
        k = self.rrf_k
        bm25_weight = 1.0 - self.dense_weight
        dense_weight = self.dense_weight

        rrf_scores: dict[int, float] = {}
        doc_map: dict[int, Document] = {}

        for rank, (doc, _score) in enumerate(bm25_results, start=1):
            key = hash(doc.page_content)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + bm25_weight / (k + rank)
            doc_map[key] = doc

        for rank, (doc, _score) in enumerate(dense_results, start=1):
            key = hash(doc.page_content)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + dense_weight / (k + rank)
            doc_map[key] = doc

        sorted_keys = sorted(rrf_scores, key=lambda k_: rrf_scores[k_], reverse=True)
        return [(doc_map[k_], rrf_scores[k_]) for k_ in sorted_keys]
