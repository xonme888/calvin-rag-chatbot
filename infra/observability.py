"""LangChain 콜백 기반 trace 로깅.

목적: 한 request 의 "선택과 과정" 을 단일 trace_id 아래 timeline 으로 기록한다.
- 라우터 결정 → 모드 호출 → LLM/도구/Retriever 호출 → 토큰/시간/결과 요약

설계:
- ``BaseCallbackHandler`` 를 상속한 ``LangChainTracer`` 가 chain/llm/tool/retriever
  start/end 를 캡처해 stdout 으로 JSON line 1줄씩 emit.
- 라우터처럼 LangChain 객체가 아닌 코드는 ``trace_event(...)`` 헬퍼로 같은 포맷에
  실어 보낸다.
- 출력: stdout (운영 환경에선 파일 또는 외부 수집기로 redirect).

향후 확장:
- file/journald/Loki/Langfuse 어댑터로 swap 가능 — ``_emit`` 한 곳만 교체.
- audit_log 의 ``trace_id`` 컬럼과 결합해 SQLite 안에서도 검색 가능.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

# ---- request 단위 trace_id 전파 (FastAPI middleware → callback) ----
_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    """새 trace_id 발급. middleware 진입 시 1회 호출."""
    return uuid.uuid4().hex[:16]


def set_current_trace_id(tid: str | None) -> None:
    _current_trace_id.set(tid)


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


# ---- 로거 ----
_logger = logging.getLogger("calvin.trace")
_logger.propagate = False
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)


def _emit(payload: dict[str, Any]) -> None:
    """단일 trace 이벤트 출력 — JSON line. ensure_ascii=False 로 한글 가독성 유지."""
    payload.setdefault("ts", time.time())
    tid = get_current_trace_id()
    if tid:
        payload.setdefault("trace_id", tid)
    try:
        _logger.info(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        # 로깅이 메인 흐름을 절대 막지 않도록
        pass


def trace_event(step: str, **fields: Any) -> None:
    """LangChain 객체 외부 (예: 라우터, 가드) 코드에서 직접 trace 한 줄 기록."""
    _emit({"step": step, **fields})


def _truncate(text: str, n: int = 160) -> str:
    if len(text) <= n:
        return text
    return text[:n] + "…"


def _summarize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """LLM start 의 messages 인자 (BaseMessage 또는 dict) 를 prompt preview 로 요약."""
    out: list[dict[str, Any]] = []
    for m in messages[:3]:  # 너무 많으면 노이즈
        role = getattr(m, "type", None) or getattr(m, "role", "unknown")
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        out.append({"role": str(role), "content": _truncate(str(content), 200)})
    return out


class LangChainTracer(BaseCallbackHandler):
    """LangChain chain/llm/tool/retriever 호출을 단일 trace_id 아래 기록.

    - 1 request = 1 tracer 인스턴스 권장 (chat.py 진입부에서 생성, callbacks 에 추가)
    - run_id 별 시작 시각을 기억해 end 시점에 elapsed 계산
    - tokens 는 UsageTracker 가 별도로 누적 — 중복 회피 차원에서 여기서는 메타만
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._starts: dict[str, float] = {}

    def _record_start(self, run_id: Any, step: str, **fields: Any) -> None:
        rid = str(run_id)
        self._starts[rid] = time.time()
        _emit({"trace_id": self.trace_id, "step": step, "run_id": rid, **fields})

    def _record_end(self, run_id: Any, step: str, **fields: Any) -> None:
        rid = str(run_id)
        started = self._starts.pop(rid, None)
        elapsed_ms = int((time.time() - started) * 1000) if started else None
        _emit(
            {
                "trace_id": self.trace_id,
                "step": step,
                "run_id": rid,
                "elapsed_ms": elapsed_ms,
                **fields,
            }
        )

    # ---- chain ----
    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        **_: Any,
    ) -> None:
        name = (serialized or {}).get("name") or (serialized or {}).get("id", ["?"])[-1]
        self._record_start(
            run_id,
            "chain.start",
            name=str(name),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            input_keys=list(inputs.keys())[:5],
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any,
        **_: Any,
    ) -> None:
        self._record_end(run_id, "chain.end", output_keys=list(outputs.keys())[:5])

    def on_chain_error(self, error: BaseException, *, run_id: Any, **_: Any) -> None:
        self._record_end(run_id, "chain.error", error=type(error).__name__, message=str(error)[:200])

    # ---- llm ----
    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: Any,
        **_: Any,
    ) -> None:
        name = (serialized or {}).get("name") or (serialized or {}).get("id", ["?"])[-1]
        self._record_start(
            run_id,
            "llm.start",
            name=str(name),
            prompt_preview=_truncate(prompts[0] if prompts else "", 200),
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        *,
        run_id: Any,
        **_: Any,
    ) -> None:
        name = (serialized or {}).get("name") or (serialized or {}).get("id", ["?"])[-1]
        flat = messages[0] if messages else []
        self._record_start(
            run_id,
            "llm.start",
            name=str(name),
            messages_preview=_summarize_messages(flat),
        )

    def on_llm_end(self, response: Any, *, run_id: Any, **_: Any) -> None:
        # token usage 는 UsageTracker 와 중복이라 여기서는 텍스트 길이만
        text_len = 0
        try:
            generations = getattr(response, "generations", None) or []
            if generations and generations[0]:
                text_len = sum(len(getattr(g, "text", "") or "") for g in generations[0])
        except Exception:  # noqa: BLE001
            pass
        self._record_end(run_id, "llm.end", output_chars=text_len)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **_: Any) -> None:
        self._record_end(run_id, "llm.error", error=type(error).__name__, message=str(error)[:200])

    # ---- tool ----
    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: Any,
        **_: Any,
    ) -> None:
        name = (serialized or {}).get("name", "tool")
        self._record_start(
            run_id, "tool.start", name=str(name), input_preview=_truncate(input_str, 200)
        )

    def on_tool_end(self, output: Any, *, run_id: Any, **_: Any) -> None:
        out_str = str(output) if output is not None else ""
        self._record_end(run_id, "tool.end", output_preview=_truncate(out_str, 200))

    def on_tool_error(self, error: BaseException, *, run_id: Any, **_: Any) -> None:
        self._record_end(run_id, "tool.error", error=type(error).__name__, message=str(error)[:200])

    # ---- retriever ----
    def on_retriever_start(
        self,
        serialized: dict[str, Any] | None,
        query: str,
        *,
        run_id: Any,
        **_: Any,
    ) -> None:
        name = (serialized or {}).get("name") or (serialized or {}).get("id", ["?"])[-1]
        self._record_start(
            run_id, "retriever.start", name=str(name), query_preview=_truncate(query, 200)
        )

    def on_retriever_end(self, documents: Any, *, run_id: Any, **_: Any) -> None:
        try:
            count = len(documents)
        except TypeError:
            count = 0
        self._record_end(run_id, "retriever.end", doc_count=count)
