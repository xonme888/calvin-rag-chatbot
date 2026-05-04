---
status: draft
group: A
created: 2026-05-04
related_prd: docs/prd/draft/001-tools-input-extension.md
---

# TRD-001: 도구/입력 확장 (Tool Registry + MCP + 이미지 + Reasoning Trace)

## 1. AS-IS 분석

### 1.1 도구 결합 — Agentic 모드에 직결합

`rag_core/agentic.py:225` — `self._tools: list[BaseTool] = [self._make_search_tool()]`.
`AgenticRAG.__init__` 안에서 `_make_search_tool()` 클로저로 `search_documents` 한 개를 만들고, 같은 함수 안에서 `create_agent(model, tools, system_prompt)` (line 229~233) 에 박는다.

결과:

- 새 도구 추가 = `agentic.py` 수정 + 재배포. 외부 모듈/플러그인이 도구를 기여할 수 없다.
- MCP 서버 (예: 외부 검색, 사내 KMS) 같은 동적 출처를 붙이려면 Agentic 클래스 자체를 손봐야 한다.
- 현재 도구 수: 1개 (`search_documents`). 도구 등록 지점: 단일 (line 225).

### 1.2 입력 채널 — 텍스트 단일

`api/schemas.py:31~45` — `ChatRequest`. 필드: `question`, `mode`, `chat_history`, `dense_weight`. 첨부/이미지 필드는 없다.

`web/lib/sessionStore.ts:15~19` — `SessionAttachment` 인터페이스는 이미 정의되어 있으나(`payload: Record<string, unknown>`), 어떤 컴포넌트도 `attachments` 필드에 값을 넣지 않는다. AS-IS 사용처: 0건.

### 1.3 Reasoning trace — 백엔드 전용

`infra/observability.py:93~243` — `LangChainTracer` 가 `chain/llm/tool/retriever` start/end 를 stdout JSON line 으로 emit. trace_id 는 `api/routes/chat.py:131` (sync) / `:418` (stream) 에서 발급되어 응답 metadata 에 포함되지만, 개별 step 이벤트는 클라이언트로 전달되지 않는다.

Agentic 모드의 `tool_calls` 는 `rag_core/agentic.py:319~322` 에서 sync metadata 로 노출된다 (`tool_calls: list[{tool, args}]`). 그러나 프론트(`web/components/blockRenderers.tsx:38~92`) RENDERERS 에는 tool 시각화 블록이 없다 — 답변 헤더에 "도구 N회" 카운트만 (`MessageHeader.tsx:87`).

### 1.4 한계 / 변경 비용 / 회귀 위험

| 항목 | 현재 비용 | 위험 |
|---|---|---|
| 신규 도구 추가 | `agentic.py` 직접 수정 | Agentic 회귀 (1개 모드만) |
| MCP 서버 통합 | 신규 어댑터 작성 + agentic 재작성 | Agentic 의 `_make_search_tool` 패턴과 충돌 |
| 이미지 입력 | `ChatRequest` 스키마 + 3 모드 분기 + 프론트 멀티파트 | 3 모드 모두 영향 |
| Reasoning UI | `tool_calls` metadata 는 있으나 Block 미존재 | 신규 Block 추가만으로 가능 (낮음) |

## 2. TO-BE 설계

### 2.1 신규 모듈

```
rag_core/
  tool_registry.py          신규 — 도구 등록/조회 단일 진입점
  tools/
    __init__.py             신규 — 기본 도구 (search_documents) 등록
    search_documents.py     이전 — agentic._make_search_tool 의 클로저를 함수로 외부화
    mcp_adapter.py          신규 — MCP 서버 → BaseTool 변환
    vision_describe.py      신규 — 이미지 묘사 도구 (선택, PRD 결정 후)
```

### 2.2 인터페이스 (Python sketch)

```python
# rag_core/tool_registry.py
from langchain_core.tools import BaseTool
from typing import Callable

ToolFactory = Callable[[], BaseTool]  # 지연 생성 (의존 무거우면 lazy)

def register(name: str, factory: ToolFactory) -> None: ...
def get(name: str) -> BaseTool: ...
def all_tools() -> list[BaseTool]: ...
def names() -> list[str]: ...
```

