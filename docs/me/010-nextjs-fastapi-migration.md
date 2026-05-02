# 010. Next.js + FastAPI + SSE 마이그레이션 계획

## 상황
사용자: "API + 스트리밍이 산업 표준 아닌가? Next.js 프론트로 가야 하지 않나?"

별도 에이전트 산업 조사 결과(2025~2026) — **사용자 추정 정확**. ChatGPT/Claude/Perplexity/뤼튼/라이너 모두 **Next.js 프론트 + Python 백엔드(FastAPI 계열) + SSE 스트리밍** 동일 골격.

현재 시스템(Streamlit)은 프로토타이핑/내부 도구 표준이며 *실 운영에는 분리 프론트/백이 산업 정합*. 우리는 **인터넷 공개 운영을 목표** (`docs/me/009`)이므로 마이그레이션이 옳은 방향.

## 현재 상태 (출발점)
- Streamlit 챗봇 (메인 + 비교 페이지, 멀티페이지)
- 3 모드 (Hybrid / Agentic / Knowledge Graph)
- Hexagonal Port/Adapter — `RetrieverPort` / `KnowledgeGraphPort` / `GuardrailPort`
- 관측성 — `infra/usage_tracker.py` (LangChain 콜백)
- 가드 Phase A 완료 — Length/Keyword/OpenAI Moderation
- 누적 단위 테스트 123/123 PASS (LLM/네트워크 호출 0회)
- 외부 학습 코드 무의존, `rag_core/` + `infra/` 자체 완결

→ **Hexagonal 분리 덕에 마이그레이션 비용 낮음**. `rag_core/` + `infra/`를 FastAPI에 *그대로 마운트* 가능.

## 산업 표준 검증

| 시스템 | 프론트 | 백엔드 | 스트리밍 | 인증 |
|---|---|---|---|---|
| ChatGPT (OpenAI) | Next.js (App Router) | Python | SSE | Edge + 자체 |
| Claude.ai | Next.js + React | Python | SSE | OAuth + JWT |
| Perplexity | React/Next.js | Python (Sonar 라우팅) | SSE | API key + 세션 |
| Cursor | Electron(React) | Node + Python 마이크로서비스 | SSE | 자체 토큰 |
| 뤼튼 (Wrtn) | Next.js (한국어 카카오톡) | 자체 모델 서버 | SSE 추정 | 자체 OAuth |
| 라이너 (Liner) | Next.js | Python AI 백엔드 | SSE 추정 | 자체 토큰 |

WebSocket은 음성/멀티모달 보조 채널이며 **텍스트 챗봇의 1차 채널은 SSE**. gRPC는 내부 마이크로서비스용이며 클라이언트 직결은 드뭄.

## 마이그레이션 목적

1. **운영 안전 — Hybrid 모드 가드 한계 해소**: Streamlit `st.write_stream`이 화면에 토큰 흘려놓은 후 가드 적용 (cosmetic 한계). API 분리 시 가드 → 응답 흐름 깔끔
2. **Phase B 가드 정착 위치** — Cloudflare WAF, rate limit, audit log를 FastAPI 단에 미들웨어로 자연 정착 (`docs/me/009`)
3. **산업 표준 정합** — 면접 시연에서 "운영 URL" 임팩트
4. **Hexagonal 자산 활용 검증** — Port/Adapter 추상화가 *마이그레이션 비용 0*으로 빛나는 시점

## 자바 개발자 ↔ Python/Next.js 1:1 매핑 (면접 어필)

| Spring (Java) | LLM 챗봇 | 비고 |
|---|---|---|
| `@RestController` + `@PostMapping` | FastAPI `@router.post("/chat/sync")` | 1:1. Pydantic = DTO + Bean Validation |
| `WebFlux Flux<String>` (`stream()`) | FastAPI `StreamingResponse` / async generator | Reactor backpressure ↔ `astream` chunk yield |
| `ServerSentEvent<T>` | `EventSourceResponse` (sse-starlette) | Spring `MediaType.TEXT_EVENT_STREAM_VALUE` |
| **Spring AI `Advisor` 체인** | **Hexagonal `GuardrailPort` 체인 + `mode_dispatcher`** | 프롬프트 전후 hook 1:1 |
| `ChatClient.prompt().user().stream()` | `chain.astream(question)` | Fluent API ↔ LCEL |
| Spring Security `SecurityFilterChain` | Cloudflare Access JWT + `Depends(verify_jwt)` | filter chain ↔ DI |
| `@Async` + `BackgroundJobManager` | FastAPI `BackgroundTasks` | audit log 비동기 |
| Micrometer + Actuator | `usage_tracker` 콜백 + `/health`, `/stats` | 관측성 |

