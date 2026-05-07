# Next.js 프론트 기능 정의서

`app/calvin_chatbot.py` (메인 572줄) + `app/pages/01_compare_modes.py` (비교 219줄) 의
모든 기능을 Next.js로 이식하기 위한 단일 진실 원천 명세.

## 매핑 원칙

| Streamlit | Next.js |
|---|---|
| `st.sidebar` | 좌측 `<aside>` 또는 모바일 햄버거 메뉴 |
| `st.radio` / `st.button` | 자체 button 컴포넌트 |
| `st.slider` | `<input type="range">` + 값 표시 |
| `st.chat_input` | form + textarea/input |
| `st.chat_message` | 메시지 카드 (user/assistant 구분) |
| `st.write_stream` | 자체 SSE 파싱 (이미 `lib/api.ts` 에 구현) |
| `st.status(expanded)` | `<details open>` + 상태 라벨 변경 |
| `st.expander` | `<details><summary>` |
| `st.spinner` | 로딩 스피너 컴포넌트 |
| `st.markdown` | `react-markdown` 또는 plain text |
| `st.error` / `st.warning` / `st.info` | 색상 박스 컴포넌트 (red/amber/blue) |
| `st.metric` | 값 + 라벨 카드 |
| `st.code` | `<pre><code>` |
| `st.divider` | `<hr>` |
| `st.session_state.messages` | React state (혹은 zustand 향후) |
| `st.cache_resource` | API `/modes` 응답 (서버 측 캐시) |

---

## 메인 페이지 (`/`) — 기능 명세

### 사이드바

| ID | 기능 | Streamlit 위치 | Next.js 구현 | Tier |
|---|---|---|---|---|
| F-MAIN-S01 | "설정" 제목 | line 277~278 | `<aside><h2>설정</h2></aside>` | P0 |
| F-MAIN-S02 | **모드 라디오** (Hybrid/Agentic/KG) | line 286~296 | 이미 `ModeSelector.tsx` 구현 — KG 가용성 자동 | **P0 ✓** |
| F-MAIN-S03 | KG 미가용 정보 배너 ("Neo4j 미연결" 등 사유 + 복구 명령) | line 298~302 | 색상 박스 + 사유 텍스트 | **P0** |
| F-MAIN-S04 | **dense_weight 슬라이더** (Hybrid 전용, 0.0~1.0, 0.1 step) | line 305~314 | `<input type="range">` + 현재값/BM25 weight 표시 | **P0** |
| F-MAIN-S05 | Agentic/KG 모드 안내 caption | line 315~321 | 모드별 텍스트 | P1 |
| F-MAIN-S06 | 데이터 정보 (1,251p / 5,657 청크) | line 326~342 | 정적 텍스트 카드 | P2 |
| F-MAIN-S07 | 기술 스택 (Hybrid/Agentic/KG/임베딩/LLM/한국어 토크나이저) | line 326~342 | 정적 리스트 | P2 |
| F-MAIN-S08 | 모드 비교 팁 (Hybrid 빠름 / Agentic 거절 / KG 그래프) | line 326~342 | 정적 리스트 | P2 |
| F-MAIN-S09 | **누적 사용 통계 expander** (모드별 호출/토큰/₩비용 + 합계) | line 350~370 | `<details>` + `/stats` API 호출 + 모드별 행 | **P1** |
| F-MAIN-S10 | 통계 리셋 버튼 | line 368~370 | 미구현 (`/stats` reset 엔드포인트 없음 — 서버 재시작 필요. 일단 P3) | P3 |
| F-MAIN-S11 | **대화 초기화 버튼** | line 374~377 | `setMessages([])` + 확인 prompt | **P0** |

### 메인 화면

