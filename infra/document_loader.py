"""문서 로더.

PDF/텍스트 파일을 langchain Document 리스트로 로드한다.

칼빈 강요 PDF 경로는 환경변수 ``CALVIN_PDF_PATH``로 override 가능.
미설정 시 이 repo의 ``data/calvin/calvin_institutes.pdf``를 사용.
학습 repo(rag-study-tracks)와 PDF를 공유하려면 환경변수에 절대경로 지정.
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.documents import Document

# 프로젝트 루트 (calvin-rag-chatbot/) 기준 데이터 경로 fallback
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _resolve_calvin_pdf_path() -> Path:
    """칼빈 PDF 경로를 결정한다.

    우선순위:
        1. 환경변수 ``CALVIN_PDF_PATH``
        2. 이 repo의 ``data/calvin/calvin_institutes.pdf`` (fallback)
    """
    env_path = os.getenv("CALVIN_PDF_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return DATA_DIR / "calvin" / "calvin_institutes.pdf"


# 모듈 레벨 상수: import 시점에 한 번 결정
CALVIN_PDF_PATH = _resolve_calvin_pdf_path()


def load_text_file(file_path: str | Path) -> list[Document]:
    """단일 텍스트 파일을 Document 리스트로 로드한다.

    Args:
        file_path: 텍스트 파일 경로

    Returns:
        Document 리스트 (길이 1)

    Raises:
        FileNotFoundError: 파일이 없을 때
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    content = path.read_text(encoding="utf-8")
    return [
        Document(
            page_content=content,
            metadata={"source": str(path), "filename": path.name},
        )
    ]


def load_pdf(file_path: str | Path) -> list[Document]:
    """PDF를 페이지 단위 Document 리스트로 로드한다.

    PyMuPDFLoader는 한국어 PDF 추출 품질이 PyPDFLoader보다 낫다.
    각 Document의 metadata에 0-indexed page 번호가 포함된다.

    Args:
        file_path: PDF 파일 경로

    Returns:
        페이지마다 Document 1개씩

    Raises:
        FileNotFoundError: 파일이 없을 때
        ImportError: pymupdf 미설치 시
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF를 찾을 수 없습니다: {path}")

    try:
        from langchain_community.document_loaders import PyMuPDFLoader
    except ImportError as e:
        raise ImportError(
            "pymupdf가 설치되지 않았습니다. uv pip install -e . 로 설치하세요."
        ) from e

    loader = PyMuPDFLoader(str(path))
    docs = loader.load()

    for d in docs:
        d.metadata.setdefault("source", str(path))
        d.metadata.setdefault("filename", path.name)

    return docs


def load_calvin() -> list[Document]:
    """기독교 강요 PDF를 로드한다.

    경로는 ``CALVIN_PDF_PATH`` 환경변수 우선, 미설정 시 이 repo의 ``data/`` fallback.
    저작권 보호를 위해 PDF 폴더는 .gitignore 에 등록되어 있음.

    Returns:
        페이지 단위 Document 리스트 (길이 ≈ 1,251)

    Raises:
        FileNotFoundError: PDF 파일이 없을 때
    """
    if not CALVIN_PDF_PATH.exists():
        raise FileNotFoundError(
            f"칼빈 강요 PDF가 없습니다: {CALVIN_PDF_PATH}\n"
            f".env의 CALVIN_PDF_PATH를 확인하거나 위 경로에 PDF를 두세요."
        )
    return load_pdf(CALVIN_PDF_PATH)
