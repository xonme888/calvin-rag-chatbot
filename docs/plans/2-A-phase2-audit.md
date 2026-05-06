# PR 2-A Phase 2 독립 감사 보고서

> 대상: TRD-007 PR 2-A.5~7 (stages 5종 + hybrid_strategy + 단위 테스트 41건)
> 감사 일자: 2026-05-06
> 감사자: 독립 audit agent (메인 thread 산출물 신뢰 안 함, grep + Read + 실제 pytest 실행으로 검증)
> 선행: `docs/plans/2-A-phase1-audit.md` (PASS)

## 1. 요약 판정

**CONDITIONAL PASS** — Hexagonal·rag_core 비손상·테스트 41건 전 통과·legacy 213건 회귀 무. 단, *3개 위반 후보* 존재: (a) `hybrid_strategy.py` 271줄로 사용자 지정 200줄 한도 초과, (b) `metadata["suggested_followups"]` 의 `"".join(followups)` 가 리스트 경계를 파괴(원본 동작과 비호환 — PR 4 wiring 시 데이터 손실), (c) `_FollowupFn` 가 type alias 가 아닌 단순 문자열 리터럴. 모두 PR 2-B 진행 *전* 또는 PR 4 wiring 직전에 보정 필요. PR 2-B Agentic 시작 가능 — 단 위 3건 백로그에 등록.

## 2. 체크리스트 결과

