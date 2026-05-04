"""사용자 입력 / 답변 / 로그의 PII 패턴 마스킹.

목적: audit_log SQLite + trace stdout 양쪽에서 사용자 PII 가 평문으로 잔존하지
않도록 진입부에서 redact. PRD-5 데이터 거버넌스의 1차 방어선.

설계:
- 보수적 정규식 — false positive 회피 우선 (사용자 답변이 깨지지 않게)
- 한국 (주민번호, 휴대폰) + 국제 (이메일, IPv4, 카드 Luhn 무검증)
- 마스킹 형식: `[REDACTED:type]` 으로 통일 — 로그 분석 가능

향후 확장:
- LLM 기반 entity recognition (false negative 회피)
- 도메인별 커스텀 패턴 (병원 차트번호 등)
"""

from __future__ import annotations

import re
from typing import Final

# 한국 주민번호 — YYMMDD-XXXXXXX (앞 6자리는 날짜 형식)
_RRN = re.compile(r"\b(\d{2}[01]\d[0-3]\d)-(\d{7})\b")

# 한국 휴대폰 — 010/011/016/017/018/019-XXXX-XXXX (- 또는 공백 또는 없음)
_PHONE = re.compile(
    r"\b(01[016789])[-\s]?(\d{3,4})[-\s]?(\d{4})\b"
)

# 이메일 — 보수적 패턴 (RFC 5322 완전 대응 X, 일반 케이스만)
_EMAIL = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
)

# IPv4 — 0~255 4 옥텟
_IPV4 = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}\b"
)

# 신용카드 — 13~19 자리 숫자 (- 또는 공백 분리). Luhn 검증은 별도 호출.
_CARD: Final = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_valid(digits: str) -> bool:
    """Luhn checksum — 카드 false positive 줄임."""
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 13:
        return False
    total = 0
    parity = len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _redact_card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = "".join(c for c in raw if c.isdigit())
    if _luhn_valid(digits):
        return "[REDACTED:card]"
    return raw  # Luhn fail → false positive 회피, 원본 유지


def redact(text: str) -> str:
    """PII 패턴을 [REDACTED:type] 으로 마스킹. 빈 입력은 그대로."""
    if not text:
        return text
    # 순서 중요 — 카드 (긴 숫자) 먼저, 그 다음 휴대폰/주민번호 (짧은 숫자)
    text = _CARD.sub(_redact_card, text)
    text = _RRN.sub("[REDACTED:rrn]", text)
    text = _PHONE.sub("[REDACTED:phone]", text)
    text = _EMAIL.sub("[REDACTED:email]", text)
    text = _IPV4.sub("[REDACTED:ip]", text)
    return text


def has_pii(text: str) -> bool:
    """PII 패턴 존재 여부만 빠르게 검사 (alerting 용)."""
    if not text:
        return False
    if _RRN.search(text) or _PHONE.search(text) or _EMAIL.search(text):
        return True
    if _IPV4.search(text):
        return True
    for m in _CARD.finditer(text):
        digits = "".join(c for c in m.group(0) if c.isdigit())
        if _luhn_valid(digits):
            return True
    return False
