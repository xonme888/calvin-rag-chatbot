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
    """칼빈 PDF 경로를 결정한다 — 매 호출 환경변수 재읽기.

    우선순위:
        1. 환경변수 ``CALVIN_PDF_PATH``
        2. 이 repo의 ``data/calvin/calvin_institutes.pdf`` (fallback)

    .env 파싱 잔존 문자 (따옴표·공백·CR) 제거 + ~ 확장.
    """
    # macOS 에디터/터미널 복붙 시 흔한 보이지 않는 문자 모두 제거:
    # NBSP (U+00A0), ZWSP (U+200B), BOM (U+FEFF), 일반 공백/탭/CR/LF/따옴표
    env_path = os.getenv("CALVIN_PDF_PATH", "").strip(
        " \t\r\n\"' ​﻿"
    )
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DATA_DIR / "calvin" / "calvin_institutes.pdf"


# 하위 호환 — 일부 모듈이 import 시점 값으로 참조 가능. load_calvin 은 매번 재해석.
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
    매 호출 환경변수 재읽기 — .env 변경 즉시 반영.

    Returns:
        페이지 단위 Document 리스트 (길이 ≈ 1,251)

    Raises:
        FileNotFoundError: PDF 파일이 없을 때 — 부모 디렉토리 listing 포함
    """
    path = _resolve_calvin_pdf_path()
    if not path.exists():
        # 진단 — 부모 디렉토리에 어떤 파일이 있는지 노출
        parent = path.parent
        listing = "(부모 디렉토리도 없음)"
        if parent.exists():
            entries = sorted(p.name for p in parent.iterdir())[:20]
            listing = "\n  - " + "\n  - ".join(entries) if entries else "(비어있음)"
        raise FileNotFoundError(
            f"칼빈 강요 PDF가 없습니다.\n"
            f"  resolved={path}\n"
            f"  raw env={os.getenv('CALVIN_PDF_PATH', '<unset>')!r}\n"
            f"  parent={parent} 내용:{listing}\n"
            f".env의 CALVIN_PDF_PATH 값에 따옴표/공백이 있거나 경로가 다른지 확인하세요."
        )
    return load_pdf(path)
