---
status: draft
group: D
created: 2026-05-04
related_prd: docs/prd/draft/004-operational-safety.md
---

# TRD-004: 운영 안전망 (사용자별 budget + Circuit Breaker + Health/Alerting + Log sink)

## 1. AS-IS 분석

### 1.1 토큰 budget — 전역 단일 카운터

`api/middleware/token_budget.py:19~21` — `DAILY_TOKEN_CAP=1_000_000` 환경변수, 전 사용자 합산.
`check_token_budget(stats: SessionStats)` 가 `stats.total_input_tokens + total_output_tokens` 만 본다 (line 30~38).
`SessionStats` 는 `infra/usage_tracker.py:53~106` — 프로세스 단위 싱글톤 (`api/dependencies.py:64~71 get_session_stats` `@lru_cache`).

결과:
- 한 명이 1M 소진하면 전체 차단. 무료/유료 사용자 구분 없음.
- 다중 워커 운영 시 워커별 독립 카운터 → cap 무의미.
- TRD-002 인증 도입 후에도 user_id 기준 cap 부재.

### 1.2 Rate limiter — IP 단일 키

`api/middleware/rate_limiter.py:17~23` — slowapi `key_func=get_remote_address`, `default_limits=["10/minute","200/day"]`.
같은 IP (NAT/회사 망) 사용자 다수면 한 명이 cap 소진 가능. user_id 결합 없음.

### 1.3 Health endpoint — liveness 만

`api/routes/health.py:15~22` — `status="ok"` 고정 반환. 의존성 (OpenAI, Supabase, Neo4j) ping 없음.
`/modes` (line 25~42) 는 `entry.health()` 호출하지만 KG 만 의미 있음 — `mode_registry.py:29~32` 의 health 기본값은 항상 `(True, None)`.
즉 OpenAI 가 다운되어도 `/health` 200, 사용자가 첫 질문 던지고 나서야 발견.

### 1.4 Circuit Breaker — 부재

`api/routes/chat.py:165~171 _invoke_sync` 는 `Exception` catch → `HTTPException(500)`. 재시도 정책/breaker 없음.
OpenAI 5xx 가 1분간 100건 와도 그대로 전부 호출 → 비용 + latency 누적.

### 1.5 알림 / 로그 sink — stdout 단일

`infra/observability.py:50~54` — `StreamHandler(sys.stdout)` 만. Loki/CloudWatch 어댑터 없음.
`_emit` (line 57~67) 한 곳이 sink 결정 — 라이브러리 swap 지점은 명확.
Sentry/Slack webhook 통합 0건 (`grep -rn "sentry\|slack" api/ infra/` → 0건).

### 1.6 한계 / 변경 비용 / 회귀 위험

| 항목 | 현재 비용 | 위험 |
|---|---|---|
| 사용자별 budget | TRD-002 user_id + budget 모듈 신규 | 인증 선행 필수 |
| IP+user 복합 키 | rate_limiter `key_func` 1줄 | 낮음 |
| /health 의존성 ping | health.py 1라우트 + ping 함수 3개 | 낮음 |
| Breaker | 신규 모듈 + ModeEntry 1필드 + chat.py 진입부 | 중간 |
| Log sink swap | `_emit` 한 곳 + 어댑터 인터페이스 | 낮음 |
| Sentry/Slack | SDK 통합 + before_send hook (PII) | 중간 |

## 2. TO-BE 설계

### 2.1 신규 모듈

```
infra/
  budget.py                 신규 — 사용자별 토큰 cap (Redis backed, in-memory fallback)
  circuit_breaker.py        신규 — 모드/도구별 회로 차단 state machine
  alerting.py               신규 — Sentry + Slack webhook 통합
  observability_sinks.py    신규 — Stdout/Loki/CloudWatch 어댑터 + LOG_SINK env switch
api/
  middleware/
    token_budget.py         변경 — infra/budget 위임 (글로벌 cap fallback 유지)
    rate_limiter.py         변경 — key_func: f"{ip}:{user_id or 'anon'}"
  routes/
    health.py               변경 — 의존성 ping (openai/supabase/neo4j) 추가
rag_core/
  mode_registry.py          변경 — ModeEntry 에 circuit_breaker 필드 추가
```

