# PR 2-B Phase 2 Audit (PR 2-B.5~7)

> 독립 감사 — `chatbot/application/registries.py`, `chatbot/infrastructure/strategies/agentic_strategy.py + _config.py`,
> 그리고 6개 단위 테스트 파일 (49 케이스).
> 메인 thread 산출물을 grep/Read/실 pytest 로 직접 검증.

## 1. 요약 판정

**PASS** (CONDITIONAL 사유 없음).

- Hexagonal 의존방향 위반 0, rag_core/api 변경 0.
- 단위 테스트 49건 / 회귀 213건 모두 통과 (실측, 7.4초).
- ruff check + format 21 파일 통과.
- 단일 책임 / 라인 한도 / 메서드 30줄 한도 모두 충족.
- PRD-001 (`rag_core/tools/registry.py + policy.py`) 의 어휘·동작이
  `InMemoryToolRegistry` 에 *동등* 보존됨.

남은 항목은 모두 INFO 권고 (PR 2-C/PR 4 wiring 시 재방문) — 본 phase 차단 사유 아님.

## 2. 체크리스트 결과

### A. Hexagonal & 의존방향 — PASS

`chatbot/application/registries.py` 의 import 실측:

| 라인 | import | 평가 |
|------|--------|------|
| 11 | `import os` | std |
| 12 | `from dataclasses import dataclass, field` | std |
| 13 | `from typing import TYPE_CHECKING` | std |
| 15 | `from chatbot.domain.tools import Tool, ToolRegistry` | domain — OK |
| 17-20 | `if TYPE_CHECKING: chatbot.domain.{corpus,retrieval,strategy}` | domain — OK |

`chatbot.infrastructure` 직접 import 0건. Strategy/Corpus/RetrievalRequest 는 모두
`TYPE_CHECKING` 가드 하 forward reference. 런타임 의존 그래프 깨끗.

`agentic_strategy.py` 의 import 실측:

- domain: corpus / retrieval / tools (OK).
- infrastructure 동일 레이어: parsers, strategies._config, tools._adapters (OK — 같은 레이어 합류).
- LangChain (`BaseChatModel`, `create_agent`, `HumanMessage`) 은 `TYPE_CHECKING` 또는
  메서드 내부 lazy import 로 모듈-import 시점 충격 회피 (line 30, 46, 78).

### B. rag_core 비손상 — PASS

```bash
git status --porcelain rag_core/  # 출력: (없음)
git diff rag_core/                # diff 0
```

rag_core/tools/{registry,policy,mcp_adapter}.py + rag_core/agentic.py 모두 그대로.

### C. 단일 책임 / 라인 한도 — PASS

| 파일 | 라인 | 한도 200 | 평가 |
|------|------|----------|------|
| `application/registries.py` | 163 | OK | ToolPolicy + role_meets + InMemoryTool/Strategy/Corpus Registry |
| `strategies/agentic_strategy.py` | 135 | OK | AgenticStrategy 단일 클래스 |
| `strategies/_config.py` | 51 | OK | HybridStrategyConfig + AgenticStrategyConfig 2 dataclass |
| `strategies/__init__.py` | 21 | OK | export only |

**메서드 30줄 한도** (AST 라인 카운트, `def` 본문 기준):

`agentic_strategy.py` (8개 메서드):
- `__init__`: 19줄, `name`/`label`: 2-3줄, `is_available`: 6줄,
- `supports`: 3줄, `run`: 13줄, `_build_result`: 27줄, `_tool_outputs_to_refs`: 16줄.
- 최대 27줄 < 30 — PASS.

`registries.py` (17개 함수/메서드): `register`/`enabled_for`/`role_meets`/`_allowlist_from_env`
모두 17~19줄 — 전부 한도 내.

**`_config.py` 에 두 dataclass 합류한 점** — 한 파일에 `HybridStrategyConfig` + `AgenticStrategyConfig`:
- 각 dataclass 가 *공유 필드 0* (line 4 docstring 명시) → 응집은 낮지만 결합도 0.
- 향후 `KGStrategyConfig`/`VisionStrategyConfig` 합류 시점이 *분리 트리거*. 50줄 단계에서는 분리 ROI 음.
- **권고**: `_config.py` 가 100줄 초과 시 `_config/` 디렉토리로 분리. 본 phase 무관.

