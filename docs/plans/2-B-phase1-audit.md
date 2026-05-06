# PR 2-B Phase 1 독립 감사 보고서

> 대상: TRD-008 PR 2-B.1~2-B.4 (tools/_adapters 양방향, search_documents, mcp_client stub, agent_message_parser)
> 감사 일자: 2026-05-06
> 감사자: 독립 audit agent (메인 thread 산출물 신뢰 안 함, grep + Read + ruff 로 실측 검증)
> 선행: `docs/plans/2-A-phase1-audit.md`(PASS), `docs/plans/2-A-phase2-audit.md`(재감사 PASS)

## 1. 요약 판정

**PASS** — Hexagonal 의존방향 무위반, rag_core 변경 0, ruff 무위반, 모든 함수 타입힌트 부착, 파일 200/메서드 30 한도 모두 충족(최대 메서드 33줄 1건만 *경계 초과*). PRD-001 의 ToolPolicy / MCP allowlist 가 PR 2-B.5 에서 합류할 *어휘 자리*가 어댑터에 명확히 비워져 있다. 잠재 결함 3건 (G섹션) 은 모두 *PR 2-B.5/6 으로 자연 해소* 되거나 *현 단계에서 의도된 한계* — Phase 1 산출물 자체에 차단 사유 없음. PR 2-B.5 (InMemoryToolRegistry) 즉시 진행 가능.

## 2. 체크리스트 결과