| ID | 기능 | Streamlit 위치 | Next.js 구현 | Tier |
|---|---|---|---|---|
| F-MAIN-M01 | "칼빈 신학 챗봇" 제목 | line 384 | `<h1>` 이미 있음 | **P0 ✓** |
| F-MAIN-M02 | 모드별 caption (3종) | line 385~389 | 모드 변경 시 동적 caption | **P0** |
| F-MAIN-M03 | **멀티턴 채팅 히스토리** | line 393~422 | React state messages 배열 + chat_history API 전달 | **P0** (chat_history 전달은 Hybrid에서) |
| F-MAIN-M04 | **챗 인풋** (placeholder 포함) | line 424 | `<form>` + 이미 있음 | **P0 ✓** |
| F-MAIN-M05 | **입력 가드 차단 메시지** (red 박스) | line 426~433 | API 400/422 응답 시 에러 표시 | **P0** |
| F-MAIN-M06 | **사용자 메시지** (오른쪽 정렬, 파랑 배경) | line 397, 436 | 이미 있음 | **P0 ✓** |
| F-MAIN-M07 | **응답 시간 caption** (`X.XX초`) | line 83, 117, 225 | 메시지 메타에 표시 | **P0** |
| F-MAIN-M08 | **출처 expander** (페이지 + 본문 미리보기) | line 88~95 | 이미 `SourceCard.tsx` 구현 | **P0 ✓** |
| F-MAIN-M09 | RRF top scores expander (Hybrid debug) | line 419~421, 559~561 | `<details>` + JSON 렌더 | P2 |

### 모드별 응답 처리

#### Hybrid (P0)
| ID | 기능 | Streamlit 위치 | Next.js 구현 |
|---|---|---|---|
| F-HY-01 | 검색 spinner ("검색 중 (dense_weight=X.X)") | line 539 | "검색 중…" + dense_weight 표시 |
| F-HY-02 | **토큰 단위 스트리밍** (write_stream) | line 543 | 이미 `chatStream()` 구현 ✓ |
| F-HY-03 | 가드 caption (마스킹 시) | line 549 | sanitize 시 `<small>` 표시 |
| F-HY-04 | 출처 페이지 + 청크 본문 expander | line 557 | F-MAIN-M08 |
| F-HY-05 | RRF top scores expander | line 559~561 | F-MAIN-M09 |

#### Agentic (P1) — 가장 임팩트 큰 부분
| ID | 기능 | Streamlit 위치 | Next.js 구현 |
|---|---|---|---|
| F-AG-01 | **st.status "Agent 작동 중…" 박스** | line 478~492 | `<details open>` + 라벨 변경 ("작동 중" → "완료") |
| F-AG-02 | **thinking 이벤트** ("검색 도구 호출: search_documents" + args) | line 481~485 | 박스 안에 라인 추가 |
| F-AG-03 | tool_result 이벤트 ("N개 청크 검색 완료") | line 486~487 | 박스 안에 라인 추가 |
| F-AG-04 | answer 이벤트 ("답변 생성 완료") | line 488~490 | 박스 안에 라인 추가 |
| F-AG-05 | status 박스 종료 (state="complete", expanded=False) | line 492 | `<details>` open 해제 + "완료" 라벨 |
| F-AG-06 | **메타 caption** (응답시간/도구호출/LLM호출/cache hit) | line 117, 502~516 | 메시지 메타로 표시 |
| F-AG-07 | **도구 호출 내역 expander** (각 tool name + args code 블록) | line 120~124 | `<details>` + `<pre>` |
| F-AG-08 | **검색된 본문 expander** (각 검색 결과 미리보기) | line 126~132 | `<details>` + 카드 |

→ 현재 Next.js 는 Agentic 모드를 sync 호출하고 있음. **stream_steps 이벤트를 SSE로 받는 별도 엔드포인트**를 추가하든가, 또는 sync 응답의 metadata.tool_calls 를 그대로 표시.
**결정**: 시연 시간 절약 위해 sync 메타 표시만 (P1). stream_steps SSE는 P3.

#### Knowledge Graph (P1)
| ID | 기능 | Streamlit 위치 | Next.js 구현 |
|---|---|---|---|
| F-KG-01 | "그래프 + 벡터 검색 중…" spinner | line 450 | "그래프 + 벡터 검색 중…" |
| F-KG-02 | 답변 + 가드 caption | line 460~462 | 메시지 본문 |
| F-KG-03 | **메타 caption** (응답시간/엔티티수/intent/노드·엣지/청크) | line 218~225 | 메시지 메타 |
| F-KG-04 | **관계 그래프 시각화** (streamlit-agraph, height 450) | line 232~258 | `react-flow` 또는 `@xyflow/react` 또는 `cytoscape.js` |
| F-KG-05 | 그래프 텍스트 fallback expander | line 259~262 | F-KG-04 미설치 시 텍스트 |
| F-KG-06 | 본문 출처 expander | line 264~270 | F-MAIN-M08 |