### 2.2 인터페이스

#### 2.2.1 사용자별 budget

```python
# infra/budget.py
from typing import Literal

Role = Literal["anon", "free", "paid", "admin"]

ROLE_DAILY_TOKEN_CAP: dict[Role, int] = {
    "anon": 5_000,
    "free": 10_000,
    "paid": 100_000,
    "admin": 10_000_000,
}

def check_user_budget(user_id: str | None, role: Role) -> None:
    """누적치가 role 별 cap 초과 시 ``HTTPException(429)``."""

def record_usage(
    user_id: str | None,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    """LLM 호출 1회 누적. Redis INCRBY + EXPIRE (자정까지)."""
```

Redis 미운영 시 `_InMemoryBudget` fallback — 싱글 워커 가정. 다중 워커는 PRD 결정 후 Redis 강제.

#### 2.2.2 Circuit Breaker

```python
# infra/circuit_breaker.py
from dataclasses import dataclass, field
from enum import Enum
import time

class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreaker:
    name: str
    fail_threshold: int = 5         # 연속 실패
    fail_rate_window_s: int = 60    # 윈도우 60s
    fail_rate_threshold: float = 0.5
    cooldown_s: int = 30
    state: BreakerState = BreakerState.CLOSED
    _failures: list[float] = field(default_factory=list)
    _opened_at: float | None = None

    def call(self, fn, *args, **kwargs):
        """state 검사 → fn 실행 → 결과/예외 기반 transition."""
```

ModeEntry 확장 (`mode_registry.py:21~32`):

```python
@dataclass(frozen=True)
class ModeEntry:
    ...
    circuit_breaker: CircuitBreaker | None = None
```

`_invoke_sync` (chat.py:102) 변경:

```python
rag = entry.factory()
breaker = entry.circuit_breaker
if breaker:
    return breaker.call(rag.query, req.question, callbacks=callbacks)
return rag.query(req.question, callbacks=callbacks)
```

#### 2.2.3 Health 의존성 ping

```python
# api/routes/health.py 신규 헬퍼
def _ping_openai() -> tuple[bool, str | None]:
    """OpenAI /v1/models HEAD — 200ms timeout. cache 60s."""

def _ping_supabase() -> tuple[bool, str | None]:
    """Supabase REST GET / — 200ms timeout."""

def _ping_neo4j() -> tuple[bool, str | None]:
    """KG adapter health_check() — 이미 dependencies.py:53 에 존재."""

@router.get("/health")
async def health() -> HealthResponse:
    deps = {
        "openai": _ping_openai(),
        "supabase": _ping_supabase(),
        "neo4j": _ping_neo4j(),
    }
    overall = all(ok for ok, _ in deps.values())
    if not overall:
        raise HTTPException(503, detail={"deps": deps})
    return HealthResponse(status="ok", ...)
```

Liveness 와 Readiness 분리: `/health/live` (앱 부팅만), `/health/ready` (의존성 포함). k8s 친화.

#### 2.2.4 Alerting

```python
# infra/alerting.py
from typing import Literal

Level = Literal["info", "warn", "error", "critical"]

def alert(level: Level, message: str, **context: object) -> None:
    """level → 채널 라우팅:
    - critical: Slack + Sentry
    - error: Sentry
    - warn: Slack
    - info: stdout 만
    """
```

Sentry SDK `before_send` hook 으로 PII 제거 (TRD-005 의 redactor 재사용).

#### 2.2.5 Log sink

```python
# infra/observability_sinks.py
class LogSink(Protocol):
    def emit(self, payload: dict[str, object]) -> None: ...

class StdoutSink: ...
class LokiSink: ...        # http push, batch + flush
class CloudWatchSink: ...  # boto3.logs.put_log_events

def get_sink() -> LogSink:
    """env LOG_SINK=stdout|loki|cloudwatch — 기본 stdout."""
```

`infra/observability.py:_emit` (line 57~67) 1곳만 sink 위임으로 교체.

### 2.3 의존성 방향

