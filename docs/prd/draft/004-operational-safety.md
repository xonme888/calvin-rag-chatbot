---
status: draft
group: D
created: 2026-05-04
related_trd: docs/trd/draft/004-operational-safety.md
---

# PRD: 운영 안전망 (사용자별 cap · SLO/알림 · circuit breaker · 로그 수집)

## 1. 배경 / 문제

현재 비용 가드는 전역 누적 한 줄이다. `api/middleware/token_budget.py:19-21` 의 `_budget_cap()` 은 환경변수 `DAILY_TOKEN_CAP` 단일 값이고, `check_token_budget(stats)` 의 `stats` 는 `infra/usage_tracker.py` 의 프로세스 단일 카운터다 — 사용자 1명이 하루치를 다 써버리면 다른 모든 사용자가 막힌다. 다중 워커로 확장되는 순간 카운터가 워커별로 분리되어 cap 자체가 의미를 잃는다.

알림은 없다. `infra/observability.py:48-67` 의 `_emit` 는 stdout JSON line 만 발행한다. 5xx 가 폭주하거나 OpenAI 가 다운되어도 로그 파일을 사람이 들여다봐야 안다. `api/routes/health.py:16-22` 의 `/health` 도 `{"status": "ok"}` 만 반환할 뿐 의존성(OpenAI/Supabase/Neo4j) 가용성을 검사하지 않는다 — liveness 만 있고 readiness 가 없다.

Circuit breaker 도 없다. OpenAI 호출이 30초 timeout 으로 줄줄이 실패하면 사용자는 30초씩 기다린 끝에 에러를 받는다. Rate limiter (`api/middleware/rate_limiter.py:14-23`) 는 IP 단위 분당 10회로 1차 방어만 할 뿐, "어떤 사용자가 어떤 도구로 얼마나 썼는지" 단위 quota 가 없다.

본 PRD 는 **PRD-2 (인증) 와 같은 sprint** 다. 인증 없이는 사용자별 cap 키가 잡히지 않는다 — `request.client.host` 는 NAT/모바일 환경에서 같은 IP 다수가 공유되어 cap 키로 부적절하다.

## 2. 목표

- 사용자 1명의 폭주가 다른 사용자에게 전파되지 않는다 (격리).
- 의존 서비스 다운 / 에러율 폭증 / cap 도달을 운영자가 5분 안에 인지한다.
- LLM/외부 API 가 일시적으로 죽어도 사용자 latency 가 30초씩 늘어나지 않고 곧장 fallback 모드 안내로 떨어진다.
- 다중 워커/인스턴스로 수평 확장해도 위 보장이 유지된다.

## 3. 비-목표

- 사용자 인증 자체 (PRD-2 가 책임). 본 PRD 는 `user_id` 가 request 에 들어와 있다고 가정한다.
- 비용 결제/요금제 자동화 (Stripe 등). free/paid/admin 의 등급 구분만 하고, paid 등업 결제 흐름은 별도.
- BFF/멀티 region 배포. 현재 단일 region 가정.
- LLM 응답 품질 회귀 감지 (RAGAS 자동화). `experiments/eval/` 의 별도 트랙.

## 4. 사용자 시나리오 / BDD

- Given free 등급 사용자가 일일 10,000 토큰 cap 에 도달했고
  When 11번째 질문을 보내면
  Then 즉시 429 + "오늘 사용량을 초과했습니다. 자정 KST 에 초기화됩니다" 안내가 뜨고, 같은 시점에 다른 사용자는 정상 응답을 받는다.

- Given OpenAI API 가 5분간 연속 실패 중일 때
  When 사용자가 Agentic 모드로 질문을 보내면
  Then circuit breaker 가 open 상태로 전환되어 응답이 30초 timeout 을 기다리지 않고 즉시 "외부 의존 서비스 일시 장애 — KG/Hybrid 모드로 재시도해주세요" 로 떨어진다.

