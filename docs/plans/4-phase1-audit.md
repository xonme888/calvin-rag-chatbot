# PR 4 Phase 1 감사 보고서 — 인프라 구체 + 단위 테스트

> 대상: PR 4.1 ~ 4.4 (chatbot/infrastructure 4 파일 + tests/chatbot 4 파일).
> 방법: grep 카운팅 + Read + 실제 pytest/ruff 실행. 추측 배제, 모든 결함은 파일:줄 근거.
> 결과: **PASS** (Critical 0, Warning 0, Info 3).

## 판정 요약

| # | 영역 | 판정 | 핵심 발견 | 조치 |
|---|------|:----:|-----------|:----:|
| A | Hexagonal & 의존방향 | PASS | infra → `_protocols` 만 import. langchain/pydantic 모두 lazy. | - |
| B | rag_core/api 비손상 | PASS | `git diff --stat rag_core/ api/` 빈 출력. | - |
| C | 단일 책임 / 라인 한도 | PASS | 최대 파일 141줄, 최대 메서드 28줄. | - |
| D | PRD-006 §5 결정 1 (휴리스틱→LLM) | PASS | NEW_QUESTION 디폴트 시에만 LLM, env 게이트, 우선순위 검증됨. | - |
| E | PRD-006 §5 결정 2 (Rewriter) | PASS | except 블록 fallback, _format_history 6개 컷 docstring 명시. | - |
| F | 타입 / 스타일 (ruff) | PASS | ruff check + format 8/8 clean. Protocol 만족 4/4. | - |
| G | 테스트 품질 | PASS | 30/30 통과, 0.26s. LLM 호출 0 (FakeListChatModel + stub). | - |
| H | 회귀 안전성 | PASS | tests/chatbot 193 통과, 레거시 213 통과. | - |
| I | 잠재적 결함 | INFO | 동적 Pydantic 클래스 / META_REFERENCE 메타 평탄화 / vision 1순위. | PR 5 권고 |

콘솔 한 줄: **PASS — Critical 0, Warning 0, Info 3 (PR 4 Phase 2 진입 가능)**.

---

## A. Hexagonal & 의존방향 — PASS

```bash
grep -nE "^(from|import) chatbot\.application" chatbot/infrastructure/{intent_llm,rewriter_llm,router,answer_composer}.py
```

- `intent_llm.py:18`: `from chatbot.application._protocols import IntentClassifier`
- `rewriter_llm.py:13`: `from chatbot.application._protocols import QueryRewriter`
- `router.py:14`: `from chatbot.application._protocols import StrategyRouter`
- `answer_composer.py:16`: `from chatbot.application._protocols import AnswerComposer`

4개 파일 모두 application 의 *Protocol 만* 의존 — 다른 application 모듈 (orchestrator/registries/nodes) import 0건. Hexagonal 의존방향 준수.

**LangChain/Pydantic top-level import 검증**:
```bash
grep -nE "^(from|import) (langchain|pydantic)" chatbot/infrastructure/{intent_llm,rewriter_llm,router,answer_composer}.py
```
빈 결과. 모든 langchain/pydantic 은 *메서드 본문* 에서 lazy import (intent_llm.py:91-92, rewriter_llm.py:40-41, answer_composer.py:103). 모듈 로드 시 langchain 임포트 비용 회피 — startup 빠름, 테스트 격리 용이.

**키워드 사전 — 복제 vs 재사용**: `router.py:19-24` 의 `_KG_KEYWORDS`/`_AGENTIC_KEYWORDS` 는 `rag_core/router.py:27-51` 의 `_KG_HINTS`/`_AGENTIC_HINTS` 와 어휘 동일하나 *복제*. `rag_core/` 의존을 끊는 단순화 — 의도된 격리. router.py:18 주석에 명시.

## B. rag_core / api 비손상 — PASS

```bash
git diff --stat rag_core/ api/
```
빈 출력. 본 phase 변경은 `chatbot/infrastructure/` 와 `tests/chatbot/` 에만 한정.

