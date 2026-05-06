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

# .env 로드 — Pydantic Settings 외 모듈 (infra.invite_codes 등 os.getenv 사용) 도 읽도록
# import 이전에 호출해야 환경변수가 모듈 import 시점부터 보인다.
try:
    from dotenv import load_dotenv

    _env_path = _PROJECT_ROOT / ".env"
    _loaded = load_dotenv(_env_path, override=True)
    # 시연 디버그 — INVITE_CODES 활성 상태를 부팅 로그에서 즉시 확인 가능 (마스킹)
    import os as _os

    _invite_raw = _os.getenv("INVITE_CODES", "").strip()
    _invite_count = len([c for c in _invite_raw.split(",") if c.strip()])
    _calvin_path_raw = _os.getenv("CALVIN_PDF_PATH", "<unset>")
    # PDF 실제 존재 여부도 같이 진단 — uvicorn 콘솔만 봐도 즉시 식별
    _calvin_exists: bool | str = "<unset>"
    try:
        from infra.document_loader import _resolve_calvin_pdf_path

        _resolved = _resolve_calvin_pdf_path()
        _calvin_exists = f"{_resolved} exists={_resolved.exists()}"
    except Exception as _e:
        _calvin_exists = f"resolve error: {_e}"
    print(
        f"[boot] .env loaded={_loaded} from={_env_path}\n"
        f"  INVITE_CODES count={_invite_count}\n"
        f"  CALVIN_PDF_PATH raw={_calvin_path_raw!r}\n"
        f"  resolved={_calvin_exists}",
        flush=True,
    )
except ImportError:
    pass  # python-dotenv 미설치 시 스킵 — 운영 환경에선 OS env 가 직접 주입

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.middleware.rate_limiter import limiter
from api.routes import chat, chat_v2, glossary, health, invite, stats, title

app = FastAPI(
    title="Calvin RAG Chatbot API",
    description="칼빈 강요 RAG 챗봇 — Hybrid / Agentic / Knowledge Graph 3 모드",
    version="0.1.0",
)

# CORS — Next.js 프론트 (Vercel preview 포함) 와 통신
# 환경변수 CORS_ORIGINS (콤마 구분) 으로 좁힘. 미설정 시 개발 모드 와일드카드.
# 운영 시 예: CORS_ORIGINS=https://chat.example.com,https://chat-staging.example.com
import os as _cors_os

_cors_raw = _cors_os.getenv("CORS_ORIGINS", "").strip()
if _cors_raw:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _cors_credentials = True
else:
    # 개발 모드 — 와일드카드 (credentials False — 브라우저가 wildcard+credentials 거부)
    _cors_origins = ["*"]
    _cors_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
print(
    f"[boot] CORS allow_origins={_cors_origins} credentials={_cors_credentials}",
    flush=True,
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
app.include_router(chat_v2.router)
app.include_router(title.router)
app.include_router(invite.router)
app.include_router(glossary.router)


# ---- 부팅 시 chat_v2 orchestrator 사전 빌드 ----
# lru_cache 라 첫 /chat/v2 호출 시까지 lazy 인데, 그러면 KG/Agentic 등록 로그가
# 부팅 단계가 아니라 *첫 요청 응답 후* 에야 보여 진단이 어렵다. 부팅 직후 1회 호출로
# 등록 결과 (KG nodes / Agentic / Vision) 를 즉시 stdout 에 노출.
@app.on_event("startup")
async def _prebuild_chat_v2_orchestrator() -> None:
    try:
        chat_v2._orchestrator()
    except Exception as e:  # noqa: BLE001 — 부팅은 막지 않는다
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "chat_v2 orchestrator prebuild failed: %s: %s", type(e).__name__, e
        )
