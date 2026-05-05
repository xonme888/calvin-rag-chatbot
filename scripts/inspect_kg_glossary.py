"""KG 글로서리 후보 검증 — D 마이그레이션 1단계.

목적: build_glossary_from_kg.py 를 만들기 전, 현재 Neo4j 의 노드 descriptions
품질을 spot check. 정의가 부실하면 D 의 진리값으로 부적합.

흐름:
1. KG 어댑터 health_check
2. 노드 stats (총 개수, 타입별 분포, description 보유율)
3. 샘플 N개 (description 길이 순) 출력
4. 기존 calvin.json 60개와 label 겹침 추정

사용:
    python scripts/inspect_kg_glossary.py [--limit 50]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="KG 글로서리 후보 검증")
    parser.add_argument("--limit", type=int, default=20, help="샘플 출력 개수")
    args = parser.parse_args()

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
        print("[error] Neo4j 연결 실패 — 서비스 실행 중인지 확인", file=sys.stderr)
        return 1

    print("=" * 60)
    print("KG 노드 stats")
    print("=" * 60)
    stats = adapter.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print()
    print("=" * 60)
    print("타입별 분포 + description 보유율")
    print("=" * 60)
    type_rows = adapter.query_cypher(
        """
        MATCH (n:__Entity__)
        WITH n, [l IN labels(n) WHERE l <> '__Entity__' | l] AS lbls
        UNWIND lbls AS lbl
        WITH lbl,
             count(n) AS total,
             count(CASE WHEN n.description IS NOT NULL AND n.description <> '' THEN 1 END) AS with_desc
        RETURN lbl, total, with_desc
        ORDER BY total DESC
        """
    )
    for row in type_rows:
        lbl = row.get("lbl", "?")
        total = row.get("total", 0)
        with_desc = row.get("with_desc", 0)
        rate = (with_desc / total * 100) if total else 0
        print(f"  {lbl:20s}  total={total:4d}  with_desc={with_desc:4d}  ({rate:.0f}%)")

    print()
    print("=" * 60)
    print(f"description 샘플 (상위 {args.limit}개, 길이 desc)")
    print("=" * 60)
    samples = adapter.query_cypher(
        """
        MATCH (n:__Entity__)
        WHERE n.description IS NOT NULL AND n.description <> ''
        WITH n, [l IN labels(n) WHERE l <> '__Entity__' | l] AS lbls
        RETURN n.id AS id, lbls AS types, n.description AS desc, size(n.description) AS dlen
        ORDER BY dlen DESC
        LIMIT $limit
        """,
        params={"limit": args.limit},
    )
    for s in samples:
        types = ",".join(s.get("types", []))
        desc = s.get("desc", "")
        if len(desc) > 140:
            desc = desc[:137] + "..."
        print(f"  [{types}] {s.get('id')}\n    → {desc}\n")

    # curated 글로서리와 겹침 추정
    print("=" * 60)
    print("curated calvin.json 과 KG label 겹침")
    print("=" * 60)
    curated_path = _PROJECT_ROOT / "data" / "glossary" / "calvin.json"
    if not curated_path.exists():
        print("  curated JSON 없음 — skip")
    else:
        curated = json.loads(curated_path.read_text(encoding="utf-8"))
        curated_terms = {item["term"] for item in curated if isinstance(item, dict)}
        # KG 의 모든 label
        kg_labels = adapter.query_cypher(
            "MATCH (n:__Entity__) RETURN DISTINCT n.id AS id"
        )
        kg_label_set = {row.get("id") for row in kg_labels if row.get("id")}
        overlap = curated_terms & kg_label_set
        only_curated = curated_terms - kg_label_set
        only_kg_count = len(kg_label_set - curated_terms)
        print(f"  curated 총: {len(curated_terms)}")
        print(f"  KG 총: {len(kg_label_set)}")
        print(f"  겹침: {len(overlap)} ({len(overlap) / len(curated_terms) * 100:.0f}%)")
        print(f"  curated 만: {len(only_curated)}")
        print(f"  KG 만: {only_kg_count}")
        if only_curated:
            print(f"  curated only 예: {sorted(only_curated)[:10]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