```
api/routes/chat.py  →  infra/budget  →  redis (또는 in-memory)
                  →  infra/circuit_breaker
api/middleware/token_budget  →  infra/budget
api/middleware/rate_limiter  →  user_id (TRD-002 의 get_current_user)
api/routes/health  →  infra/(openai|supabase|neo4j) ping helpers
infra/observability  →  infra/observability_sinks  →  Loki/CloudWatch SDK
infra/alerting  →  sentry-sdk + http (Slack webhook)
```

도메인 (`rag_core`) 은 budget/breaker/alerting 를 모른다. ModeEntry 는 breaker 를 옵션으로 받지만 RAG 클래스 자체 무수정.

## 3. 변경 사항 단계 (커밋 단위)

### C1. infra/budget + token_budget 위임 (Redis 옵션)

- 신규: `infra/budget.py` (~120줄)
- 변경: `api/middleware/token_budget.py:24~38` — `check_token_budget(stats)` → `check_user_budget(user_id, role)` 으로 swap. 호출 측 (chat.py:142, 415) 에 user/role 전달.
- 의존성: `pyproject.toml` 에 `redis>=5.0` 추가 (optional extras `[ops]`)
- ENV: `REDIS_URL`, `BUDGET_BACKEND=redis|memory`
- 검증: anon 5K 도달 시 429, paid 100K 까지 통과
- 회귀: `tests/test_token_budget.py` (있다면) PASS, 없으면 신규

### C2. /health 의존성 ping

- 변경: `api/routes/health.py` — `/health/live` 분리 + 기존 `/health` 를 readiness 로
- 신규: `infra/healthchecks.py` — openai/supabase/neo4j ping (각 200ms timeout, 60s cache)
- 검증: openai mock down 시 503, 정상 시 200

### C3. Sentry SDK + alerting (PII 제외)

- 신규: `infra/alerting.py`
- 변경: `api/main.py` 부팅 시 `sentry_sdk.init(before_send=pii_filter)` 호출
- 의존성: `sentry-sdk>=2.0` (extras `[ops]`)
- ENV: `SENTRY_DSN`, `SLACK_WEBHOOK_URL`
- 검증: 강제 예외 → Sentry 1건, critical alert → Slack 1건

### C4. Slack webhook

- C3 와 함께. 별도 라우팅 함수 `_post_slack(msg, channel)` 만 분리.
- 검증: webhook URL 부재 시 silent skip (운영 환경 깨지지 않게)

### C5. Circuit breaker + ModeEntry 통합

- 신규: `infra/circuit_breaker.py` (~150줄, 직접 구현 — `pybreaker` 의존 회피)
- 변경: `rag_core/mode_registry.py:21` ModeEntry 에 `circuit_breaker` 필드
- 변경: `api/dependencies.py` 모드 등록부에 `circuit_breaker=CircuitBreaker(name=...)` 추가
- 변경: `api/routes/chat.py:102~113 _invoke_sync` — `breaker.call(rag.query, ...)` 패턴
- 검증: 5회 연속 5xx → state OPEN, 30초 후 HALF_OPEN
- Fallback: state OPEN 시 503 + alert("critical", "mode_breaker_open")

### C6. observability_sinks (선택)

- 신규: `infra/observability_sinks.py` — Stdout/Loki/CloudWatch 3 어댑터
- 변경: `infra/observability.py:57~67 _emit` — sink 위임
- ENV: `LOG_SINK=stdout|loki|cloudwatch`, `LOKI_URL`, `AWS_LOG_GROUP`
- 검증: LOG_SINK=loki 시 stdout 무출력, Loki batch 1회 flush 확인

## 4. 마이그레이션 전략

- 데이터: 신규 외부 의존 (Redis/Sentry/Slack/Loki) 모두 옵셔널. ENV 미설정 시 기존 동작.
- 코드 호환:
  - `check_user_budget` 는 `user_id=None` 도 받음 — TRD-002 미배포 상태에서도 동작 (anon role).
  - `circuit_breaker=None` 기본값 — 미설정 모드는 기존 호출 그대로.
  - `_emit` 위임은 sink 인터페이스만 일치하면 swap 가능.