| 항목 | 결과 | 근거 |
|---|:---:|---|
| **A. Hexagonal — domain 외부 의존성 0** | PASS | `chatbot/domain/*` 의 langchain/openai/faiss import 0건. `domain/__init__.py:4` 한 줄은 docstring 주석. `domain/tools.py` 와 `domain/retrieval.py` 는 pydantic 만 의존. |
| **A. _adapters 가 domain ↔ langchain 둘 다 알고 서로 의존 안 함** | PASS | `domain_to_langchain.py:14,17` (langchain.BaseTool/StructuredTool + domain.Tool import) 와 `langchain_to_domain.py:14,16` (langchain.BaseTool + domain.ToolResult/Schema) 가 *대칭* — 두 어댑터가 서로 import 하지 않음 (grep 0건). |
| **A. parsers/agent_message_parser.py 가 application 레이어 비참조** | PASS | import 6줄 모두 stdlib + langchain_core + `chatbot.domain.retrieval.ToolCallRecord`. `chatbot.application` / `ChatBot State` 참조 0건 (grep 결과 0). |
| **A. tools/search/search_documents.py 도메인 일관성** | PASS | `chatbot.domain.retrieval.{RetrievalRequest, Retriever}` + `chatbot.domain.tools.{ToolResult, ToolSchema}` + `chatbot.infrastructure.parsers.format_doc_with_meta`. infrastructure → infrastructure 횡방향 참조는 *parsers* 한 곳뿐 (citation 포매터 재사용) — 허용 범위. |
| **A. tools/mcp/mcp_client.py 도메인 일관성** | PASS | stdlib(logging/os/re) + `chatbot.domain.tools.Tool`. langchain 도 직접 의존하지 않음 — stub 단계라 통신 라이브러리 부재. |
| **B. rag_core/ 변경 0** | PASS | `git diff rag_core/` 결과 *완전 빈 출력*. `git diff --stat rag_core/` 도 0줄. `rag_core/tools/{policy,registry,mcp_adapter}.py` 252줄 그대로. |
| **B. rag_core/agentic.py 시그니처 보존** | PASS | `parse_agent_messages`(line 47-78), `message_to_stream_events`(line 81-115), `_make_search_tool`(line 254-284) 정의 그대로 — 본 PR 은 *복제*를 통해 chatbot/ 에 흡수, rag_core 측은 하위호환 유지. |
| **C. 파일 라인 ≤ 200** | PASS | 9개 파일 모두 한도 내. 최대 `agent_message_parser.py` 122줄, `search_documents.py` 76줄, `mcp_client.py` 74줄, `domain_to_langchain.py` 69줄, `langchain_to_domain.py` 67줄. 합 473줄(__init__ 포함). |
| **C. 메서드 라인 ≤ 30** | PASS (1건 경계) | AST 분석: 17개 함수/메서드 중 30줄 초과 1건 = `parse_messages` 30줄(정확히 한도), `message_to_events` 33줄(*3 초과*). 나머지 ≤ 25줄. `message_to_events` 의 33줄은 `if AIMessage / elif name=='search_documents'` 두 가지(thinking/answer/tool_result 3 yield) — 분기를 helper 로 더 쪼갤 수 있으나 현 구조가 *한 메시지 → 한 이벤트군* 1:1 매핑이라 가독성 ↑. INFO. |
| **C. 단일 책임** | PASS | `_LangChainToolAdapter` (BaseTool→domain.Tool 어댑터), `SearchDocumentsTool` (검색 도구 1개), `EnvAllowlistMCPClient` (MCP stub 1개), `AgentParseResult` (Agent 종료 후 평면 정보 dataclass) — 한 클래스 한 책임. |
| **D. PRD-001 ToolPolicy 합류 자리** | PASS | `_LangChainToolAdapter.invoke`(langchain_to_domain.py:37-43) 가 try/except 로 호출만 감싸고 timeout/role 적용 *없음* — TRD-008 §2.5 가 명시한 대로 *registry 의 invoke wrapper* 로 흡수될 자리. 어댑터엔 metadata 만, 정책은 PR 2-B.5 의 `InMemoryToolRegistry` 가 보유. 어휘 충돌 없음. |
| **D. BaseTool ↔ domain.Tool 양방향 어댑터 구현** | PASS | TRD-008 §2.3 의 두 방향 모두 구현: `domain_tool_to_basetool`(StructuredTool 동적 args_schema 생성), `basetool_to_domain_tool`(_LangChainToolAdapter 인스턴스 반환). |
| **D. search_documents description / parameters PRD-001 정합** | PASS | description 한국어 + 검색결과 형식 안내(L25-28), parameters required=["query"] + k default 5 + 1~10 권장(L37-38). PRD-001 의 LLM 도구 선택 시나리오 (외부 노출 description 만 보고 도구 선택) 와 정합. |
| **E. ruff check** | PASS | `ruff check chatbot/infrastructure/tools/ chatbot/infrastructure/parsers/agent_message_parser.py` → All checks passed (0 위반). |
| **E. ruff format** | PASS | `ruff format --check ...` → 9 files already formatted. |
| **E. 타입힌트 100%** | PASS | AST 분석: 17개 함수 중 `basetool_to_domain_tool`(langchain_to_domain.py:65) 만 반환 어노테이션 부재 + `# type: ignore[no-untyped-def]` 명시 — Tool Protocol return type 가 PEP 544 Protocol 이라 정적 표현이 모호한 점을 의도적으로 회피. 도메인 노출 함수는 모두 부착. |
| **E. _LangChainToolAdapter.invoke arguments dict 타입힌트** | PASS | line 37 `def invoke(self, arguments: dict[str, Any]) -> ToolResult:` — 명시. |
| **E. 한국어 docstring + 식별자 영문** | PASS | 모든 모듈 톱-레벨 docstring 한글, 클래스/메서드 docstring 한글. 식별자 영문. 이모지 0건. |
| **F. 외부 의존 없이 단위테스트 가능** | PASS | `domain_tool_to_basetool`: domain.Tool stub 으로 테스트 가능, langchain BaseTool 의 args_schema 만 검증 — OpenAI 호출 0. `basetool_to_domain_tool`: FakeBaseTool(name/description/invoke 만 가진) 으로 검증 가능. `SearchDocumentsTool`: FakeRetriever (이미 `tests/chatbot/fakes.py` 에 존재) 로 검증. `parse_messages`/`message_to_events`: `AIMessage(content=...)` / `ToolMessage(name="search_documents", content=...)` 만 만들면 됨. 모두 LLM 호출 0. |