**면접 한 줄**: "Hexagonal Port/Adapter 로 가드/RAG 코어를 추상화하고 FastAPI async generator + SSE 로 스트리밍을 구현했습니다. 자바 관점에서 보면 `GuardrailPort` 체인은 Spring AI Advisor 체인과, async generator + SSE 는 WebFlux `Flux<ServerSentEvent>` 와 같은 역할입니다 — 패턴 *비교* 차원이고 Spring AI 코드를 옮긴 것은 아닙니다."

## 마이그레이션 단계 (~6일)

전제: 모노레포 — 단일 repo 안에 `api/` + `web/` (별도 repo는 CI/배포 동기화 비용 ↑)

| 일차 | Step | 작업 | 산출물 | 리스크 |
|---|---|---|---|---|
| **D+1 오전** | 1 | 모노레포 폴더 (`api/`, `web/`), FastAPI 골격, `pyproject.toml` 분리 (api/web 의존성 격리) | 빈 FastAPI 앱 booting | 낮음 |
| **D+1 오후 ~ D+2** | 2 | 엔드포인트 — `POST /chat/stream` (SSE, `x-vercel-ai-ui-message-stream: v1`), `POST /chat/sync`, `GET /health`, `GET /stats`, `GET /modes`. Pydantic v2 모델 | curl로 SSE 검증 통과 | 중 — `mode_dispatcher` ThreadPool → `run_in_executor` 래핑 |
| **D+3** | 3 | 가드/관측성/audit 이전 — `GuardrailPort` → `Depends`, `usage_tracker` → middleware, 신규 `infra/audit_log` → `BackgroundTasks` | 가드 동작 + audit log 기록 | 중 — 출력 가드 stream chunked vs sync 모드만 결정 |
| **D+4 ~ D+5** | 4 | Next.js App Router + Vercel AI SDK `useChat` + 모드 셀렉터 + 출처 카드 + Tailwind | localhost:3000 동작 | 낮음 — 표준 패턴 |
| **D+6 오전** | 5 | Cloudflare Access (이메일 OTP) + FastAPI `Cf-Access-Jwt-Assertion` 검증 미들웨어 | 인증된 요청만 통과 | 낮음 — CF 공식 패키지 |
| **D+6 오후 ~ D+7** | 6 | 배포 — Next.js → Vercel (무료), FastAPI → Cloud Run (asia-northeast1) 또는 Fly.io NRT, 도메인 연결 | 운영 URL 동작 | 중 — Cloud Run SSE는 `--cpu-boost` + timeout 60분 설정 |

**위험 분산**: D+3 시점에 Streamlit이 같은 FastAPI를 호출하도록 *thin client*로 전환 (+0.5d). 시연 시점에 Streamlit + Next.js 둘 다 살아 있어 어느 쪽이 죽어도 다른 쪽으로 전환 가능. D+8 이후 Streamlit 폐기.

## 가드/관측성 위치 변화

| 항목 | 현재 (Streamlit) | FastAPI 후 |
|---|---|---|
| **입력 가드** (Length/Keyword/Moderation) | 페이지 함수 직접 호출 | FastAPI `Depends(InputGuardrailChain)` — 라우트 진입 즉시 검증, 차단 시 `HTTPException(400)` |
| **출력 가드** | 응답 후 검사 | (a) **stream 도중 chunked guard** (UX 좋음, 복잡) / (b) **sync 모드만 가드 + stream은 cheap check + 후처리 audit** ★ |
| **Audit log** | `infra/audit_log` 동기 호출 | `BackgroundTasks` 비동기 — stream 종료 후 final_answer + sources + token cost 기록 |
| **Rate limit** | 없음 | **Cloudflare WAF rate limiting rules** (per-IP 분당 N회) + FastAPI `slowapi` (per-user 일일 token 한도) — 2단 |
| **Token budget cap** | 없음 | FastAPI middleware가 사용자별 누적치 체크 후 차단 (`infra/usage_tracker` 활용) |
| **관측성** | LangChain BaseCallbackHandler (in-process) | 동일 — FastAPI 프로세스 안에 그대로. OpenTelemetry export는 선택 |

