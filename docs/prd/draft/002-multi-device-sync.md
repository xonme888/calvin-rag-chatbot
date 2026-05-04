---
status: draft
group: B
created: 2026-05-04
---

# PRD: 인증 + 다기기 세션 동기화

## 1. 배경 / 문제

세션 영속화는 현재 브라우저 단일 디바이스에 묶여 있다. `web/lib/sessionStore.ts:39-40` 의 `KEY_SESSIONS = "calvin-chat:sessions"` 키가 가리키는 곳은 `localStorage` 다 (`sessionStore.ts:108-135`). 노트북에서 시작한 대화가 폰에서는 보이지 않는다.

사용자 식별은 아직 없다. `api/routes/chat.py` 가 익명 요청을 그대로 받는다. 누가/언제/무엇을 물었는지 audit 와 묶을 안정적 식별자가 없으므로 — `infra/observability.py` 의 `trace_id` 는 요청 단위 추적이지 사용자 단위 추적이 아니다.

또 PRD-1 이 `SessionMessage.attachments` 에 도구 결과/이미지 메타를 채우기 시작하면, localStorage 5MB 한도(특히 KG subgraph + 도구 결과 누적) 와 다기기 동기화 부재가 동시에 압박이 된다. 그래서 **PRD-1 직후, PRD-3 보다 먼저** 다룬다.

이 PRD 는 외부 노출/배포 자체는 다루지 않는다. 인증/동기화의 **데이터·인터페이스 모양** 만 정한다 (배포는 별도).

## 2. 목표

- 한 사용자가 여러 디바이스에서 로그인했을 때 같은 대화 목록과 같은 메시지 본문을 본다.
- 인증 도입이 익명 시연 흐름(로컬 dev) 을 부수지 않는다 — 로그인 없이도 단일 디바이스 사용은 유지.
- `useSessions` 인터페이스(`sessionStore.ts:79-98`) 를 깨지 않는다 — 백엔드 영속화로 어댑터만 swap.

## 3. 비-목표

- 권한/공유 (다른 사용자에게 대화 공유). 본 PRD 는 단일 사용자의 다기기만.
- 서버에서 답변을 다시 생성 후 "이어쓰기" 하는 시나리오 (디바이스 전환 중 진행 중인 SSE 스트림 인계). `pendingIds` 는 메모리만 유지하고, 디바이스 전환 시 진행 중 답변은 끊는다.
- Encryption-at-rest 정책 / 백업 전략. TRD 또는 별도 PRD.
- Streamlit 레거시 측 동기화 — 이 PRD 는 Next.js 경로만.

## 4. 사용자 시나리오 / BDD

- Given 사용자가 노트북에서 로그인하고 3개 세션을 만든 상태에서
  When 폰 브라우저로 같은 계정으로 로그인하면
  Then 사이드바에 같은 3개 세션이 같은 순서로 노출되고, 각 세션의 마지막 답변까지 그대로 보인다.

- Given 사용자가 노트북에서 답변 스트리밍 중에 폰에서 같은 세션을 열고
  When 폰에서 새 질문을 입력하면
  Then 노트북의 진행 중 답변은 중단되고, 폰의 새 질문이 그 다음 메시지로 추가된다 (충돌 시 last-write-wins, 사용자에게 토스트).

- Given 인증을 켠 상태에서 비로그인 사용자가 접속하면
  When `/login` 으로 리다이렉트되며
  Then Magic Link 또는 OAuth 중 1가지 방식으로 로그인할 수 있다.

- Given 로컬 dev 모드(`AUTH_ENABLED=false`) 에서
  When 비로그인 사용자가 접속하면
  Then 익명 device-scoped 세션이 그대로 동작한다 (오늘과 동일).

## 5. 결정해야 할 사항