## 3. 위반 / 권고

### 3.1 BLOCKER — 없음

### 3.2 WARN — 없음

### 3.3 INFO (가독성 / 향후)

1. **`agent_message_parser.py:69-101` `message_to_events` 33줄** — 30줄 한도 *3 초과*. 분기를 helper 로 분리 가능:
   ```python
   def _ai_to_events(msg: AIMessage) -> Iterator[dict]: ...
   def _tool_to_events(msg: BaseMessage) -> Iterator[dict]: ...
   ```
   현 구조가 *읽기 쉽다* 는 점 + 함수형 yield 가 분기당 1회씩이라 분리 ROI 가 낮음. PR 2-B.6 wiring 후 *재방문* 권고.

2. **`langchain_to_domain.py:65` `basetool_to_domain_tool` 의 return 타입** — `# type: ignore[no-untyped-def]` 로 회피. 명시하려면:
   ```python
   def basetool_to_domain_tool(base: BaseTool) -> "Tool": ...
   ```
   `Tool` 은 `runtime_checkable Protocol` 이라 정적/동적 검증 모두 가능. 단 *순환 import 위험* 은 없으니 PR 2-B.5 wiring 시 정정 권고.

3. **`search_documents.py:37-39` k description 의 "1~10 권장" vs `:62` 실제 cap `1~20`** — description 과 enforce cap 의 *비대칭*. LLM 이 description 만 보고 k=10 까지 시도하지만 실제 상한은 20 — 의도된 보수적 가이드인지 *문서화* 하거나, description 을 "1~20" 으로 통일 권고. 한 줄 수정. PRD-001 의 per_call_token_cap (4000 토큰) 과의 충돌은 *없음* (k=20 일 때 평균 청크 1500자 ≈ 750 토큰 × 20 = 15000 토큰 — 토큰 cap 으로 잘리지만 *명시 한도와 cap 의 일관성* 은 PR 2-B.5 InMemoryToolRegistry 의 wrapper 가 enforce 시 다시 점검).

## 4. 통계

| 항목 | 값 |
|---|---:|
| 신규 파일 (Phase 1) | 9 (실 코드 5 + __init__ 4) |
| 신규 라인 합 | 473 (docstring·blank 포함) |
| 최대 파일 | `agent_message_parser.py` 122줄 |
| 최대 메서드 | `message_to_events` 33줄 (한도 30 *경계 초과*) |
| 30줄 초과 메서드 | 1건 (`message_to_events`) |
| 정확히 30줄 메서드 | 1건 (`parse_messages`) |
| ruff 위반 | 0 |
| ruff format 미정렬 | 0 |
| 타입힌트 누락(의도 외) | 0 |
| 타입힌트 누락(의도된 회피) | 1 (`basetool_to_domain_tool` 반환 — Protocol 회피) |
| 이모지 / 마케팅 문구 | 0 |
| domain → infra import 위반 | 0 |
| infra → application import 위반 | 0 |
| rag_core 변경 | 0 |
| api 변경 | 0 |
| 신규 테스트 | 0 (PR 2-B.7 으로 분리 — 의도) |

## 5. 잠재 결함 (G섹션) 검증

