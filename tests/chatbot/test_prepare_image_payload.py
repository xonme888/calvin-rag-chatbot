"""PrepareImagePayloadStage 테스트 — Attachment → OpenAI multimodal payload."""

from __future__ import annotations

from chatbot.domain.conversation import Attachment
from chatbot.infrastructure.stages import PrepareImagePayloadStage


def test_단일_이미지_텍스트():
    out = PrepareImagePayloadStage().run(
        ("이 도판은?", [Attachment(kind="image_url", value="https://x.com/img.jpg")])
    )
    assert out["text"] == "이 도판은?"
    assert len(out["parts"]) == 2
    assert out["parts"][0] == {"type": "text", "text": "이 도판은?"}
    assert out["parts"][1]["type"] == "image_url"
    assert out["parts"][1]["image_url"]["url"] == "https://x.com/img.jpg"
    assert out["parts"][1]["image_url"]["detail"] == "low"


def test_다중_이미지():
    out = PrepareImagePayloadStage().run(
        (
            "?",
            [
                Attachment(kind="image_url", value="https://x"),
                Attachment(kind="image_base64", value="data:image/png;base64,abc"),
            ],
        )
    )
    assert len(out["parts"]) == 3
    assert out["parts"][1]["image_url"]["url"] == "https://x"
    assert out["parts"][2]["image_url"]["url"].startswith("data:image/png")


def test_빈_첨부_텍스트만():
    out = PrepareImagePayloadStage().run(("?", []))
    assert len(out["parts"]) == 1


def test_detail_high_커스텀():
    out = PrepareImagePayloadStage(detail="high").run(
        ("?", [Attachment(kind="image_url", value="https://x")])
    )
    assert out["parts"][1]["image_url"]["detail"] == "high"


def test_빈_value_스킵():
    out = PrepareImagePayloadStage().run(("?", [Attachment(kind="image_url", value="")]))
    assert len(out["parts"]) == 1  # 텍스트만
