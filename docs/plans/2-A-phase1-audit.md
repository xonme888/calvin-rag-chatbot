# PR 2-A Phase 1 독립 감사 보고서

> 대상: TRD-007 §2.1 신규 모듈 중 *기반 어댑터 4종* (corpora / retrievers / rerankers / prompts+parsers)
> 감사 일자: 2026-05-06
> 감사자: 독립 audit agent (메인 thread 산출물 신뢰 안 함, grep + Read + 동등성 실행 검증)

## 1. 요약 판정

**PASS** — Hexagonal 의존성, rag_core 비손상, 기존 동작 동등성, 단일 책임 모두 충족. RRF 의 chunk_id dedup 으로의 의도된 변경이 미세한 행동 차이(같은 키 충돌 시 우선권)를 만들지만, 정량 결과 정합성(동등 점수 산식·정렬)은 보존됨. Phase 2 (stages·strategy·tests) 진행 가능.

## 2. 체크리스트 결과

| 항목 | 결과 | 근거 |
|---|:---:|---|
| A. Hexagonal — domain 의 외부 의존 0 | PASS | `chatbot/domain/*` 의 import 는 `pydantic`, `typing`, `enum`, `datetime`, 자기 도메인 모듈만. langchain/faiss/openai/chatbot.infrastructure 부재 (grep 결과). |
| A. Hexagonal — infrastructure 의 cross-feature 의존 0 | PASS | 모든 import 가 `chatbot.domain.*`, 표준 라이브러리, `langchain_core/community`, `rag_core.*` 어댑터 자산만. |
| B. rag_core 비손상 | PASS | `git status` 깨끗(rag_core 변경 0). `rag_core/*.py` mtime 모두 5/5 17:52 이전(chatbot 도입은 5/6 10:00). 인터페이스 호출(BM25Retriever.search, page_to_section_label) 만 사용. |
| C. cache_key_parts 동등성 | PASS | `('calvin', 'chunk{N}', 'overlap{M}')` — `calvin_builder.py:69-73` 와 동일. 실제 import 후 `(800,100)` 호출 결과 일치. |
| C. format_doc_with_meta 동등성 | PASS | 4개 케이스 (page만/filename/source/none) 모두 `_format_doc_with_meta` 와 동일 출력. `+1` 페이지 변환·fallback 우선순위 일치. |
| C. extract_cited_pages 동등성 | PASS | 4개 케이스(중복·없음·연속·유사패턴) 모두 `extract_cited_pages_from_text` 와 정확히 동일 리스트 반환. 정규식·dedup·순서 보존. |
| C. build_hybrid_prompt 구조 | PASS | `[System(system_prompt), MessagesPlaceholder('chat_history', optional=True), Human('{question}')]` — `hybrid.py:193-199` 와 메시지 종류·순서·optional 플래그 일치. |
| C. RRF 수식 동등 (의도된 차이 명시) | CONDITIONAL | 분자/분모(가중치/(rrf_k+rank))·정렬 동일. **dedup 키가 `hash(content)` → `chunk_id` 로 변경**(의도). 부수 효과: bm25/dense 가 같은 키를 둘 다 보면 어댑터는 *bm25 ref 우선*(`setdefault`), 원본은 *dense 가 덮어씀*(`doc_map[key]=doc`). content/metadata 동일이라 보통 무해. 본 보고서에 명시. |
| D. 단일 책임 — 파일 라인 수 | PASS | 14 파일, 총 612줄. 최대 파일 `flashrank_reranker.py` 106줄. 모두 200줄 미만. |
| D. 단일 책임 — 클래스/메서드 통계 | PASS | 클래스당 최대 5 메서드(`FlashRankRerankerStage`), 메서드 최대 27줄(`run`). 한도(7/30) 모두 만족. |
| E. ruff check / format | PASS | `ruff check chatbot/infrastructure/` → All checks passed. `ruff format --check` → 14 files already formatted. |
| E. 타입 힌트 100% | PASS | AST 기반 검사로 모든 함수의 파라미터·반환에 annotation 부착(`__init__` 의 return 제외). |
| E. 한국어 docstring | PASS | 14 파일 모두 모듈/클래스 docstring 한국어. 식별자는 영문(전역 규칙 준수). 이모지·마케팅 문구 0건. |
| F. 생성자 주입 (테스트 용이성) | PASS | `BM25Retriever(chunks=...)`, `DenseRetriever(vector_store=...)`, `HybridRetriever(bm25, dense, ...)`, `FlashRankRerankerStage(model_name=..., top_k=...)` — 모든 외부 의존 명시 주입. 글로벌·싱글톤 캡처 0. `Retriever` Protocol 만 만족하면 FakeRetriever 로 대체 가능(실제 RRF 동등성 검증에 사용). |
| G. dense_weight 경계 (0.0/1.0 허용) | PASS | `0.0 <= x <= 1.0` (이상부등식). 0.0/1.0 모두 통과, -0.01/1.01 거부. setter 도 동일. 회귀 없음. |
| G. chunk_id 결정성 | PASS | 같은 `(source, page, content)` → 같은 SHA1[:10] 기반 ID. 4 케이스(동일/source 변경/page 변경/content 변경) 모두 기대값. `usedforsecurity=False` 명시(보안용 아님 — 결정성 ID). |
| G. FlashRank with_query 의도 | PASS | 새 인스턴스 반환(immutable 정신). `clone._ranker = self._ranker` 로 *모델 인스턴스 공유* — 비용 절감 의도가 주석에 명시. lazy load 시 주 인스턴스가 보유. |
| H. TRD-007 §2.1 매핑 일치 | PASS | corpora/retrievers(3)/rerankers/prompts/parsers 7개 파일 + 각 `__init__.py` — TRD 의 8개 신규 모듈 중 Phase 1 범위(7개) 완전 일치. |
| H. Phase 1 범위 — 없어야 할 것 부재 | PASS | `chatbot/infrastructure/stages/`, `chatbot/infrastructure/strategies/`, `chatbot/tests/` 디렉토리 부재. `tests/` 에도 chatbot 관련 파일 0건. |