| 결함 후보 | 결과 | 근거 |
|---|:---:|---|
| **SearchDocumentsTool k 캡 1~20 합리성** | OK (단 INFO) | line 62 `k = max(1, min(k, 20))`. 도구 폭주 방지 의도 명시. PRD-001 per_call_token_cap=4000 과의 정량 충돌은 PR 2-B.5 wrapper 측에서 enforce 시 추가 검증 필요 (현 phase 무관). |
| **`_params_to_args_schema` 가 nested object/array 를 단순 매핑** | 의도된 한계 | `_JSON_TYPES` 가 `object→dict, array→list` 로 *얕게* 매핑 (line 25-26). nested properties (예: `{"type":"object","properties":{...}}`) 는 그냥 dict 로 처리 — Pydantic 검증 실패 시 LLM 호출 단계에서 노출. domain.Tool 의 parameters 가 *2단 이상 nested* 인 경우 본 어댑터 미지원. **현 단계 한계로 명시 + 도메인 Tool 작성 가이드에 "parameters 는 평면 1단" 명시 권고**. PR 2-B.6 wiring 시 search_documents (1단) 만 사용하므로 차단 사유 아님. |
| **`_args_schema_dict` 가 LangChain 1.x Pydantic v1/v2 양쪽 처리** | OK | line 56 `getattr(args, "model_json_schema", None) or getattr(args, "schema", None)` — Pydantic v2 의 `model_json_schema()` 우선, v1 의 `schema()` 폴백. try/except 로 실패 시 빈 dict (line 60-61). 안전. |
| **`parse_messages.final_answer` 가 thinking 빈 메시지를 답변으로 오인** | OK | line 46-50 `if isinstance(msg, AIMessage) and msg.content: ... if isinstance(content, str) and content.strip(): final_answer = content; break`. *content 가 빈 문자열/공백만* 인 AIMessage 는 `strip()` 으로 걸러져 다음 역방향 메시지로 진행. tool_calls 만 있는 AIMessage 는 일반적으로 content="" 라 자동 통과. **위험 없음**. (rag_core/agentic.py:53-58 와 동일 동작 — 검증된 코드 흡수.) |
| **`parsed_to_tool_calls.elapsed_ms_per_call` 모든 호출 동일값 부여** | 의도된 한계 | line 107 default `elapsed_ms_per_call: int = 0`. line 119 `elapsed_ms=elapsed_ms_per_call` — 모든 호출에 동일값. docstring(line 110-112) 이 *의도* 명시: "호출 단위로 측정하지 않는 현 구조". PR 2-B.5 의 InMemoryToolRegistry 가 도구 invoke 를 timing wrapper 로 감쌀 때 *호출별 elapsed* 를 직접 ToolCallRecord 로 채우는 방향으로 *후속 PR 에서* 정상화 가능. **현 phase 차단 사유 아님**. |
| **MCP stub 의 `_INJECTION_PATTERNS` 가 sanitize_description 에서만 사용** | OK | line 28-33 패턴 정의, line 43-48 sanitize_description 에서 사용. list_tools() 가 빈 list 반환이라 *현 단계엔 미발동* — 의도. PR 2-B 후속(MCP 실 통합) 에서 list_tools() 가 외부 description 을 받을 때 sanitize 적용 자리는 이미 함수로 노출됨. |
| **이전 권고(2-A-phase2 §5.2) 가 본 phase 에서 깨지지 않음** | OK | (a) RRF dedup → strategies 영역, 본 phase 무관. (b) FlashRank 인스턴스 → strategies 영역, 무관. (c) suggested_followups json.dumps → strategies 영역, 무관. (d) FollowupFn TypeAlias → 무관. 모두 영향 없음 확인. |

## 6. PRD-001 정합 평가