`mode_registry.ModeEntry` 와 동형. 기존 패턴을 그대로 따른다 (line 38~54 참조).

`AgenticRAG.__init__` 변경:

```python
# Before (agentic.py:225)
self._tools = [self._make_search_tool()]

# After
from rag_core.tool_registry import all_tools
self._tools = all_tools()  # registry 가 결정. 테스트는 register/reset 으로 격리
```

### 2.3 MCP 어댑터

라이브러리 후보: `langchain-mcp-adapters` (공식, MCP → BaseTool 변환). 실측 미정. 어댑터를 직접 작성할 경우 인터페이스:

```python
# rag_core/tools/mcp_adapter.py
def load_mcp_tools(server_url: str, transport: Literal["stdio", "sse"]) -> list[BaseTool]: ...
```

기동 시점 (`api/main.py:64~66` include_router 직전) 에서 `tool_registry.register` 로 흡수.

### 2.4 이미지 입력 — Vision 도구 vs 별도 모드

PRD 결정 후 확정. 두 옵션 모두 인터페이스 변경은 같다:

`api/schemas.py:31` `ChatRequest` 에 `attachments: list[Attachment] = Field(default_factory=list)` 추가. `Attachment = {kind: "image", url | base64, mime}`.

옵션 A (Vision 도구): `tools/vision_describe.py` 를 registry 에 등록. Agentic 이 호출 가능.
옵션 B (별도 모드): `mode_registry.register(ModeEntry(name="vision", ...))`. Hybrid/Agentic 과 분리.

### 2.5 Reasoning Trace UI

신규 Block 타입:

```ts
// web/lib/blocks.ts:37 Block union 에 추가
| { type: "tool_trace"; calls: Array<{ tool: string; args: Record<string, unknown> }> }
```

`web/lib/blocks.ts:111~157 messageToBlocks` 에서 `msg.meta?.metadata.tool_calls` 가 비어있지 않으면 `tool_trace` block 을 본문 직전에 push. RENDERERS 에 entry 1줄 추가 (blockRenderers.tsx:38~92 패턴).

스트리밍 trace (실시간 reasoning 표시) 는 별도 SSE 채널로 흘릴 수 있으나 PRD 가 "선후 표시" 로 결정 시 sync 응답 metadata 만으로 충분.

### 2.6 의존성 방향

```
api/routes/chat.py
       ↓
rag_core/agentic.py  →  rag_core/tool_registry.py  ←  rag_core/tools/*.py
                                                          ↓
                                                  langchain_core.tools.BaseTool
```

`tool_registry` 는 어떤 RAG 클래스도 import 하지 않는다 (mode_registry 와 동일 원칙).

## 3. 변경 사항 단계 (커밋 단위)

### C1. tool_registry 골격 + 기존 도구 이전 (회귀 위험 낮음)

- 신규: `rag_core/tool_registry.py` (60~70 줄, mode_registry 동형)
- 신규: `rag_core/tools/__init__.py`, `rag_core/tools/search_documents.py` — 기존 클로저를 외부화
- 변경: `rag_core/agentic.py:237~267 _make_search_tool` 제거, line 225 `self._tools = all_tools()`
- 검증: 기존 Agentic 테스트 PASS (회귀 0건)
- 롤백: `git revert` 1 commit. registry 가 비면 빈 tools 로 동작 (Agentic 자체는 살아있음)

### C2. MCP 어댑터 (옵션, PRD 결정 후)

- 신규: `rag_core/tools/mcp_adapter.py`
- 의존성: `pyproject.toml` 에 `langchain-mcp-adapters` 추가
- 변경: `api/main.py` 또는 별도 `bootstrap.py` 에서 `register("mcp_search", lambda: load_mcp_tools(...))`
- 환경변수: `MCP_SERVERS=url1,url2` 같은 형태
- 검증: MCP 서버 mock + tool_call 1회 PASS

### C3. ChatRequest.attachments 스키마 (이미지 진입)

