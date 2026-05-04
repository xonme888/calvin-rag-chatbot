---
status: draft
group: E
created: 2026-05-04
related_trd: docs/trd/draft/005-data-governance.md
---

# PRD: 데이터 거버넌스 (사용자 권리 · 보존 정책 · PII redaction · 약관/저작권)

## 1. 배경 / 문제

PRD-2 가 인증을 도입하고 사용자 데이터(chat_sessions, audit_log, trace stdout) 가 식별자에 묶이는 순간, PIPA(국내) / GDPR(국외) 의 사용자 권리 — 삭제권 · 열람권 · 익스포트 권 — 가 법적 기본 의무가 된다. 외부 사용자 1명이라도 노출되면 "처리방침에 명시된 보존 기간 / 사용자 권리 행사 절차" 가 없는 상태는 위반 위험이다.

현재 audit_log 는 `api/middleware/audit_log.py:31-50` 의 `AuditRecord` 가 `ip` (식별자) + `question` 본문 (PII 가능) 을 영구 저장한다. `_DEFAULT_DB_PATH = ~/.calvin-rag-chatbot/audit.db` (line 21) 에 무기한 누적된다. 사용자가 "내 기록을 지워달라" 고 요청해도 cascade 가 없다.

trace stdout (`infra/observability.py:47-67`) 도 `_emit` 가 prompt preview 를 200자 잘라 출력하는데, 사용자가 질문에 이메일/전화/주민번호를 붙여 넣으면 그대로 stdout 에 남고, 운영 환경에서 외부 수집기로 보내지면 회수 불가하다.

약관/방침/저작권 페이지도 없다. 칼빈 강요 한국어 번역본은 출판사 저작권 자료 (CLAUDE.md 의 "Data & License" 명시) — 외부 공개 챗봇이 인용을 그대로 노출하면 저작권 면책 고지가 필요하다.

본 PRD 는 **PRD-2 직후** 다룬다. 인증이 들어가야 사용자 단위 cascade 가 의미 있고, PRD-4 의 quota 가 들어가야 cascade 호출 자체가 폭주 차단된다.

## 2. 목표

- 사용자가 "내 데이터 삭제" / "내 데이터 익스포트" 를 셀프서비스로 1클릭 요청할 수 있다 (PIPA 제 36/37조, GDPR Art. 15/17 충족).
- 모든 PII 후보(이메일/전화/주민번호 등) 가 audit_log 와 trace 에 들어가기 전 마스킹된다.
- 보존 기간이 명시되고, 자동 익명화 cron 이 실행된다.
- 약관 / 처리방침 / 저작권 고지 페이지가 회원가입 동의 흐름과 결합된다.

## 3. 비-목표

- 결제 / 요금제 약관 (PRD-4 가 결제 도입 시 별도).
- KG / Vector index 의 사용자별 격리 — 본 챗봇은 단일 도메인(칼빈 강요) read-only index 를 공유한다. 사용자가 인덱스에 기여하지 않으므로 격리 불필요.
- LLM 모델 학습 데이터 옵트아웃 정책 — OpenAI 의 enterprise 옵션은 별도 계약. 본 PRD 는 운영자가 OpenAI 와 무엇을 계약했는지 약관에 명시만.
- 데이터 portability (다른 챗봇으로 import 가능한 표준 포맷). 본 PRD 는 JSON dump 만.
- 다국어 약관 (영문/일문). 한국어 1종.

## 4. 사용자 시나리오 / BDD

- Given 로그인 사용자가 설정 페이지의 "내 데이터 삭제" 버튼을 누르고 비밀번호 재확인을 통과하면
  When `DELETE /api/me` 가 호출되며
  Then chat_sessions 가 즉시 삭제되고, audit_log 의 user_id 가 24시간 안에 "deleted-{hash}" 로 익명화되며, 처리 완료 시 등록된 이메일로 1회 통보가 간다.

- Given 로그인 사용자가 "내 데이터 다운로드" 를 요청하면
  When `GET /api/me/export` 가 호출되며
  Then 모든 chat_sessions + audit_log 본인 row + 동의 이력이 단일 JSON 파일로 묶여 24시간 만료 다운로드 링크가 메일로 발송된다.