### D. PRD-001 ToolPolicy 정합 — PASS

| 동작 | rag_core/tools | InMemoryToolRegistry | 일치 |
|------|----------------|----------------------|------|
| ALLOWED_TOOLS allowlist | `_allowlist()` (registry.py:63) | `_allowlist_from_env()` (registries.py:117) | 동일 |
| role 위계 | `_ROLE_RANK = {free:0,paid:1,admin:2}` (policy.py:32) | 동일 (registries.py:38) | 동일 |
| `role_meets` fallback 0 | get(role,0) ≥ get(req,0) | 동일 시그니처 | 동일 |
| policy.name 정정 | 도구이름으로 강제 (registry.py:42-49) | 동일 (registries.py:70-77) | 동일 |
| 중복 register 덮어쓰기 | line 50 | line 78 | 동일 |
| reset 헬퍼 | `reset_registry` (line 92) | `reset()` (line 112) | 동일 |

PRD-001 의 `enabled_tools(user_role)` → InMemory 의 `enabled_for(user_role)` 로 *동등 명명*되어
시맨틱 동치. 단 반환 타입이 BaseTool → domain.Tool 로 *역전* — 의도된 변경
(domain.Tool 이 더 협소한 계약).

**현 단계 한계**: `timeout_seconds` / `per_call_token_cap` / `description_safe` 는 *보유만 하고
enforce 하지 않음*. 도구 호출 wrapper (PR 4 wiring 시점) 에서 enforce 예정.
registries.py:25-29 docstring 에 "registry 가 호출 직전 enforce" 라고 적혀 있으나
현재는 *enforce 코드 없음* — 한계가 코드/주석에 명시되었는지 검증:
- registries.py:24-29: "InMemoryToolRegistry 가 본 정책을 함께 보유한다 — 도구 자체 (domain.Tool)
  는 정책을 모르고, *registry 가* 호출 직전 enforce 한다" — *예언적 docstring* 으로 enforce
  지점을 약속했지만 현재 코드 없음.
- **INFO 1**: registries.py 에 "현 phase 는 timeout/token cap enforce 없음 — PR 4
  wiring 시 추가" 한 줄 명시 권고. 1줄 수정.

### E. 타입 / 스타일 — PASS

```bash
ruff check chatbot/application/ chatbot/infrastructure/strategies/ tests/chatbot/
# All checks passed!
ruff format --check ...   # 21 files already formatted
```

- 모든 함수/메서드 타입힌트 명시 (registries.py / agentic_strategy.py 전수 점검).
- 한국어 docstring + 식별자 영문 — 위반 0.
- emoji 스캔 (regex `[\U0001F300-\U0001FAFF...]`): 9개 대상 파일 0건.

**Protocol 만족 검증**:
```python
# registries.py:125
_: type[ToolRegistry] = InMemoryToolRegistry  # type: ignore[type-abstract]
```
- *정적* 검증 (mypy/pyright) — 모듈 import 시 변수 할당으로 타입 호환을 검사.
- 런타임에는 `type[X]` 검증이 발생하지 않음 (Python 은 nominal subtyping 미강제).
- **의도된 패턴**: domain.ToolRegistry 가 `runtime_checkable Protocol` 이므로
  `isinstance(reg, ToolRegistry)` 도 가능하지만, 정적 lint 가 더 빠른 피드백 제공.
- Phase 1 audit INFO #2 (basetool_to_domain_tool 반환 타입) 는 본 phase 에서
  *미정정* — `type: ignore[no-untyped-def]` 그대로. 본 phase 범위 외 (PR 2-B.1).

### F. 테스트 품질 — PASS

```
pytest tests/chatbot/ -q
89 passed in 0.67s
```

- 49 신규 테스트 (Phase 2) + 40 기존 (Phase 1 + 기타) = 89.
- LLM 호출 0건: `FakeListChatModel(responses=["답변"])` 만 사용 (test_agentic_strategy.py:50).
  실제 `_agent.invoke` 미호출 — `_build_result` / `is_available` / `supports` / `name` /
  `label` 만 검증. **AgenticStrategy.run() 회귀 테스트 부재**.
