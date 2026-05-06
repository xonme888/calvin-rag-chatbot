"""첨부 서버측 검증 — MIME 화이트리스트, 크기, 개수, data_url 형식.

PRD-001 의 vision 게이팅 부분 충족. 클라이언트 검증 (web/AttachmentInput.tsx 의 25MB
원본 / 2MB 리사이즈) 만으로는 *악의적 우회* 가능 — 본 레이어가 마지막 차단선.

design:
- 검증 실패 시 ``AttachmentValidationError`` 발생. 호출자(strategy) 가 ``ToolResult.is_error``
  또는 사용자 안내 메시지로 변환.
- 매직 바이트 검증은 본 phase 미포함 — ``python-magic`` 의존성 도입 결정 후 별도 PR.
- MAX_ATTACHMENTS = 4 — vision 1회당 이미지 4장 한도. 비용 폭주 방어.
"""

from __future__ import annotations

import re

from chatbot.domain.conversation import Attachment


class AttachmentValidationError(ValueError):
    """첨부가 정책 위반. 메시지에 위반 사유 1개를 명시."""


# data:image/<mime>;base64,<...>  형식 강제. http(s):// URL 도 허용.
_DATA_URL_RE = re.compile(r"^data:(image/[a-z0-9.+\-]+);base64,(.+)$", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class AttachmentValidator:
    """첨부 1건 또는 시퀀스를 검증. 인스턴스화 후 ``validate`` 1회 호출.

    DEFAULT 한도:
    - ALLOWED_MIME = jpeg/png/webp/gif (이미지만)
    - MAX_DATA_URL_BYTES = 10MB (base64 ~7MB 원본 이미지)
    - MAX_ATTACHMENTS = 4 (vision 1회당 비용 cap)

    호출자가 한도를 조정할 수 있도록 모두 생성자 인자.
    """

    DEFAULT_ALLOWED_MIME: frozenset[str] = frozenset(
        {
            "image/jpeg",
            "image/jpg",
            "image/png",
            "image/webp",
            "image/gif",
        }
    )
    DEFAULT_MAX_DATA_URL_BYTES: int = 10 * 1024 * 1024
    DEFAULT_MAX_ATTACHMENTS: int = 4

    def __init__(
        self,
        *,
        allowed_mime: frozenset[str] | None = None,
        max_data_url_bytes: int | None = None,
        max_attachments: int | None = None,
    ) -> None:
        self._allowed_mime = allowed_mime or self.DEFAULT_ALLOWED_MIME
        self._max_bytes = max_data_url_bytes or self.DEFAULT_MAX_DATA_URL_BYTES
        self._max_count = max_attachments or self.DEFAULT_MAX_ATTACHMENTS

    def validate_all(self, attachments: list[Attachment]) -> None:
        """시퀀스 단위 검증 — 개수 + 각 항목. 위반 시 즉시 raise."""
        if len(attachments) > self._max_count:
            raise AttachmentValidationError(
                f"첨부 개수 한도 초과: {len(attachments)} > {self._max_count}"
            )
        for att in attachments:
            self.validate(att)

    def validate(self, attachment: Attachment) -> None:
        """단일 첨부 검증. data_url 형식·MIME·크기를 차례로 본다."""
        if attachment.kind == "image_url":
            self._validate_url_value(attachment.value)
            return
        if attachment.kind == "image_base64":
            self._validate_data_url_value(attachment.value)
            return
        # frozen Literal 의 케이스 외 — 정의 변경 시 도달
        raise AttachmentValidationError(f"지원하지 않는 첨부 종류: {attachment.kind}")

    def _validate_url_value(self, value: str) -> None:
        """https:// URL 또는 data: URL 둘 다 허용."""
        if _DATA_URL_RE.match(value):
            self._validate_data_url_value(value)
            return
        if not _HTTP_URL_RE.match(value):
            raise AttachmentValidationError(
                "URL 형식이 아닙니다 (http(s):// 또는 data:image/... 만 허용)"
            )

    def _validate_data_url_value(self, value: str) -> None:
        match = _DATA_URL_RE.match(value)
        if not match:
            raise AttachmentValidationError(
                "data URL 형식이 아닙니다 (data:image/<mime>;base64,...)"
            )
        mime = match.group(1).lower()
        if mime not in self._allowed_mime:
            raise AttachmentValidationError(
                f"비허용 MIME 타입: {mime} (허용: {sorted(self._allowed_mime)})"
            )
        # 길이 검증 — base64 디코딩 없이 *문자열 길이* 만 본다 (성능).
        if len(value) > self._max_bytes:
            raise AttachmentValidationError(
                f"data URL 크기 한도 초과: {len(value)} > {self._max_bytes}"
            )
