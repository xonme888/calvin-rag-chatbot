# 011. Perplexity 스타일 UI/UX — 우리 자산 재사용 분석

## 상황
사용자: "FEATURES.md + 현재 시스템 위에 Perplexity 모방 기독교 챗봇 만들고 싶다."
별도 에이전트로 산업 사례 조사 + 우리 자산 매핑 + 단계별 일정 설계 결과.

## 결론 한 줄
**`RAGResponse.cited_pages` 가 이미 존재**. Perplexity의 가장 강한 차별화인 "인라인 [1][2] 인용"을 백엔드 변경 1줄(시스템 프롬프트에 "각 주장 끝에 [N] 표기")로 구현 가능. 시연 1일 추가 투입으로 Perplexity 동급 UX 도달.

## Perplexity 핵심 UX 정리표

| 요소 | 우리 적용 | 근거 |
|---|---|---|
| 답변 위 출처 carousel | **Y** | `source_documents`/`SourceCard` 이미 존재. 위치만 이동 |
| 인라인 [1][2] 인용 | **Y (1줄)** | `RAGResponse.cited_pages` 이미 LLM `with_structured_output`로 추출됨 |
| 검색 진행 단계 시각화 | **Y (Agentic만)** | LangGraph `stream_mode=["updates","custom","messages"]` 활용 |
| Follow-up 질문 자동 생성 | **Y** | LLM 1회 후처리 (~₩1) — 신학 도메인 chip 차별화 |
| Pro/Auto 모드 토글 | **Y (변형)** | 우리 Hybrid/Agentic/KG 3모드를 *입력창 옆*으로 격상 |
| 미니멀 single-column | **Y** | 사이드바 → "About" 모달 |
| Share/Copy/Regenerate | **부분 Y** | Copy/Regenerate 비용 0, Share는 DB 필요 (P-C) |
| 관련 이미지 카드 | **변형 N** | PDF 도메인 → "KG 그래프 미니맵"으로 대체 |

## 신학 도메인 변형 (5가지)

1. **출처 카드 라벨 = "p.124 (3권 21장 「예정」)"** — 권/장 + 페이지 (PyMuPDFLoader page는 0-indexed, 표시 +1)
2. **인라인 [1] 클릭 → PDF deep link** — 시연 단계 단순 hover popover, 운영 단계 `react-pdf` 인라인 viewer + page highlight
3. **KG 모드 그래프 미니맵 = Perplexity 의 "관련 이미지" 자리** — 답변 우상단 thumbnail + 클릭 시 모달 (`@xyflow/react`)
4. **Follow-up = 신학 도메인 chip** — "이 답변과 관련된 다른 단원은?", "루터의 입장과 비교?", "칼빈은 같은 주제를 다시 어디서 다루는가?"
5. **Pro/Auto 토글 → 모드 격상** — 입력창 위 세그먼티드 컨트롤 ("빠르게 / 자율 / 그래프")

## FEATURES.md 재배치 (Perplexity 기준)

| 항목 | 기존 | 신규 | 처리 | 사유 |
|---|---|---|---|---|
| 모드 라디오 | P0 | **P-A** | 변형 | 사이드바 → 입력창 위 세그먼티드 |
| dense_weight 슬라이더 | P0 | **P-C** | 강등 | Perplexity 미니멀 — "고급 설정"에 숨김 |
| 정적 사이드바 (데이터/스택/팁) | P2 | **P-C** | 강등 | "About" 모달 통합 |
| 응답 시간 caption | P0 | **P-A 변형** | 답변 *상단* meta 행으로 |
| 출처 expander | P0 | **P-A 변형** | expander → 답변 *위* 가로 carousel |
| Agentic 메타 | P1 | **P-B** | "Searching/Reading/Generating" 박스 |
| KG 그래프 | P1 | **P-B** | 답변 우측 thumbnail + 모달 |
| 비교 페이지 | P1 | **P-C 분리** | 별도 실험실 라우트 (메인 UX 변경 후 분리) |
| **신규** 인라인 [1] 인용 | — | **P-A** | 시스템 프롬프트 1줄 + 정규식 |
| **신규** Follow-up chip | — | **P-B** | LLM 1회 후처리 |
| **신규** Copy/Regenerate | — | **P-B** | 백엔드 변경 0 |
| **신규** Share URL | — | **P-C** | DB 필요 |

## 백엔드 변경 영향도

| 변경 | 비용 | 권장 |
|---|---|---|
| 인라인 [1][2] | **1줄** (시스템 프롬프트에 "각 주장 끝에 [N] 표기") + 클라이언트 정규식 `/\[(\d+)\]/g` | **P-A 즉시** |
| Follow-up | LLM 1회 (~₩1) — 응답 후처리 | P-B |
| Agentic 단계 SSE | LangGraph `stream_mode=["updates","custom","messages"]` 분리 | P-B |
| Regenerate | 0 — 클라이언트만 | P-B |
| Share URL | DB 스키마 + 엔드포인트 | P-C |

## 단계별 작업

### P-A — 시연 직전 (총 ~1일, 시연 임팩트 17/20)

