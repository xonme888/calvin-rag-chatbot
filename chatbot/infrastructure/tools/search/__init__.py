"""검색 도구 모음 — corpus 본문 검색을 LLM 도구로 노출.

각 도구는 *한 검색 알고리즘 또는 한 corpus 의 검색* 만 책임진다.
새 도구 = 본 디렉토리에 1개 파일 + ToolRegistry 등록.
"""

from chatbot.infrastructure.tools.search.search_documents import SearchDocumentsTool

__all__ = ["SearchDocumentsTool"]