## C. 단일 책임 / 라인 한도 — PASS

| 파일 | 줄 수 | ≤200 |
|------|------:|:----:|
| intent_llm.py | 120 | OK |
| rewriter_llm.py | 75 | OK |
| router.py | 67 | OK |
| answer_composer.py | 141 | OK |

**메서드 라인 수** (AST 기반 측정, 최대 30줄 한도):

| 위치 | 메서드 | 줄 수 |
|------|--------|------:|
| intent_llm.py:89 | `_classify_with_llm` | 28 |
| router.py:36 | `choose` | 25 |
| answer_composer.py:96 | `_invoke_llm` | 23 |
| rewriter_llm.py:38 | `rewrite` | 23 |
| answer_composer.py:50 | `compose` | 19 |

가장 긴 메서드도 28줄 (한도 30 이내). `compose` 는 4 분기 (retrieval / RECAP / REFERENCE / SMALLTALK) 를 if-chain 으로 처리하되 각 분기는 `_compose_meta_recap` / `_compose_meta_reference` / `_compose_smalltalk` 별도 메서드로 위임 — SRP 준수.

`HeuristicIntentClassifier` 와 `HeuristicWithLLMFallbackClassifier` 분리: 휴리스틱 only 분류기 (LLM 의존 0) 와 fallback 합성 분류기 (휴리스틱을 *내포* 하여 위임) 가 별도 클래스. 테스트·시연에서 LLM 없이 동작 가능.

## D. PRD-006 §5 결정 1 (휴리스틱→LLM fallback) — PASS

`HeuristicWithLLMFallbackClassifier.classify` (intent_llm.py:72-78):

```python
heuristic = self._heuristic.classify(message=message, last_turn=last_turn)
if not _llm_fallback_enabled() or heuristic != Intent.NEW_QUESTION:
    return heuristic
llm_decision = _classify_with_llm(self._llm, message)
return llm_decision or heuristic
```

검증 사항:
- **NEW_QUESTION 디폴트 시에만 LLM** — META_RECAP/META_REFERENCE/SMALLTALK/FOLLOWUP 은 휴리스틱 결과 *그대로* 반환 (test_intent_classifier.py:107-109 가 검증).
- **환경변수 게이트** — `CHATBOT_INTENT_LLM` 미설정/false 시 LLM 미호출 (test_intent_classifier.py:74-89 가 검증).
- **우선순위** — META_REFERENCE > META_RECAP > SMALLTALK > FOLLOWUP > NEW_QUESTION (intent_llm.py:46-56). test_intent_classifier.py:65-71 은 동일 메시지에 META_REFERENCE/META_RECAP 키워드가 동시 존재할 때 META_REFERENCE 가 1위임을 검증.
- **FOLLOWUP last_turn 분기** — last_turn=None 이면 FOLLOWUP 키워드가 있어도 NEW_QUESTION (intent_llm.py:54). test_intent_classifier.py:49-53 가 검증.

PRD 결정 1 의 절충안 (휴리스틱 성능 + LLM 정확도 보강) 정합.

## E. PRD-006 §5 결정 2 (Rewriter — FOLLOWUP 만) — PASS

- **rewriter 의 fallback 위치**: rewriter_llm.py:58-60 — `except Exception:` 블록에서 `return message.content` 으로 *원문 그대로*. LLM 실패 시 라우팅이 멈추지 않고 원문 standalone 으로 진행. test_query_rewriter.py:33-42 가 `_BadLLM` 으로 검증.
- **6개 컷 docstring**: rewriter_llm.py:64-67 — `_format_history` docstring 에 "최근 6개 메시지(3턴)만 — rewrite 컨텍스트 토큰 비용 절감" 명시. test_query_rewriter.py:23-30 가 잘림 동작 검증.
- **호출 시점은 노드 책임**: PR 3 Phase 1 audit 에서 `rewrite_question` 노드가 Intent.FOLLOWUP 분기에서만 호출함을 검증 — 본 PR 의 rewriter 자체는 *호출되면 항상 LLM* 시도. 책임 분리 적절.

