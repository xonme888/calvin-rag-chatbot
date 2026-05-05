"""Vision RAG — 사용자 첨부 이미지에 대한 답변.

목적: 사용자가 이미지를 첨부하면 OpenAI Vision (gpt-4o-mini) 으로 해석 + 질문 응답.
1단계 구현은 RAG 결합 없음 (이미지 단순 분석). 2단계에서 hybrid 검색 결합 가능.

설계:
- mode_registry 의 새 모드 — register("vision", VisionRAG) 한 줄로 통합
- ModeEntry.factory → VisionRAG 인스턴스
- chat.py _invoke_sync 가 attachments 를 query() 에 전달

비용 가드 (TRD-1 §2.4):
- ``image_url detail="low"`` 강제 — 이미지 1장 = 65 토큰 (~₩0.1, gpt-4o-mini)
  high 모드 대비 1/10~1/30 비용. 본문 인식엔 부족하나 신학 도식·인물 사진엔 충분.
- ``VISION_ENABLED=false`` 환경변수로 모드 자체 비활성 가능 (외부 노출 시 게이팅).
- budget cap (PRD-4) + circuit breaker 가 폭주 방어.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


_VISION_SYSTEM = """당신은 칼빈 신학 챗봇의 비전 분석 어시스턴트입니다.
사용자가 첨부한 이미지를 한국어로 분석합니다.

규칙:
- 이미지에 보이는 내용을 정확하게 묘사
- 칼빈 신학과 관련 있는 인물/문서/도식이면 그 맥락을 우선 설명
- 추정·추측은 명확히 표시 ("…로 보입니다")
- 이미지에 없는 내용은 만들어내지 않습니다 (환각 금지)
"""


class VisionRAG:
    """이미지 첨부에 대한 단순 vision 답변. RAG 결합은 차후."""

    PATTERN_NAME: str = "Vision"

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        if llm is None:
            from langchain_openai import ChatOpenAI

            # 다른 RAG 와 동일 패턴 — Config (.env) 의 SecretStr 명시 전달.
            # 환경변수 자동 읽기에 의존하지 않음 (main.py 가 dotenv 안 부르는 환경에서도 동작).
            from rag_core.hybrid import get_config

            cfg = get_config()
            llm = ChatOpenAI(
                api_key=cfg.open_api_key,
                model="gpt-4o-mini",  # vision 지원 + 가장 저렴
                temperature=0,
            )
        self.llm: BaseChatModel = llm

    def query(
        self,
        question: str,
        attachments: list[dict[str, Any]] | None = None,
        callbacks: list[BaseCallbackHandler] | None = None,
    ) -> dict[str, Any]:
        """이미지 + 질문 → 답변. attachments 는 dict (Pydantic Attachment 의 dict 형태).

        Returns:
            envelope 표준 (다른 모드와 같은 키 셋):
                final_answer, source_documents, metadata{pattern, vision_attachments,
                source_pages, source_pages_label, subgraph, tool_calls,
                suggested_followups, cache_*}
        """
        from infra.llm_cache import cache_delta, cache_snapshot

        cache_start = cache_snapshot()
        start = time.time()

        atts = attachments or []
        # OpenAI multimodal 메시지 형식 — system + human(text + image_url N개)
        # 시스템 지시는 user message 와 분리해야 모델이 정확히 따른다.
        human_content: list[dict[str, Any]] = [{"type": "text", "text": question}]
        for att in atts:
            url = att.get("data_url") if isinstance(att, dict) else getattr(att, "data_url", None)
            if not url:
                continue
            # detail="low": 이미지 1장 = 65 토큰 고정 (~₩0.1)
            # 비용 폭주 방어 — 신학 도식/인물 사진 인식엔 충분.
            human_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": url, "detail": "low"},
                }
            )

        messages = [
            SystemMessage(content=_VISION_SYSTEM),
            HumanMessage(content=human_content),
        ]
        invoke_config: dict[str, Any] = {}
        if callbacks:
            invoke_config["callbacks"] = callbacks

        response = self.llm.invoke(messages, config=invoke_config)
        answer = response.content if hasattr(response, "content") else str(response)

        elapsed = time.time() - start
        return {
            "final_answer": answer if isinstance(answer, str) else str(answer),
            "source_documents": [],
            "metadata": {
                "pattern": self.PATTERN_NAME,
                "vision_attachments": len(atts),
                "elapsed_seconds": elapsed,
                "source_pages": [],
                "source_pages_label": [],
                "subgraph": None,
                "tool_calls": [],
                "suggested_followups": [],
                **cache_delta(cache_start),
            },
        }
