"""한국어 토크나이저 + BM25 키워드 검색기.

운영 환경에선 Mecab/Komoran 등 형태소 분석기 사용을 권장.
이 구현은 정규식 기반 단순 분리 + 1글자 토큰 제거로 학습/시연용.
"""

from __future__ import annotations

import re

import numpy as np
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi


class KoreanTokenizer:
    """간단한 한국어 토크나이저 (형태소 분석 대용)."""

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """텍스트를 토큰으로 분리한다.

        - 특수문자 제거 후 공백 단위로 분리
        - 1글자 토큰 제거
        """
        text = re.sub(r"[^\w\s가-힣]", " ", text)
        tokens = text.lower().split()
        return [t for t in tokens if len(t) > 1]


class BM25Retriever:
    """BM25 기반 키워드 검색기."""

    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.tokenizer = KoreanTokenizer()
        self.tokenized_docs = [self.tokenizer.tokenize(doc.page_content) for doc in documents]
        self.bm25 = BM25Okapi(self.tokenized_docs)

    def search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        """BM25 점수 기반 검색.

        Returns:
            (Document, score) 튜플 리스트. 점수 0 초과만 포함.
        """
        tokenized_query = self.tokenizer.tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = np.argsort(scores)[::-1][:k]

        results: list[tuple[Document, float]] = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self.documents[idx], float(scores[idx])))
        return results
