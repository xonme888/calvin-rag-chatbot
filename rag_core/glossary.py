"""도메인 용어집 — 답변 안 핵심 용어 inline tooltip 의 진리값.

목적: LLM 이 매번 다르게 정의할 위험을 방지. 핵심 신학 용어는 정적 사전에서
직접 lookup → 환각 0 + 정의 일관성.

설계:
- ``data/glossary/calvin.json`` 이 단일 소스
- ``find_terms_in(text)`` 가 답변 본문에서 매칭 발견 (등장 순서 보존, 중복 제거)
- 매칭은 term + aliases 모두 시도, 한국어 어미 변화는 단순 substring (보수적)
- API 응답 ``metadata.matched_terms`` 로 프론트에 동봉
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TermSource:
    page: int
    label: str


@dataclass(frozen=True)
class GlossaryTerm:
    term: str
    aliases: tuple[str, ...]
    definition: str
    sources: tuple[TermSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "aliases": list(self.aliases),
            "definition": self.definition,
            "sources": [{"page": s.page, "label": s.label} for s in self.sources],
        }


_GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "data" / "glossary" / "calvin.json"


@lru_cache(maxsize=1)
def load_glossary() -> tuple[GlossaryTerm, ...]:
    """JSON 파일을 한 번만 로드. 파일 없으면 빈 튜플."""
    try:
        if not _GLOSSARY_PATH.exists():
            logger.warning("glossary 파일 없음: %s — 빈 사전 사용", _GLOSSARY_PATH)
            return ()
        raw = json.loads(_GLOSSARY_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("glossary 로드 실패 — 빈 사전 사용: %s", e)
        return ()

    out: list[GlossaryTerm] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        aliases = tuple(
            str(a).strip() for a in entry.get("aliases", []) if str(a).strip()
        )
        definition = str(entry.get("definition", "")).strip()
        sources = tuple(
            TermSource(page=int(s.get("page", 0)), label=str(s.get("label", "")))
            for s in entry.get("sources", [])
            if isinstance(s, dict) and s.get("page") is not None
        )
        out.append(
            GlossaryTerm(term=term, aliases=aliases, definition=definition, sources=sources)
        )
    return tuple(out)


def all_terms() -> list[dict[str, Any]]:
    """전체 글로서리 — /glossary 엔드포인트용."""
    return [t.to_dict() for t in load_glossary()]


def find_terms_in(text: str) -> list[dict[str, Any]]:
    """답변 본문에서 글로서리 용어 매칭 — 등장 순서 보존, 중복 제거.

    매칭 우선순위:
    1. term 자체
    2. aliases 중 첫 매칭

    한국어 조사·어미 변화는 substring 매칭으로 흡수 (예: "예정론은" 에서 "예정론" 매칭).
    영문 alias 는 단어 경계는 무시 — 보수적 (false positive 가 일부 있어도 OK,
    답변 안에서 등장한 단어이므로 의미는 통상 같음).
    """
    if not text:
        return []
    terms = load_glossary()
    if not terms:
        return []

    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in terms:
        candidates = (entry.term, *entry.aliases)
        for c in candidates:
            if c and c in text:
                if entry.term not in seen:
                    matched.append(entry.to_dict())
                    seen.add(entry.term)
                break
    return matched


def reset_cache() -> None:
    """테스트용 — 글로서리 재로드."""
    load_glossary.cache_clear()