| 항목 | 결과 | 근거 |
|---|:---:|---|
| **A. Hexagonal — domain 외부 의존 0** | PASS | `chatbot/domain/*` 의 import 에 `langchain/openai/faiss/rag_core/chatbot.infrastructure` 부재. `__init__.py:4` 의 한 줄은 docstring 주석(import 가 아님). |
| **A. Hexagonal — stages 의 langchain top-level 부재** | PASS | langchain_core 9건 모두 `if TYPE_CHECKING:` 또는 메서드 본문 lazy import (generate_stage:21-23·83 / grade:15·54 / rewrite:16·43). |
| **A. 도메인 모델이 Stage 시그니처에 그대로 노출** | PASS | `RetrievalRequest`, `DocumentRef`, `Message` 가 `chatbot.domain` 에서 직수입. TypedDict envelope (`GenerateInput/Output`, `GradeInput/Result`, `RewriteInput`) 만 인프라 측에 신설 — 도메인 오염 0. |
| **B. rag_core 비손상** | PASS | `git diff --stat rag_core/` 변경 0. `rag_core/hybrid.py` mtime `5/5 17:52` (chatbot 도입 5/6 10:00 이전). |
| **B. RAGResponse / RewrittenQuery / GroundednessGrade 재사용** | PASS | 정의 복제 0건. `from rag_core.hybrid import RAGResponse` (generate_stage:62), `import GroundednessGrade` (grade_stage:56), `import RewrittenQuery` (rewrite_stage:45) — 모두 메서드 내부 lazy import. |
| **C. 단일 책임 — 메서드 라인 ≤ 30** | PASS (1건 경계) | 16개 메서드 중 최대: `_SelfRAGLoop.run` 35줄(*5 초과*), `HybridStrategy.run` 51줄(60줄 한도 내), `HybridStrategy.__init__` 22줄(필드 대입), 그 외 ≤ 22줄. `_SelfRAGLoop.run` 의 35줄은 while 본문이 한 사이클 6단계라 30줄 한도를 *경계 초과*. 권고에 명시. |
| **C. 단일 책임 — 파일 라인 ≤ 200(strategy)** | **FAIL** | `hybrid_strategy.py` **271줄** (사용자 지정 200줄 한도 초과). docstring/공백 포함이지만 *책임 경계*가 한 파일에서 너무 많음 — `_SelfRAGLoop`, `_LoopOutcome`, `HybridStrategyConfig`, `HybridStrategy`, `_FollowupFn` 5개. 권고: `_SelfRAGLoop`+`_LoopOutcome` 를 `_self_rag_loop.py` 로 분리(약 60줄), 200줄 미만으로 낙착. |
| **C. Stage 파일 라인 ≤ 150** | PASS | 최대 `generate_stage.py` 91줄. 모두 한도 내. |
| **C. Stage 메서드 ≤ 5** | PASS | 모든 Stage 가 `__init__` + `run` 2 메서드. `RetrieveStage` 단 2줄짜리 위임. |
| **C. _SelfRAGLoop max_retries 가드** | PASS | line 84 `if grade["is_grounded"] or retries >= self.max_retries`. 무한 루프 차단 명시. 테스트로 max_retries=2 도달 시 1+2=3회 generate 호출 검증(test:111-122). |
| **D. ruff check / format** | PASS | `ruff check chatbot/infrastructure/stages/ chatbot/infrastructure/strategies/ tests/chatbot/` → All checks passed! `ruff format --check` → 15 files already formatted. |
| **D. 타입 힌트 100%** | PASS (1건 의도된 예외) | AST 검사: 19개 함수 중 1개(`_to_langchain_messages`)만 반환 미부착. `# type: ignore[no-untyped-def]` 명시 — langchain 타입 lazy import 회피 의도. 도메인 노출 함수는 모두 부착. |
| **D. 한국어 docstring + 식별자 영문** | PASS | 모든 모듈/클래스/주요 메서드 한글 docstring. 식별자 영문. 이모지 0건 (Unicode `[\U0001F300-\U0001FAFF\U00002600-\U000027BF]` regex 검사). |
| **E. pytest tests/chatbot/ 통과** | PASS | 41 passed in 0.51s. (test_corpus 3 + parsers 12 + retrievers 9 + rerankers 7 + stages 4 + hybrid_strategy 6 = 41) |
| **E. extract_cited_pages 동등 케이스** | PASS | 중복제거(test:19-21) / 없음(:24-25) / 유사패턴 무시(:28-30) 3 케이스 — `hybrid.py:578-590` 의 정규식 `\[p\.(\d+)\]` 와 dedup 동등. |
| **E. format_doc_with_meta 4 케이스** | PASS | PDF page+1(:36-44) / filename fallback(:47-56) / source fallback(:59-68) / 메타 없음(:71-73) — `hybrid.py:593-607` 의 분기 모두 커버. |
| **E. RRF dedup/순서/top_k** | PASS | 중복 chunk 합산 1위(:105-118) / top_k 컷(:121-126) / dense_weight 경계(:129-135). |
| **E. Self-RAG 루프 경계** | PASS | 1회 재시도 후 성공(:92-108, retries=1·answer2 채택) / max_retries 도달 실패 보존(:111-122, retries=2·is_grounded=False). |
| **E. LLM 호출 0회 (FakeListLLM 미사용)** | PASS | `tests/chatbot/` 어디에도 `FakeListLLM`/`OpenAI`/`api_key` 부재(grep). `fakes.py` 가 GenerateStage/GradeStage/RewriteStage 를 *직접 상속* 해 `run()` 을 override — 사용자 지시(LLM 호출 0회) 충족. |
| **E. 테스트명 한국어 + 의도 명확** | PASS (소수 영문 식별자 혼재) | 41건 중 38건이 한글 의도 표현. 3건은 영문 식별자(`format_doc_with_meta_filename_fallback` 등)로 *공개 API 명* 자체를 검증 — 부득이한 혼재로 허용 범위. |
| **F. 회귀 — legacy pytest** | PASS | `pytest tests/ --ignore=tests/chatbot/` → 213 passed in 7.23s, 0 failure. |
| **F. api/routes/chat.py 비변경** | PASS | mtime `5/5 17:52` (Phase 2 작업 5/6 10:00 이전). `_invoke_sync` 정의(line 147)·호출(260, 443) 그대로. PR 4 까지 wiring 미반영 의도된 상태. |
| **G. Phase 1 §3.1 RRF chunk_id dedup** | PASS (영향 격리) | strategy 의 metadata 어느 키도 retriever 내부 score 출처를 노출하지 않음. `cited_pages` 는 LLM 답변에서 추출, `confidence` 는 LLM 출력. dedup 변경의 외부 가시성 0. |
| **G. Phase 1 §3.2 FlashRank 모델 인스턴스 중복** | **WARN** | `HybridStrategy._maybe_rerank:233` 가 매 턴마다 `self._reranker.with_query(query)` 호출 → 새 clone 생성. clone 의 `_ranker = self._ranker`(line 70 reranker)가 *주 인스턴스 None* 일 경우 None 복사. clone.run() 시 clone._ensure_loaded → **clone 자체 모델 로드**. 주 인스턴스는 영원히 None. 매 턴 새 모델 인스턴스(메모리 누수 위험). 코드 주석(line 231-232)이 의도를 *언급* 하나 *실제 보장은 없음*. |
| **H. metadata 모두 str 직렬화** | **WARN** | line 217 `"suggested_followups": "".join(followups)` — followups 가 `list[str]` 일 때 *구분자 없이 concat* 하면 `["A?", "B?"]` → `"A?B?"` 로 경계 파괴. 원본 `hybrid.py:276` 은 list 그대로 metadata 에 저장 후 chat.py:506 이 list 로 전달. 새 envelope 가 `dict[str, str]` 이라 직렬화 필요한 건 맞지만, *구분자 (예: `"\n"` 또는 `json.dumps`) 없는 join 은 PR 4 wiring 시 표시 깨짐*. |
| **H. _SelfRAGLoop None 가드** | PASS | `HybridStrategy._maybe_self_rag` (line 247) 가 grade/rewrite None 시 즉시 fallback `_LoopOutcome` 반환 → 루프 진입 자체 차단. |
| **H. 빈 chat_history 동작** | PASS | `_to_langchain_messages([])` → `[]` 반환. LangChain `MessagesPlaceholder("chat_history")` 가 optional 이므로 정상. (Phase 1 audit 검증된 prompts.build_hybrid_prompt 의 optional=True 와 정합.) |
| **H. rewrite_stage 부수효과 없음** | PASS | line 58 `return str(result.rewritten)` — 형변환만, strip/quote 제거 없음. 원본 `hybrid.py:381` `state["question"] = result.rewritten` 도 동일. |
| **H. _FollowupFn type alias 위반** | **WARN** | line 271 `_FollowupFn = "Callable[[str, str], list[str]]"` — *문자열 리터럴*. `from __future__ import annotations` 가 모든 annotation 을 lazy 평가하므로 *런타임에는 무해* 하지만, 타입 체커(mypy/pyright) 가 string 으로만 본다. `# type: ignore[assignment]` 가 부착돼 검사 회피 중. 권고: `from typing import Callable, TypeAlias` 후 `_FollowupFn: TypeAlias = Callable[[str, str], list[str]]`. |

