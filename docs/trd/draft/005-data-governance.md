---
status: draft
group: E
created: 2026-05-04
related_prd: docs/prd/draft/005-data-governance.md
---

# TRD-005: 데이터 거버넌스 (PII redaction + Export/Delete + 보존 cron + Terms/Privacy)

## 1. AS-IS 분석

### 1.1 PII 마스킹 — 부재

`api/middleware/audit_log.py:104~133 log_chat` — `record.question[:500]`, `record.answer_preview[:500]` 그대로 SQLite 저장 (line 120~121).
`infra/observability.py:75~78 _truncate` 는 길이만 자르고, 마스킹 없음. `_emit` (line 57~67) 의 payload (prompt_preview/messages_preview/input_preview/query_preview/output_preview) 전부 raw 텍스트.

`grep -rn "redact\|mask\|pii" infra/ api/` → 0건.

결과:
- 사용자가 "내 주민번호 700101-1234567 이야" 라고 입력 → audit.db + stdout trace 양쪽에 평문 저장.
- 외부 trace 수집기 (TRD-004 의 Loki/CloudWatch) 로 전송 시 그대로 노출.

### 1.2 사용자 데이터 권리 — 부재

`api/routes/` 에 `me/`, `users/`, `account/` 라우트 없음 (`ls api/routes/` → `chat.py`, `health.py`, `stats.py`).
GDPR Right of Access (export) / Right to Erasure (delete) 미구현.

### 1.3 보존 정책 — 부재

`scripts/` 폴더에 정리 cron 없음 (`grep -rn "cleanup\|retention\|expire" scripts/` → 0건).
audit_log SQLite 는 단순 INSERT — 무한 누적. 1년 운영 시 GB 단위 가능.

### 1.4 약관/개인정보처리방침 — 부재

`web/app/` 에 `terms/`, `privacy/`, `license/` 페이지 없음 (현재 `globals.css`, `layout.tsx`, `page.tsx` 만).
가입 동의 흐름도 없음 (TRD-002 인증 미구현이라 자연스러움).

### 1.5 한계 / 변경 비용 / 회귀 위험

| 항목 | 현재 비용 | 위험 |
|---|---|---|
| PII redactor | 신규 모듈 + 진입부 3곳 (audit/trace/req) | 정규식 false positive |
| 데이터 권리 라우트 | TRD-002 인증 선행 필수 | 인증 의존 |
| 보존 cron | 신규 스크립트 + GH Actions 또는 cloud cron | 익명화 후 복구 불가 — 통보 필요 |
| 정적 페이지 3개 | Next.js app router 페이지 추가 | 낮음 |
| 동의 체크박스 | TRD-002 의 signup 페이지에 1줄 | 낮음 |

## 2. TO-BE 설계

### 2.1 신규 모듈

```
infra/
  pii_redactor.py            신규 — 정규식 기반 PII 마스킹 (한국+국제)
api/
  routes/
    me.py                    신규 — GET /me/export, DELETE /me
scripts/
  cleanup_old_data.py        신규 — 보존 기간 cron (audit 90일 익명화, trace 7일 삭제)
web/app/
  terms/page.tsx             신규 — 이용약관
  privacy/page.tsx           신규 — 개인정보처리방침
  license/page.tsx           신규 — 라이선스/저작권 (칼빈 강요 출판사 고지 포함)
web/app/auth/signup/
  page.tsx                   변경 (TRD-002 신규) — 동의 체크박스 추가
```

### 2.2 인터페이스

#### 2.2.1 PII redactor

```python
# infra/pii_redactor.py
import re

# 한국 패턴
_KR_RRN = re.compile(r"\b\d{6}-\d{7}\b")               # 주민등록번호
_KR_PHONE = re.compile(r"\b01[016-9]-?\d{3,4}-?\d{4}\b")
# 국제
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")  # Luhn 검증은 _is_luhn 보조

def redact(text: str) -> str:
    """모든 PII 패턴 마스킹. 원문 길이 보존 위해 동일 길이 ``*`` 로 교체."""
    text = _KR_RRN.sub(_mask_match, text)
    text = _KR_PHONE.sub(_mask_match, text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _IPV4.sub("[IP]", text)
    text = _CARD.sub(_mask_card_if_luhn, text)
    return text
```

