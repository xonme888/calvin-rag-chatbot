# Calvin RAG Chatbot API — Fly.io / Cloud Run 호환 Dockerfile
#
# 빌드: docker build -t calvin-api .
# 로컬 실행: docker run -p 8000:8000 --env-file .env calvin-api
#
# 인덱스 캐시 (~50MB FAISS) 는 이미지에 포함하지 않고 첫 부팅 시 PDF 에서 빌드.
# 또는 빌드 시점에 PDF 를 image 에 ADD 한 뒤 entrypoint 가 인덱싱 후 시작 (권장).

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
COPY infra ./infra
COPY scripts ./scripts
COPY data/glossary ./data/glossary

# 칼빈 PDF — 저작권으로 git 무추적. 배포 시 별도 mount 또는 빌드 시 ADD.
# 운영: fly.toml volume 또는 Cloud Run Cloud Storage mount.
# 환경변수 CALVIN_PDF_PATH 로 위치 지정.
RUN mkdir -p /app/data/calvin /app/indexes /root/.calvin-rag-chatbot

# ---- 헬스체크 ----
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

EXPOSE 8000

# ---- 엔트리포인트 ----
# Fly.io 는 PORT 를 동적으로 주입할 수 있음 — fallback 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
