# 013. Supabase 영속화 — 4가지 결정의 근거

> 2026-05-06

## 결정

PRD-002 (다기기 동기화) 합류 단계에서:

1. **사용자 식별**: Supabase Auth + 이메일 Magic Link
2. **스키마**: JSONB 1-table (`conversations(id, user_id, state jsonb, ...)`)
3. **Checkpointer**: 자체 `ConversationStore` Protocol 어댑터 (langgraph-checkpoint-postgres 미사용)
4. **절체 방식**: Supabase 진실원천 + IndexedDB 캐시

## 왜

### 결정 1 — Magic Link

비밀번호가 *없어서 좋다*. 사용자는 이메일만 입력하면 된다. 챗봇이 시연 / 학습 자산이라
"포트폴리오 보여주는 사람이 비밀번호 만드는 마찰" 자체가 무의미. OAuth (구글) 도 가능하나
도메인 등록·콘솔 의존이 추가되고, Magic Link 만으로 *다기기 동기화 본질* 은 충분히 풀린다.

### 결정 2 — JSONB 1-table

도메인의 `Conversation` 이 frozen Pydantic 이라 `model_dump_json` 이 *손상 없는* 단일 직렬화
포인트다. 그러면 DB 스키마는 *단일 jsonb 필드* 로 충분하다. 도메인 스키마 변경 시 DB
마이그레이션 0 — 도메인만 갱신하면 됨.

부분 쿼리·인덱싱은 jsonb 위에 GIN 인덱스로 풀 수 있다. 데이터 규모가 *부분 쿼리 비용을
정당화* 하는 시점이 오면 정규화된 `turns` 테이블로 옮긴다 (TRD-011 §결정 2 의 향후 출구).

### 결정 3 — 자체 ConversationStore

LangGraph 의 `langgraph-checkpoint-postgres` 는 *messages* 추상에 묶여 있고, 우리 도메인
`Turn` 은 messages 보다 풍부하다 (intent / standalone_question / selected_strategy /
retrieval_result_ref / trace_id / elapsed_ms / started_at). 그것을 messages 로 평탄화하면
강제 손실이 발생.

자체 어댑터는 chatbot 도메인 모델을 그대로 직렬화. 변경 자유 (LangGraph 라이브러리 변화에
독립). 약 150줄.

### 결정 4 — Supabase 진실원천

PRD-002 의 본질이 *다기기 동기화* 다. 두 디바이스에서 같은 데이터를 보장하려면 *공통 진실원천*
이 서버여야 한다. IndexedDB 가 진실원천이면 디바이스 간 충돌이 일상적.

IndexedDB 는 *오프라인 fallback + 첫 로딩 캐시* 로 강등. Supabase 가 1차, IndexedDB 가 2차.

## 트레이드오프

| 받아들인 것 | 잃는 것 |
|---|---|
| Vendor lock-in (Supabase) | 운영 단순성 — 인증·DB·Realtime·Storage 가 한 콘솔 |
| jsonb 단일 필드 (부분 쿼리 어려움) | 향후 정규화 출구는 명시 — TRD §결정 2 |
| 자체 어댑터 (~150줄 직접 구현) | LangGraph 라이브러리 변화 독립 |
| 첫 빌드 시 Supabase 프로젝트 + Auth UX 추가 | 다기기 동기화 본질 살아남 |

## 대안과 기각 사유

### A. Cloudflare Access (Zero Trust)

인증만 단일 진입점으로. 그러나 챗봇 자체 회원 모델이 없고 *다기기 = 같은 IdP 로그인 전제*.
Supabase 를 안 쓰면 DB 도 별도 선정 필요 → 외부 의존이 둘로 늘어남. 단순성 우선으로 기각.

### B. device_id 만 (인증 X)

IndexedDB 그대로 유지하고 device_id 로 사용자 격리. 다기기 동기화 *불가능*. PRD-002 의
목표 자체와 충돌 — 기각.

### C. langgraph-checkpoint-postgres 표준

LangGraph 의 표준 추상 사용. 우리 도메인이 더 풍부해서 강제 손실. 또 LangGraph 라이브러리
변화에 종속. 기각.

### D. 정규화된 `turns` 테이블 (옵션 c)

부분 쿼리·인덱싱 명확. 그러나 *현 단계* 에서 부분 쿼리 압박이 없고, 도메인 스키마 변경 시
DB 마이그레이션 비용이 추가됨. 출구로 명시하되 현재는 (b) JSONB 채택.

## 회귀 방어선

- PR 12~14 (백엔드만) 머지 후 *프론트는 IndexedDB 그대로*. 백엔드가 Supabase 인지하나 프론트
  미절체 — `ConversationStore=None` 받으면 stateless fallback (PR 11 의 도메인 Protocol 이
  optional 로 받음).
- PR 15 (프론트 절체) 후 1주 안정화. 이전 IndexedDB 사용자 데이터는 PR 16 의 일회성
  마이그레이션 + readonly 보존.
- `AUTH_ENABLED=false` 환경변수 — dev/시연 모드는 익명 path 그대로.

## 메모

- Supabase service_key 는 *서버 컨테이너* 에서만 사용. RLS 우회 가능하므로 외부 노출 0.
- 프론트는 anon_key 만. RLS 가 사용자 격리 보장.
- LangGraph 자체 사용은 그대로 — 본 결정은 *checkpointer (영속화 추상)* 만 자체 구현.
- 4 결정 모두 PR 단위로 검증 — 각 audit-agent 가 분기 위반 없는지 확인.