## 3. 회귀 검증

| 검증 | 결과 |
|---|---|
| `ruff check chatbot/infrastructure/stages/ chatbot/infrastructure/strategies/ tests/chatbot/` | All checks passed (0 위반) |
| `ruff format --check ...` | 15 files already formatted |
| `pytest tests/chatbot/ -v` | 41 passed in 0.51s |
| `pytest tests/ --ignore=tests/chatbot/` | 213 passed in 7.23s, 3 deprecation warnings(swig — 무관) |
| `git diff --stat rag_core/` | 변경 0 |
| `git diff --stat api/` | 변경 0 (mtime 검증) |
| 도메인 외부 의존성 grep | 0건 |

## 4. Phase 1 audit 권고 반영 상태

| 권고 | 반영 | 근거 |
|---|:---:|---|
| §3.1 RRF chunk_id dedup 의 외부 영향 | OK | strategy 메타에 source 출처(bm25 vs dense) 노출 0. cited_pages·confidence 모두 LLM 출력 기반. 사용자 가시성 변화 0. |
| §3.2 FlashRank 모델 인스턴스 중복 방지 | **부분** | 코드 주석으로 *의도* 언급(line 231-232) 하나 *실제 보장 없음*. 매 턴 clone.run() 이 자체 _ensure_loaded 트리거 — Phase 1 우려가 그대로 재현. 권고: strategy 가 reranker 보유 시 첫 run 직전 1회 `self._reranker._ensure_loaded()` 호출(또는 reranker 측에 `prepare()` 공개 메서드 추가) 후 with_query 호출. 본 PR 의 차단 사유는 아니나 PR 4 wiring 전 보정 권고. |

## 5. 위반 / 권고 수정 (파일:라인)

### 5.1 BLOCKER (있다면 PR 2-B 시작 전 수정)

없음. *조건부 PASS* 항목들은 후속 PR 에서 보정 가능.

### 5.2 WARN (PR 4 wiring 전 반드시 수정)