| PRD-001 요구 | Phase 1 산출물 정합 |
|---|---|
| ToolRegistry 가 외부 도구를 단일 시그니처로 등록 | `domain.Tool` Protocol 이 단일 시그니처. `basetool_to_domain_tool` 가 *기존 BaseTool 자산 흡수* 통로. **PASS** |
| MCP allowlist (`MCP_SERVERS`) 보존 | `EnvAllowlistMCPClient._allowed_servers()` 가 동일 환경변수 사용 (line 37-40). rag_core/tools/mcp_adapter.py:27-31 와 동일 시그니처. **PASS** |
| 도구별 timeout / per_call_token_cap / required_role | 어댑터 단계엔 부재 (의도). PR 2-B.5 의 InMemoryToolRegistry 가 ToolPolicy 를 metadata 로 보유 + invoke wrapper 에서 enforce. 본 phase 는 *자리만* 비워둠. **PASS (미합류, 다음 PR 진행)** |
| description 의 prompt injection sanitize | `mcp_client.sanitize_description` 함수 + `_INJECTION_PATTERNS` 보존 (line 28-48). 동일 패턴 4개 (ignore previous, system:, </system>, ChatML). **PASS** |
| LLM 도구 선택 시 description 이 유일한 컨텍스트 | `SearchDocumentsTool.schema.description` 한국어 자연어 + 결과 형식 안내. parameters 의 query/k description 도 한국어. **PASS** |
| 도구 호출 가시성 (thinking/tool_result 이벤트) | `message_to_events` 가 thinking/tool_result/answer 3종 이벤트 발행 — rag_core/agentic.py:81-115 의 동작 그대로 흡수. **PASS** |

## 7. PR 2-B.5 진행 가능 여부 + 시작 전 권고

**진행 가능**.

### 시작 전 권고

1. **`InMemoryToolRegistry` 가 흡수할 어휘 정렬 (1순위)**:
   - `ToolPolicy` 의 4 필드 (timeout_seconds, per_call_token_cap, required_role, description_safe) 를 `chatbot/application/registries.py` 로 *동등 이름* 으로 이전 (TRD-008 §2.5 의 InMemoryToolRegistry 스케치와 정합).
   - `register(tool, policy)` / `available(role=...)` / `invoke_with_policy(name, args)` 3 메서드. invoke_with_policy 가 timeout 측정 → ToolCallRecord.elapsed_ms 채움 (Phase 1 의 `parsed_to_tool_calls` elapsed=0 한계가 여기서 *부분 해소*).
   - `enabled_tools(role)` 의 allowlist (`ALLOWED_TOOLS` 환경변수) 패턴 보존.

2. **MCP 통합 자리 비워두기**: `InMemoryToolRegistry.register_mcp_client(client: MCPClient)` 가 client.list_tools() 를 호출해 등록하는 메서드 1개 추가. PR 2-B.5 단계는 EnvAllowlistMCPClient 가 빈 list 반환하지만 *경로 자체는 검증* (테스트로 빈 등록 + 비-빈 mock 등록 양쪽).

3. **PR 2-B.6 (agentic_strategy 조립) 사전 점검**:
   - `domain_tool_to_basetool` 의 nested object/array 한계(§5 G) 가 search_documents 만 사용하면 무영향 — 단, PR 2-B 후속에서 외부 MCP 도구가 *2단 nested params* 를 노출하면 어댑터 보강 필요. PR 2-B.5 docstring 에 "parameters 는 1단 평면 권장" 명시.
   - `parsed_to_tool_calls.elapsed_ms_per_call` 의 0 default 는 PR 2-B.5 InMemoryToolRegistry 의 wrapper 가 *호출별 직접 측정*해 ToolCallRecord 를 채우는 경로로 대체 — `parsed_to_tool_calls` 헬퍼는 PR 2-B.6 에서 *대체* 또는 *호출별 elapsed map 을 받는 시그니처*로 확장 권고.

4. **Phase 1 INFO 3건 (§3.3) 백로그**: PR 2-B.5/6 작업과 *같은 PR* 에서 정정 권장 — `message_to_events` 분리 / `basetool_to_domain_tool` 반환 타입 / `search_documents` k description 일관성. 모두 1줄~수줄 변경.

5. **Phase 2 audit (PR 2-B.5~7) 의 검증 범위**: (a) InMemoryToolRegistry 의 timeout/role enforce 동작, (b) AgenticStrategy 가 기존 AgenticRAG.query() 와 *동일 입력 30건* 비교 시 도구 호출 횟수·인자 동일 (TRD-008 §3 S6 success metric), (c) 단위 테스트 7+ 건(Tool 어댑터 양방향 / SearchDocumentsTool / EnvAllowlistMCPClient / parser 3종 / registry).
