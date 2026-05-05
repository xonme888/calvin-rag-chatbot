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
    """KG 의 모든 entity 노드 + description + 출처 페이지."""
    rows = adapter.query_cypher(
        """
        MATCH (n:__Entity__)
        WHERE n.description IS NOT NULL AND n.description <> ''
        WITH n, [l IN labels(n) WHERE l <> '__Entity__' | l] AS lbls
        OPTIONAL MATCH (n)-[:MENTIONED_IN]->(d:Document)
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
    rows = _fetch_kg_terms_safe(adapter)
    alias_lookup = _build_alias_lookup()

    out: list[dict[str, Any]] = []
    for row in rows:
        term = (row.get("term") or "").strip()
        if not term:
            continue
        # aliases — alias 사전 + 반대 방향 (canonical 이 term 인 경우)
        aliases = alias_lookup.get(term, []).copy()
        # 만약 term 자체가 raw form 이면 canonical 도 alias 로
        try:
            from rag_core.kg.entity_normalizer import ENTITY_ALIASES

            canonical = ENTITY_ALIASES.get(term)
            if canonical and canonical != term:
                aliases.append(canonical)
        except ImportError:
            pass

        # sources — 페이지별로 1줄
        pages = row.get("pages") or []
        section_labels = row.get("section_labels") or []
        sources: list[dict[str, Any]] = []
        for i, p in enumerate(pages):
            if p is None:
                continue
            label_str = section_labels[i] if i < len(section_labels) else ""
            sources.append(
                {
                    "page": int(p) + 1 if isinstance(p, int) else int(p),
                    "label": _make_label(int(p) + 1 if isinstance(p, int) else int(p), label_str),
                }
            )
        out.append(
            {
                "term": term,
                "aliases": list(dict.fromkeys(aliases)),  # dedup
                "definition": row.get("description", "").strip(),
                "sources": sources,
                "source": "kg",
            }
        )
    return out


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