## F. 타입 / 스타일 — PASS

```bash
ruff check chatbot/infrastructure/{intent_llm,rewriter_llm,router,answer_composer}.py tests/chatbot/test_{intent_classifier,query_rewriter,strategy_router,answer_composer}.py
# All checks passed!

ruff format --check ...
# 8 files already formatted
```

**Protocol 만족 검증 패턴**:
- `intent_llm.py:120`: `_: type[IntentClassifier] = HeuristicIntentClassifier`
- `rewriter_llm.py:75`: `_: type[QueryRewriter] = LLMQueryRewriter`
- `router.py:67`: `_: type[StrategyRouter] = KeywordStrategyRouter`
- `answer_composer.py:141`: `_: type[AnswerComposer] = HistoryAwareAnswerComposer`

4 클래스 모두 정적 검증 표시. runtime isinstance 도 True (수동 확인).

**한국어 docstring + 영문 식별자**: 4 파일 module docstring/메서드 docstring 모두 한국어. 클래스명 `HeuristicIntentClassifier` 등 영문. 이모지 0건.

## G. 테스트 품질 — PASS

```bash
pytest tests/chatbot/test_{intent_classifier,query_rewriter,strategy_router,answer_composer}.py -q
# 30 passed in 0.26s
```

| 파일 | 케이스 | 비고 |
|------|------:|------|
| test_intent_classifier.py | 8 | META 우선 / RECAP / SMALLTALK / FOLLOWUP 분기 / NEW default / 우선순위 / fallback 비활성 / NEW 시 fallback |
| test_query_rewriter.py | 4 | history 프리픽스 / 빈 / 6개 컷 / 예외 fallback |
| test_strategy_router.py | 7 | vision 1순위 / KG 4 키워드 / Agentic 4 키워드 / hybrid default / 빈 / hybrid 없음 / vision-kg 동시 |
| test_answer_composer.py | 11 | retrieval 그대로 / answer 없음 / RECAP LLM / RECAP 실패 / REFERENCE 빈 / REFERENCE 호출 / SMALLTALK / 헬퍼 4 |
| **합계** | **30** | 명세 일치 |

**LLM 호출 0**: FakeListChatModel (langchain_core fake) + 직접 stub (`_Counter`, `_LLM`, `_BadLLM`) 만 사용. OPENAI_API_KEY 미사용. test_intent_classifier.py:84-87 의 stub 패턴이 monkeypatch 와 결합하여 LLM 호출 카운터로 fallback 발동 조건 정량 검증.

## H. 회귀 안전성 — PASS

```bash
pytest tests/chatbot/ -q       # 193 passed in 0.75s
pytest tests/ --ignore=tests/chatbot -q  # 213 passed in 6.10s
```

본 phase 의 30개 테스트 추가로 chatbot 영역이 163 → 193. 레거시 213 그대로. PR 2-A/2-B/2-C/2-D + 3-phase1/2 audit 권고 영향 0 — infrastructure 추가만 있으므로 application/domain/registries 변경 없음.

## I. 잠재적 결함 (Info)

세 항목 모두 **동작 정확성에는 문제 없음**, PR 5 wiring 시 최적화/보강 권고.

### I-1. 동적 Pydantic 클래스 생성 비용 (Info, 낮음)

- `intent_llm.py:94-97`: `_classify_with_llm` 본문 안에서 `_Decision(BaseModel)` 정의. 매 호출마다 클래스 생성.
- `rewriter_llm.py:43-44`: `LLMQueryRewriter.rewrite` 본문 안에서 `_Rewritten(BaseModel)` 정의. 매 호출마다 클래스 생성.

