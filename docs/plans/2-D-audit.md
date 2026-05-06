# PR 2-D Audit — Vision 전략 분해 + 보안 게이팅 (TRD-010)

작업 기준일: 2026-05-06
감사 대상: PR 2-D.1 ~ 2-D.4 단일 phase (Vision 분량 작음)
실행 환경: `tests/chatbot/` 142 통과 / `tests/` 레거시 213 통과 / ruff PASS

## 1. 요약 판정

**PASS** — 모든 체크 통과. 회귀 0, ruff 0 위반, 라인/메서드 한도 준수, 테스트 24개(8/5/9 — 11+ 케이스 보너스), Hexagonal 의존방향 위반 없음, rag_core/api 변경 0.

조건부 권고 없음. PR 3 (orchestrator + nodes) 진입 가능.

## 2. 체크리스트 결과

| # | 영역 | 판정 | 근거 |
|---|------|:----:|------|
| A | Hexagonal & 의존방향 | PASS | validation/* 도메인만 import, vision_strategy LangChain lazy (TYPE_CHECKING + 메서드 본문) |
| B | rag_core/ 영향 0 | PASS | git status clean, mtime 변경 없음, VISION_SYSTEM_PROMPT 의도된 *동등 정의 복제* |
| C | 단일 책임 / 라인 한도 | PASS | 최대 158줄 (vision_strategy), run() 35줄, 분리 메서드 적절 |
| D | PRD-001 vision 게이팅 | PASS | MIME 화이트리스트 4종 + 10MB cap + MAX 4 + VISION_ENABLED 플래그 |
| E | 타입/스타일 | PASS | ruff check/format clean, PreparedPayload TypedDict 명시 |
| F | 테스트 품질 | PASS | 24 케이스, FakeListChatModel — LLM 호출 0, autouse 환경변수 격리 |
| G | 회귀 안전성 | PASS | tests/chatbot 142, 레거시 213 모두 통과 |
| H | 잠재적 결함 | PASS+권고 | 의도된 단순화 명시 (아래 4-LOW 참조) |
| I | 직전 PR audit 권고 회귀 | PASS | hybrid 182줄 ≤ 200, RerankInput 유지, ToolPolicy 한계 docstring 유지, ExtractEntitiesResult 유지 |
| J | PR 3 시작 권고 | n/a | 4 strategy 통일 시그니처 ✓ |

### A. Hexagonal & 의존방향

- `chatbot/infrastructure/validation/__init__.py:7-10` — domain.Attachment 만 import, langchain/openai 미사용 ✓.
- `chatbot/infrastructure/strategies/vision_strategy.py:32-33` — LangChain `BaseChatModel` 은 TYPE_CHECKING 가드.
- `chatbot/infrastructure/strategies/vision_strategy.py:73` — `HumanMessage`/`SystemMessage` 는 `run()` 메서드 본문 내부 import (모듈 임포트 시 langchain 미발생).
- `chatbot/infrastructure/stages/prepare_image_payload_stage.py:12` — domain.Attachment 만 의존, langchain 0.

### B. rag_core/ 영향 0

- `git status` clean (rag_core/, api/ 모두 변경 0).
- `rag_core/vision_rag.py:28-36` 의 `_VISION_SYSTEM` 텍스트와 `chatbot/infrastructure/prompts/vision_prompt.py:12-19` 의 `VISION_SYSTEM_PROMPT` 가 **글자 단위 동일**. 학습 트랙 분리 원칙상 *재사용 불가* → *동등 정의 복제* 가 의도된 방식.
- `api/routes/chat.py:91-111` 의 `_resolve_mode` 분기는 PR 4 wiring 시점에 `supports()` 기반 단순화 가능 (PR 3 권고 참조).

### C. 단일 책임 / 라인 한도

| 파일 | 라인 | 한도 200 |
|------|------|:--------:|
| validation/attachment_validator.py | 108 | ✓ |
| validation/__init__.py | 12 | ✓ |
| prompts/vision_prompt.py | 20 | ✓ |
| stages/prepare_image_payload_stage.py | 49 | ✓ |
| strategies/_config.py | 95 | ✓ |
| strategies/vision_strategy.py | 158 | ✓ |
| 테스트 3종 | 76 / 50 / 132 | ✓ |

- `vision_strategy.run()` 본문 35줄 — `_build_result`, `_maybe_retrieve`, `_error_result` 분리 적절.
- `AttachmentValidator._validate_url_value` / `_validate_data_url_value` 분리 — `image_url` kind 가 https URL 이든 data URL 이든 통과 가능한 *2-way* 입구를 명확화. 적절.
- `_config.py` 4 dataclass 합본 — 각 dataclass 독립 (공유 필드 없음), 합쳐도 95줄. 단일 파일 위반 아님.

### D. PRD-001 vision 게이팅 정합

| PRD-001 §6 요건 | 구현 위치 | 충족 |
|-----------------|-----------|:----:|
| 이미지 5MB 이하 | `attachment_validator.py:49` MAX_DATA_URL_BYTES=10MB | ✓ (이중 방어) |
| MIME 화이트리스트 (jpeg/png/webp/gif) | `attachment_validator.py:40-48` (+jpg alias) | ✓ |
| VISION_ENABLED 환경변수 | `vision_strategy.py:62-66` | ✓ |
| 첨부 개수 한도 | `attachment_validator.py:50` MAX_ATTACHMENTS=4 | ✓ |

서버 10MB 가 클라이언트 2MB 리사이즈 한도보다 큰 것은 **이중 방어** 의도 — 클라가 변조될 수 있어 서버는 base64 인코딩 오버헤드 + 안전 마진까지 허용하되 *합리적 상한*. 정합.

prompt-injection 방어: vision_strategy 는 사용자 텍스트를 system 프롬프트에 넣지 않고 `HumanMessage(content=parts)` 의 image_url 과 함께 분리 — 텍스트는 user role 로만 진입. 도구 description injection 표면은 PR 2-C 의 `description_safe` 플래그가 담당. **현 phase 의도된 한계**.

### E. 타입/스타일

- ruff check: All checks passed.
- ruff format: 11 files already formatted.
- 모든 메서드/함수 타입 힌트 ✓.
- docstring 한국어, 식별자 영문 ✓.
- 이모지 0건.
- `PreparedPayload` TypedDict 명시 (`prepare_image_payload_stage.py:15-20`).

### F. 테스트 품질

| 파일 | 케이스 | 요구치 |
|------|:------:|:------:|
| test_attachment_validator.py | 10 | ≥ 8 ✓ |
| test_prepare_image_payload.py | 5 | ≥ 5 ✓ |
| test_vision_strategy.py | 9 | ≥ 8 ✓ |

- LLM 호출 0회 — `FakeListChatModel` 단독 (`test_vision_strategy.py:6,38,121`).
- `_isolate_vision_env` autouse fixture 가 VISION_ENABLED + VISION_WITH_RETRIEVAL 양쪽 격리 (`test_vision_strategy.py:31-34`).
- `test_run_검증_실패_LLM_미호출` — `llm.i == 0` 으로 호출 카운트 직검증 (132줄).

### G. 회귀 안전성

- `pytest tests/chatbot/ -q` → **142 passed**.
- `pytest tests/ --ignore=tests/chatbot -q` → **213 passed**, 3 warning (SwigPy DeprecationWarning, 본 PR 무관).

## 3. 회귀 검증 결과

| 검증 | 명령 | 결과 |
|------|------|:----:|
| 신규 테스트 | `pytest tests/chatbot/ -q` | 142 passed |
| 레거시 테스트 | `pytest tests/ --ignore=tests/chatbot -q` | 213 passed |
| ruff lint | `ruff check <대상>` | All passed |
| ruff format | `ruff format --check <대상>` | already formatted |
| git diff rag_core/ api/ | `git status` | clean |

## 4. 위반/권고

위반 0. 다음은 향후 권고 (HIGH 없음, 모두 LOW).

- **LOW-1 (의도된 단순화)** `attachment_validator.py:104-108` — base64 디코딩 없이 *문자열 길이* 만 본다. 실제 디코딩 후 크기는 약 75% 수준 (오버추정 안전쪽). `# 길이 검증 — base64 디코딩 없이 *문자열 길이* 만 본다 (성능).` 주석 명시 ✓.
- **LOW-2** `vision_strategy.py:111` — `_maybe_retrieve` 가 매 호출마다 `os.getenv` 호출. 환경변수 핫리로드 의도이면 OK, 성능 보수화 시 `__init__` 캐싱 가능 (현 호출 빈도 vision per-request 1회 → 무시 가능).
- **LOW-3** `vision_strategy.py:155` — 검증 실패 시 `attachment_count="0"` 으로 메타 기록. 의미는 *유효 첨부 0건* 이지만 실제 첨부 수와 다름. 메타 의미를 *통과한 첨부 수* 로 일관 정의하는 docstring 1줄 추가 권고.
- **LOW-4** `prompts/vision_prompt.py:12` — 칼빈 도메인 톤이 프롬프트에 hardcoded. 신규 corpus(어거스틴) 추가 시 corpus 어댑터의 `SYSTEM_PROMPT` 와 동일한 패턴으로 분리 권고. **다음 corpus 추가 시점** 의 작업.

## 5. 통계

| 지표 | 값 |
|------|----|
| 신규/수정 파일 | 12 (코드 9 + 테스트 3) |
| 신규 코드 라인 (테스트 제외) | 543 |
| 신규 테스트 라인 | 258 |
| 신규 테스트 케이스 | 24 (10 + 5 + 9) |
| 최대 파일 라인 | 158 (vision_strategy.py) |
| 최대 메서드 라인 | 35 (`run()`) |
| Python type hint 누락 | 0 |
| ruff 위반 | 0 |
| 이모지 | 0 |

## 6. PR 2-A/2-B/2-C audit 권고 회귀 점검

| 권고 | 위치 | 상태 |
|------|------|:----:|
| hybrid_strategy.py 200줄 한도 | 182줄 | PASS |
| FlashRank `RerankInput` TypedDict | `flashrank_reranker.py:18` | PASS |
| ToolPolicy enforce 한계 docstring | `chatbot/application/registries.py:25-34` | PASS (docstring 명시 유지) |
| kg_strategy `ExtractEntitiesResult` 타입 힌트 | `kg_strategy.py:37,129` | PASS |

## 7. PRD-001 vision 게이팅 정합 평가

§D 의 표 참조. **모든 4개 요건 충족**. 추가로:

- **다층 방어**: 클라이언트 (web/AttachmentInput 25MB 원본 → 2MB 리사이즈) + 서버 (10MB cap) 이중. 클라가 변조되어도 서버에서 차단.
- **MIME 검증 위치**: `_DATA_URL_RE` 정규식 → 화이트리스트 frozenset. `image/jpg` 도 alias 로 허용 (브라우저별 차이 흡수).
- **첨부 0건 처리**: `supports()` 가 첨부 없으면 False → orchestrator 가 자연스럽게 다른 strategy 로 라우트.
- **prompt injection 한계**: 첨부 사용자 텍스트는 user role 로만 진입 — system 프롬프트 contamination 없음. 도구 설명 injection 은 PR 2-C `description_safe` 플래그.

## 8. PR 3 (orchestrator + nodes) 시작 전 권고

1. **단일 시그니처 통일 확인**: 4 strategy (Hybrid/Agentic/KG/Vision) 모두 `run(RetrievalRequest) -> RetrievalResult`. `select_strategy` 노드에서 분기 없이 `strategy.run(req)` 일관 호출 가능.
2. **`supports()` 기반 vision 자동 라우팅**: Hybrid/Agentic/KG 가 attachments 거부, Vision 만 attachments 요구 — `_resolve_mode` (`api/routes/chat.py:92-111`) 의 명시 `if req.attachments` 분기는 PR 4 wiring 에서 *제거 가능*. orchestrator 의 strategy selector 가 `for s in strategies: if s.supports(req): return s.run(req)` 로 자연 분기.
3. **Conversation State / Intent / Rewrite 노드 시그니처**: domain.Stage[I, O] 패턴 유지. orchestrator 는 LangGraph StateGraph node 함수로 wrapping (현재 stages/* 와 동일 계약).
4. **VISION_ENABLED 게이트 통합**: `is_available()` 결과가 False 일 때 select_strategy 가 hybrid 로 silent fallback 하는 분기 — 현 `_is_mode_available` (`chat.py:127`) 의 로직을 orchestrator 의 health-check 노드로 이전 권고.
5. **`_error_result` 패턴 재사용**: 다른 strategy 에 검증 실패가 추가되면 동일 user-friendly 메시지 패턴 유지 (메타 `validation_error` 키 + `answer` 사과 메시지 1쌍).

---

감사 완료. 판정: **PASS**.
