---
status: draft
group: A
created: 2026-05-06
---

# PRD-006: 대화 우선 오케스트레이터 (멀티턴/메타-참조의 일관성)

## 1. 배경 / 문제

현재 챗봇은 4가지 모드(`hybrid`/`agentic`/`kg`/`vision`)를 라우터로 골라 호출한다. 그런데 *대화 자체*는 모드 위 레이어가 아니라 모드 안에 종속되어 있다 — `api/routes/chat.py:180-189` 의 `_invoke_sync` 가 **Hybrid 만 chat_history 를 전달**하고, Agentic/KG/Vision 의 `query()` 에는 history 인자 자체가 없다 (`agentic.py:290`, `kg/pipeline.py:158`, `vision_rag.py:60`).

라우터 (`router.py:61` `route_question(question)`) 는 *현재 질문 한 줄만* 본다. 직전 턴의 모드·답변·서브그래프·인용은 라우팅 결정에 들어가지 않는다.

결과로 다음 시나리오가 깨진다:

- 사용자가 "예정론을 설명해줘" → Hybrid → 답변 A
- "그럼 칼빈, 베자, 멜란히톤 사이의 관계는?" → KG (관계 키워드) → 답변 B (KG 는 history 안 받음)
- "위 내용을 전부 요약해줘" → 라우터는 "요약" 키워드 미매칭 → Hybrid 디폴트 → 검색기가 "요약" 단어로 PDF 청크 검색 → 사용자가 의도한 *직전 두 답변의 요약* 과 **무관한 답변**

본 PRD 는 *대화*를 모드보다 위 레이어로 끌어올려, 어떤 모드(검색 기법)을 선택했든 **멀티턴/메타-참조가 일관되게 동작**하도록 한다. 검색 기법은 도구이지 챗봇의 정체성이 아니다.

본 PRD 는 PRD-001(도구 확장)·PRD-002(인증·동기화)·PRD-004(운영 안전)·PRD-005(데이터 거버넌스) 의 *기반 레이어*다. 도구·세션·감사 로그가 모두 "Turn"이라는 단일 단위에 정렬되어야 후속 PRD 들이 깔끔하게 합류한다 — 그래서 본 PRD 를 가장 먼저 다룬다.

## 2. 목표

- 어떤 모드로 라우팅되어도 사용자가 chat_history 를 가정한 후속 질문을 일관되게 던질 수 있다.
- "위 내용 요약/정리", "방금 그래프 다시", "그 인용 페이지가 어디였지?" 같은 메타-참조가 RAG 우회 또는 직전 턴 메타 재사용으로 자연스럽게 답변된다.
- 새 검색 기법·도구·MCP 서버·도메인(책) 추가가 *기존 코드 한 줄도 손대지 않고* 가능하다 (registry 등록 한 줄).
- 코드 리뷰어가 "이 챗봇은 어떻게 동작하는가?" 를 *그래프 한 장* 으로 답할 수 있다.

## 3. 비-목표

- RAGAS 4지표 평가 인프라 (`experiments/eval/`) 의 변경. 본 PRD 는 평가 도구를 깨뜨리지 않는 선에서만 retrieval envelope 을 통일.
- 학습 트랙 repo (`rag-study-tracks/`) 의 패턴 코드. 본 PRD 는 챗봇 repo 안에서만 진행.
- 새 검색 알고리즘·새 모드 도입. 본 PRD 는 *기존 4개 모드를 그대로 유지* 하되 추상 위로 환원만 한다.
- 음성·비디오 입력. 별도 PRD.
- 영속화 백엔드 교체 (Postgres/Redis). 본 PRD 는 LangGraph in-memory checkpointer 까지만 — 영속화 백엔드는 PRD-002 합류 후.

## 4. 사용자 시나리오 / BDD

- Given 사용자가 "예정론을 설명해줘" 라고 묻고 Hybrid 가 답변했고,
  When 사용자가 "그럼 칼빈, 베자, 멜란히톤 사이의 관계는?" 이라고 묻고
  Then 라우터가 KG 로 라우팅하더라도, 답변 직후 사용자가 "위 두 내용을 표로 요약해줘" 라고 후속하면 RAG 검색 없이 chat_history 만으로 요약이 생성된다.