→ **F-KG-04** 는 외부 라이브러리 추가 필요. `react-flow` 추천 (light, App Router 호환).

---

## 비교 페이지 (`/compare`) — 기능 명세

| ID | 기능 | Streamlit 위치 | Next.js 구현 | Tier |
|---|---|---|---|---|
| F-CMP-01 | "3 모드 동시 비교" 제목 + caption | line 121~123 | `<h1>` + 부제 | **P1** |
| F-CMP-02 | KG 미가용 경고 배너 | line 132~133 | 색상 박스 | **P1** |
| F-CMP-03 | 사이드바 metric (누적 호출/비용) | line 135~143 | 사이드바 카드 | P2 |
| F-CMP-04 | **챗 인풋** (질문 1개 → 3 모드 동시) | line 145 | 메인과 동일 | **P1** |
| F-CMP-05 | 예시 질문 안내 | line 147~152 | 정적 텍스트 | P2 |
| F-CMP-06 | 입력 가드 차단 | line 156~159 | F-MAIN-M05 | **P1** |
| F-CMP-07 | 질문 표시 | line 161 | `<blockquote>` | **P1** |
| F-CMP-08 | "3 모드 동시 호출 중 (병렬)" spinner | line 176 | 로딩 표시 | **P1** |
| F-CMP-09 | **3 column 레이아웃** | line 186 | `grid grid-cols-3` (Tailwind) | **P1** |
| F-CMP-10 | column별 모드 이름/응답시간 | line 188~193 | `<h2>` + caption | **P1** |
| F-CMP-11 | column별 답변 + 가드 caption | line 195~205 | 메시지 본문 + 작은 텍스트 | **P1** |
| F-CMP-12 | column별 메타데이터 expander (JSON) | line 207~214 | `<details>` + `<pre>` | **P1** |
| F-CMP-13 | column별 출처 expander | line 216~219 | F-MAIN-M08 | **P1** |
| F-CMP-14 | KG column 그래프 시각화 | (메인과 동일) | F-KG-04 | **P2** (시연 시간 따라) |

→ 비교 페이지는 백엔드에 **`POST /chat/compare` 엔드포인트** 또는 클라이언트가 3 모드를 *동시* 호출. 클라이언트 동시 호출이 단순 (Promise.all + sync 호출).
**결정**: 클라이언트가 3 모드 sync 동시 호출. 백엔드 변경 0.

---

## 공통 컴포넌트 (재사용)

| ID | 컴포넌트 | 사용처 |
|---|---|---|
| C-01 | `ModeSelector` | 메인 사이드바 ✓ (이미 있음) |
| C-02 | `SourceCard` | 메인 + 비교 양쪽 ✓ (이미 있음) |
| C-03 | `MetadataExpander` (key-value JSON 렌더) | 메인 Agentic/KG + 비교 |
| C-04 | `MessageCard` (user/assistant 통일 스타일) | 메인 + 비교 |
| C-05 | `LoadingSpinner` | 메인 + 비교 |
| C-06 | `ErrorBanner` (red 박스) | 입력 가드 차단 |
| C-07 | `WarningBanner` (amber 박스) | KG 미가용 |
| C-08 | `InfoBanner` (blue 박스) | 안내 메시지 |
| C-09 | `RangeSlider` (라벨 + 현재값) | dense_weight |
| C-10 | `StatsPanel` (모드별 행 + 합계) | 메인 사이드바 + 비교 사이드바 |
| C-11 | `AgentStatusBox` (단계 진행) | 메인 Agentic |
| C-12 | `KnowledgeGraphView` (`react-flow` 래퍼) | 메인 KG + 비교 KG |

---

## 외부 라이브러리 추가

