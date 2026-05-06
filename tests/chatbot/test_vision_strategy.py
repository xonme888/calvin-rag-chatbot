"""VisionStrategy 합성 테스트 — Fake LLM 으로 LLM 호출 0회."""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from chatbot.domain.conversation import Attachment
from chatbot.domain.corpus import DocumentRef
from chatbot.domain.retrieval import RetrievalRequest
from chatbot.infrastructure.stages import PrepareImagePayloadStage
from chatbot.infrastructure.strategies import VisionStrategy, VisionStrategyConfig
from chatbot.infrastructure.validation import AttachmentValidator


class _FakeRetriever:
    name = "fake"

    def retrieve(self, request: RetrievalRequest) -> list[DocumentRef]:
        return [
            DocumentRef(
                corpus_id="calvin",
                source_id="institutes_v1",
                chunk_id="c:1",
                page=779,
                content="예정론 본문",
            )
        ]


@pytest.fixture(autouse=True)
def _isolate_vision_env(monkeypatch):
    monkeypatch.delenv("VISION_ENABLED", raising=False)
    monkeypatch.delenv("VISION_WITH_RETRIEVAL", raising=False)


def _make(*, with_retriever: bool = False, llm_response: str = "이미지 분석 결과"):
    return VisionStrategy(
        llm=FakeListChatModel(responses=[llm_response]),
        validator=AttachmentValidator(),
        prepare_stage=PrepareImagePayloadStage(),
        text_retriever=_FakeRetriever() if with_retriever else None,
        config=VisionStrategyConfig(),
    )


def _att(value: str = "https://x.com/img.jpg") -> Attachment:
    return Attachment(kind="image_url", value=value)


def test_name_label():
    s = _make()
    assert s.name == "vision"
    assert s.label == "Vision"


def test_is_available_VISION_ENABLED_미설정시_False():
    s = _make()
    ok, reason = s.is_available()
    assert ok is False
    assert "VISION_ENABLED" in (reason or "")


def test_is_available_VISION_ENABLED_truthy_True(monkeypatch):
    monkeypatch.setenv("VISION_ENABLED", "true")
    ok, _ = _make().is_available()
    assert ok is True


def test_supports_attachments_있을때만_True():
    s = _make()
    assert s.supports(RetrievalRequest(standalone_question="?")) is False
    assert s.supports(RetrievalRequest(standalone_question="?", attachments=(_att(),))) is True


def test_run_정상_envelope():
    s = _make(llm_response="이미지에 표지가 보입니다")
    req = RetrievalRequest(standalone_question="이 도판은?", attachments=(_att(),))
    result = s.run(req)
    assert result.metadata["pattern"] == "Vision"
    assert result.metadata["attachment_count"] == "1"
    assert result.metadata["with_retrieval"] == "false"
    assert "이미지에 표지" in result.metadata["answer"]
    assert len(result.documents) == 0
    assert len(result.citations) == 0


def test_run_text_retriever_미통합_default():
    """text_retriever 가 주입되어도 VISION_WITH_RETRIEVAL 미설정 시 검색 안 함."""
    s = _make(with_retriever=True)
    result = s.run(RetrievalRequest(standalone_question="?", attachments=(_att(),)))
    assert result.metadata["with_retrieval"] == "false"
    assert len(result.documents) == 0


def test_run_text_retriever_env_flag_활성(monkeypatch):
    monkeypatch.setenv("VISION_WITH_RETRIEVAL", "1")
    s = _make(with_retriever=True, llm_response="답변 [p.780]")
    result = s.run(RetrievalRequest(standalone_question="?", attachments=(_att(),)))
    assert result.metadata["with_retrieval"] == "true"
    assert len(result.documents) == 1
    # cited_pages [780] → DocumentRef.page=779 매칭 → citation 1개
    assert len(result.citations) == 1
    assert "p.780" in result.citations[0].page_label


def test_run_검증_실패_사과_메시지():
    """비허용 MIME → AttachmentValidationError → 사과 메시지 + validation_error 메타."""
    s = _make()
    bad = Attachment(kind="image_base64", value="data:image/svg+xml;base64,abc")
    req = RetrievalRequest(standalone_question="?", attachments=(bad,))
    result = s.run(req)
    assert "validation_error" in result.metadata
    assert "MIME" in result.metadata["validation_error"]
    assert result.metadata["answer"].startswith("첨부")
    assert result.documents == ()


def test_run_검증_실패_LLM_미호출():
    """첨부 검증 실패 시 LLM 호출이 없어야 — FakeListChatModel responses 가 소진되지 않음."""
    llm = FakeListChatModel(responses=["should_not_be_called"])
    s = VisionStrategy(
        llm=llm,
        validator=AttachmentValidator(),
        prepare_stage=PrepareImagePayloadStage(),
        config=VisionStrategyConfig(),
    )
    bad = Attachment(kind="image_base64", value="not_data_url")
    req = RetrievalRequest(standalone_question="?", attachments=(bad,))
    s.run(req)
    # LLM 호출 0회 — i 인덱스가 0 (소진 안 됨)
    assert llm.i == 0
