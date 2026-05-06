"""Retriever 어댑터 — domain.Retriever Protocol 구현.

각 어댑터는 *검색 알고리즘 1개* 만 책임진다. 합성(예: BM25+Dense RRF)은
별도 어댑터 (``HybridRetriever``) 가 두 retriever 를 받아 조립한다.
"""

from chatbot.infrastructure.retrievers._converters import to_document_ref
from chatbot.infrastructure.retrievers.bm25_retriever import BM25Retriever
from chatbot.infrastructure.retrievers.dense_retriever import DenseRetriever
from chatbot.infrastructure.retrievers.hybrid_retriever import HybridRetriever

__all__ = ["to_document_ref", "BM25Retriever", "DenseRetriever", "HybridRetriever"]
