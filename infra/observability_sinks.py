"""Trace 이벤트 출력 sink — observability._emit 가 사용.

목적: stdout 만 emit 하던 trace 를 환경변수로 외부 수집기 (Loki/CloudWatch/
Datadog) 로 redirect 가능하게 분리. 인터페이스만 분리, 외부 의존성 추가는
실제 도입 시점에 별도 commit.

환경변수: ``LOG_SINK=stdout|loki|cloudwatch|noop`` (기본 stdout)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Protocol


class Sink(Protocol):
    """Trace 이벤트 출력 어댑터 인터페이스."""

    def write(self, event: dict[str, Any]) -> None: ...


class StdoutSink:
    """기본 sink — stdout 에 JSON line 1줄. 개발 + Cloud Run 기본."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("calvin.trace")
        self._logger.propagate = False
        if not self._logger.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(h)
            self._logger.setLevel(logging.INFO)

    def write(self, event: dict[str, Any]) -> None:
        try:
            self._logger.info(json.dumps(event, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001
            # 로깅이 메인 흐름을 절대 막지 않게
            pass


class NoopSink:
    """테스트/디버그용 — 모든 이벤트 무시."""

    def write(self, event: dict[str, Any]) -> None:  # noqa: ARG002
        pass


class LokiSink:
    """Loki HTTP push API stub — 실제 구현은 도입 시점에.

    환경변수: LOKI_URL, LOKI_AUTH (선택)
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("LOKI_URL", "")
        # 실제 push 는 batch + async 권장 — stub 단계에서 stdout fallback
        self._fallback = StdoutSink()

    def write(self, event: dict[str, Any]) -> None:
        # TODO: requests.post(self.url, json={"streams": [...]})
        self._fallback.write(event)


class CloudWatchSink:
    """CloudWatch Logs stub — boto3 logs put_log_events.

    환경변수: AWS_REGION, CLOUDWATCH_LOG_GROUP, CLOUDWATCH_LOG_STREAM
    """

    def __init__(self) -> None:
        self._fallback = StdoutSink()

    def write(self, event: dict[str, Any]) -> None:
        # TODO: boto3 logs client + sequence token 관리
        self._fallback.write(event)


def make_sink_from_env() -> Sink:
    """환경변수 ``LOG_SINK`` 로 sink 선택. default stdout."""
    name = os.getenv("LOG_SINK", "stdout").lower()
    if name == "noop":
        return NoopSink()
    if name == "loki":
        return LokiSink()
    if name == "cloudwatch":
        return CloudWatchSink()
    return StdoutSink()


# ---- 글로벌 sink (observability._emit 에서 import) ----
_sink: Sink = make_sink_from_env()


def configure_sink(sink: Sink) -> None:
    """런타임 sink 교체 (테스트/마이그레이션 용)."""
    global _sink
    _sink = sink


def emit(event: dict[str, Any]) -> None:
    """observability._emit 의 위임 지점."""
    try:
        _sink.write(event)
    except Exception:  # noqa: BLE001
        pass
