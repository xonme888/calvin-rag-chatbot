---
status: draft
group: A
created: 2026-05-04
---

# PRD: 도구/입력 확장 (Tool Registry · 이미지 입력 · Reasoning trace)

## 1. 배경 / 문제

현재 Agentic 모드는 `rag_core/agentic.py:225` 에서 `self._tools = [self._make_search_tool()]` 로 검색 도구 1개를 하드코딩한다. 도구를 늘리려면 `AgenticRAG.__init__` 와 `create_agent(tools=...)` 호출 사이를 수정해야 한다 — 외부 어댑터(MCP, 외부 API) 가 들어올 자리가 없다.

입력 측은 텍스트 1개만 허용한다. `web/lib/sessionStore.ts:15-19` 에 `SessionAttachment` 타입은 미리 마련됐지만 사용처가 없다 — 이미지/파일 첨부 흐름이 비어 있다.

도구 호출 가시성도 부족하다. `agentic.py:81-115` 의 `message_to_stream_events` 가 `thinking` / `tool_result` 이벤트를 발행하지만 프론트(`web/components/ChatPanel.tsx`, `web/lib/blocks.ts`) 는 이를 답변 본문에 흡수하지 않고 SSE 진행 표시로만 소비한다. 답변 카드 안에 "어떤 도구를 어떤 인자로 호출했는지" 가 남지 않아 신뢰/디버깅이 둘 다 약하다.

이 PRD 는 **다음 PRD-2(다기기 동기화) / PRD-3(데이터·UX 안전망) 보다 먼저** 다룬다 — 도구 출력이 늘어나면 세션 페이로드 모양이 바뀌므로 동기화 스키마를 그 뒤에 정해야 재작업이 적다.

## 2. 목표

- Agentic 모드에 도구 N 개를 등록/제거하는 비용을 "Registry 한 줄" 로 낮춘다.
- 사용자가 이미지를 첨부해 칼빈 도판/표지/필사본 사진에 대해 질문할 수 있다 (vision 한정으로 시작).
- 답변 카드에 도구 호출 단계를 접힘(collapsible) 형태로 노출해 "왜 이 답이 나왔나" 를 추적 가능하게 한다.

## 3. 비-목표

- 외부 서비스 배포·과금 정책. 도구가 외부 API 키를 요구해도 이 PRD 는 키 발급/요금 한도를 다루지 않는다.
- 이미지 생성. 입력만 허용하고 모델이 그림을 만들어주는 시나리오는 제외.
- 음성/비디오 입력. 별도 PRD.
- 도구별 RAGAS 평가 — `experiments/eval/` 의 4지표 파이프라인은 텍스트 응답을 가정한다. 도구 결과 평가 지표는 후속 작업.
- Vision 도구는 본 PRD 의 1순위가 아니다 — PRD-2 (인증) + PRD-4 (사용자별 cap) 도입 후로 게이팅. 인증 없는 vision 은 비용 폭주 위험이 가장 큰 도구이므로 quota 인프라가 선행되어야 한다.

## 4. 사용자 시나리오 / BDD

- Given 사용자가 "오늘자 칼빈주의 관련 뉴스 알려줘" 라고 묻고
  When Agentic 라우팅이 적용되며
  Then 답변 카드 상단의 reasoning trace 에 `web_search(query="...")` 호출과 결과 요약이 접혀서 표시된다.

- Given 사용자가 칼빈 강요 표지 이미지를 첨부하고 "이 판본의 출판 시기를 추정해줘" 라고 묻고
  When 이미지 입력이 vision 도구로 전달되며
  Then 답변에 "본문에서 직접 찾을 수 없습니다" 또는 vision 분석 결과가 명시되며 출처/근거가 함께 표기된다.

- Given 사용자가 reasoning trace 패널을 펼치고
  When 특정 도구 호출 행을 클릭하면
  Then 호출 인자와 응답 미리보기가 같은 행 아래 표시된다.

## 5. 결정해야 할 사항

### 결정 1 — MCP/도구 첫 후보

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 웹 검색 (Tavily 또는 Brave) | API 키 + 월 무료 한도 안 | "최신" 키워드 라우팅이 의미 있어짐 | 결과 품질 편차, 외부 의존 | ★ |
| 이미지 검색 (SerpAPI 등) | 유료 비중 큼 | 도판/지도 표시 가능 | 저작권 회색 영역 | |
| MCP filesystem | 0 (로컬) | 사용자 노트/스크랩과 연동 | 시연 가치 낮음 | |
| 칼빈 도메인 외부 도구 (스트롱코드 사전 등) | 일부 무료 API | 도메인 적합 | 적합 API 확보 불확실 | |