설계 결정:
- 보수적 패턴 우선 (false positive < false negative). 카드 번호는 Luhn 검증 통과 시에만 마스킹.
- 마스킹 결과 길이는 원문과 동일하게 유지 (분석/디버깅용 — 길이 정보는 비-PII).

#### 2.2.2 데이터 권리 라우트

```python
# api/routes/me.py
from fastapi import APIRouter, Depends
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/me", tags=["account"])

@router.get("/export")
async def export_me(user = Depends(get_current_user)) -> dict:
    """JSON dump — chat_sessions(Supabase) + audit_log(own user_id rows)."""
    sessions = await supabase.from_("chat_sessions").select("*").eq("user_id", user["sub"])
    audits = audit_log.fetch_by_user(user["sub"])
    return {
        "user": {"id": user["sub"], "email": user["email"]},
        "chat_sessions": sessions.data,
        "audit_log": audits,
        "exported_at": datetime.utcnow().isoformat(),
    }

@router.delete("")
async def delete_me(user = Depends(get_current_user)) -> dict:
    """cascade — Supabase auth.users delete (RLS cascade) + audit_log 익명화."""
    await supabase.auth.admin.delete_user(user["sub"])
    audit_log.anonymize_user(user["sub"])  # user_id/ip → NULL, question/answer 도 NULL
    return {"deleted": True, "anonymized_audit_count": ...}
```

`audit_log.anonymize_user` 신규 함수 — UPDATE 1개:

```python
def anonymize_user(user_id: str) -> int:
    """user 의 audit_log row 익명화. 통계는 보존 (count/cost/tokens)."""
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE audit_log SET ip=NULL, question=NULL, answer_preview=NULL, user_id=NULL "
            "WHERE user_id=?",
            (user_id,),
        )
        return cursor.rowcount
```

(audit_log 에 `user_id` 컬럼 추가는 TRD-002 의 C4 에서 이미 다룬다.)

#### 2.2.3 보존 cron

```python
# scripts/cleanup_old_data.py
"""매일 03:00 KST 실행. GH Actions 또는 cloud cron."""

def run_daily_cleanup() -> dict:
    # 1. audit_log: 90일 후 익명화
    cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
    n_anon = anonymize_old_records(cutoff)
    # 2. trace 로그는 sink 자체 retention 위임 (Loki retention=7d 등)
    # 3. Supabase chat_sessions: 사용자가 삭제하지 않은 세션은 보존 (UX 영향)
    return {"anonymized": n_anon, "ran_at": datetime.utcnow().isoformat()}
```

GH Actions workflow:

```yaml
# .github/workflows/data_retention.yml
on:
  schedule: [{cron: "0 18 * * *"}]  # UTC 18:00 = KST 03:00
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/cleanup_old_data.py
```

#### 2.2.4 진입부 redact 적용

3 곳에 redact 호출:

```python
# api/middleware/audit_log.py:120 변경
record.question[:500]  →  redact(record.question)[:500]
record.answer_preview[:500]  →  redact(record.answer_preview)[:500]

# infra/observability.py:_emit 변경 — 텍스트 필드 자동 redact
def _emit(payload: dict[str, Any]) -> None:
    payload = _redact_payload(payload)  # *_preview 키만 골라서 redact
    ...

# api/routes/chat.py 진입부 — req.question 도 trace 진입 전 redact 한 사본을 저장
# (실제 RAG 호출은 원문 사용 — 사용자가 의도한 검색)
trace_event("request.start", question_preview=redact(req.question)[:120])
```

주의: RAG 호출 자체는 원문 사용. 저장/관측 경로만 redact. PRD-005 의 "사용자에게 PII 입력 자제 권고" 가 1차 방어, redact 가 2차.

