"""PII redactor 단위 테스트 — 한국/국제 패턴 + false positive 회피."""

from __future__ import annotations

import pytest

from infra.pii_redactor import has_pii, redact


# ---- 한국 주민번호 ----
@pytest.mark.parametrize(
    "text,expected",
    [
        ("주민번호는 900101-1234567 입니다", "주민번호는 [REDACTED:rrn] 입니다"),
        ("851231-2345678", "[REDACTED:rrn]"),
    ],
)
def test_주민번호_마스킹(text: str, expected: str):
    assert redact(text) == expected


# ---- 한국 휴대폰 ----
@pytest.mark.parametrize(
    "text",
    [
        "연락처: 010-1234-5678",
        "010 1234 5678",
        "01012345678",
        "017-555-1234",
    ],
)
def test_휴대폰_마스킹(text: str):
    assert "[REDACTED:phone]" in redact(text)


# ---- 이메일 ----
def test_이메일_마스킹():
    assert (
        redact("문의는 user@example.com 으로")
        == "문의는 [REDACTED:email] 으로"
    )


# ---- IPv4 ----
def test_IPv4_마스킹():
    assert redact("접속 IP 192.168.1.100") == "접속 IP [REDACTED:ip]"


def test_잘못된_IP_는_원본_유지():
    # 999.999.999.999 는 정규식에서 매칭 안 됨
    assert redact("999.999.999.999") == "999.999.999.999"


# ---- 카드 (Luhn 검증) ----
def test_카드_Luhn_pass():
    # 4111-1111-1111-1111 (Visa 테스트 카드, Luhn pass)
    assert redact("카드 4111-1111-1111-1111") == "카드 [REDACTED:card]"


def test_카드_Luhn_fail_은_원본_유지():
    # 1234567890123 (Luhn fail) — false positive 회피
    assert redact("주문번호 1234567890123") == "주문번호 1234567890123"


# ---- 빈 입력 ----
def test_빈_문자열():
    assert redact("") == ""
    assert redact(None) is None  # type: ignore[arg-type]


# ---- 일반 텍스트 잔존 ----
def test_일반_텍스트는_변경_없음():
    text = "예정론은 칼빈의 핵심 교리다."
    assert redact(text) == text


# ---- has_pii ----
def test_has_pii_긍정():
    assert has_pii("test@example.com")
    assert has_pii("010-1234-5678")
    assert has_pii("4111111111111111")  # Luhn pass


def test_has_pii_부정():
    assert not has_pii("예정론은 무엇인가")
    assert not has_pii("주문번호 12345")
