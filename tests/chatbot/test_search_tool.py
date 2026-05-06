"""SearchDocumentsTool 테스트 — 도메인 Tool 으로서의 동작 검증."""

from __future__ import annotations

from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.tools.search import SearchDocumentsTool


class _FakeRetriever:
    name = "fake"

    def __init__(self, refs: list[DocumentRef]) -> None:
        self.refs = refs
        self.last: RetrievalRequest | None = None

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        self.last = request
        return list(self.refs)


def _calvin_refs() -> list[DocumentRef]:
    return [
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:1",
            page=779,
            content="예정론 본문",
        ),
        DocumentRef(
            corpus_id="calvin",
            source_id="institutes_v1",
            chunk_id="c:2",
            page=149,
            content="베자 본문",
        ),
    ]


def test_search_tool_정상_검색():
    retriever = _FakeRetriever(_calvin_refs())
    tool = SearchDocumentsTool(retriever)
    result = tool.invoke({"query": "예정론", "k": 3})
    assert result.is_error is False
    assert "[page 780]" in result.content
    assert "[page 150]" in result.content
    assert "\n\n---\n\n" in result.content
    assert result.metadata["doc_count"] == "2"
    assert retriever.last.standalone_question == "예정론"
    assert retriever.last.top_k == 3


def test_search_tool_빈_쿼리_is_error():
    tool = SearchDocumentsTool(_FakeRetriever([]))
    result = tool.invoke({"query": ""})
    assert result.is_error is True


def test_search_tool_k_default_5():
    retriever = _FakeRetriever(_calvin_refs())
    tool = SearchDocumentsTool(retriever)
    tool.invoke({"query": "예정론"})
    assert retriever.last.top_k == 5


def test_search_tool_k_상한_20_캡():
    retriever = _FakeRetriever(_calvin_refs())
    tool = SearchDocumentsTool(retriever)
    tool.invoke({"query": "예정론", "k": 100})
    assert retriever.last.top_k == 20


def test_search_tool_k_하한_1():
    retriever = _FakeRetriever(_calvin_refs())
    tool = SearchDocumentsTool(retriever)
    tool.invoke({"query": "예정론", "k": 0})
    assert retriever.last.top_k == 1


def test_search_tool_k_타입_오류_default_사용():
    retriever = _FakeRetriever(_calvin_refs())
    tool = SearchDocumentsTool(retriever)
    tool.invoke({"query": "예정론", "k": "abc"})  # type: ignore[dict-item]
    assert retriever.last.top_k == 5


def test_search_tool_빈_결과_안내_메시지():
    tool = SearchDocumentsTool(_FakeRetriever([]))
    result = tool.invoke({"query": "없는키워드"})
    assert result.is_error is False
    assert "찾을 수 없" in result.content


def test_search_tool_RuntimeError_is_error():
    class _Broken:
        name = "broken"

        def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
            raise RuntimeError("인덱싱 안됨")

    tool = SearchDocumentsTool(_Broken())
    result = tool.invoke({"query": "q"})
    assert result.is_error is True
    assert "초기화" in result.content
