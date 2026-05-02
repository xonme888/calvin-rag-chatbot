"""IP 단위 Rate limiter — slowapi 기반.

운영 환경 (인터넷 공개) 1차 방어.
- 분당 10회 / 일 200회 (기본값, 환경변수 override 가능)
- Cloudflare WAF 가 외곽에 있으면 2단 방어

다중 인스턴스 운영 시 in-memory → Redis 로 swap (slowapi 가 둘 다 지원).
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_PER_MINUTE = os.getenv("RATE_LIMIT_PER_MINUTE", "10")
_PER_DAY = os.getenv("RATE_LIMIT_PER_DAY", "200")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{_PER_MINUTE}/minute", f"{_PER_DAY}/day"],
)
