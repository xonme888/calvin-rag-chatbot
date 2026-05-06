"""FAISS Dense 검색 어댑터.

생성자에 *이미 빌드된 vector_store* 를 받는다. 인덱스 빌드/로딩은 corpus 빌더 책임 —
캐싱·임베딩 호출은 ``infra.index_cache`` 가 담당하고, 본 어댑터는 *조회만* 한다.

대안 vector store(Qdrant/PG) 도입 시 본 파일을 복제해 어댑터 1개 추가하면 된다 —
domain.Retriever Protocol 만 만족하면 다른 코드는 무수정.
"""

from __future__ import annotations

from langchain_community.vectorstores import FAISS

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.retrievers._converters import to_document_ref


class DenseRetriever:
    """FAISS similarity search — domain.Retriever 구현."""

    name: str = "dense"

    def __init__(
        self,
        vector_store: FAISS,
        *,
        default_corpus_id: str = "",
        default_source_id: str = "",
    ) -> None:
        self._store = vector_store
        self._default_corpus_id = default_corpus_id
        self._default_source_id = default_source_id

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        results = self._store.similarity_search_with_score(
            request.standalone_question, k=request.top_k
        )
        refs = [
            to_document_ref(
                content=doc.page_content,
                metadata=dict(doc.metadata),
                score=score,
                default_corpus_id=self._default_corpus_id,
                default_source_id=self._default_source_id,
            )
            for doc, score in results
        ]
        if request.corpus_ids is not None:
            refs = [r for r in refs if r.corpus_id in request.corpus_ids]
        return refs
