"""FastAPI 앱 entry point.

실행:
    uvicorn api.main:app --reload --port 8000

라우트:
- GET  /health     — 헬스 체크
- GET  /modes      — 사용 가능 모드 목록
- GET  /stats      — 누적 사용 통계 (`infra/usage_tracker` 활용)
- POST /chat/sync  — 동기 응답 (JSON, 디버깅/Phase B 가드 풀패스)
- POST /chat/stream — SSE 스트리밍 (Vercel AI SDK Stream Protocol v1 호환)

Step 1 단계에선 ``/health`` 만 구현. 나머지는 Step 2 에서 추가.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트 sys.path 보강 (uvicorn 직접 실행 시)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.middleware.rate_limiter import limiter
from api.routes import chat, health, invite, stats, title

app = FastAPI(
    title="Calvin RAG Chatbot API",
    description="칼빈 강요 RAG 챗봇 — Hybrid / Agentic / Knowledge Graph 3 모드",
    version="0.1.0",
)

# CORS — Next.js 프론트 (Vercel preview 포함) 와 통신
# 운영 단계에선 Cloudflare Access JWT (Phase 2 Step 5) 가 외곽 인증, CORS 는 origin 만 제한
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO Step 5: 운영 도메인만
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Rate limiter — IP 단위 (env: RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_DAY)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_exceeded_handler(request, exc):  # type: ignore[no-untyped-def]
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


app.include_router(health.router)
app.include_router(stats.router)
app.include_router(chat.router)
app.include_router(title.router)
app.include_router(invite.router)