이유: 모듈 top-level 로 옮기면 pydantic 이 module import 시 강제 로드 — *lazy import* 원칙 위반. 현 호출 빈도 (intent: NEW_QUESTION 디폴트 케이스 1회/턴 / rewriter: FOLLOWUP 만 1회/턴) 기준 무시 가능. 권고: PR 5 에서 `@functools.lru_cache(maxsize=1)` 헬퍼로 모델 클래스 1회 빌드 후 재사용.

### I-2. META_REFERENCE 메타 평탄화 누락 (Info, 중간)

- `answer_composer.py:80-82`:
  ```python
  last_metadata = (
      f"전략: {last_turn.selected_strategy or '(없음)'}, 의도: {last_turn.intent.value}"
  )
  ```

PRD-006 의 "방금 그 그래프/인용 페이지" 시나리오 정확도가 `selected_strategy + intent` 두 값에만 의존. `Turn` 도메인이 가지는 `subgraph_url`, `citation_pages` 등 (있다면) 이 평탄화되지 않음. PR 5 의 META_REFERENCE 정확도에 직접 영향. 권고: `Turn` 의 `metadata` 필드를 검토하고 last_metadata 에 합류시킬 키를 PR 5 에서 결정.

### I-3. KeywordStrategyRouter 의 vision 자동 1순위 (Info, 낮음)

- `router.py:48-49`: `if "vision" in by_name: return by_name["vision"]`

설계 의도는 "supports() 가 attachments 분기를 이미 했으므로 vision 후보가 들어오는 자체가 attachments 신호". 그러나 사용자가 standalone_question 을 "이미지 없는 질문" 으로 재구성한 경우에도 vision 강제 매칭 가능 — 위험성: 매우 낮음 (registry.available_for() 가 attachments 없는 요청에 vision 후보를 넣지 않음). 명시 OK. 권고: PR 5 의 `chat/v2` 라우트가 `attachments=()` 일 때 registry 가 vision 후보를 *반드시 제외* 하는지 통합 테스트로 보강.

## J. PR 4 Phase 2 진입 권고

다음 phase (4.5 ~ 4.7) 진입 전 결정 사항:

1. **bootstrap.py 의존성 자동 등록 목록**:
   - `corpus`, `retriever` (계층 1 인프라)
   - `strategy` 4종 (hybrid / agentic / kg / vision) — `is_available()` 분기로 누락 허용
   - `tool_registry` (search_tool, mcp_client)
   - `classifier` (heuristic 디폴트 / `CHATBOT_INTENT_LLM=true` 시 fallback 합성)
   - `rewriter` (`CHATBOT_REWRITER_LLM=true` 시 LLM, 아니면 identity stub?)
   - `router` (KeywordStrategyRouter 디폴트)
   - `answerer` (HistoryAwareAnswerComposer)
   → `application/_factories.py` 패턴 또는 `application/bootstrap.py` 단일 모듈 권고.

2. **/chat/v2 envelope 차이**:
   - 기존 `/chat/sync` 는 (mode, question) → (answer, citations).
   - `/chat/v2` 는 ConversationalState 의존 — 권고 envelope: `{conversation_id, turn_id, intent, selected_strategy, answer, citations, elapsed_ms}`.
   - 첫 1차 컷은 in-memory ConversationStore (대화 1개/세션) — 영속화는 후속 PR.

3. **환경변수 토글**:
   - `CHATBOT_INTENT_LLM` (이미 정의)
   - `CHATBOT_REWRITER_LLM` (Rewriter 비활성 시 identity?)
   - `CHATBOT_KG_ENABLED`, `CHATBOT_AGENTIC_ENABLED` (비활성 시 strategy 등록 스킵)
   → bootstrap.py 가 env 읽고 registry 구성. 노드 본체는 env 무관.

권고 우선순위: bootstrap.py (4.5) → /chat/v2 (4.6) → E2E 통합 테스트 (4.7) → Phase 2 audit.

---

**판정: PASS**. PR 4 Phase 1 (인프라 구체 + 단위 테스트) 완료. 회귀 0, 결함 0, Info 3 (PR 5 wiring 시 검토 권고).