- Given KG 모드 답변에 서브그래프가 표시된 직후,
  When 사용자가 "방금 그 그래프를 다시 보여줘" 라고 후속하면
  Then 직전 턴의 `subgraph` 가 재사용되어 동일 그래프가 즉시 표시된다 (Neo4j 재질의 없음).

- Given 사용자가 "이 도판은 몇 년대 판본 같아?" 라고 이미지를 첨부해 묻고 Vision 답변을 받은 직후,
  When 사용자가 "그 답변의 근거를 한 줄로 요약해줘" 라고 묻고
  Then 라우터는 첨부 없음 + 메타-참조 의도를 인식해 RAG 우회, history 만으로 답변한다.

- Given 사용자가 후속 질문을 "그 사람은 그것을 언제 발표했어?" 처럼 대명사·생략으로 던지고
  When 시스템이 standalone question 으로 재구성하면
  Then 재구성된 질문이 trace event 와 답변 메타에 노출되어 사용자가 "어떻게 이해됐는지" 검증 가능하다.

- Given 새 도메인 책 (예: 어거스틴 고백록) 을 corpus 로 추가하고
  When `chatbot/infrastructure/corpora/augustine.py` 어댑터 1개 + corpus registry 등록 1줄을 커밋하면
  Then 다른 코드 변경 없이 기존 4개 모드가 모두 새 corpus 에서도 동작한다.

## 5. 결정해야 할 사항

### 결정 1 — 의도 분류 방식

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 휴리스틱 키워드 only ("요약/정리/위/그러면") | 0 | 빠름 | "요약 모드 비교" 같은 정상 질의 오인 | |
| LLM 분류 only (gpt-4o-mini) | 호출당 ~₩0.5 | 정확 | 첫 토큰 지연 +200ms | |
| 휴리스틱 → 모호 시 LLM fallback | 평균 ₩0.1 | 정확 + 빠름 | 두 경로 유지 비용 | ★ |

### 결정 2 — Query Rewriter 적용 범위

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| FOLLOWUP 의도일 때만 | 호출당 ~₩0.3 | 비용 절약 | 의도 오분류 시 후속 질문 깨짐 | ★ |
| 모든 턴에 항상 적용 | 호출당 ~₩0.3 × 모든 턴 | 일관성 | 비용 2배 + 첫턴엔 무용 | |
| 라우터 LLM 과 합쳐 1회 호출로 | ~₩0.4 | 호출 1회 | 책임 결합으로 노드 분해 의도와 충돌 | |

### 결정 3 — 메타-참조 시 RAG 우회 정책

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| META_RECAP/REFERENCE 는 RAG 완전 우회 | 0 | 의미적 정확 | 메타 의도 오분류 시 비-요약 답변 | ★ |
| 메타라도 보조 검색 1회 | 호출당 ~₩1 | 보강 가능 | 노이즈 청크 끼어듦 | |
| 항상 검색 후 답변 합성 시 history 가중 | 호출당 ~₩1 | 단일 흐름 | 메타 질문에 PDF 잡음 | |

### 결정 4 — Conversation 영속화 시점

| 옵션 | 비용 | 가치 | 위험 | 추천 |
|---|---|---|---|---|
| 본 PRD 는 in-memory only, 영속화는 PRD-002 합류 후 | 0 | 작업 분리 | 데모 시 재시작 후 대화 유실 | ★ |
| SQLite checkpointer 를 본 PRD 에 포함 | 작업 +0.5일 | 데모 안정 | 인증 미정 → 사용자 격리 어려움 | |
| Postgres 영속화 즉시 | 작업 +2일 | 운영 환경 즉시 가능 | 인프라/마이그레이션 PRD-005 영역 | |

## 6. 기능 요건

