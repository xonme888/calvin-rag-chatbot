# PR 4 Phase 2 독립 감사 (4.5 / 4.6 / 4.7)

대상 산출물

- `chatbot/application/bootstrap.py` (205 줄)
- `api/routes/chat_v2.py` (168 줄)
- `api/main.py` (+2 줄 diff: chat_v2 import + include_router)
- `tests/test_chat_v2_endpoint.py` (192 줄, 5 케이스)

검증 환경: 작업 cwd `calvin-rag-chatbot/`, Python 3.11.14, pytest 9.0.3.

## 판정 요약

| # | 영역 | 판정 | 핵심 발견 | 조치 |
|---|------|:----:|-----------|:----:|
| A | Hexagonal & 의존방향 | PASS | bootstrap import 가 Domain+Application+Infrastructure 만. `chatbot/` 내 `from api.` import 0건. langgraph/HybridRAG TYPE_CHECKING 처리 적절. chat_v2 의 `CompiledStateGraph` 는 모듈 본문 import (영향 미미, 권고) | - |
| B | rag_core / api 비손상 | PASS | rag_core/ diff 0. chat.py diff 0. main.py diff 정확히 +2 줄 | - |
| C | 단일 책임 / 라인 한도 | WARN | 파일 ≤ 200 (bootstrap 205 — 5 줄 초과, 본문 헬퍼 분리 적절). 함수 ≤ 30 선 일부 초과: `build_default_orchestrator` 34, `_maybe_register_kg` 34, `chat_v2` 39, `_to_response` 36 — 모두 docstring + 타입선언 비중 큼 | 권고 |
| D | bootstrap 동작 | PASS | RuntimeError 가드 (l.107~108), env 토글 (`KG_/AGENTIC_/VISION_ENABLED`), Vision 항상 등록 + 게이트 위임, 6 의존성 (classifier/rewriter/strategies/router/answerer/tools) 주입 | - |
| E | chat_v2 라우트 | PASS | lru_cache(maxsize=1), reset_orchestrator 헬퍼, 변환 3 분리, trace_event start, ChatSyncResponse 반환. 첨부 변환은 `image_url` kind 흡수 | - |
| F | 타입 / 스타일 | PASS | ruff check All checks passed, ruff format All formatted, 이모지 0, 모든 함수 타입힌트 | - |
| G | 테스트 품질 | PASS | 5/5 PASS (0.58s). 5 시나리오 모두 커버. monkeypatch 가 `_orchestrator` 함수 자체 교체 (lru_cache 우회 안전). LLM 호출 0 | - |
| H | 회귀 안전성 | PASS | tests/chatbot 193, 레거시(api 외) 213, chat_v2 5 — 모두 통과 (총 411). /chat/sync 동작 변경 0 | - |
| I | 잠재 결함 | WARN | (1) `_to_response` 가 `metadata.source_pages_label` / `cited_pages` / `suggested_followups` 미생성 — 프론트가 `web/lib/blocks.ts:84`, `web/components/ChatPanel.tsx:44`, `web/lib/blocks.ts:94` 에서 사용. PR 5 절체 시 envelope 매핑 갭. (2) `_maybe_register_kg` 가 `Exception` 전부 silent fallback — 운영 KG init 실패가 로그 없이 묻힘 (Neo4j 진단 의도와 어긋남) | 개선 권장 |
| J | PR 5 권고 | INFO | envelope 매핑 정의서 선행 (intent / standalone_question / selected_strategy / pattern → 프론트 표시 + source_pages_label / cited_pages / suggested_followups 보강). conversation_id 매핑은 PRD-002 합류 시점 | 차기 PR |

종합 판정: **PASS (개선 권장 2 건)**

## 수치 증거

| 항목 | 값 | 비고 |
|------|---:|------|
| bootstrap.py 라인 | 205 | 200 한도 5 초과 (docstring 14 줄, import 32 줄 — 실 로직 ~80 줄) |
| chat_v2.py 라인 | 168 | 한도 내 |
| 함수 30 줄 초과 | 4 / 13 | C 영역 참조 |
| `from api.` in chatbot/ | 0 | grep `from api\.` |
| rag_core/ diff | 0 | git diff --stat |
| api/routes/chat.py diff | 0 | git diff --stat |
| api/main.py diff | +2 | chat_v2 import + include_router |
| 이모지 | 0 / 0 / 0 | 세 파일 모두 |
| ruff check | PASS | All checks passed |
| ruff format | clean | already formatted |
| `as any` / `TODO` | 0 | grep |
| `noqa: BLE001` | 2 | bootstrap KG, chat_v2 핸들러 — 의도된 폭넓은 catch |

## 테스트 실행 결과

| 스위트 | 결과 | 비고 |
|--------|:----:|------|
| tests/chatbot/ | 193 PASS (0.55s) | 도메인/응용/인프라 단위 |
| tests/ (레거시) | 213 PASS (4.84s) | /chat/sync, glossary 등 회귀 0 |
| tests/test_chat_v2_endpoint.py | 5 PASS (0.58s) | 5 시나리오 100% |
| 합계 | 411 PASS | (사용자가 제시한 218 추정치는 일부 범위만의 합이었음) |

5 시나리오 매핑