- **의도된 한계**: test_agentic_strategy.py:5 docstring 명시 — "create_agent 가 *그래프
  빌드만* 즉시 수행하고 invoke 는 LLM 호출이 필요하므로, 본 테스트는 _build_result /
  supports / is_available 등 *순수* 메서드만 검증". *Phase 3 audit (E2E) 영역*.
- PRD-001 ToolPolicy 동작 커버:
  - role 필터: test_role_meets_위계 + test_registry_enabled_for_role_필터.
  - allowlist: test_registry_enabled_for_allowlist_env (monkeypatch.setenv).
  - 중복 register: test_registry_같은_이름_덮어쓰기.
  - policy.name 정정: test_registry_policy_name_불일치_정정.
  - unavailable 제외: test_registry_available_unavailable_제외.
- env 변수 격리: monkeypatch 사용 (test_tool_registry.py:109, test_mcp_client.py:9/18) — OK.

테스트 케이스 분포:
| 파일 | 케이스 수 |
|------|-----------|
| test_tool_adapters.py | 7 |
| test_search_tool.py | 8 |
| test_agent_parser.py | 11 |
| test_tool_registry.py | 13 |
| test_agentic_strategy.py | 6 |
| test_mcp_client.py | 4 |
| **합계** | **49** |

### G. 회귀 안전성 — PASS

```
pytest tests/ --ignore=tests/chatbot/ -q
213 passed, 3 warnings in 7.37s
```

- `git status api/` → unchanged. `git diff api/routes/chat.py` → 0 byte.
- PR 2-A audit (Phase 1+2) 권고 5건이 본 phase 에서 깨지지 않음을 grep 으로 확인:
  - RRF dedup, FlashRank 인스턴스, suggested_followups json.dumps, FollowupFn TypeAlias —
    모두 strategies 영역 관성, agentic_strategy.py 신규 추가는 충돌 없음.
- Phase 1 INFO 3건 trace:
  1. `message_to_events` 분리 — 미정정 (영향 없음).
  2. `basetool_to_domain_tool` 반환 타입 — 미정정 (영향 없음, 본 phase 외 파일).
  3. `search_documents` k description 일관성 — **정정 완료** (line 38 `"1~20 허용"`).

### H. 잠재적 결함 — INFO

1. **`_build_result` 의 `model: getattr(self._llm, "model_name", "unknown")`**
   — `FakeListChatModel` 은 `model_name` 미보유 (`_llm_type="fake-list-chat-model"` 만
   가짐) → 메타데이터에 `"unknown"` 기록. 회귀 테스트 (`test_agentic_build_result_envelope`)
   는 model 키를 직접 assert 하지 않음 — 안전. 실제 `ChatOpenAI` 환경에서는 `"gpt-4o-mini"`
   등이 정상 기록. **OK**.

2. **AgenticStrategy.is_available 정적 평가**: `__init__` 시점에 캐시된 `self._tools` 의
   `is_available()` 만 보고 판단 — 도구 추가/삭제는 *Strategy 인스턴스 재생성* 으로만 반영.
   설계 의도 (Strategy 가 도구 카탈로그 책임을 갖지 않음) 와 일치. 동적 갱신은 Registry 책임.
   **OK** (의도된 한계).

3. **registries.py:125 `_: type[ToolRegistry] = ...` 패턴**: 정적 type checker 만족용 변수
   할당. 런타임 부담 0. **OK** (mypy/pyright 가 도입되면 즉시 효과).

4. **ToolPolicy enforce 미비** — D 항목에서 다룬 INFO 1: 한 줄 docstring 보강 권고.

5. **`_config.py` 에 system_prompt 가 hardcoded** — 칼빈 도메인에 강결합. 새 corpus
   (어거스틴 등) 추가 시 strategy 별 prompt 분기 필요. PR 2-C / PR 3 corpus 다중화
   시점에 *AgenticStrategyConfig.system_prompt* 가 corpus 별 주입 가능하게 — 의도된 노브.

### I. PR 2-C (KG) 진행 가능 여부 — GO

PR 2-B 가 PR 2-C 에 *재사용 가능* 자산:

- **InMemoryToolRegistry**: KG 도구 (`graph_traversal_tool` 등) 도 동일 register 한 줄.
  `enabled_for("free")` 자동 합류.