| # | 작업 | 시간 | 임팩트 |
|---|---|---|---|
| P-A1 | 답변 위 출처 carousel ("p.124 (3권 21장)" 라벨) | 0.3d | 5/5 |
| P-A2 | **인라인 [1] 인용 (백엔드 1줄 + react-markdown custom renderer + hover popover)** | 0.4d | **5/5** |
| P-A3 | 미니멀 single-column (사이드바 → About 모달, 모드 토글 입력창 위 격상) | 0.2d | 4/5 |
| P-A4 | 답변 헤더 meta 행 (응답시간/모드/토큰) | 0.1d | 3/5 |

### P-B — 시연 직후 ~1주 (총 ~1.6일)

| # | 작업 | 시간 | 임팩트 |
|---|---|---|---|
| P-B1 | Agentic 단계 박스 (LangGraph stream_mode + framer-motion) | 0.5d | 5/5 |
| P-B2 | Follow-up chip (LLM 후처리) | 0.4d | 4/5 |
| P-B3 | KG 미니맵 (`@xyflow/react` thumbnail + 모달) | 0.5d | 4/5 |
| P-B4 | Copy/Regenerate 버튼 | 0.2d | 2/5 |

### P-C — 운영 공개 후

| # | 작업 | 시간 |
|---|---|---|
| P-C1 | Share URL + 대화 저장 (DB) | 1.0d |
| P-C2 | 명령 팔레트 (cmdk) | 0.4d |
| P-C3 | 다크모드 + 모바일 반응형 | 0.5d |
| P-C4 | PDF inline viewer (`react-pdf` + page highlight) | 1.0d |

## 라이브러리 추가

| 도구 | 용도 | 단계 |
|---|---|---|
| `react-markdown` + `remark-gfm` | 답변 렌더 + custom `text` renderer로 [N] 파싱 | **P-A** |
| `lucide-react` | Copy/Share/Regenerate 아이콘 | **P-A** |
| `framer-motion` (Motion) | 단계 박스 fade/slide | P-B |
| `@xyflow/react` | KG 그래프 (FEATURES.md 이미 후보) | P-B |
| `cmdk` | 명령 팔레트 (옵션) | P-C |

## 참고 오픈소스 (산업 사례)

| 프로젝트 | 적용 가치 |
|---|---|
| **Verba (Weaviate)** | PDF 도메인 가장 근접 — 청크/페이지 highlight 패턴 1:1 |
| **Morphic** (Vercel + AI SDK + shadcn) | 모드 토글 패턴, 답변 레이아웃 직접 참조 (Apache-2.0) |
| **Perplexica** | "Focus mode" 개념 — 우리 3모드 격상 영감 |
| **Liner (라이너)** | 한국 학술 인용 양식 → 신학 인용 ("Institutes 3.21.5") 변형 |
| **shadcn-chatbot-kit** | Message/Reasoning/Sources 블록 cherry-pick |
| **AI SDK `InlineCitation*` 컴포넌트** | hover popover + carousel 표준 anatomy |

## 시연 1순위 추천 (에이전트 결론)

> **"인라인 [1] 인용 + 답변 위 출처 carousel + Agentic 단계 박스"** 3종 세트가 면접 차별화 핵심.

근거:
- **P-A2 (인라인 인용)** — `RAGResponse.cited_pages` 이미 LLM에서 추출. 백엔드 1줄, 클라이언트 정규식 1개로 Perplexity 동급. ROI 최고
- **P-A1 (출처 carousel)** — "p.124 (3권 21장)" 라벨이 범용 RAG 데모와 즉시 구별
- **P-B1 (Agentic 단계 박스)** — Spring AI Advisor ↔ LangGraph 노드 emit 매핑, 자바 백그라운드 어필

## 면접 어필 한 줄

> "LangGraph 노드를 SSE `stream_mode=updates` 로 emit 하고 `with_structured_output(RAGResponse)` 로 LLM 이 인용 페이지를 구조화 반환합니다 — 정규식 후처리 0. 자바 Spring AI 사용처에선 Advisor 체인이 같은 역할을 하지만, 본 프로젝트는 Python LangChain/LangGraph로 *직접* 구현된 것이며 Spring AI 이식이 아닙니다."

## 회피 사항

- Vercel AI SDK `useChat` 즉시 마이그레이션 (현 `lib/api.ts` 충분, 교체 ROI 낮음)
- `dense_weight` 슬라이더 메인 노출 (Perplexity 기준 정보 과다)
- `/compare` 메인 UX 통합 (별도 실험실 페이지 유지)

## 핵심 출처
- [AI SDK Inline Citation anatomy](https://elements.ai-sdk.dev/components/inline-citation)
- [Perplexity Citation-Forward 설계 (Unusual)](https://www.unusual.ai/blog/perplexity-platform-guide-design-for-citation-forward-answers)
- [LangChain Perplexity Pro Search 케이스](https://www.langchain.com/breakoutagents/perplexity)
- [Verba (Weaviate)](https://weaviate.io/blog/verba-open-source-rag-app)
- [Morphic](https://github.com/miurla/morphic)
- [LangGraph Streaming docs](https://docs.langchain.com/oss/python/langgraph/streaming)
