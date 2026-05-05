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

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _allowed_codes() -> frozenset[str]:
    raw = os.getenv("INVITE_CODES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


def is_enforcement_enabled() -> bool:
    """초대 코드 검증이 활성화되어 있는가 (환경변수 비어있으면 False)."""
    return bool(_allowed_codes())


def verify_code(code: str | None) -> bool:
    """초대 코드 유효성 검증.

    Returns:
        True — 유효 또는 검증 비활성
        False — 검증 활성 + 코드 없음 또는 화이트리스트 외
    """
    if not is_enforcement_enabled():
        return True  # 개발 모드 — 모든 요청 통과
    if not code:
        return False
    return code in _allowed_codes()


def mask_code(code: str | None) -> str | None:
    """audit_log 저장용 — 코드 앞 4자만 노출."""
    if not code:
        return None
    if len(code) <= 4:
        return code
    return code[:4] + "***"


def reset_cache() -> None:
    """테스트용 — 환경변수 변경 후 재로드."""
    _allowed_codes.cache_clear()