- **InMemoryStrategyRegistry**: KGStrategy 도 `register(KGStrategy(...))` 한 줄. `available_for`
  로 자동 후보.
- **`_config.py`**: `KGStrategyConfig` dataclass 추가 한 자리 명확.
- **AgenticStrategy 패턴**: KG 도 `create_agent(model=...,tools=[graph_tool,search_tool])` 로
  동일하게 조립 가능 — 두 strategy 가 도구 셋만 다르면 거의 동일 코드. **KG 와 Agentic 의
  중복이 보이면 base 추출 권고** (Phase 3 audit 시점).

**시작 전 권고**:
1. (INFO 1) registries.py docstring 1줄 보강: "timeout/token cap enforce 는 PR 4 wiring 에서".
2. KGStrategy 작성 시 `AgenticStrategy` 와의 중복 발생 여부를 *처음 단계부터* 비교 — 중복
   ≥ 50% 면 `_BaseToolStrategy` 추출. 중복 < 50% 면 그대로 분리.
3. `_config.py` 가 100줄 초과 트리거: 디렉토리 분할.

## 3. 위반 / 권고

위반 0. INFO 1건만:

| # | 종류 | 위치 | 내용 | 조치 |
|---|------|------|------|------|
| 1 | INFO | `chatbot/application/registries.py:24-29` | ToolPolicy enforce 시점이 docstring 에 약속 ("registry 가 호출 직전 enforce") 되었으나 현재 enforce 코드 없음 | 한 줄 추가 권고: "현 phase 는 *보유만*. enforce 는 PR 4 호출 wrapper" |

## 4. 회귀 검증 결과

| 검증 | 결과 |
|------|------|
| `pytest tests/chatbot/ -q` | 89 passed, 0.67s |
| `pytest tests/ --ignore=tests/chatbot/ -q` | 213 passed, 7.37s, warnings 3 (rag_core 외부 SwigPy, 무관) |
| `ruff check` (대상 9 파일) | All checks passed |
| `ruff format --check` (21 파일) | already formatted |
| `git status rag_core/` | unchanged |
| `git status api/` | unchanged |
| `git diff api/routes/chat.py` | empty |

## 5. PRD-001 정합 평가

PASS. PRD-001 의 핵심 동작 6개 (allowlist / role 위계 / role_meets fallback / policy.name 정정 /
중복 덮어쓰기 / reset) 가 InMemoryToolRegistry 에 동등 보존됨. 반환 타입만 BaseTool →
domain.Tool 로 *축소* — 헥사고날 의도와 일치.

미보존 동작: `iter_entries()` (rag_core/tools/registry.py:87-89). 본 메서드는 PR 4 wiring 의
internal 전용 — 도메인 헬퍼로 노출 불필요. **의도된 미보존**.

## 6. PR 2-A audit 권고와의 정합

PR 2-A audit 의 권고 5건 (Phase 1+2 합) 모두 영향 없음 — 다른 strategies (HybridStrategy)
영역. 본 phase 의 신규 추가 (AgenticStrategy + registries) 는 _config.py 에 dataclass
하나 합류한 것 외에 기존 strategies 와 결합 0.

## 7. 통계

- 신규/변경 파일: 11 (코드 5 + 테스트 6).
- 코드 라인: 375 (registries 163 + agentic 135 + _config 51 + __init__ 21 + application/__init__ 5).
- 테스트 라인: 668 (6개 테스트 파일 합).
- 메서드/함수: 25 (registries 17 + agentic 8) — 모두 ≤ 30줄.
- 테스트 케이스: 49 (chatbot/ 신규 49건; 누적 89건).
- 회귀 통과: 213/213 (legacy) + 89/89 (chatbot/).

## 8. PR 2-C (KG) 진행 가능 여부 — GO

GO. 본 phase 가 KG 합류를 위한 *조립 자산* 을 깨끗이 노출. 시작 전 INFO 1건 (1줄 docstring)
정정 권고 외 차단 없음.

다음 PR 시작 전 권고:
1. registries.py docstring 한 줄 보강 (INFO 1).
2. PR 2-C 의 KGStrategy 와 AgenticStrategy 중복 ≥ 50% 면 base 추출.
3. KG 도구의 ToolPolicy `required_role="paid"` 검토 (KG traversal 비용).