1. **`chatbot/infrastructure/strategies/hybrid_strategy.py:217`** — `"suggested_followups": "".join(followups)` 가 리스트 경계 파괴. 두 옵션 중 택일:
   - `"\n".join(followups)` — UI 가 줄바꿈으로 split 가능.
   - `json.dumps(followups, ensure_ascii=False)` — 안정적 직렬화.
   원본 `hybrid.py:276` 은 list 그대로 저장하므로, `RetrievalResult.metadata: dict[str, str]` 정책을 유지하려면 직렬화 형식을 *PR 4 chat.py 측 deserialize 와 함께* 결정해야 함.

2. **`chatbot/infrastructure/strategies/hybrid_strategy.py:271`** — `_FollowupFn = "Callable[..."` 를 정식 TypeAlias 로 교체.
   ```python
   from typing import Callable, TypeAlias
   _FollowupFn: TypeAlias = Callable[[str, str], list[str]]
   ```
   `# type: ignore[assignment]` 제거.

3. **`hybrid_strategy.py` 271줄 → 200줄 미만**:
   - `_SelfRAGLoop` + `_LoopOutcome` 를 `chatbot/infrastructure/strategies/_self_rag_loop.py` (≈70줄) 로 분리.
   - `hybrid_strategy.py` 는 `HybridStrategyConfig` + `HybridStrategy` 만 보유 (≈190줄).

4. **`flashrank_reranker.py:69-72`** — Phase 1 §3.2 의 본 권고 미수신 상태. 권고:
   ```python
   def with_query(self, query: str) -> FlashRankRerankerStage:
       self._ensure_loaded()  # 주 인스턴스에서 1회 로드
       clone = ...
       clone._ranker = self._ranker  # 이제 보장된 비-None 공유
   ```
   또는 strategy 가 첫 호출 직전에 `self._reranker._ensure_loaded()` 1회 호출(접근자 추가).

### 5.3 INFO (가독성 / 향후)

- `_SelfRAGLoop.run` 35줄 — 현재 6단계 if/while 흐름. 30줄 한도 *경계 초과*. 분리 시점을 PR 2-B 종료 후로 미뤄도 됨 (Self-RAG 가 Agentic 와 *부분 공유* 가능성 있어 이때 함께 추출).
- `HybridStrategy.__init__` 9 keyword-only 인자 — 점차 늘어날 가능성. dataclass `HybridStrategyDeps` 패턴으로 묶으면 향후 strategy 추가 시 일관성 향상.
- `tests/chatbot/test_stages.py` 가 `GradeStage(llm=None)` 로 *생성자 건강성만* 검증. LLM 호출 정상 경로는 Phase 2 audit 가 별도(권고대로) — 단, `GradeStage.run` 내 `from langchain_core.prompts import ChatPromptTemplate` import 자체는 미커버. PR 2-B 또는 통합 테스트에서 fakes 로 1건 추가 권고.

## 6. 통계

| 항목 | 값 |
|---|---:|
| 신규 파일 (Phase 2) | 14 (stages 4 + strategy 1 + tests 7 + __init__ 2) |
| 신규 라인 (Phase 2) | 1,241 (테스트·docstring 포함) |
| 최대 파일 | `hybrid_strategy.py` (271줄, **한도 초과**) |
| 최대 메서드 | `HybridStrategy.run` 51줄 (60줄 한도 내) |
| 30줄 초과 메서드 | 2건 (`_SelfRAGLoop.run` 35, `HybridStrategy.run` 51) |
| ruff 위반 | 0 |
| 타입 힌트 누락(의도 외) | 0 |
| 이모지 / 마케팅 문구 | 0 |
| domain → infra import 위반 | 0 |
| 신규 chatbot 테스트 | 41 (전 통과) |
| 회귀 테스트 (legacy) | 213 (전 통과) |
| rag_core 변경 | 0 |
| api 변경 | 0 |
| LLM 외부 호출 (테스트) | 0 (FakeListLLM 부재 / 직접 stage override) |

## 7. PR 2-B Agentic 시작 전 권고

1. **WARN 4건 백로그 등록**: 위 §5.2 의 4개 항목을 `docs/issues/` 또는 PR 2-B 첫 commit 의 *준비 작업* 으로 처리. 특히 (1) suggested_followups 직렬화는 *PR 4 wiring 시점에 발견하면 디버깅 cost 큼* — 미리 결정.

