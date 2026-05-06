"""Attachment 시퀀스 → OpenAI multimodal payload 변환 단계.

기존 ``rag_core/vision_rag.py:79-94`` 의 ``human_content`` 조립 로직을 *Stage* 로 격리.
``detail="low"`` 는 비용 가드 (이미지 1장 = 65 토큰 고정) — config 로 노출 가능하나
디폴트 보수적.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from chatbot.domain.conversation import Attachment


class PreparedPayload(TypedDict):
    """OpenAI multimodal HumanMessage.content 에 들어가는 dict 시퀀스 + 텍스트."""

    text: str
    parts: list[dict[str, Any]]
    """``[{"type": "text", "text": ...}, {"type": "image_url", "image_url": {...}}, ...]``"""


class PrepareImagePayloadStage:
    """Attachment list + 질문 텍스트 → OpenAI multimodal payload."""

    name: str = "prepare_image_payload"

    def __init__(self, *, detail: Literal["low", "high", "auto"] = "low") -> None:
        self._detail = detail

    def run(self, input: tuple[str, list[Attachment]]) -> PreparedPayload:
        """``(question, attachments)`` 튜플 입력 → PreparedPayload.

        Stage Protocol 의 단일 인자 제약을 *튜플 envelope* 으로 풀어냄. text 와 attachments
        가 항상 함께 전달되어야 하므로 별도 envelope 클래스보다 튜플이 가벼움.
        """
        question, attachments = input
        parts: list[dict[str, Any]] = [{"type": "text", "text": question}]
        for att in attachments:
            url = att.value
            if not url:
                continue
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": url, "detail": self._detail},
                }
            )
        return PreparedPayload(text=question, parts=parts)