- 변경: `api/schemas.py:31` ChatRequest 에 `attachments` 필드 추가 (default_factory=list)
- 변경: `web/lib/api.ts:17 ChatRequest` 인터페이스 동기화
- 회귀: 기존 클라이언트는 빈 배열 전송 → 동일 동작
- 검증: 빈 배열로 sync/stream 모두 PASS

### C4. Vision 도구 또는 vision 모드 (PRD 결정 후)

- C4a (도구 옵션): `rag_core/tools/vision_describe.py` 등록
- C4b (모드 옵션): `rag_core/vision.py` + `mode_registry.register`
- 프론트: 파일 업로드 UI + `attachments` 채우기

### C5. Reasoning Trace Block

- 변경: `web/lib/blocks.ts:37` Block union 에 `tool_trace` 추가
- 변경: `web/lib/blocks.ts:111` messageToBlocks 에 추출 로직 1개
- 변경: `web/components/blockRenderers.tsx:38` RENDERERS 에 entry 1개
- 신규: `web/components/ToolTraceView.tsx` — 도구명 + args JSON 토글
- 검증: Agentic 모드 답변에 tool_trace 노출, 다른 모드에선 없음

## 4. 마이그레이션 전략

- 데이터: 스키마 변경 없음. SQLite audit_log 무영향.
- 코드 호환:
  - C1 은 내부 리팩토링 — 외부 인터페이스 (`AgenticRAG.query`) 무변동.
  - C3 은 Pydantic v2 default_factory 라 기존 요청 그대로 통과.
- 운영: 다운타임 0. C2 는 MCP 서버 부재 시 registry 가 fallback 으로 빈 결과 반환.

## 5. 검증 계획

### 5.1 단위 테스트 후보

```python
# tests/test_tool_registry.py
def test_register_and_get():
    register("dummy", lambda: dummy_tool)
    assert get("dummy") is dummy_tool

def test_all_tools_preserves_order():
    register("a", ...); register("b", ...)
    assert [t.name for t in all_tools()] == ["a", "b"]

# tests/test_agentic_uses_registry.py
def test_agentic_loads_tools_from_registry(reset_registry):
    register("search_documents", make_search_factory(hybrid))
    rag = AgenticRAG(hybrid_rag=hybrid)
    assert len(rag._tools) == 1
```

### 5.2 통합 / E2E

- 기존 `tests/test_agentic_rag.py` 회귀 PASS — `_make_search_tool` 제거에도 동작 동일해야 한다.
- 신규 E2E: `/chat/sync mode=agentic` 호출 → 응답 `metadata.tool_calls[0].tool == "search_documents"` PASS.

### 5.3 정량 지표

| 지표 | 목표 |
|---|---|
| 신규 도구 추가 시 변경 파일 수 | `tools/<name>.py` 신규 + bootstrap 1줄 = 2 파일 (현재 1+많음) |
| Agentic 모드 회귀 테스트 | 기존 N개 PASS 유지 |
| `agentic.py` 줄 수 | 현재 424 → C1 후 약 380 (≈10% 감소) |

## 6. 위험 / 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| MCP 서버 다운 시 Agentic 무한 대기 | 사용자 timeout | `recursion_limit` (이미 line 159) + per-tool timeout wrap |
| 이미지 첨부 → 토큰 폭증 | 비용 | Vision 호출 시 별도 token budget 분리 |
| `langchain-mcp-adapters` 라이브러리 정착 미흡 | 직접 구현 필요 | C2 를 옵셔널로 분리, 직접 구현 fallback 인터페이스 동일 |
| Tool registry 등록 순서 의존 | 테스트 격리 실패 | `reset()` 헬퍼 (mode_registry 의 line 57~59 패턴) |

## 7. 비-목표 / TRD 범위 외

- 여러 LLM provider 지원 (Anthropic/Gemini swap) — 별도 TRD
- 도구 권한 모델 (사용자별 도구 접근 제어) — TRD-002 인증 도입 후 추후
- 도구 결과 영속화 (audit_log 에 도구 호출 기록 컬럼 추가) — TRD-003 라우터 학습과 묶어 검토
- 이미지 OCR / PDF 파싱 — 도구 옵션 결정 후 별도
