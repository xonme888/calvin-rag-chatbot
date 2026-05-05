"""KG 인덱싱 스크립트.

4가지 모드:
- --sample N : 핵심 단원에서 무작위 N청크 인덱싱 (스키마 검증용)
- --balanced N : 단원별 N청크 균등 추출 (5단원 시 ~5N개) — 점진적 보강에 적합
- --full : 균형안 5단원 전체 인덱싱
- --clear : 그래프 전체 비우기 (재인덱싱 전 사용)

사용 예:
    python scripts/index_kg.py --sample 50          # 무작위 50청크 (~₩17, ~6분)
    python scripts/index_kg.py --balanced 30        # 단원별 30 × 5 = 150청크 (~₩50, ~18분)
    python scripts/index_kg.py --full               # 526청크 전체 (~₩180, ~1시간)
    python scripts/index_kg.py --clear              # 그래프 초기화
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from langchain_core.documents import Document

# 프로젝트 루트 sys.path 추가 (스크립트로 직접 실행 시)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from infra.document_loader import load_calvin  # noqa: E402
from infra.env_loader import load_env  # noqa: E402
from rag_core.calvin_builder import build_calvin_rag  # noqa: E402
from rag_core.kg.section_filter import (  # noqa: E402
    DEFAULT_CALVIN_SECTIONS,
    estimate_cost,
    filter_chunks_by_sections,
)
from rag_core.kg.factory import get_kg_adapter  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Calvin KG 인덱싱")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", type=int, metavar="N", help="N청크 무작위 샘플 (스키마 검증용)")
    g.add_argument(
        "--balanced",
        type=int,
        metavar="N",
        help="단원별 N청크 균등 추출 (5단원이면 ~5N개). 이미 인덱싱된 청크와 중복은 건너뜀",
    )
    g.add_argument("--full", action="store_true", help="균형안 5단원 전체 인덱싱")
    g.add_argument("--clear", action="store_true", help="그래프 전체 비우기")
    parser.add_argument("--seed", type=int, default=42, help="샘플 추출 시드")
    parser.add_argument("--no-confirm", action="store_true", help="비용 확인 프롬프트 스킵")
    args = parser.parse_args()

    if not load_env():
        print("ERROR: OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
        sys.exit(1)

    print("KG 어댑터 초기화...")
    adapter = get_kg_adapter()
    if not adapter.health_check():
        print("ERROR: Neo4j 연결 실패. docker compose ps / .env 확인")
        sys.exit(1)
    print(f"  연결 OK. 현재 그래프 상태: {adapter.stats()}")

    if args.clear:
        confirm = input("\n그래프를 모두 비웁니다. 계속 (y/N)? ").strip().lower()
        if confirm == "y":
            adapter.clear()
            print(f"완료. 현재 상태: {adapter.stats()}")
        else:
            print("취소.")
        return

    print("\n칼빈 강요 PDF 로드 + 단원 필터링...")
    docs = load_calvin()
    rag = build_calvin_rag()  # text_splitter 재사용 목적
    chunks = rag.retriever.text_splitter.split_documents(docs)
    filtered = filter_chunks_by_sections(chunks, DEFAULT_CALVIN_SECTIONS)
    print(f"  전체 청크: {len(chunks)}, 5단원 필터링 후: {len(filtered)}")

    # 단원별 분포 출력
    by_section: dict[str, int] = {}
    for c in filtered:
        slug = c.metadata.get("section_slug", "?")
        by_section[slug] = by_section.get(slug, 0) + 1
    for slug, n in sorted(by_section.items()):
        section = next((s for s in DEFAULT_CALVIN_SECTIONS if s.slug == slug), None)
        label = section.label if section else "?"
        print(f"    {slug:5s} ({label:15s}): {n}청크")

    # 인덱싱 대상 결정
    if args.sample is not None:
        random.seed(args.seed)
        target = random.sample(filtered, min(args.sample, len(filtered)))
        mode_label = f"무작위 샘플 {len(target)}청크"
    elif args.balanced is not None:
        # 단원별 균등 추출 — 이미 인덱싱된 청크와의 중복은 회피하지 않음 (LLMGraphTransformer는 멱등 X)
        # 사용자가 사전에 ``--clear`` 또는 추가 인덱싱 의도임을 인지하고 있다고 가정.
        random.seed(args.seed)
        per_section: dict[str, list[Document]] = {}
        for c in filtered:
            slug = c.metadata.get("section_slug", "?")
            per_section.setdefault(slug, []).append(c)
        target = []
        for slug, items in per_section.items():
            random.shuffle(items)
            target.extend(items[: args.balanced])
        mode_label = f"단원별 균등 {args.balanced}청크 × {len(per_section)}단원 = {len(target)}청크"
    else:
        target = filtered
        mode_label = f"전체 {len(target)}청크"

    cost = estimate_cost(target)
    print(f"\n인덱싱 모드: {mode_label}")
    print(f"  추정 비용: ~₩{cost['krw']} (~${cost['usd']:.3f})")
    print(f"  추정 시간: ~{cost['minutes']}분")

    if not args.no_confirm:
        confirm = input("\n진행할까요? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소.")
            return

    # 진행률 콜백
    def on_progress(current: int, total: int) -> None:
        pct = int(current / total * 100)
        bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
        print(f"\r  [{bar}] {current}/{total} ({pct}%)", end="", flush=True)

    print()
    start = time.time()
    indexed = adapter.index_chunks(target, progress_callback=on_progress)
    elapsed = time.time() - start
    print()  # 진행률 바 다음 줄

    final_stats = adapter.stats()
    print(f"\n완료: {indexed}청크 인덱싱, {elapsed:.1f}초 소요")
    print(f"  최종 그래프 상태: {final_stats}")
    print("  Neo4j Browser: http://localhost:7474")
    print("  Cypher 예시: MATCH (n:__Entity__) RETURN n LIMIT 25")


if __name__ == "__main__":
    main()