| 라이브러리 | 용도 | Tier | 비고 |
|---|---|---|---|
| `react-markdown` + `remark-gfm` | F-MAIN-M03 답변에 **`,*,코드 등 렌더 (Streamlit st.markdown 호환) | P1 | 권장 |
| `@xyflow/react` (구 `react-flow`) | F-KG-04 그래프 시각화 | P1 | streamlit-agraph 대체 |
| `clsx` 또는 `tailwind-merge` | 조건부 className 정리 | P2 | 작은 유틸 |

---

## 백엔드 API 의존성 (현재 상태)

| 엔드포인트 | 메인 페이지 | 비교 페이지 | 상태 |
|---|---|---|---|
| `GET /health` | ❌ | ❌ | 운영 모니터링용 |
| `GET /modes` | F-MAIN-S02 (모드 가용성) | F-CMP-02 | ✓ 동작 |
| `GET /stats` | F-MAIN-S09 | F-CMP-03 | ✓ 동작 |
| `POST /chat/v2` | Agentic/KG 모드 | F-CMP-09 (3 모드 동시) | ✓ 동작 |
| `POST /chat/v2/stream` (SSE) | Hybrid 모드 | — | ✓ 동작 |
| `POST /chat/agentic-stream` (Step별 이벤트) | F-AG-01~05 정밀 구현 시 | — | **신규 — P3** |

→ 시연 시점엔 기존 5개 엔드포인트로 충분. Agentic 단계 표시(F-AG-01~05)는 sync 메타로 갈음.

---

## 구현 우선순위 (Tier 분류)

### P0 — 시연 필수 (~0.5일)
- F-MAIN-S03 (KG 미가용 배너)
- F-MAIN-S04 (dense_weight 슬라이더)
- F-MAIN-S11 (대화 초기화)
- F-MAIN-M02 (모드별 caption 동적)
- F-MAIN-M05 (입력 가드 차단)
- F-MAIN-M07 (응답 시간 caption)

### P1 — 시연 임팩트 (~1일)
- F-MAIN-S05 (모드 안내 caption)
- F-MAIN-S09 (누적 사용 통계 expander)
- F-AG-01~08 (Agentic 메타 표시 — sync 응답 그대로 활용)
- F-KG-01~06 (KG 메타 + 그래프 시각화 — `@xyflow/react` 추가)
- F-CMP-01~13 (비교 페이지 신규)
- C-12 (`KnowledgeGraphView` 컴포넌트)
- `react-markdown` 도입 (답변 마크다운 렌더)

### P2 — 사이드바 보강 (~0.3일)
- F-MAIN-S06~08 (데이터 정보 / 기술 스택 / 모드 비교 팁)
- F-MAIN-M09, F-HY-05 (RRF debug expander)
- F-CMP-03, F-CMP-05 (비교 사이드바 + 예시 안내)
- F-CMP-14 (KG column 그래프)

### P3 — 보너스 / 운영 단계
- F-MAIN-S10 (통계 리셋 — 백엔드 엔드포인트 추가 필요)
- `POST /chat/agentic-stream` SSE — Agentic 단계별 정밀 이벤트
- 다크 모드, 모바일 반응형
- i18n (영문 옵션)

---

## 작업 단계 (구현 시점)

| Step | 작업 | 시간 |
|---|---|---|
| **W1** | P0 일괄 — 슬라이더/대화초기화/caption/입력가드/응답시간 | 0.5d |
| **W2** | P1 — 누적통계 + Agentic 메타 + KG 그래프 (react-flow) + react-markdown | 1d |
| **W3** | P1 — 비교 페이지 (`/compare`) | 0.5d |
| **W4** | P2 — 사이드바 보강 + RRF debug | 0.3d |

총 ~2.3일.

## 수용 기준 (Acceptance Criteria)

각 기능 구현 후 다음을 만족해야 시연 가능:
- Streamlit 메인/비교에서 사용자가 보는 *정보*가 Next.js에서도 보임 (1:1 매핑)
- API 호출 횟수 동일 (메인 1회, 비교 3회 / 질문)
- 가드/관측성 동작 동일 (차단/마스킹/통계)
- 시연용 8개 큐레이션 질문 (`docs/demo-questions.md`) 모두 정상 응답

## 참고
- Streamlit 메인: `app/calvin_chatbot.py`
- Streamlit 비교: `app/pages/01_compare_modes.py`
- 의사결정: `docs/me/010-nextjs-fastapi-migration.md`
- 시연 데이터셋: `docs/demo-questions.md`