### 결정 2 — 이미지 입력 범위

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| vision 첨부만 (OpenAI vision 모델 1개 경로) | 적음 | 시연 강함 | 모델 비용 상승 | ★ |
| 이미지 검색 결과 노출 | 중간 | 시각화 풍부 | 저작권 | |
| 이미지 생성 (DALL·E 등) | 큼 | 도메인 적합도 낮음 | 환각/오해 유발 | |
| 안 함 (텍스트만 유지) | 0 | 작업량 0 | 입력 확장 불가 | |

### 결정 3 — Reasoning trace 상세도

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 도구 호출 이름 + 인자만 | 적음 | "무엇을 했나" 만 보임 | 디버깅 부족 | |
| LLM 프롬프트 preview 까지 | 큼 | 디버깅 강력 | 토큰 비용/스크롤 폭주, 노이즈 | |
| 단순 timeline (도구 호출 + 결과 요약) | 중간 | "왜 이 답인가" 가 읽힘 | 결과 요약 로직 추가 | ★ |

## 6. 기능 요건

- 사용자가 첨부 버튼으로 이미지를 업로드할 수 있다 (단일, 5MB 이하, 형식 TRD 에서 확정).
- 첨부된 이미지는 답변 카드 위쪽에 썸네일로 남는다 (메시지 영구 첨부물).
- Agentic 모드 답변 카드에 "도구 호출 (N)" 토글이 표시되고, 펼치면 호출 순서대로 행이 나열된다.
- 등록된 도구 목록은 `/api/health` 또는 `/api/modes` 응답에 노출된다 (운영자 가시성).
- 도구 추가/제거가 `mode_registry.py` 와 동일한 Registry 패턴 ("한 곳에서 선언") 으로 가능하다.
- MCP 서버 등록은 환경변수 `MCP_ALLOWED_SERVERS` allowlist 만 허용한다 — 임의 MCP URL 주입을 LLM 이 도구 인자로 시도하더라도 등록되지 않은 서버는 호출 불가.
- 도구 description / schema 는 시스템 prompt 와 분리된 별도 message 영역 (LangChain `tools` 인자) 으로만 LLM 에 노출 — 사용자 입력이 도구 description 자리에 끼어들 수 없도록 격리.
- 도구별 per-call timeout (기본 10초) 및 호출당 토큰 cap (기본 입력 2,000 / 출력 4,000) 을 registry 메타데이터로 선언. 한 도구가 LLM context 를 폭주시키는 것을 차단.
- 외부 API 가 timeout / 5xx 로 응답하면 PRD-4 의 circuit breaker 가 30초 내 fallback 모드 전환을 트리거 — 본 PRD 는 도구 실패를 trace event 로 emit 만 하고 차단 정책은 PRD-4 에 위임.

## 7. 성공 지표 (정량)

- 도구 1개 추가 시 변경 파일 수 ≤ 2 개.
- Reasoning trace 펼침으로 모든 Agentic 답변에 호출 내역이 100% 노출 (답변 후 trace 비어 있음 0건).
- 이미지 첨부 질의 5건 시범 시, 4건 이상에서 vision 응답이 본문에 맥락 있게 인용됨 (수동 평가).
- 도구 호출 평균 응답 시간 증가가 기존 Agentic 대비 +30% 이내 (외부 API latency 포함).
- 도구 호출 실패율 < 1% (5분 평균). 외부 API circuit open 시 30초 내 fallback 모드 전환 (PRD-4 의 breaker 임계와 동일).

## 8. 의존 / 영향 / 회귀 위험

- **의존**: 없음. PRD-2(인증) 보다 먼저 진행 가능.
- **영향**: `SessionMessage.attachments` 가 실제로 채워지므로, 직후 PRD-2 의 서버 영속화 스키마는 attachments 를 포함해야 한다. 작업 순서 권장: 본 PRD → PRD-2.
- **회귀 위험 (중)**: Agentic 의 SSE 이벤트 (`stream_steps`) 가 reasoning trace 표시를 위해 페이로드 모양이 살짝 변경된다. `web/components/ChatPanel.tsx` 의 SSE 소비 경로를 동시에 수정해야 한다.
- **회귀 위험 (저)**: 이미지 첨부 페이로드가 추가되면 `/chat` 엔드포인트 요청 스키마(`api/schemas.py`) 가 multipart 또는 base64 로 분기된다 — 텍스트 전용 흐름은 그대로 두고 신규 경로로 분리.
- **회귀 위험 (저)**: 외부 도구 도입 시 `infra/observability.py` trace event 가 외부 호출까지 포함하도록 확장. 누락 시 라우터 audit 가 절반만 보인다.

비고: 도구 결과의 RAGAS 평가, 이미지 검색 저작권 처리, 도구 권한 모델은 본 PRD 범위 외이며 이후 별도 TRD/PRD 에서 다룬다.