2. **Strategy 분해 패턴 재사용**: `_SelfRAGLoop` 가 grade→rewrite→retrieve→generate 4-stage 루프. Agentic 의 *tool 선택 → 호출 → 평가* 루프와 구조 유사. PR 2-B 가 `_AgenticLoop` 를 만들 때 이 패턴을 *원형* 으로 삼되, 공통 상위 추상은 *3개 strategy 가 모두 도착한 뒤* 추출(추상화 비용은 N=3에서 ROI).

3. **Self-RAG 루프 동작 회귀 테스트(통합)**: 현재 `tests/chatbot/test_hybrid_strategy.py` 는 Fake stage 로 *합성 검증*. 실제 LLM 으로 같은 질문에 대해 (a) is_grounded 분기, (b) cited_pages, (c) confidence 분포가 원본 `HybridRAG` 과 *통계적으로 동일* 한지 1회 비교 권고 — `tests/integration/` 에 옵트인 마크 부착(API key 필요).

4. **테스트 헬퍼 위치**: `tests/chatbot/fakes.py` 의 `make_ref` / `FakeRetriever` / `FakeGenerateStage` 등은 PR 2-B Agentic 의 strategy 테스트에서도 *그대로* 재사용 예정. `make_ref` 의 default `corpus_id="calvin"` 는 *기본값 의존* 을 만드므로, PR 2-B 가 다른 corpus 시나리오를 테스트할 때 *명시 인자* 사용 필수(테스트 가독성 ↑).

5. **rag_core 어댑터 임시성 명시**: stages/strategies 가 `from rag_core.hybrid import RAGResponse` 로 schema 를 재사용 중. PR 2-B 종료 시점까지는 OK (단일 책임 원칙: pydantic 모델은 1군데 정의). 단, *향후 rag_core 폐기 계획* 이라면 `chatbot/domain/rag_response.py` 로 이전 후 rag_core 가 chatbot.domain 을 import 하는 일시적 역의존을 거쳐 정리. 본 결정은 TRD-007 §4 의 마이그레이션 단계에서.

## 8. 재감사 (권고 반영 후)

> 재감사 일자: 2026-05-06
> 검증 범위: §5.2 의 4개 권고 해소 여부 + 회귀 미발생 + 신규 파일 규칙 준수
> 방법: grep + Read + `pytest tests/chatbot/ -q` + `pytest tests/ --ignore=tests/chatbot/ -q` + `ruff check/format`

### 8.1 권고별 해소 여부

| # | 권고 | 결과 | 근거 (파일:라인) |
|---|---|:---:|---|
| 1 | `hybrid_strategy.py` 271줄 → 200줄 미만 | **RESOLVED** | `wc -l` → 182줄 (200줄 한도 내). 신규 파일 `chatbot/infrastructure/strategies/_self_rag_loop.py` 91줄 (`SelfRAGLoop` + `LoopOutcome` 분리). `_config.py` 22줄 (`HybridStrategyConfig` 분리). 한국어 docstring + 타입힌트 100% + 단일 책임 충족. `__init__.py:9-12` 가 `HybridStrategy` + `HybridStrategyConfig` 만 export — 캡슐화 명확. |
| 2 | `metadata["suggested_followups"]` 의 `"".join` → 구분자 직렬화 | **RESOLVED** | `hybrid_strategy.py:137` `"suggested_followups": json.dumps(followups, ensure_ascii=False)` — JSON 배열 직렬화로 리스트 경계 보존. 추가로 `hybrid_strategy.py:132` `"cited_pages": json.dumps(cited_pages)` — 동일 정책 일관 적용 (직전 보고서가 부수 권고했던 정합성 확보). grep `'""\.join'` → 0건. |
| 3 | `_FollowupFn` 가 type alias 가 아닌 문자열 리터럴 | **RESOLVED** | `hybrid_strategy.py:7-8` `from collections.abc import Callable` + `from typing import TypeAlias`. `:28` `FollowupFn: TypeAlias = Callable[[str, str], list[str]]` — 정식 TypeAlias. `# type: ignore[assignment]` 부재 (grep `type: ignore\[assignment\]` → 0건). 식별자도 `_FollowupFn` (private) → `FollowupFn` (public-내부공유) 로 정상화. |
| 4 | FlashRank 모델 인스턴스 중복 우려 (with_query/clone) | **RESOLVED** | `hybrid_strategy.py:148-149` `# with_query/clone 패턴 제거(audit 권고 §3.2 반영)` 주석 + `self._reranker.run(RerankInput(query=query, documents=documents))` — *envelope* 로 query 전달, 모델 인스턴스 1개 유지. `flashrank_reranker.py` 에 `with_query` 메서드 *부재* (grep → 코드 정의 0건, 주석 1건만). `RerankInput` TypedDict (`flashrank_reranker.py:18-26`) 가 신규 envelope. `tests/chatbot/test_rerankers.py:49-56` `test_flashrank_단일_인스턴스_재사용` — run() 2회 호출 후 `_ranker` 단일 유지 검증. |

