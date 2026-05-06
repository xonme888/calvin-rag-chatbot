# 012. 대화 우선 아키텍처 — 모드를 Strategy 추상으로 환원

> 2026-05-06

## 결정

챗봇의 1차 책무는 *대화*고, RAG 모드(`hybrid`/`agentic`/`kg`/`vision`)는 그 대화 안에서 근거를 끌어오는 도구다. 이 인식을 코드 구조에 박기 위해:

1. **`chatbot/` 패키지를 `rag_core/` 와 분리**해 신설한다 (이미 PR 1 머지).
2. 기존 4개 모드를 **`RetrievalStrategy` 추상의 어댑터**로 환원한다.
3. `Retriever`, `Tool`, `RetrievalStrategy` 셋을 분리해 *한 단어 "모드"* 가 떠안던 책임을 셋으로 쪼갠다.
4. 대화 오케스트레이터는 LangGraph 노드 5개 (`classify_intent` / `rewrite_question` / `select_strategy` / `invoke_strategy` / `compose_answer`) 로 표현한다.

## 왜

### 모드 안에 멀티턴이 들어가 있는 모순

`api/routes/chat.py:_invoke_sync` (180-189) 가 Hybrid 만 `chat_history` 를 전달했다. Agentic/KG/Vision 의 `query()` 시그니처에는 history 인자 자체가 없었다. 사용자가 "위 내용을 요약해줘" 라고 했을 때 라우터가 어디로 보내든 history 가 일관되게 보존되어야 하는데, *모드 선택의 부산물* 로 history 가 사라지는 구조였다.

이건 시그니처 차이의 문제가 아니라 *레이어가 잘못 쌓인* 문제다. RAG 모드를 챗봇 본체 자리에 둔 결과.

### 한 단어 "모드" 가 너무 많은 책임을 떠안았다

기존 hybrid.py 는 607줄 한 클래스 안에 LLM 초기화·검색 조립·재랭크·Self-RAG 루프·인용 라벨링·스트리밍·메타 집계가 묶여 있다. agentic.py 도 437줄 한 클래스에 도구 정의·도구 호출 루프·메시지 파싱·스트리밍이 묶여 있다. 사람도 AI 도 *어디를 만져야 할지* 가 보이지 않는다.

추상을 셋으로 쪼개면:
- `Retriever` — 검색 알고리즘 1개 (BM25, Dense, Hybrid, Graph)
- `Tool` — 외부 호출 1개 (검색·MCP·도메인 API)
- `RetrievalStrategy` — 위 둘을 *조립한 레시피* (= 구 "모드")

새 검색기는 Retriever 1개 추가, 새 도구는 Tool 1개 추가, 새 모드는 *기존 부품을 조립한 Strategy* 1개. 변경 반경이 항상 "포트 1구현 + registry 한 줄" 로 떨어진다.

### LangGraph 노드 시퀀스 = 그래프 한 장 = 명세

대화 오케스트레이터를 LangGraph 로 표현하면 빌드된 그래프가 곧 다이어그램이다. 시연/리뷰에서 "이 챗봇은 어떻게 동작하는가?" 의 답이 그림 한 장이 된다. 노드는 `state -> state` 의 순수 함수에 가깝게 — 다른 노드를 부르지 않으므로 변경 반경이 한 파일에 갇힌다.

## 트레이드오프

| 받아들인 것 | 잃는 것 |
|---|---|
| 추상 5층 (Conversation/Intent/Strategy/Retriever/Tool) | 첫 합류자가 익혀야 할 용어가 많아짐 |
| 같은 데이터(예: history)가 ConversationState 와 RetrievalRequest 에 중복 보유 | 단일 진실원천이 더 엄격하지 않음 |
| Strategy 가 여러 Stage/Retriever 를 조립하므로 단순 모드보다 호출 깊이가 깊어짐 | 디버깅 시 콜스택이 길어짐 |
| LangGraph 의존 추가 (이미 deps 에 있긴 함) | 비-LangGraph 사용자가 합류 시 학습 비용 |

용어 6개 (Conversation, Turn, Intent, RetrievalStrategy, Retriever, Tool) 만 익히면 전체가 읽힌다 — 이 학습 비용은 *변경할 때마다 코드 곳곳을 뒤지는 비용* 보다 작다고 판단했다.

## 대안과 기각 사유

### A. 기존 `_invoke_sync` 분기에 history 만 추가

비용은 가장 작다. 그러나 *근본 문제* (모드 위에 대화가 없다는 것) 를 가린다. 다음에 또 다른 시그니처 차이(예: 도구 결과 메타) 가 생기면 같은 분기가 늘어난다.

### B. 모드를 그대로 두되 라우팅 앞단에 메타-의도 분기만 추가

라우터 앞에 "요약/되짚기" 트리거를 잡아 RAG 우회. 1~2시간이면 끝난다. 그러나 *후속 질문 rewrite* 가 빠지면 "그 사람은?" 같은 대명사 후속이 여전히 깨지고, 새 모드 추가 비용도 그대로다.

### C. Vision 을 Tool 로 흡수하고 모드를 3개로 줄인다

Vision 의 retrieval 부재가 자연스러워진다. 그러나 첨부 라우팅 흐름이 사용자 인지에서 멀어지고 (Agentic 의 한 도구라는 멘탈 모델), UI 의 첨부 버튼이 어떤 모드와 연결되는지 모호해진다. 본 결정은 Vision 을 Strategy 로 유지하되 *Hybrid retriever 를 선택적으로 통합* 하는 절충 (TRD-010 결정).

## 회귀 방어선

- PR 1~5 동안 기존 `/chat/sync`·`/chat/stream` 라우트는 그대로 동작.
- PR 4 에서 신규 `/chat/v2` 추가. 두 라우트가 1주 공존하며 envelope 키 셋 스냅샷 비교.
- PR 6 에서 레거시 제거. 그 직전까지 라우팅 분포·답변 텍스트·인용 페이지의 ±5% 회귀를 audit log 비교로 검증.

## 메모

- `corpus_id` 가 모든 인용/메타에 박혀 있어야 새 도메인(어거스틴 고백록 등) 추가 시 책임이 격리된다. PR 1 의 `Citation`/`DocumentRef` 가 이 필드를 1급으로 들고 있다.
- LangGraph checkpointer 를 SQLite/Postgres 로 올리는 작업은 PRD-002 합류 시점에 — 본 결정 범위 밖.
- 4개 모드 분해 TRD 들 (007~010) 이 본 결정의 *구체* 다. 이 me 문서는 그 위의 *왜* 만 기록한다.
