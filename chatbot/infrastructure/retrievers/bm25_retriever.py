"""BM25 키워드 검색 어댑터.

기존 ``rag_core/tokenizer.py`` 의 KoreanTokenizer + BM25Retriever 를 본 어댑터가
래핑한다. 도메인 Retriever Protocol 의 ``retrieve(request)`` 시그니처에 맞춰
DocumentRef 를 반환한다.

향후 형태소 분석기(Mecab/Komoran) 교체는 본 파일의 tokenizer 만 갈아끼우면 된다.
"""

from __future__ import annotations

from langchain_core.documents import Document

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.retrievers._converters import to_document_ref
from rag_core.tokenizer import BM25Retriever as _LegacyBM25


class BM25Retriever:
    """BM25Okapi 기반 키워드 검색 — domain.Retriever 구현.

    인덱싱 책임은 본 클래스가 갖지 않는다. 이미 분할된 chunk(LangChain Document)
    리스트를 생성자에 받아 BM25 인덱스를 구축한다 — corpus 빌더가 한 번 호출.
    """

    name: str = "bm25"

    def __init__(
        self,
        chunks: list[Document],
        *,
        default_corpus_id: str = "",
        default_source_id: str = "",
    ) -> None:
        self._chunks = chunks
        self._impl = _LegacyBM25(chunks)
        self._default_corpus_id = default_corpus_id
        self._default_source_id = default_source_id

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        results = self._impl.search(request.standalone_question, k=request.top_k)
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
        # corpus_ids 필터 — vector store 와 달리 BM25 는 metadata filter 가 없으므로 post-filter
        if request.corpus_ids is not None:
            refs = [r for r in refs if r.corpus_id in request.corpus_ids]
        return refs