### 결정 1 — 인증 방식

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| Supabase Auth + Magic Link | 무료 한도 충분, 1~2일 | UI 단순, 비밀번호 없음 | 메일 전달 지연 | ★ |
| Supabase Auth + Google OAuth | 1~2일, OAuth 콘솔 등록 필요 | 클릭 한 번 로그인 | 도메인 등록·콘솔 의존 | |
| Cloudflare Access JWT (이미 task #33 에 잡혀 있던 것) | Zero Trust 무료 한도, 0.5일 | 인프라 단일 진입점 | 챗봇 자체 회원 모델 안 가짐 — 다기기는 같은 IdP 로그인 전제 | |
| device_id 만 (인증 X) | 0 | 익명 유지 | 다기기 동기화 불가 — 본 PRD 의 목표와 충돌 | |

비고: Supabase 를 고르면 다기기 동기화의 DB(Postgres + Realtime) 도 같은 벤더로 묶인다. Cloudflare Access 를 고르면 DB 는 별도 선정 필요.

### 결정 2 — 다기기 동기화 시점

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 인증 + 동기화 동시 도입 | 3~4일 | "본 PRD 가 목표한 모양" 그대로 | 큰 PR, 회귀 위험 집중 | ★ |
| 인증만 먼저, 동기화는 다음 단계 | 1~2일 인증 + 1~2일 동기화 분리 | 단계별 검증 가능 | 인증만 켜진 동안 다기기 미동기 → 사용자 혼란 | |
| localStorage 유지하고 IndexedDB 가지치기만 (PRD-3 의 W1 으로 처리) | 0.5일 | 다기기 미해결, 단일 디바이스 한도만 회피 | 본 PRD 의 목표 미달 | |

### 결정 3 — 동기화 충돌 정책

옵션은 단일 PRD 안에서 합의 — last-write-wins (서버 timestamp 기준) + 충돌 시 사용자 토스트. CRDT 등 본격 머지는 비-목표. ★ 채택.

## 6. 기능 요건

- 로그인/로그아웃 UI (헤더 우측). 미로그인 상태에서 사이드바는 익명 세션만 노출.
- `/api/sessions` GET / PUT / DELETE — 사용자 단위 세션 목록 동기화.
- `/api/sessions/{id}/messages` — 메시지 append. 메시지 단위 영속화 (전체 세션 통째 저장 X).
- 로그인 시점에 익명 localStorage 세션을 사용자 계정으로 "병합" 할지 묻는 1회성 다이얼로그 (Yes/No).
- 환경 플래그 `AUTH_ENABLED` — `false` 면 모든 인증/서버 동기화 우회 (dev/시연용).
- 로그인 사용자의 trace event 에 `user_id` (해시) 포함 — `infra/observability.py` 의 trace event 확장.

## 7. 성공 지표 (정량)

- 동일 계정 두 디바이스에서 세션 목록 일치율 100% (10건 시범, 5초 이내 반영).
- `useSessions` 의 외부 호출자(현재 `web/components/SessionSidebar.tsx`, `web/components/ChatPanel.tsx`) 코드 변경 0줄 (어댑터 swap 만으로).
- 인증 도입 후 익명 dev 시연 회귀 0건.
- 메시지 append 평균 latency ≤ 200ms (서버 동기화 path).

## 8. 의존 / 영향 / 회귀 위험

- **의존**: PRD-1 의 `SessionMessage.attachments` 가 채워진 뒤 본 PRD 의 동기화 스키마를 정한다. 그렇지 않으면 attachments 가 누락된 스키마로 굳어 재마이그레이션이 필요해진다.
- **영향**: PRD-3 의 W1(localStorage → IndexedDB) 은 본 PRD 가 진행되면 자동 무력화된다. 결정 5(라우터 진화) 의 audit log 조회는 사용자 단위로 묶을 수 있게 된다.
- **회귀 위험 (중)**: `useSessions` 어댑터 swap 시 `pendingIds` 의 메모리 전용 가정이 깨질 수 있다 — 멀티 탭/다기기에서 진행 중 표시가 어떻게 되는지 BDD 명시 필요.
- **회귀 위험 (중)**: 백엔드 인증 미들웨어 추가 시 SSE 엔드포인트(`api/routes/chat.py`) 의 `EventSource` 헤더 인증을 어떻게 통과시킬지 결정 필요 — 쿠키 기반이 자연스러우나 cross-origin 시 별도 처리. 세부 TRD.
- **회귀 위험 (저)**: 인증 추가 후 trace event 에 `user_id` 가 들어가면 PII 정책을 정해야 한다 (해시 권장). TRD 에서 확정.

비고: SSE 인계, 권한/공유, encryption-at-rest 는 본 PRD 외. CRDT/오프라인 머지도 비-목표.