### 2.3 의존성 방향

```
api/middleware/audit_log  →  infra/pii_redactor
infra/observability       →  infra/pii_redactor
api/routes/me             →  api/middleware/auth (TRD-002) + api/middleware/audit_log + supabase
scripts/cleanup_old_data  →  api/middleware/audit_log (anonymize 함수)
web/app/{terms,privacy,license}  →  정적, 의존성 없음
```

도메인 (`rag_core`) 무관여.

## 3. 변경 사항 단계 (커밋 단위)

### C1. infra/pii_redactor + 단위 테스트

- 신규: `infra/pii_redactor.py` (~80줄)
- 신규: `tests/test_pii_redactor.py` — 한국 RRN/전화/이메일/IP/카드 30 케이스
- 검증: precision/recall 측정 — false positive < 5%

### C2. audit_log + trace event 진입부 redact

- 변경: `api/middleware/audit_log.py:120~121` — `redact()` 통과
- 변경: `infra/observability.py:57~67 _emit` — `_redact_payload(payload)` 추가
- 변경: `api/routes/chat.py:137, 424 trace_event(question_preview=...)` 도 `redact()` 통과
- 검증: "내 RRN 700101-1234567" 입력 → audit.db question 컬럼에 `[REDACTED]` 또는 `*` 마스킹

### C3. /me/export + /me/delete 라우트

- 신규: `api/routes/me.py`
- 변경: `api/middleware/audit_log.py` — `fetch_by_user(user_id)`, `anonymize_user(user_id)` 함수 추가
- 변경: `api/main.py:64` — `app.include_router(me.router)`
- 의존: TRD-002 의 `get_current_user` 선행
- 검증: 로그인 후 GET /me/export → JSON 다운로드, DELETE /me → 모든 row 익명화

### C4. 보존 cron 스크립트

- 신규: `scripts/cleanup_old_data.py`
- 변경: `api/middleware/audit_log.py` — `anonymize_old_records(cutoff_iso)` 추가
- 신규: `.github/workflows/data_retention.yml`
- 검증: 90일 + 1일 인공 데이터 1건 → 실행 후 익명화 1건 확인

### C5. 정적 페이지 3개

- 신규: `web/app/terms/page.tsx`, `web/app/privacy/page.tsx`, `web/app/license/page.tsx`
- 내용: 약관 본문은 PRD-005 결정 (법무 검토 또는 표준 템플릿 인용)
- 변경: `web/app/layout.tsx` 푸터에 3 페이지 링크
- 검증: 3 URL 200 OK, 모바일 반응형 PASS

### C6. 동의 체크박스 (signup)

- 변경: `web/app/auth/signup/page.tsx` (TRD-002 의 C2 산출물)
- 추가 필드: `agreedToTerms: boolean` (필수), `agreedToMarketing: boolean` (선택)
- Supabase user_metadata 에 `consented_at: ISO string` 저장
- 검증: 미동의 시 가입 불가, 동의 후 metadata 저장 확인

## 4. 마이그레이션 전략

- 데이터:
  - 기존 audit.db row 는 redact 적용 안됨 (소급 적용은 별도 1회성 스크립트, PRD 결정 후)
  - Supabase chat_sessions 는 새 데이터부터 redact 적용 (백엔드 진입부에서 처리)
- 코드 호환:
  - redact 는 idempotent (이미 마스킹된 텍스트도 안전)
  - `/me` 라우트는 인증 미들웨어 통과 시에만 동작 — TRD-002 미배포 시 자동 비활성
- 운영:
  - C1~C2 단독 배포 가능 (인증 무관)
  - C3~C6 은 TRD-002 인증 배포 후
  - 보존 cron 은 staging 에서 1주 dry-run (`--dry-run` 플래그) 후 prod

## 5. 검증 계획

### 5.1 단위 테스트

