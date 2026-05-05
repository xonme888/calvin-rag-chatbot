"""테스트 공통 fixture.

격리해야 할 환경 변수 — 운영용 .env 가 테스트 결과에 영향 주지 않도록.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_invite_codes(monkeypatch: pytest.MonkeyPatch):
    """INVITE_CODES 를 테스트 단위로 비워 두 — 운영 .env 가 401 일으키지 않도록.

    개별 테스트가 invite 동작을 검증하려면 monkeypatch 로 다시 설정.
    """
    monkeypatch.delenv("INVITE_CODES", raising=False)
    # cache 초기화 — 이전 테스트의 환경변수 잔존 회피
    try:
        from infra.invite_codes import reset_cache

        reset_cache()
    except ImportError:
        pass
    yield
