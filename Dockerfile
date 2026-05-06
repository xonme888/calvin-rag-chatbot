# Calvin RAG Chatbot API — Hugging Face Spaces / Fly.io / Cloud Run 호환 Dockerfile
#
# 빌드: docker build -t calvin-api .
# 로컬 실행: docker run -p 7860:7860 --env-file .env calvin-api
#
# 인덱스 storage 분리:
#   - 책 본문 청크가 들어 있는 indexes/ 는 image 에 포함하지 않는다 (저작권 보호).
#   - 부팅 시 scripts/boot.sh 가 HF_INDEX_REPO (Private Dataset) 에서 fetch.
#   - 로컬 개발은 indexes/ 가 그대로 있어 fetch 없이 동작.
#   - rag_core/calvin_builder.py 가 has_cache(...) hit 시 PDF 로드를 스킵하므로
#     인덱스만 있으면 PDF 없이 부팅 가능.
#
# 포트:
#   - HF Spaces: 7860 (기본). app_port = 7860 (README.md frontmatter 에 명시)
#   - Fly.io: PORT 환경변수로 동적 주입 가능 — fallback 7860

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 시스템 의존성 — pymupdf 가 빌드 시 필요
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- 의존성 설치 (캐시 효율화) ----
COPY pyproject.toml ./
COPY README.md ./
RUN pip install --upgrade pip && \
    pip install -e ".[all]" || pip install -e .

# ---- 애플리케이션 코드 ----
COPY api ./api
COPY rag_core ./rag_core
COPY chatbot ./chatbot
COPY infra ./infra
COPY scripts ./scripts
COPY data/glossary ./data/glossary

# 인덱스/PDF 모두 image 에 포함하지 않는다.
# 인덱스: 부팅 시 scripts/boot.sh 가 HF Dataset 에서 fetch.
# PDF: 저작권상 image 미포함 (개발용 .env 에서 절대경로로만 주입).
RUN mkdir -p /app/indexes /app/data/calvin /root/.calvin-rag-chatbot

# ---- 헬스체크 ----
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-7860}/health/live || exit 1

# HF Spaces 기본 포트 7860. Fly.io 는 PORT 를 동적으로 주입한다.
EXPOSE 7860

# ---- 엔트리포인트 ----
# scripts/boot.sh: 인덱스 fetch (선택) → uvicorn exec
CMD ["/bin/sh", "/app/scripts/boot.sh"]