```python
# tests/test_pii_redactor.py
@pytest.mark.parametrize("text,expected_contains_pii", [
    ("내 주민번호는 700101-1234567 입니다", False),
    ("연락처: 010-1234-5678", False),
    ("이메일: foo@bar.com 으로 답변", False),
    ("IP 192.168.1.1 차단", False),
    ("카드 4532-1234-5678-9010", False),  # Luhn pass 가정
    ("정상 텍스트 — 칼빈의 예정론", True),  # PII 없음, 원문 유지
])
def test_redact_핵심_패턴(text, expected_contains_pii):
    out = redact(text)
    if expected_contains_pii:
        assert out == text  # 무수정
    else:
        assert "700101" not in out
        assert "010-" not in out or "01" + "0-" not in out
```

```python
# tests/test_me_routes.py
def test_export_returns_only_own_data(client_authed):
    r = client_authed("user-1").get("/me/export")
    assert all(s["user_id"] == "user-1" for s in r.json()["chat_sessions"])

def test_delete_anonymizes_audit(client_authed):
    client_authed("user-1").delete("/me")
    rows = audit_log.fetch_by_user("user-1")
    assert all(r["question"] is None for r in rows)
```

### 5.2 통합 / 보안

- 다른 user 의 user_id 로 /me/export 시도 → 403 (RLS + 미들웨어)
- 미인증 GET /me/export → 401
- DELETE /me 후 1초 내 audit_log UPDATE 완료 (대기 시간 측정)

### 5.3 회귀

- 기존 chat 통합 테스트 PASS (redact 적용 후에도 RAG 정확도 무영향 — RAG 는 원문 사용)
- audit_log 기존 row 읽기 PASS (NULL 컬럼 허용)

### 5.4 정량 지표

| 지표 | 목표 |
|---|---|
| PII redact precision | > 95% (한국 RRN/전화 100%) |
| PII redact false positive rate | < 5% (일반 숫자 → 카드 오인 등) |
| /me/export 응답 시간 (1000 row) | < 2s |
| 보존 cron 익명화 처리량 | > 10K row / 분 |
| 정적 페이지 3개 Lighthouse | accessibility ≥ 90 |

## 6. 위험 / 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 정규식 false positive (예: 13자리 일반 숫자 → 카드 오인) | 답변 텍스트 마스킹 | Luhn 검증 통과 시에만 카드 마스킹, roll-forward |
| 익명화 후 사용자 후회 (복구 불가) | 컴플레인 | 90일 시점 통보 메일 (선택, PRD 결정), DELETE /me 는 7일 grace period 권장 |
| Sentry/Loki 외부 sink 가 raw payload 캡처 | PII 외부 노출 | `_emit` 진입에서 redact, Sentry `before_send` hook 동일 redactor 재사용 (TRD-004 와 결합) |
| 약관 변경 시 재동의 강제 | UX 마찰 | `consented_at + version` 저장, version mismatch 시 재동의 모달 |
| GDPR 외 지역 (한국 PIPA) 요건 차이 | 법적 위험 | C5 약관에 적용 법률 명시, 변호사 검토 권장 (PRD-005 비-목표지만 권장) |
| 보존 cron 실패 시 무한 누적 | DB 비대화 | GH Actions 실패 알림 → infra/alerting (TRD-004) 으로 critical |

## 7. 비-목표 / TRD 범위 외

- 기존 audit.db 1회성 redact 마이그레이션 — 소급 적용은 별도 스크립트, PRD 결정 후
- DSAR (Data Subject Access Request) 자동화 워크플로우 — 수동 응대로 시작
- ML 기반 PII 탐지 (Microsoft Presidio 등) — 정규식 1차로 충분 시 도입 보류
- 데이터 가명화/암호화 (at-rest) — 인프라 영역, TRD 범위 외 (Supabase 기본 암호화 의존)
- 데이터 거주지 (region) 강제 — Supabase project region 선택으로 위임
- 쿠키 동의 배너 (GDPR cookie law) — 분석 도구 도입 시 별도