- 모든 모드(`hybrid`/`agentic`/`kg`/`vision`) 가 동일한 `RetrievalRequest` (standalone_question + chat_history + attachments) envelope 를 받는다.
- 라우터는 *standalone question* 기준으로 동작한다 — 후속 질문이 대명사/생략을 가지고 있으면 rewrite 결과로 라우팅한다.
- 의도 분류 결과 (`Intent`), 재구성된 질문 (`standalone_question`), 선택된 strategy 가 답변 metadata 에 노출되어 UI/감사가 검증 가능하다.
- 직전 턴의 `RetrievalResult` (subgraph/citations/attachments) 가 `Conversation` State 에 보존되어, META_REFERENCE 의도일 때 재사용된다.
- 새 corpus 추가는 `KnowledgeSource` 1개 + `Corpus` registry 등록 1줄로 끝난다 — 모드 코드 변경 0.
- 새 검색기 추가는 `Retriever` Protocol 구현 1개 + registry 등록 1줄. 기존 strategy 들은 자동으로 그것을 활용 가능.
- 새 도구·MCP 서버 추가는 `Tool` Protocol 어댑터 1개 + ToolRegistry 등록 1줄. PRD-001 의 ToolRegistry 와 정합.
- 회귀 호환: 기존 `/chat/sync`·`/chat/stream` 엔드포인트는 그대로 동작한다 (TRD-006 의 PR 4 에서 신규 `/chat/v2` 경로로 분리, 기존 경로는 PR 6 에서 제거).

## 7. 성공 지표 (정량)

- 멀티턴 시나리오 (3턴 이상, 모드 가로지름) 5건 시범 시, 5건 모두에서 마지막 메타-참조 턴이 history 일관성을 유지하며 답변 (수동 평가).
- 라우터 정확도: 후속 질문 50건 라벨링 데이터셋에서 rewrite 적용 후 정확도 ≥ 85% (rewrite 미적용 baseline 대비 +20%p).
- 새 corpus 추가 PR 의 변경 파일 수 ≤ 3 개 (corpus 어댑터 + registry + corpus 전용 테스트).
- 코드 리뷰 시간: TRD-006 기준 마스터 PR(오케스트레이터) 의 변경 라인 ≤ 600줄, 모드별 분해 PR 의 변경 라인 ≤ 800줄 (리뷰어 1인이 30분 안에 검토 가능).
- 회귀: 기존 `/chat/sync`·`/chat/stream` 의 응답 envelope 키 셋이 PR 6 직전까지 변하지 않음 (스냅샷 테스트).

## 8. 의존 / 영향 / 회귀 위험

- **의존**: 없음. PRD-001~005 와 독립적으로 진행 가능. 단, PRD-002(영속화) 와 PRD-004(circuit breaker) 의 단위가 본 PRD 의 `Turn` 으로 정렬되도록 합류 시점 조율 필요.
- **영향**: `/chat/v2` 라우트 추가 후 프론트가 절체되면, PRD-001 의 `tool_calls` 메타 + PRD-003 의 인용 UI 가 모두 *Turn 단위 envelope* 로 흡수된다 — 후속 PRD 의 작업이 가벼워진다.
- **회귀 위험 (중)**: 라우터 결정에 `standalone_question` 이 들어가므로 *기존 한 줄 라우팅* 의 결정 분포가 바뀐다. PR 4 시점에 기존 라우터 결정과 신 라우터 결정을 24시간 audit log 로 비교해 ±10%p 이상 차이는 회귀로 간주.
- **회귀 위험 (저)**: 의도 분류기 LLM 호출이 첫 토큰 지연을 +100~200ms 추가. 결정 1 에서 휴리스틱 우선으로 평균 +30ms 이내로 관리.
- **회귀 위험 (저)**: 모든 모드의 `query()` 시그니처를 통일하므로, 기존 `_invoke_sync` 분기가 사라진다. 분기 제거 PR 4 직후 1주 동안 두 라우트 응답을 비교하는 쉐도우 트래픽 권장.

비고: 영속화 백엔드(SQLite/Postgres), 사용자 인증, 도구별 RAGAS 평가, 그리고 모드 자체의 알고리즘 변경(예: Self-RAG 루프 개선)은 본 PRD 범위 밖이며 후속 PRD/TRD 에서 다룬다.
