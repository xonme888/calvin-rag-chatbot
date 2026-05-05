#!/bin/sh
# 컨테이너 entrypoint — 부팅 시 인덱스 fetch (저작권 자산 분리).
#
# HF_INDEX_REPO 가 설정돼 있고 로컬 캐시가 없으면 Private HF Dataset 에서 다운로드.
# 그 외엔 image 안에 미리 들어 있는 indexes/ 또는 첫 빌드(개발 환경) 사용.
#
# 환경변수:
#   HF_INDEX_REPO  (선택) — 인덱스가 들어 있는 Private Dataset repo id
#   HF_TOKEN       (선택) — HF read 토큰 (Private Dataset 접근)
#   PORT           (선택) — uvicorn 바인딩 포트 (기본 7860, HF Spaces 기본)

set -e

INDEX_TARGET="${INDEX_DIR:-/app/indexes}/calvin__chunk500__overlap50/index.faiss"

if [ -n "$HF_INDEX_REPO" ] && [ ! -f "$INDEX_TARGET" ]; then
    echo "[boot] 인덱스 fetch from HF Dataset: $HF_INDEX_REPO"
    python - <<PYEOF
import os
from huggingface_hub import snapshot_download

repo = os.environ["HF_INDEX_REPO"]
token = os.environ.get("HF_TOKEN")
local = os.environ.get("INDEX_DIR", "/app/indexes")

snapshot_download(
    repo_id=repo,
    repo_type="dataset",
    local_dir=local,
    token=token,
)
print(f"[boot] 인덱스 다운로드 완료: {local}")
PYEOF
elif [ -f "$INDEX_TARGET" ]; then
    echo "[boot] 로컬 인덱스 사용: $INDEX_TARGET"
else
    echo "[boot] 경고: 인덱스 없음 + HF_INDEX_REPO 미설정 — 첫 부팅 시 PDF 가 필요합니다."
fi

exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-7860}"