1. NEW_QUESTION 정상 envelope — `intent / selected_strategy / pattern / trace_id` 모두 검증 (`test_chat_v2_new_question_정상`)
2. META_RECAP RAG 우회 — `selected_strategy=None`, `source_documents=[]`, `meta:meta_recap` (`test_chat_v2_meta_recap_RAG_우회`)
3. 첨부 vision 자동 라우팅 — `selected_strategy=="vision"` (`test_chat_v2_attachment_vision`)
4. 오케스트레이터 예외 → 500 — `RuntimeError` → `HTTPException 500` (`test_chat_v2_오케스트레이터_예외_500`)
5. 라우트 등록 확인 — `/chat/v2` + `/chat/sync` 둘 다 OpenAPI 노출 (`test_chat_v2_라우트_등록_확인`)

## Critical (즉시 수정)

없음.

## Warning (개선 권장)

W1. **chat_v2 응답 envelope 갭 (PR 5 절체 차단요인)**

`_to_response` (chat_v2.py:148~166) 가 metadata 에 채우는 키:

- `intent`, `standalone_question`, `selected_strategy`, `trace_id`, `pattern`, `citations`, (조건부) `subgraph`

레거시 `/chat/sync` 가 `metadata` 에 채우는 키 (chat.py:493~496):

- `cited_pages`, `source_pages_label`, `suggested_followups` 등

프론트 사용 위치 (grep 실측):

- `web/lib/blocks.ts:84` — `metadata.source_pages_label`
- `web/lib/blocks.ts:94` — `metadata.suggested_followups`
- `web/components/ChatPanel.tsx:44` — `metadata.source_pages_label`
- `web/components/MessageHeader.tsx:49` — `metadata.pattern` (chat_v2 도 채움 — OK)

PR 5 에서 web 절체 시 시각적 회귀 (페이지 라벨 미표시, 후속 질문 미노출). PR 5 진입 전 envelope 매핑 보강 또는 `_to_response` 에 키 채우기 필요.

W2. **bootstrap `_maybe_register_kg` silent fallback 가시성 부족**

```python
try:
    port = get_kg_adapter()
except Exception:  # noqa: BLE001 — Neo4j 미연결 등 시 등록 스킵
    return
```

`bootstrap.py:166~169`. 최근 커밋 `0f1f5f6`/`ff26f30` 흐름이 KG init 실패 진단을 강화한 것과 어긋남. 운영 환경에서 KG 가 의도와 달리 비활성화될 때 부팅 로그가 침묵. 권고: `logger.warning("KG strategy not registered: %s", exc)` 등 1줄 추가.

## Info (참고)

I1. `chat_v2` 함수 39 줄, `_to_response` 36 줄 — 30 한도 미세 초과. 모두 docstring + try/except 의 비중. 가독성 저해 없음. 굳이 분리한다면 `_to_response` 를 `_metadata_from_result` + `_documents_from_result` 로 쪼개는 정도.

I2. `bootstrap.py` 205 줄 — 한도 200 의 5 줄 초과. KG/Agentic/Vision 분기 헬퍼 4 개를 같은 파일에 둔 결과. 분리 시 `bootstrap/` 패키지로 가야 하므로 현 단계에선 유지.

I3. `_orchestrator()` 의 `lru_cache` 는 *모듈 import 단위 싱글톤* — 테스트는 `monkeypatch.setattr(chat_v2_module, "_orchestrator", _factory)` 로 함수 객체 자체를 교체해 캐시 우회. 패턴 안전. 다만 리얼 부트스트랩 (HybridRAG 빌드 + 인덱스 로드) 의 회귀 검증은 본 PR 범위 밖이므로 PR 5 (UI 절체) 의 컨트랙트 테스트가 별도로 다뤄야 함.

I4. `langgraph.graph.state.CompiledStateGraph` 가 `chat_v2.py:18` 에 모듈 본문 import. 본 프로젝트의 핵심 의존이라 영향 미미하지만, 체크리스트 A 권고 (함수 본문/TYPE_CHECKING) 와는 어긋남. 향후 langgraph 버전 호환 이슈 발생 시 회피 비용 증가 가능.

## PR 5 (UI 절체) 시작 전 권고

1. `web/lib/api.ts` 가 `/chat/v2` 로 절체 시 envelope 매핑 명세 (W1) 선행 작성.
2. 절체 후 `/chat/sync` deprecation 시점은 PR 6 으로 분리 — 두 라우트 동시 노출 기간 최소 1 PR.
3. 영속화 (PRD-002) 합류 시 `_to_state` 의 `Conversation(id=trace_id, turns=())` 를 `conversation_id` 기반으로 교체 — 현재는 매 호출 새 conversation.

## 회귀 보호 확인

- `git diff HEAD` 기준 `rag_core/` 변경 0.
- `api/routes/chat.py` 변경 0 (`git diff --stat HEAD -- api/routes/chat.py` 출력 없음).
- `api/main.py` 변경 정확히 +2 줄 (import 1 줄 수정 + include_router 1 줄 추가).
- 직전 10 회 audit 권고 위반 0 — 한국어 docstring, 타입힌트, 이모지 0, 영문 식별자, no_emoji, no_spring_ai_reimplementation 모두 준수.