- 운영:
  - C1 단독 배포 — 기존 글로벌 cap 사용자 모르게 사용자별 cap 으로 전환 (값 동일하면 행동 동일)
  - C5 breaker 는 staging 에서 fail 임계 검증 후 prod (오탐 → 사용자 차단 위험)

## 5. 검증 계획

### 5.1 단위 테스트

```python
# tests/test_user_budget.py
def test_anon_cap_5k():
    record_usage(None, 4_999, 0, 0.0)
    check_user_budget(None, "anon")  # PASS
    record_usage(None, 2, 0, 0.0)
    with pytest.raises(HTTPException) as e:
        check_user_budget(None, "anon")
    assert e.value.status_code == 429

def test_paid_cap_100k():
    record_usage("u1", 99_999, 0, 0.0)
    check_user_budget("u1", "paid")  # PASS

# tests/test_circuit_breaker.py
def test_open_after_5_consecutive_failures():
    br = CircuitBreaker(name="t", fail_threshold=5)
    for _ in range(5):
        with pytest.raises(RuntimeError):
            br.call(lambda: (_ for _ in ()).throw(RuntimeError()))
    assert br.state == BreakerState.OPEN
    with pytest.raises(HTTPException):  # 503 fast-fail
        br.call(lambda: "ok")
```

### 5.2 통합

- `/health` — openai mock down → 503 + body.deps.openai = (False, reason)
- `/chat/sync` — anon 6번 호출 (각 ~1K 토큰) → 6번째 429
- breaker open 상태에서 `/chat/sync mode=hybrid` → 503 fast-fail (LLM 호출 0)

### 5.3 회귀

- 기존 pytest 189개 (현재 추정치, 실측 후 확정) PASS
- ENV 미설정 시 모든 신규 모듈 silent skip — 기존 동작 동일

### 5.4 정량 지표

| 지표 | 목표 |
|---|---|
| /health latency (정상) | < 300ms (3 ping 병렬) |
| Breaker open 후 fast-fail latency | < 5ms |
| Sentry before_send PII 제거율 | 100% (TRD-005 redactor 재사용 단위 테스트) |
| Redis 미운영 fallback 동작 | in-memory 로 silent 동작 + warn alert 1회 |

## 6. 위험 / 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| Redis 미운영 + 다중 워커 → cap 의미 상실 | 비용 폭주 | 운영 시 Redis 필수, in-memory fallback 시작 시 warn alert 발생 |
| Sentry SDK 가 OpenAI prompt 자동 캡처 → PII 누출 | GDPR 위반 | `before_send` hook + TRD-005 PII redactor 재사용 단위 테스트 필수 |
| Breaker 오탐 (네트워크 일시 지연을 실패로 분류) | 정상 사용자 차단 | fail_threshold=5 + fail_rate_window 60s 보수적, staging 1주 관찰 후 prod |
| Slack webhook 폭주 (alert storm) | 채널 노이즈 | rate limit (분당 5회 cap), critical 만 즉시, 나머지 5분 batch |
| /health 의존성 ping 비용 | OpenAI 호출 비용 미미하나 누적 | 60s 캐시 + HEAD 메서드 사용, k8s probe period 30s 권장 |
| Loki/CloudWatch SDK 부재 시 import 실패 | 부팅 실패 | 어댑터 lazy import, 미설치 + LOG_SINK=loki 면 부팅 시 명시적 에러 |

## 7. 비-목표 / TRD 범위 외

- APM (분산 트레이싱 — OpenTelemetry) — 별도 TRD
- 모드별/사용자별 비용 대시보드 — `infra/usage_tracker` 의 SessionStats 가 이미 by_mode 분리, UI 만 추가하면 됨 (UX TRD)
- Auto-scaling / Pod 다중 인스턴스 운영 — 인프라 영역, TRD 범위 외
- Synthetic monitoring (외부 uptime probe) — 외부 SaaS 사용 권장 (Better Uptime 등)
- Redis Sentinel / Cluster 운영 — 단일 인스턴스 가정, 트래픽 도달 시 검토