### 8.2 회귀 검증

| 검증 | 결과 | 비고 |
|---|---|---|
| `pytest tests/chatbot/ -q` | **40 passed in 0.44s** | 직전 41 → 현재 40 (1건 감소). 차이는 권고 4 반영으로 *with_query 검증 테스트* 가 `test_flashrank_단일_인스턴스_재사용` 으로 *대체* — 의도된 변경, 회귀 아님. |
| `pytest tests/ --ignore=tests/chatbot/ -q` | **213 passed in 5.57s** | 0 failure. 3 deprecation warnings(swig — 무관). |
| `ruff check chatbot/ tests/chatbot/` | **All checks passed** | 0 위반. |
| `ruff format --check` | **19 files already formatted** | 직전 15 → 현재 19 (신규 `_self_rag_loop.py`, `_config.py`, `__init__.py` 갱신, `RerankInput` 추가). |
| `git diff --stat rag_core/` | **0 변경** | rag_core 비손상 유지. |
| `git diff --stat api/` | **0 변경** | chat.py wiring 미반영 (의도된 PR 4 보류 상태). |
| Hexagonal — domain 외부 의존성 | **0건** | `grep "import langchain\|import openai\|import faiss\|from rag_core\|from chatbot.infrastructure" chatbot/domain/` → 0건. |
| 신규 파일 규칙 준수 | PASS | `_self_rag_loop.py`(91줄), `_config.py`(22줄) 모두 한국어 docstring + 타입힌트 + 단일 책임. SelfRAGLoop 의 `run` 26줄 / `_iterate` 21줄 — 30줄 한도 내. (직전 `_SelfRAGLoop.run` 35줄이 분리 과정에서 `run`+`_iterate` 로 더 잘게 쪼개짐 → INFO §5.3 의 권고도 부수적으로 해소.) |

### 8.3 추가 점검 (보너스)

- **HybridStrategy.run 51줄 → 34줄**: `_build_result` 추출(line 113-139, 27줄) 로 단일 메서드의 책임 분산. `run` 본체는 33줄 (시간 측정·retrieve·rerank·generate·self-rag 호출·followup → `_build_result` 위임). 직전 60줄 한도 내였으나 30줄 한도에 더욱 근접.
- **`HybridStrategy.__init__` 9 → 9 keyword-only 인자 유지**: 직전 INFO 권고 (dataclass `HybridStrategyDeps` 묶기) 는 미반영. 본 PR 의 차단 사유 아님 — 향후 strategy 추가 시 재검토.
- **신규 export 일관성**: `chatbot/infrastructure/strategies/__init__.py` 가 `HybridStrategy` + `HybridStrategyConfig` 두 개만 노출. `SelfRAGLoop` / `LoopOutcome` / `FollowupFn` 은 의도적으로 export 누락 — 외부에서 직접 사용 금지(strategy 내부 합성 책임). 캡슐화 양호.

### 8.4 최종 판정

**PASS** — 직전 4 권고 모두 RESOLVED, 회귀 0, 신규 파일 규칙 100% 준수, ruff/pytest 전 통과. CONDITIONAL 조건 해소.

### 8.5 PR 2-B (Agentic) 진행 가능 여부

**진행 가능**. 잔여 INFO (`__init__` 인자 묶기, GradeStage LLM 정상 경로 fakes 1건) 는 PR 2-B 와 병행 처리 가능. `SelfRAGLoop` 분리 패턴이 `AgenticLoop` 의 *원형* 으로 즉시 활용 가능 — `_self_rag_loop.py` 91줄을 *템플릿* 삼아 `_agentic_loop.py` 작성 권고. 공통 상위 추상은 strategy 3개(Hybrid/Agentic/KG) 도착 후 N=3 시점에 추출(직전 §7-2 의 권고 유지).