## 3. 위반 / 권고 사항

### 3.1 의도된 행동 변경 — 보고서로 명시 (CONDITIONAL 항목)

`hybrid_retriever.py:80` 의 `ref_map.setdefault(ref.chunk_id, ref)` 는 *bm25 우선* 이다. 원본 `retriever.py:168` 의 `doc_map[key] = doc` 은 *dense 덮어쓰기*. 같은 chunk_id 면 content/metadata 가 동일하므로 (chunk_id 정의상) 답변 텍스트에는 영향 없으나, **score 필드의 source 출처(bm25 vs dense 의 RRF 기여 구분 외부 노출 시)** 가 달라질 수 있다. 권고: 차이를 docs/me/ 에 기록하고 Phase 2 의 회귀 테스트에 *의도된 변경* 으로 명시.

### 3.2 사소한 가독성 권고 (LOW — 차단 아님)

- `flashrank_reranker.py:70` `clone._ranker = self._ranker` 가 *언더스코어 속성 외부 접근*. 동일 클래스 내부라 Python 적법. 그러나 `with_query` 가 주 인스턴스의 lazy 상태를 미리 로드해두지 않고 새 clone 으로 복사하므로, 주 인스턴스가 한 번도 `run()` 되지 않은 상태에서 `with_query` 만 받은 clone 들은 각자 `_ensure_loaded` 를 호출 → **여러 모델 인스턴스가 생길 수 있음**. 권고: Phase 2 의 strategy 가 *주 인스턴스에서 1회 `_ensure_loaded` 호출 후 with_query* 패턴을 명시하거나, `with_query` 가 주 인스턴스의 ranker 가 None 일 때 호출자에게 경고.
- `hybrid_retriever.py:54` 에서 `fused[: request.top_k]` 컷이 RRF 결과를 잘라낸다. 두 retriever 가 각각 `top_k` 받아오므로 합쳐서 최대 2*top_k 후보, top_k 컷 — 원본 동작 동일. 그러나 reranker 가 뒤따르는 경우 *컷이 너무 빠를 수* 있다. Phase 2 strategy 조립 시 `retrieve.top_k = generate.top_k * fanout` 패턴 권장.

