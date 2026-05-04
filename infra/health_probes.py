"""의존성별 health probe — /health/ready 가 호출.

설계:
- 각 probe 는 ``ProbeResult`` 반환 (ok/latency_ms/reason)
- 빠른 경량 체크만 (실제 LLM 호출 X — 비용/latency 회피)
- 외부 서비스 미설정 시 ``configured=False`` 로 noop (실패 X)

향후 확장:
- Sentry/Slack alerting 이 ready=false 감지 시 경보
- /health/ready 가 503 반환하면 LB 가 트래픽 차단
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProbeResult:
    name: str
    ok: bool
    configured: bool  # 환경변수 등 의존성 설정 여부
    latency_ms: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _measure(fn) -> tuple[bool, int, str | None]:
    start = time.time()
    try:
        ok, reason = fn()
    except Exception as e:  # noqa: BLE001
        return False, int((time.time() - start) * 1000), f"{type(e).__name__}: {e}"
    return ok, int((time.time() - start) * 1000), reason


def probe_openai() -> ProbeResult:
    """OpenAI API key 존재 + 형식만 검증. 실제 API 호출 X (비용)."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return ProbeResult(
            name="openai", ok=False, configured=False, latency_ms=0, reason="OPENAI_API_KEY 미설정"
        )
    if not key.startswith(("sk-", "sk_")):
        return ProbeResult(
            name="openai", ok=False, configured=True, latency_ms=0, reason="키 형식 비정상"
        )
    return ProbeResult(name="openai", ok=True, configured=True, latency_ms=0)


def probe_neo4j() -> ProbeResult:
    """Neo4j 어댑터 health_check + 그래프 비어있는지."""
    def _do() -> tuple[bool, str | None]:
        try:
            from rag_core.kg.factory import get_kg_adapter
        except ImportError:
            return False, "kg 모듈 import 실패"
        try:
            adapter = get_kg_adapter()
        except Exception as e:  # noqa: BLE001
            return False, f"어댑터 생성 실패: {type(e).__name__}"
        if not adapter.health_check():
            return False, "Neo4j 연결 실패"
        if adapter.stats().get("nodes", 0) == 0:
            return False, "그래프 비어있음 (kg ingest 필요)"
        return True, None

    ok, latency, reason = _measure(_do)
    return ProbeResult(
        name="neo4j",
        ok=ok,
        configured=bool(os.getenv("NEO4J_URI")) or True,  # docker 기본 가정
        latency_ms=latency,
        reason=reason,
    )


def probe_supabase() -> ProbeResult:
    """Supabase URL 환경변수 존재만 (PRD-2 도입 후 실제 ping)."""
    url = os.getenv("SUPABASE_URL", "").strip()
    if not url:
        return ProbeResult(
            name="supabase",
            ok=True,  # 미설정 = 인증/동기화 비활성, 서비스는 살아있음
            configured=False,
            latency_ms=0,
            reason="미설정 (PRD-2 인증 도입 전)",
        )
    return ProbeResult(name="supabase", ok=True, configured=True, latency_ms=0)


ALL_PROBES = (probe_openai, probe_neo4j, probe_supabase)


def run_all_probes() -> list[ProbeResult]:
    return [p() for p in ALL_PROBES]


def overall_status(probes: list[ProbeResult]) -> str:
    """전체 상태 — ok / degraded / failed.

    - ok: 모든 configured probe 통과
    - degraded: 일부 configured probe 실패 (서비스는 부분 가용)
    - failed: 모든 configured probe 실패 (= openai 다운)
    """
    configured = [p for p in probes if p.configured]
    if not configured:
        return "ok"  # 아무 것도 설정 안 됨 = 부팅 직후
    failed = [p for p in configured if not p.ok]
    if not failed:
        return "ok"
    if len(failed) == len(configured):
        return "failed"
    return "degraded"
