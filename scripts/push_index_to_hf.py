"""로컬 FAISS 인덱스를 Private HF Dataset 으로 push.

저작권 보호: 칼빈 강요 본문 청크가 들어 있는 인덱스는 Public 노출 불가.
Private HF Dataset 에 보관하고, 배포된 HF Space 가 부팅 시 토큰으로 fetch.

사용:
    export HF_TOKEN=hf_xxxxxxxxx
    export HF_INDEX_REPO=<user>/calvin-rag-indexes
    python scripts/push_index_to_hf.py

또는 직접 인자로:
    python scripts/push_index_to_hf.py --repo <user>/calvin-rag-indexes --token hf_xxx

첫 실행 시 Dataset repo 가 없으면 자동으로 Private 으로 생성한다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.utils import HfHubHTTPError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_DIR = PROJECT_ROOT / "indexes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="인덱스 → Private HF Dataset")
    parser.add_argument(
        "--repo",
        default=os.environ.get("HF_INDEX_REPO"),
        help='Dataset repo id (예: "username/calvin-rag-indexes")',
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN"),
        help="HF write 토큰 (환경변수 HF_TOKEN 으로도 가능)",
    )
    parser.add_argument(
        "--index-dir",
        default=str(DEFAULT_INDEX_DIR),
        help=f"로컬 인덱스 디렉토리 (기본: {DEFAULT_INDEX_DIR})",
    )
    parser.add_argument(
        "--commit-message",
        default="update calvin index",
        help="커밋 메시지",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.repo:
        print("ERROR: --repo 또는 HF_INDEX_REPO 환경변수 필요", file=sys.stderr)
        print('예: --repo "username/calvin-rag-indexes"', file=sys.stderr)
        return 2
    if not args.token:
        print("ERROR: --token 또는 HF_TOKEN 환경변수 필요", file=sys.stderr)
        return 2

    index_dir = Path(args.index_dir).expanduser().resolve()
    if not index_dir.exists() or not any(index_dir.iterdir()):
        print(f"ERROR: 인덱스 디렉토리가 비어 있음: {index_dir}", file=sys.stderr)
        print("먼저 로컬에서 인덱싱을 실행하세요:", file=sys.stderr)
        print(
            '  python -c "from rag_core.calvin_builder import build_calvin_rag; build_calvin_rag()"',
            file=sys.stderr,
        )
        return 2

    api = HfApi(token=args.token)

    # Dataset repo 존재 확인 — 없으면 Private 으로 생성
    try:
        api.repo_info(repo_id=args.repo, repo_type="dataset")
        print(f"기존 Dataset repo 사용: {args.repo}")
    except HfHubHTTPError:
        print(f"Dataset repo 신규 생성 (Private): {args.repo}")
        api.create_repo(
            repo_id=args.repo,
            repo_type="dataset",
            private=True,
            exist_ok=True,
        )

    # 업로드
    print(f"업로드 시작: {index_dir} → {args.repo}")
    api.upload_folder(
        folder_path=str(index_dir),
        repo_id=args.repo,
        repo_type="dataset",
        commit_message=args.commit_message,
    )
    print(f"완료. https://huggingface.co/datasets/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