### 3.3 의도된 결정 — 보존

- `to_document_ref` 가 `corpus_id`/`source_id` 가 metadata 에 없으면 `default_*` fallback. 이 정책이 Phase 2 의 chunk 인덱싱 시점 메타 박기와 일치하는지 strategy 측에서 보강 필요(현재는 빈 문자열로도 통과 — 누락 시 sliently 빈 corpus_id 가 됨, citations 의 출처 표기가 깨질 수 있음).

## 4. 통계

| 항목 | 값 |
|---|---:|
| 신규 파일 수 | 14 |
| 신규 라인 수 | 612 (주석·docstring 포함) |
| 최대 파일 | `flashrank_reranker.py` (106줄) |
| 최소 파일 | `infrastructure/__init__.py` (7줄) |
| 클래스 수 | 4 (BM25Retriever / DenseRetriever / HybridRetriever / LongContextReorderStage / FlashRankRerankerStage = 5 클래스) |
| 메서드 수 | 15 (init 제외 public) |
| 클래스당 최대 메서드 | 5 (FlashRankRerankerStage) |
| 메서드 최대 줄 수 | 27 (`HybridRetriever._reciprocal_rank_fusion`) |
| ruff lint 위반 | 0 |
| 타입 힌트 누락 | 0 |
| 이모지/마케팅 문구 | 0 |
| 도메인 → 인프라 import 위반 | 0 |
| rag_core 변경 | 0 (mtime + git status 검증) |
| 누락된 Phase 1 모듈 | 0 |
| 잘못 들어간 Phase 2 모듈 | 0 (stages/strategies/tests 부재 확인) |

## 5. Phase 2 시작 전 권고

1. **회귀 테스트 가이드라인**: Phase 2 의 `hybrid_strategy` 합성 후 다음을 *동일 인덱스* 로 비교 — 같은 질문에 대한 (a) 검색 top-k 의 chunk_id 집합, (b) 답변 텍스트의 인용 페이지 집합, (c) 답변 글자 수 분포. RRF dedup 키 변경(content hash → chunk_id)이 (a) 에 미치는 영향을 *수치로* 기록.

2. **stages 추상**: TRD-007 §2.3 이 명시한 5개 stage 중 `generate_stage` 가 가장 무겁다(원본 56줄). 단일 메서드 30줄 한도를 지키려면 *컨텍스트 조립* 과 *LLM 호출* 을 분리할 가능성 큼. 본 Phase 1 의 `format_doc_with_meta` 가 컨텍스트 조립 헬퍼로 그대로 사용될 것.

3. **chunk_id 메타 박기**: corpus 빌더가 청크 메타에 `corpus_id="calvin"`, `source_id="institutes_v1"` 를 *반드시* 넣어야 `to_document_ref` 의 default fallback 에 의존하지 않는다. Phase 2 의 corpora/calvin_institutes 빌더 함수 추가 시 이 단계 명시.

4. **Self-RAG 루프 보존**: 본 Phase 1 은 grade/rewrite stage 미포함. Phase 2 에서 `LoopOrchestrator` 와 함께 추가될 때 max_retries 를 명시(원본 `_grade_router` 387-393 무한루프 가능성).

5. **테스트 커버리지 권장**: Phase 2 의 PR 2-A.7 단위 테스트는 본 보고서가 직접 검증한 5개 항목 — extract_cited_pages 동등성 / format_doc_with_meta 동등성 / cache_key_parts 동등성 / chunk_id 결정성 / dense_weight 경계 — 를 *그대로* 케이스로 옮기길 권장.
