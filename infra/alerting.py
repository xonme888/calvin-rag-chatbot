"""운영 알림 — Sentry / Slack / NoOp 어댑터.

설계:
- ``Alerter`` Protocol — 어댑터 swap
- 환경변수로 자동 선택 (SENTRY_DSN, SLACK_WEBHOOK_URL)
- 둘 다 설정 시 ``MultiAlerter`` 로 동시 발송
- 미설정 시 ``NoopAlerter`` — 코드는 alert() 호출하지만 무동작 (개발 단계)

사용 지점:
- circuit.open / circuit.half_open_failed
- /health/ready overall=failed
- audit_log 쓰기 실패
- 사용자 cap 도달 (전체 트래픽 신호)

PII 방어: ``message`` / ``context`` 전송 전 PII redact 통과.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger("calvin.alerting")


class Level(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


class Alerter(Protocol):
    def alert(self, level: Level, message: str, context: dict[str, Any] | None = None) -> None: ...


class NoopAlerter:
    """미설정 시 default — debug 로그만."""

    def alert(self, level: Level, message: str, context: dict[str, Any] | None = None) -> None:
        logger.debug("[alert:%s] %s context=%s", level.value, message, context)


class SentryAlerter:
    """Sentry SDK 어댑터 — DSN 설정 시 자동 활성화. lazy import 로 의존성 강제 X."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._sentry: Any = None
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=dsn,
                # PII 방어 — Sentry 가 prompt/answer 까지 자동 캡처하지 않게
                send_default_pii=False,
                before_send=self._before_send,
            )
            self._sentry = sentry_sdk
        except Exception as e:  # noqa: BLE001
            logger.warning("Sentry SDK 초기화 실패 — alert 비활성: %s", e)

    @staticmethod
    def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
        """Sentry 전송 직전 PII redact."""
        try:
            from infra.pii_redactor import redact

            if "message" in event and isinstance(event["message"], str):
                event["message"] = redact(event["message"])
            # extras / breadcrumbs 도 보호
            for k in ("extra", "tags"):
                v = event.get(k)
                if isinstance(v, dict):
                    for ek, ev in list(v.items()):
                        if isinstance(ev, str):
                            v[ek] = redact(ev)
        except Exception:  # noqa: BLE001
            pass
        return event

    def alert(self, level: Level, message: str, context: dict[str, Any] | None = None) -> None:
        if self._sentry is None:
            return
        try:
            with self._sentry.push_scope() as scope:
                if context:
                    for k, v in context.items():
                        scope.set_extra(k, v)
                self._sentry.capture_message(message, level=level.value)
        except Exception:  # noqa: BLE001
            pass


class SlackAlerter:
    """Slack incoming webhook — POST JSON. 의존성 0 (urllib)."""

    def __init__(self, webhook_url: str) -> None:
        self.url = webhook_url

    def alert(self, level: Level, message: str, context: dict[str, Any] | None = None) -> None:
        # PII redact
        try:
            from infra.pii_redactor import redact

            message = redact(message)
        except Exception:  # noqa: BLE001
            pass
        emoji = {"info": ":information_source:", "warn": ":warning:", "error": ":x:", "critical": ":rotating_light:"}
        body = {
            "text": f"{emoji.get(level.value, '')} *[{level.value.upper()}]* {message}",
            "attachments": [
                {
                    "color": {"info": "#36a64f", "warn": "#ffae42", "error": "#e01e5a", "critical": "#9b0000"}.get(level.value, "#888"),
                    "fields": [
                        {"title": k, "value": str(v)[:200], "short": True}
                        for k, v in (context or {}).items()
                    ],
                }
            ] if context else [],
        }
        try:
            req = urllib.request.Request(
                self.url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:  # noqa: BLE001
            logger.warning("Slack alert 실패: %s", e)


class MultiAlerter:
    """여러 alerter 동시 호출 — 한 곳 실패해도 다른 곳 전송."""

    def __init__(self, alerters: list[Alerter]) -> None:
        self.alerters = alerters

    def alert(self, level: Level, message: str, context: dict[str, Any] | None = None) -> None:
        for a in self.alerters:
            try:
                a.alert(level, message, context)
            except Exception:  # noqa: BLE001
                pass


def _make_alerter_from_env() -> Alerter:
    alerters: list[Alerter] = []
    sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
    if sentry_dsn:
        alerters.append(SentryAlerter(sentry_dsn))
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if slack_url:
        alerters.append(SlackAlerter(slack_url))
    if not alerters:
        return NoopAlerter()
    if len(alerters) == 1:
        return alerters[0]
    return MultiAlerter(alerters)


_alerter: Alerter = _make_alerter_from_env()


def configure_alerter(alerter: Alerter) -> None:
    global _alerter
    _alerter = alerter


def alert(level: Level, message: str, context: dict[str, Any] | None = None) -> None:
    """전역 alert 호출 — 미설정 시 noop."""
    _alerter.alert(level, message, context)
