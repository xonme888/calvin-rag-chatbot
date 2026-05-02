"""환경변수 로더.

프로젝트 루트의 .env 파일을 자동으로 찾아 로드한다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def find_root_env() -> Path | None:
    """현재 파일 위치에서 상위로 올라가며 .env 파일을 찾는다.

    Returns:
        .env 파일 경로 또는 None
    """
    current = Path(__file__).resolve().parent

    # 최대 5단계 상위까지 검색
    for _ in range(5):
        env_file = current / ".env"
        if env_file.exists():
            return env_file

        # pyproject.toml이 있는 디렉토리를 루트로 간주
        if (current / "pyproject.toml").exists():
            candidate = current / ".env"
            return candidate if candidate.exists() else None

        parent = current.parent
        if parent == current:  # 파일시스템 루트 도달
            break
        current = parent

    return None


def load_env() -> bool:
    """루트 .env 파일을 로드한다.

    Returns:
        OPENAI_API_KEY가 유효하게 설정되었는지 여부
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and api_key != "sk-your-key-here":
        return True

    env_file = find_root_env()
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "")
    return bool(api_key) and api_key != "sk-your-key-here"


def get_required(key: str) -> str:
    """필수 환경변수를 가져온다. 없으면 ValueError.

    Args:
        key: 환경변수 키

    Returns:
        환경변수 값

    Raises:
        ValueError: 환경변수가 설정되지 않은 경우
    """
    value = os.getenv(key)
    if not value:
        raise ValueError(f"필수 환경변수 '{key}'가 설정되지 않았습니다. .env 파일을 확인하세요.")
    return value