→ **Phase B 5층 방어가 마이그레이션과 함께 자연 정착**. Streamlit에서 만들 이유 없음.

## 시연 일정 양립 — 하이브리드 권장 경로

```
Phase 0 (오늘):   docs/me/010 박제 — 1h
                       ↓
Phase 1 (시연일까지):  Streamlit 안정화 + 시연 데이터셋 다듬기 + (선택) KG --full 인덱싱
                       ↓
Phase 2 (시연 후 6일): FastAPI + Next.js 마이그레이션 (위 6 Step)
                       │
                       │  ← D+3에 Streamlit이 FastAPI thin client로 전환 (위험 분산)
                       │  ← D+7 Vercel + Cloud Run 배포
                       ↓
Phase 3 (D+8 이후):    Phase B 가드 마무리 + Streamlit 폐기 + 운영 공개
                       │
                       │  ← Cloudflare WAF rule, Token budget cap, OpenAI hard limit
                       │  ← 모니터링 dashboard (Audit log SQL 뷰)
                       ↓
                    운영 URL (https://...)
```

**근거**: 시연 당일 SSE 끊김은 치명적 → 같은 FastAPI를 두 프론트가 보는 구조로 위험 분산. 면접에서 "이 시스템은 D+8부터 운영됩니다"가 가장 강한 어필.

## 구현 세부 — 핵심 패턴 메모

### Vercel AI SDK + FastAPI Stream Protocol
- `x-vercel-ai-ui-message-stream: v1` 헤더 필수
- 포맷: `data: {"type":"text-delta","delta":"..."}\n\n` ... `data: [DONE]`
- `useChat({ api: "/chat/stream" })` Hook 한 줄로 클라이언트 연동
- 공식 템플릿: vercel-labs/ai-sdk-preview-python-streaming

### FastAPI SSE
```python
from sse_starlette import EventSourceResponse

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, ...):
    async def gen():
        async for chunk in pipeline.astream_events(req.question, version="v2"):
            yield {"event": "message", "data": json.dumps({"type": "text-delta", "delta": chunk})}
        yield {"event": "done", "data": "[DONE]"}
    return EventSourceResponse(gen(), headers={"X-Accel-Buffering": "no"})
```

### LangGraph stream → SSE
```python
async for chunk in graph.astream(state, stream_mode=["updates", "custom", "messages"]):
    # updates: 노드 진행상태 / messages: 토큰 / custom: 우리 메타
    ...
```

### Cloudflare Access + FastAPI 검증
```python
from fastapi import Depends, Header, HTTPException

async def verify_cf_jwt(cf_jwt: str = Header(alias="Cf-Access-Jwt-Assertion")):
    # CF 공식 라이브러리로 JWKS 검증
    ...

@router.post("/chat/stream", dependencies=[Depends(verify_cf_jwt)])
```

## 위험 분산 — 하이브리드 패턴 (D+3 ~ D+7)

```
사용자 → [Cloudflare Access] → FastAPI
                                  │
                  ┌───────────────┴───────────────┐
                  │                               │
            Streamlit thin client          Next.js + Vercel AI SDK
                  │                               │
                  │  (D+3 부터 동시 동작)          │
                  │                               │
                  └─────── 시연 시 사용 ──────────┘
                                  │
                                  ↓
                          D+8: Streamlit 폐기
```