- Given 사용자가 질문에 "제 이메일은 abc@example.com 인데" 라고 입력하면
  When 입력이 audit_log 에 기록되며
  Then question 필드에는 "제 이메일은 [REDACTED:email] 인데" 로 마스킹되어 저장되고, trace stdout 의 prompt preview 도 동일하게 마스킹된다.

- Given 신규 회원가입 흐름에서
  When 사용자가 약관 / 처리방침 / 저작권 고지를 모두 체크하지 않으면
  Then "가입" 버튼이 비활성 상태이고, 체크 후 가입 시 동의 시각이 auth.users metadata 에 박힌다.

- Given audit_log 에 91일 전 row 가 있으면
  When 일일 익명화 cron 이 돌면
  Then user_id 와 ip 컬럼이 "anonymized" 로 마스킹되고, question/answer_preview 는 그대로 유지된다 (운영 분석용).

## 5. 결정해야 할 사항

### 결정 1 — 약관 작성 주체

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 직접 작성 (한국 PIPA 표준 구성 따라) | 0.5일 + 본인 시간 | 가장 빠름 | 법적 검토 부재, 외부 사용자 늘 때 재작성 | ★ (Phase 1) |
| 표준 템플릿 (Termly, iubenda 등) | 월 $0~20 | 양식 안정성 | 도메인 특수 항목 (LLM, 칼빈 PDF 인용) 자동 반영 안 됨 | |
| 변호사 검토 | 50만원~ | 법적 안정성 | 시연 단계에 과투자 | (외부 사용자 N>10 시) |

비고: Phase 1 은 직접 작성, "본 서비스는 시연/포트폴리오 목적이며 정식 사용 시 별도 검토 필요" 명시. PRD-2 의 외부 사용자 본격 노출 전 변호사 검토.

### 결정 2 — 자동 익명화 시점

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 90일 후 익명화 | 짧음 | 운영 분석 데이터 적음 | PIPA 권장 보존 기간 (1년) 보다 짧음 — 단 동의 받으면 OK | ★ |
| 180일 후 익명화 | 중간 | 운영 분석 충분 | 저장 비용 누적 | |
| 1년 후 익명화 | 김 | 장기 추세 분석 가능 | 개인정보 보유 위험 누적 | |

비고: 처리방침에 "audit log 90일, 익명화 후 추가 1년 보관" 명시. user 가 명시적으로 삭제 요청하면 90일 전이라도 즉시 익명화.

### 결정 3 — PII redaction 범위

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 한국 한정 (주민번호 / 전화) | 0.5일 | 핵심만 | 이메일 / 카드번호 노출 위험 | |
| 국제 (이메일 / 전화 / 주민번호 / 카드 / IP) | 1일 | 외부 사용자 대비 | 가짜 양성 (정상 텍스트 마스킹) 위험 | ★ |
| LLM 기반 분류 (cheap LLM 으로 PII 탐지) | 호출 1회/메시지 | 정확도 | 비용 + latency | (외부 사용자 본격 노출 시) |

비고: 정규식 기반 1차, 가짜 양성 발생 시 사용자가 "마스킹 해제" 토글 (저장된 audit log 는 마스킹 유지, 그 메시지만 원문 노출). LLM 기반은 후속.

### 결정 4 — 익스포트 포맷

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 단일 JSON dump | 적음 | 단순, 기계 읽기 쉬움 | 사람이 읽기 불편 | ★ |
| Markdown 대화록 + JSON 메타 | 중간 | 사람이 읽기 좋음 | 구현 복잡 | |
| GDPR 표준 SCIM/JSON-LD | 큼 | 표준 준수 | 외부 사용자 N<10 에 과투자 | |

## 6. 기능 요건

- `DELETE /api/me` — 인증 + 비밀번호 재확인 후 cascade 트리거. 응답은 202 Accepted (비동기 처리).
  - chat_sessions: 즉시 삭제
  - audit_log: user_id → `deleted-{user_id 의 sha256 prefix 8자}`, ip → null, question/answer_preview 는 본문 보존 (운영 분석)
  - trace stdout: 보존 기간 (Phase 1 = stdout 7일 default) 후 자동 삭제
  - 처리 완료 시 메일 알림