- Given Supabase 가 3분간 다운 상태일 때
  When 운영자가 `/health` 를 호출하면
  Then `{"status": "degraded", "deps": {"supabase": {"ok": false, "latency_ms": null}, "openai": {"ok": true, "latency_ms": 320}}}` 가 반환되고, Slack #ops 채널에 동일 알림이 1회 발송된다.

- Given 5xx rate 가 5분 평균 1% 를 넘는 순간
  When 알림 라우터가 그 임계를 감지하면
  Then Sentry issue 가 생성되고 Slack #ops 에 trace_id 와 함께 1회 알림이 간다 (5분 dedup).

## 5. 결정해야 할 사항

### 결정 1 — 등급별 일일 토큰 cap 기본값

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| free 10,000 / paid 100,000 / admin 무제한 | 한국 LLM 시세에서 free 1인당 일 ~₩3 | 무료 시연 + 유료 등급 분리 가능 | free 가 너무 빠듯해 시연 도중 잘림 | ★ |
| free 5,000 / paid 50,000 | 더 보수적 | 비용 안전 | free 시연이 5질문 컷 — 데모 가치 손상 | |
| 단일 등급 (전 사용자 동일) | 단순 | 유료 구분 없음 | 비용/가치 분리 불가 | |

### 결정 2 — Redis 인스턴스 (사용자별 카운터 backend)

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| Upstash Redis (서버리스) | 무료 한도 일 10,000 command, 이후 종량 | 운영 0, 다중 region | vendor lock-in, latency p95 ~50ms | ★ |
| 자체 호스팅 Redis (Fly.io/Cloud Run sidecar) | 인스턴스 비용 + 운영 | 데이터 주권, latency 낮음 | 운영 부담 | |
| Supabase Postgres advisory lock + counter | 0 (Supabase 가 이미 있음) | 신규 의존 없음 | RDB 에 hot row, 카운터 부하 | |

비고: PRD-2 가 Supabase 를 채택하면 옵션 3 도 고려 가치 있음 — 단, 카운터 쓰기 트래픽이 Supabase free 한도(500MB egress/월) 를 빠르게 갉아먹는다.

### 결정 3 — 알림 채널

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| Sentry only | Sentry 무료 5K event/월 | 에러 trace 자동 수집 | 운영 알림 (cap 도달 등) 부적합 | |
| Slack webhook only | 0 | 즉시 받기 좋음 | 에러 stacktrace 가독성 낮음 | |
| Sentry (에러) + Slack (운영) 둘 다 | 0~Sentry 무료 한도 | 책임 분리 | 채널 2개 운영 | ★ |

### 결정 4 — Circuit breaker 임계

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 연속 5회 실패 시 open, 30초 후 half-open | 단순 | 단발 장애에 민감 | 정상 회복 중 false-trip | |
| 최근 1분 실패율 50% 이상 시 open, 60초 후 half-open | 중간 | 안정적 | 1분 sliding window 구현 필요 | ★ |
| sliding window 5분 / 실패율 30% | 보수적 | 회복 지연 | 사용자 체감 장애가 길어짐 | |

### 결정 5 — 로그 수집기

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| stdout 만 유지 (Cloud Run/Fly.io 기본 log viewer) | 0 | 즉시 가능 | 7일 retention, 검색 부실 | ★ (Phase 1) |
| Grafana Loki (자체 호스팅) | 인스턴스 비용 | 강력한 검색, 비용 낮음 | 운영 1축 추가 | (Phase 2) |
| Datadog / CloudWatch | 큼 | 통합 관측 | 비용/lock-in | |

비고: Phase 1 은 stdout 유지, `infra/observability.py:_emit` 한 곳만 어댑터 인터페이스로 추출. Loki/Datadog 으로의 swap 은 인스턴스 도달 시 결정.

## 6. 기능 요건