근거 자료: [Streamlit + FastAPI 2-tier RAG 사례](https://prepvector.substack.com/p/deploying-a-two-tier-rag-chatbot)

## 면접 어필 내러티브

> "RAG 시스템을 Streamlit 단일 프로세스에서 시작했지만, *인터넷 공개 운영을 목표*로 두면 산업 표준은 분리 프론트/백입니다.
>
> ChatGPT, Claude, Perplexity 모두 **Next.js + Python(FastAPI 계열) + SSE** 골격을 채택하고, 한국 운영사(뤼튼, 라이너)도 동일 패턴입니다.
>
> 그래서 6일 마이그레이션 계획을 박제했습니다. 핵심은 **이미 도입한 Hexagonal Port/Adapter (`RetrieverPort`/`KnowledgeGraphPort`/`GuardrailPort`)가 마이그레이션 비용을 0에 가깝게 만든다는 점**입니다. RAG 코어는 그대로 import해 FastAPI 라우트에 마운트하고, Streamlit은 시연일까지 thin client로 위험 분산용으로 살려둔 뒤 폐기합니다.
>
> Hexagonal Port/Adapter 로 가드/RAG 코어를 추상화하고 FastAPI async generator + SSE 로 스트리밍을 구현했습니다. 자바 관점에서 매핑하면 `GuardrailPort` 체인은 Spring AI Advisor 체인과, async generator 는 WebFlux `Flux` 와, Cloudflare Access JWT 검증은 Spring Security `SecurityFilterChain` 과 같은 역할입니다 — *패턴 비교* 차원이고 Spring AI 코드를 옮긴 것은 아닙니다."

## 검증 체크리스트 (Phase 2 완료 시점)

| 항목 | 검증 방법 |
|---|---|
| FastAPI 엔드포인트 5개 정상 | `curl /health`, `curl /chat/sync -d '...'`, `curl /chat/stream -N` |
| SSE 토큰 단위 도착 | EventSource로 chunk 시간 차 확인 |
| 가드 미들웨어 동작 | 2,000자 초과 입력 → 400, 시스템 프롬프트 leak → block |
| Audit log 비동기 기록 | `BackgroundTasks` 후 SQLite 조회 |
| Cloudflare Access JWT | 인증 없는 직접 호출 → 401 |
| Next.js useChat | `localhost:3000` 모드 토글 + 출처 카드 + 토큰 스트림 |
| 회귀 테스트 | Streamlit과 Next.js가 같은 질문에 동일 final_answer |
| 단위 테스트 | FastAPI 엔드포인트 httpx + pytest, 가드 미들웨어 |

## 의존성 — 신규 추가 예상

```toml
# api/pyproject.toml (신규 분리 또는 [project.optional-dependencies] 그룹)
fastapi = ">=0.115"
uvicorn = {version = ">=0.30", extras = ["standard"]}
sse-starlette = ">=2.0"
slowapi = ">=0.1.9"      # rate limiting
pyjwt = ">=2.8"          # CF Access JWT 검증
httpx = ">=0.27"         # CF JWKS fetch
pytest-asyncio = ">=0.23"
```

```json
// web/package.json (신규)
{
  "dependencies": {
    "next": "^15",
    "react": "^19",
    "ai": "^4",
    "@ai-sdk/react": "^1",
    "tailwindcss": "^3"
  }
}
```

## 핵심 출처
- [AI SDK UI: Stream Protocol](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)
- [AI SDK Python Streaming Template](https://vercel.com/templates/next.js/ai-sdk-python-streaming)
- [Streaming AI Agent with FastAPI & LangGraph (2025-26)](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn)
- [Cloudflare Access + FastAPI 공식 튜토리얼](https://developers.cloudflare.com/cloudflare-one/tutorials/fastapi/)
- [Spring AI Advisors API](https://docs.spring.io/spring-ai/reference/api/advisors.html)
- [sse-starlette](https://github.com/sysid/sse-starlette)
- [FastAPI 공식 SSE 가이드](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [Streamlit + FastAPI 2-tier RAG 사례](https://prepvector.substack.com/p/deploying-a-two-tier-rag-chatbot)

## 미래 작업 시 컨텍스트 전달

이 문서가 **Phase 2/3 작업의 단일 진실 원천**. 향후 별도 에이전트에게 마이그레이션 세부 작업을 위임할 때:
- 이 문서를 컨텍스트로 *명시 전달* (이전 사례: 환경 가정 잘못 잡으면 결론 왜곡됨)
- 또는 본 repo에서 직접 처리 — 컨텍스트 누락 위험 0
- 컨텍스트 없이 던지지 않는다 (사용자 명시 학습)