- `GET /api/me/export` — 동기 응답. 1MB 미만이면 inline JSON, 초과 시 background job + 메일 링크 (만료 24시간).
- `infra/pii_redactor.py` 신규 — 정규식 기반 마스킹.
  - 패턴: 이메일, 한국 전화 (010/02-XXX), 주민번호 (NNNNNN-NNNNNNN), IPv4, 카드번호 (16자리)
  - 호출 위치: `api/middleware/audit_log.py:log_chat` 의 question/answer_preview 저장 직전, `infra/observability.py:_emit` 의 prompt preview 직전
  - 마스킹 형식: `[REDACTED:email]`, `[REDACTED:phone]` 등
- 보존 정책 cron — 일 1회 실행:
  - audit_log: 91일 이전 row 익명화
  - audit_log: 1년 + 90일 (총 455일) 이전 row 삭제 (익명화 + 1년 보관)
  - 만료된 export 다운로드 링크 정리
- 약관/방침/저작권 페이지 (Next.js):
  - `/terms` — 서비스 약관 (사용자 책임, AI 답변 부정확 가능 면책, OpenAI 데이터 처리 명시)
  - `/privacy` — 개인정보 처리방침 (수집 항목, 보존 기간, 사용자 권리, 문의처)
  - `/license` — 칼빈 강요 PDF 출판사 저작권 + 인용 사용 면책 ("학습/포트폴리오 목적, 상업 이용 금지")
- 회원가입 동의 — 3개 항목 별도 체크박스 + 동의 시각/버전을 `auth.users.user_metadata.consents` 에 저장.

## 7. 성공 지표 (정량)

- DELETE /api/me 요청 → cascade 완료 → 메일 알림까지 24시간 내 100%.
- audit_log / trace stdout 의 PII 정규식 검출 0건 (월간 sampling 100건 검사 기준).
- 약관/방침 미동의 가입 시도 0건 (UI 차단 + 백엔드 검증 이중).
- 91일 이전 audit_log 의 user_id 비익명 row 0건.

## 8. 의존 / 영향 / 회귀 위험

- **의존**: PRD-2 (인증/`user_id`/메일) 가 선행. PRD-2 없이는 cascade/익스포트 키가 잡히지 않는다. PRD-4 의 quota 가 들어가야 export 요청 폭주 방어 가능.
- **영향**: `api/middleware/audit_log.py:AuditRecord` 에 `user_id` 필드가 추가된다 (PRD-2 가 정의). 기존 row 는 `user_id=null` 유지 — schema 마이그레이션은 `_ensure_schema` 의 ALTER 패턴 그대로.
- **회귀 위험 (중)**: PII 마스킹이 RAG 입력 question 자체를 변형하면 답변 품질에 영향. 본 PRD 는 audit/trace 만 마스킹하고 LLM 으로 가는 question 은 원문 유지. 단, 사용자가 "프롬프트에 PII 가 들어가면 OpenAI 로 전송됨" 을 약관에 명시.
- **회귀 위험 (중)**: cascade 의 audit_log 익명화는 운영 분석 (라우터 정확도 등) 에 영향 없음 — 본문은 보존. 단 사용자별 라우팅 패턴 분석은 익명화 후 불가.
- **회귀 위험 (저)**: 보존 정책 cron 이 다운되면 91일 초과 row 가 누적된다 — PRD-4 의 health/알림에 cron 마지막 성공 시각 포함.
- **회귀 위험 (저)**: 회원가입 동의 체크박스 추가가 PRD-2 의 Magic Link 흐름에 1단계 더 추가됨 — UX 마찰 증가.

비고: 본 PRD 는 한국어/한국 사용자 가정. 영문 약관, 다국가 PIPA-등가 법령(CCPA/LGPD 등) 대응은 외부 사용자 본격 진출 시 별도. KG/Vector index 격리, OpenAI enterprise 계약, 변호사 검토는 본 PRD 외.
