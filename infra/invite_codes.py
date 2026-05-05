"""초대 코드 검증 — 환경변수 기반 화이트리스트.

목적: 외부 노출 단계에서 사용자 베이스를 명시적으로 통제. 면접관·친구만 접근.

설계:
- 환경변수 ``INVITE_CODES`` (콤마 구분) 가 진리값
  - 미설정 또는 빈 값 → 검증 비활성 (개발 모드, 모든 요청 통과)
  - 값 있음 → 화이트리스트에 있는 코드만 허용
- 코드 자체는 짧은 문자열 (예: ``portfolio2026``, ``demo-friend``)
- 검증 실패 시 401 — 호출측 (FastAPI dependency 또는 미들웨어) 책임

향후 확장:
- 만료 일자 (``code:YYYY-MM-DD`` 형식) — 환경변수에 인코딩
- DB 저장 (PRD-2 인증과 결합)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _allowed_codes() -> frozenset[str]:
    """매 호출 환경변수 재읽기 — uvicorn --reload + .env 변경에도 즉시 반영."""
    raw = os.getenv("INVITE_CODES", "").strip()
    if not raw:
        return frozenset()
    # 콤마 구분 + 공백/탭/CR 제거 (.env 파싱 잔존 문자 방어)
    return frozenset(
        c.strip(" \t\r\n\"'") for c in raw.split(",") if c.strip(" \t\r\n\"'")
    )


def is_enforcement_enabled() -> bool:
    """초대 코드 검증이 활성화되어 있는가 (환경변수 비어있으면 False)."""
    return bool(_allowed_codes())


def verify_code(code: str | None) -> bool:
    """초대 코드 유효성 검증.

    Returns:
        True — 유효 또는 검증 비활성
        False — 검증 활성 + 코드 없음 또는 화이트리스트 외
    """
    allowed = _allowed_codes()
    if not allowed:
        return True  # 개발 모드 — 모든 요청 통과
    if not code:
        return False
    # 사용자 입력 공백/제어문자 제거
    cleaned = code.strip(" \t\r\n\"'")
    matched = cleaned in allowed
    if not matched:
        logger.warning(
            "invite verify failed — input_len=%d allowed_count=%d",
            len(cleaned),
            len(allowed),
        )
    return matched


def mask_code(code: str | None) -> str | None:
    """audit_log 저장용 — 코드 앞 4자만 노출."""
    if not code:
        return None
    if len(code) <= 4:
        return code
    return code[:4] + "***"


def reset_cache() -> None:
    """테스트 호환 — 캐시 제거 후 매 호출 환경변수 읽음. 호출은 noop."""
    return None
