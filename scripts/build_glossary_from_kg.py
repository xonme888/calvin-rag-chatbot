"""KG → 글로서리 export — D 마이그레이션의 핵심.

설계 (audit-agent 권장 a/a-분리/a/a 조합):
- KG 노드 (LLMGraphTransformer 추출, description property 보유) 가 진리값
- 기존 curated 항목 (사용자 수동 검수) 은 보존 — source 메타로 구분
- aliases: entity_normalizer.ENTITY_ALIASES 사전 reverse lookup (정적)
- 같은 term 이면 curated 우선 (충돌 시 사용자 검수 보호)
- KG 만 있는 항목은 source="kg" 로 추가

흐름:
1. KG 어댑터에서 :Person, :Concept, :Doctrine, :Event 노드 + description fetch
2. 각 노드의 출처 페이지 (Document 노드의 page property) 매핑
3. ALIAS 사전에서 reverse lookup (영문/이형 → 한글 또는 반대)
4. 기존 curated 와 term 키로 union (curated 우선, KG 만 있는 건 추가)
5. data/glossary/calvin.json 출력

사용:
    python scripts/build_glossary_from_kg.py [--out PATH] [--no-merge]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


_DEFAULT_OUT = _PROJECT_ROOT / "data" / "glossary" / "calvin.json"


# 너무 일반적인 신학 어휘 — glossary 부적합 (사용자 답변에 거의 매번 등장하면
# tooltip 이 노이즈가 됨). KG 가 추출해도 export 단계에서 제외.
_GENERIC_BLACKLIST: frozenset[str] = frozenset(
    {
        "하나님", "그리스도", "예수", "예수님", "예수 그리스도",
        "성경", "하나님의 말씀", "말씀",
        "신앙", "믿음", "신앙심",
        "기독교", "기독교인", "교인",
        "구원", "구원자",
        "아버지", "주", "주님", "주의",
        "사람", "사람들", "인간", "우리",
        "God", "Lord", "Christ", "Jesus", "Father", "Son", "Holy Spirit",
        "Bible", "Scripture", "Word",
    }
)
# Glossary 항목 길이 한도 — 8자 넘는 term 은 phrase 일 가능성 높음
_MAX_TERM_LEN = 8


def _is_glossary_noise(term: str) -> bool:
    """KG 노드 → glossary 변환 시 제외할지."""
    if term in _GENERIC_BLACKLIST:
        return True
    # 8자 초과 term 은 phrase 일 가능성 높음 (예: "주께서 그것을 만드신 목적")
    if len(term) > _MAX_TERM_LEN:
        return True
    # 띄어쓰기 포함은 phrase 가능성
    if " " in term and not term.replace(" ", "").isalpha():
        return True
    return False


def _build_alias_lookup() -> dict[str, list[str]]:
    """ENTITY_ALIASES 의 정규명 → [원본명1, 원본명2, ...] 매핑.

    예: {'어거스틴': ['Augustine', 'Augustinus', '아우구스티누스'], ...}
    """
    from rag_core.kg.entity_normalizer import ENTITY_ALIASES

    out: dict[str, list[str]] = {}
    for raw, canonical in ENTITY_ALIASES.items():
        out.setdefault(canonical, []).append(raw)
    return out


def _fetch_kg_terms(adapter: Any) -> list[dict[str, Any]]:
    """KG 의 모든 entity 노드 + description + 출처 페이지.

    LangChain ``add_graph_documents(include_source=True)`` 의 default 관계는
    ``(:Document)-[:MENTIONS]->(:__Entity__)`` (Document → Entity 방향).
    """
    rows = adapter.query_cypher(
        """
        MATCH (n:__Entity__)
        WHERE n.description IS NOT NULL AND n.description <> ''
        WITH n, [l IN labels(n) WHERE l <> '__Entity__' | l] AS lbls
        OPTIONAL MATCH (d:Document)-[:MENTIONS]->(n)
        WITH n, lbls,
             collect(DISTINCT d.page) AS pages,
             collect(DISTINCT coalesce(d.section_label, '')) AS section_labels
        RETURN n.id AS term,
               lbls[0] AS type,
               n.description AS description,
               pages,
               section_labels
        """
    )
    return rows or []


def _make_label(page: int | None, section_label: str | None) -> str:
    if page is None:
        return ""
    if section_label:
        return f"p.{page} ({section_label})"
    return f"p.{page}"


def _fetch_kg_terms_safe(adapter: Any) -> list[dict[str, Any]]:
    """MENTIONED_IN edge 가 없을 수도 — 그래프 구조 모르므로 fallback."""
    try:
        rows = _fetch_kg_terms(adapter)
        if rows:
            return rows
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] MENTIONED_IN fetch 실패 → page 없이 진행: {e}", flush=True)

    # fallback: description 만
    rows = adapter.query_cypher(
        """
        MATCH (n:__Entity__)
        WHERE n.description IS NOT NULL AND n.description <> ''
        WITH n, [l IN labels(n) WHERE l <> '__Entity__' | l] AS lbls
        RETURN n.id AS term, lbls[0] AS type, n.description AS description,
               [] AS pages, [] AS section_labels
        """
    )
    return rows or []


def _build_kg_glossary(adapter: Any) -> list[dict[str, Any]]:
    """KG 행 → 글로서리 항목. 영문/한글 alias 통합 (entity_normalizer).

    LLMGraphTransformer 가 영문 'Augustine' 노드와 한글 '어거스틴' 노드를 분리
    추출할 수 있으므로, normalize_entity_id 로 canonical 키에 통합 + 등장한 모든
    raw form 을 aliases 에 누적.
    """
    rows = _fetch_kg_terms_safe(adapter)
    alias_lookup = _build_alias_lookup()

    try:
        from rag_core.kg.entity_normalizer import (
            ENTITY_ALIASES,
            is_noise_entity,
            normalize_entity_id,
        )
    except ImportError:
        ENTITY_ALIASES = {}
        normalize_entity_id = lambda x: x.strip()  # noqa: E731
        is_noise_entity = lambda x: False  # noqa: E731

    # canonical term → 누적 데이터
    by_canonical: dict[str, dict[str, Any]] = {}
    skipped_noise = 0
    skipped_generic = 0
    for row in rows:
        raw_term = (row.get("term") or "").strip()
        if not raw_term or is_noise_entity(raw_term):
            skipped_noise += 1
            continue
        canonical = normalize_entity_id(raw_term)
        # blacklist + 길이 필터 — phrase / 너무 일반적인 단어 제외
        if _is_glossary_noise(canonical):
            skipped_generic += 1
            continue

        # 기존 entry 또는 새로 생성
        entry = by_canonical.setdefault(
            canonical,
            {
                "term": canonical,
                "aliases": list(alias_lookup.get(canonical, [])),
                "definition": "",
                "sources": [],
                "source": "kg",
            },
        )

        # raw_term 이 canonical 과 다르면 alias 로 누적 (영문/이형)
        if raw_term != canonical and raw_term not in entry["aliases"]:
            entry["aliases"].append(raw_term)

        # description 은 첫 등장의 것 사용 (또는 가장 긴 것)
        candidate_desc = (row.get("description") or "").strip()
        if candidate_desc and (
            not entry["definition"] or len(candidate_desc) > len(entry["definition"])
        ):
            entry["definition"] = candidate_desc

        # sources 누적 (페이지 dedup)
        pages = row.get("pages") or []
        section_labels = row.get("section_labels") or []
        existing_pages = {s["page"] for s in entry["sources"]}
        for i, p in enumerate(pages):
            if p is None:
                continue
            page_int = int(p) + 1 if isinstance(p, int) else int(p)
            if page_int in existing_pages:
                continue
            label_str = section_labels[i] if i < len(section_labels) else ""
            entry["sources"].append(
                {"page": page_int, "label": _make_label(page_int, label_str)}
            )
            existing_pages.add(page_int)

    # alias dedup
    for entry in by_canonical.values():
        entry["aliases"] = list(dict.fromkeys(entry["aliases"]))

    if skipped_noise or skipped_generic:
        print(
            f"  필터: noise={skipped_noise}, generic/phrase={skipped_generic}",
            flush=True,
        )
    return list(by_canonical.values())


def _union_with_curated(
    curated: list[dict[str, Any]],
    kg_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """curated 우선 union — 같은 term 이면 curated 보존, KG 만 있는 건 추가."""
    by_term: dict[str, dict[str, Any]] = {}
    for item in curated:
        if not isinstance(item, dict):
            continue
        item.setdefault("source", "curated")
        by_term[item["term"]] = item
    added = 0
    for item in kg_items:
        if item["term"] not in by_term:
            by_term[item["term"]] = item
            added += 1
    print(f"  union: curated {len(curated)} + KG 신규 {added} = 총 {len(by_term)}")
    return list(by_term.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="KG → 글로서리 export")
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="출력 JSON 경로")
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="기존 curated 와 union 안 함 — KG 만 사용 (위험: 검수 자산 소실)",
    )
    args = parser.parse_args()

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("[1/3] KG 어댑터 연결...", flush=True)
    try:
        from rag_core.kg.factory import get_kg_adapter
    except ImportError as e:
        print(f"[error] kg 모듈 import 실패: {e}", file=sys.stderr)
        return 1
    try:
        adapter = get_kg_adapter()
    except Exception as e:  # noqa: BLE001
        print(f"[error] KG 어댑터 생성 실패: {e}", file=sys.stderr)
        return 1
    if not adapter.health_check():
        print("[error] Neo4j 연결 실패", file=sys.stderr)
        return 1

    print("[2/3] KG export — entity 노드 + description...", flush=True)
    kg_items = _build_kg_glossary(adapter)
    print(f"  KG 추출: {len(kg_items)}개", flush=True)

    if args.no_merge:
        print("[3/3] curated 무시, KG only 모드", flush=True)
        final = kg_items
    else:
        print("[3/3] curated 와 union (curated 우선)...", flush=True)
        existing: list[dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = []
        final = _union_with_curated(existing, kg_items)

    out_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n완료 — {len(final)}개 ({out_path})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
