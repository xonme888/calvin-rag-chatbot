"""AttachmentValidator 테스트 — MIME 화이트리스트 / 크기 / 개수 / data_url 형식."""

from __future__ import annotations

import pytest

from chatbot.domain.conversation import Attachment
from chatbot.infrastructure.validation import (
    AttachmentValidationError,
    AttachmentValidator,
)


def test_정상_https_url():
    AttachmentValidator().validate(Attachment(kind="image_url", value="https://example.com/x.jpg"))


def test_정상_data_url_허용된_MIME():
    AttachmentValidator().validate(
        Attachment(kind="image_base64", value="data:image/png;base64,iVBOR")
    )
    AttachmentValidator().validate(
        Attachment(kind="image_base64", value="data:image/jpeg;base64,abc")
    )
    AttachmentValidator().validate(
        Attachment(kind="image_base64", value="data:image/webp;base64,abc")
    )


def test_비허용_MIME_거부():
    with pytest.raises(AttachmentValidationError, match="MIME"):
        AttachmentValidator().validate(
            Attachment(kind="image_base64", value="data:image/svg+xml;base64,abc")
        )


def test_data_URL_형식_X_거부():
    with pytest.raises(AttachmentValidationError, match="data URL"):
        AttachmentValidator().validate(Attachment(kind="image_base64", value="not_a_data_url"))


def test_image_url_kind_으로_data_url_도_허용():
    """image_url kind 라도 value 가 data URL 이면 통과 (web 클라가 보낸 형식 호환)."""
    AttachmentValidator().validate(Attachment(kind="image_url", value="data:image/png;base64,abc"))


def test_image_url_kind_비_http_거부():
    with pytest.raises(AttachmentValidationError, match="URL 형식"):
        AttachmentValidator().validate(Attachment(kind="image_url", value="ftp://x.com/x.jpg"))


def test_크기_초과_거부():
    v = AttachmentValidator(max_data_url_bytes=50)
    long_value = "data:image/png;base64," + "a" * 100
    with pytest.raises(AttachmentValidationError, match="크기"):
        v.validate(Attachment(kind="image_base64", value=long_value))


def test_validate_all_개수_초과_거부():
    v = AttachmentValidator(max_attachments=2)
    atts = [Attachment(kind="image_url", value="https://x") for _ in range(3)]
    with pytest.raises(AttachmentValidationError, match="개수"):
        v.validate_all(atts)


def test_validate_all_정상_개수():
    v = AttachmentValidator()
    atts = [Attachment(kind="image_url", value="https://x") for _ in range(4)]
    v.validate_all(atts)


def test_default_한도():
    v = AttachmentValidator()
    assert v._allowed_mime == AttachmentValidator.DEFAULT_ALLOWED_MIME
    assert v._max_bytes == AttachmentValidator.DEFAULT_MAX_DATA_URL_BYTES
    assert v._max_count == AttachmentValidator.DEFAULT_MAX_ATTACHMENTS