- `check_token_budget` 시그니처를 `(user_id: str, role: UserRole, stats)` 로 확장. 키는 `quota:{user_id}:{YYYYMMDD-KST}` 형태로 Redis INCR.
- 등급별 cap 환경변수: `QUOTA_FREE_TOKENS_PER_DAY`, `QUOTA_PAID_TOKENS_PER_DAY` (admin 은 cap 우회).
- `/api/health` 응답에 `deps` 객체 추가 — `openai`, `supabase`, `neo4j` 각각 `{ok, latency_ms, last_error}`.
- 의존성 ping 은 캐시 5초 — health 호출이 외부 API 폭주를 일으키지 않도록.
- Circuit breaker 를 LLM 호출 경로 1곳 (`rag_core/mode_dispatcher.py` 의 LLM invoke wrapper) 과 외부 도구 호출 경로 (PRD-1 의 tool registry) 에 적용. 라이브러리는 `pybreaker` 채택.
- Slack webhook 알림 트리거: 5xx rate > 1% (5분 평균), LLM 실패율 > 5%, dep down (health degraded), audit_log 쓰기 실패, 전체 사용자 중 50% 이상 cap 도달.
- 알림 dedup: 같은 트리거는 5분 내 1회만.
- Rate limiter (`api/middleware/rate_limiter.py`) 의 `key_func` 를 `get_remote_address` → `user_id_or_ip` 로 교체. 미인증은 IP fallback.
- 로그 어댑터 추출: `infra/observability.py:_emit` 가 `LogSink` Protocol 을 호출하도록 변경, 기본 구현은 stdout. Loki/CloudWatch 어댑터는 후속 PR.

## 7. 성공 지표 (정량)

- 사용자 1명이 cap 을 다 써도 다른 사용자의 성공률 100% (격리 검증).
- 의존성 다운 시 `/api/health` 가 5초 내 `degraded` 응답 + Slack 알림 도달 (1회만).
- LLM 5분 연속 실패 시 circuit open 후 사용자 응답 시간 ≤ 1초 (30초 → 1초).
- 5xx rate 1% 초과 시 Sentry issue + Slack 알림 5분 내 도달, 운영자 응답 가능.
- Chat sync p95 latency 5초 이내 (SLO), stream first token 2초 이내.

## 8. 의존 / 영향 / 회귀 위험

- **의존**: PRD-2 의 인증/`user_id` 흐름이 선행. PRD-2 가 늦어지면 본 PRD 의 사용자별 cap 은 IP 키 임시 운영으로 시작 가능 — 단 모바일 NAT 환경에서 부정확.
- **영향**: PRD-1 의 도구 호출 경로에도 circuit breaker 가 자동 적용된다 (외부 도구가 죽으면 fallback). PRD-3 의 재시도 버튼이 cap 도달 사용자에 의해 폭주하지 않도록 본 PRD 의 quota 가 재시도에도 적용된다.
- **회귀 위험 (중)**: `check_token_budget` 시그니처 변경은 호출처 (`api/routes/chat.py`) 동시 수정 필요. 미인증 dev 모드에서는 cap 우회.
- **회귀 위험 (중)**: Redis 가 다운되면 cap 검증을 어떻게 할지 정책 필요 — fail-open (cap 없이 통과) vs fail-closed (전체 차단). fail-open 이 사용자 경험 우선이지만 비용 위험. 본 PRD 는 fail-open + Slack 즉시 알림 채택.
- **회귀 위험 (저)**: Slack webhook URL 은 secret. `.env` 누락 시 알림이 silent 실패하지 않도록 부팅 로그에 경고 출력.
- **회귀 위험 (저)**: `/api/health` 가 외부 ping 을 수행하므로 health 가 LLM 비용을 발생시킬 위험 — `models.list` 같은 무료 호출만 사용하도록 명시.

비고: 결제/요금제, 멀티 region, RAGAS 자동화는 본 PRD 외. 데이터 보존/삭제/PII redaction 은 PRD-5 책임.
