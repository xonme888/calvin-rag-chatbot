"""3 모드 동시 비교 페이지.

같은 질문을 Hybrid / Agentic / KG 에 병렬로 투입해 답변/메타/그래프를 나란히 비교.
KG 가 미가용이면 Hybrid + Agentic 2 모드만 비교 (graceful degradation).

Streamlit 멀티페이지 — `app/pages/` 폴더에 두면 사이드바에서 자동 노출.
메인 페이지(`app/calvin_chatbot.py`)와 ``st.session_state.usage_stats`` 공유.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# pip install -e . 안 한 환경에서도 동작하도록 sys.path 보강
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402

from infra.usage_tracker import SessionStats, UsageTracker  # noqa: E402
from rag_core.calvin_builder import build_calvin_rag  # noqa: E402
from rag_core.guardrail import (  # noqa: E402
    GuardrailDirection,
    get_input_guardrail,
    get_output_guardrail,
)
from rag_core.mode_dispatcher import compare_all_modes  # noqa: E402

_DEFAULT_MODEL = "gpt-4o-mini"


# ============================================
# 페이지 설정
# ============================================
st.set_page_config(page_title="3 모드 비교", layout="wide")

# ============================================
# 캐시된 RAG 인스턴스 — 메인 페이지와 별도 캐시 (Streamlit cache_resource는 페이지별 격리)
# ============================================
@st.cache_resource(show_spinner="Hybrid RAG 로드 중...")
def _get_hybrid():
    return build_calvin_rag()


@st.cache_resource(show_spinner="Agentic RAG 로드 중...")
def _get_agentic():
    from rag_core.agentic import AgenticRAG

    return AgenticRAG(hybrid_rag=_get_hybrid())


@st.cache_data(ttl=30)
def _kg_status() -> tuple[bool, str | None]:
    """KG 가용성 + 사유 (30초 캐시)."""
    try:
        from rag_core.kg.factory import get_kg_adapter
    except ImportError:
        return False, "KG 의존성 미설치 — `uv pip install -e '.[kg]'`"
    try:
        adapter = get_kg_adapter()
        if not adapter.health_check():
            return False, "Neo4j 미연결 — `docker compose up -d`"
        if adapter.stats().get("nodes", 0) == 0:
            return False, "Neo4j 그래프 비어 있음 — `python scripts/index_kg.py --balanced 30`"
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:80]}"


@st.cache_resource(show_spinner="KG RAG 로드 중...")
def _get_kg_or_none():
    avail, _ = _kg_status()
    if not avail:
        return None
    from rag_core.kg.factory import get_kg_adapter
    from rag_core.kg.pipeline import KnowledgeGraphRAG

    return KnowledgeGraphRAG(kg_adapter=get_kg_adapter(), hybrid_rag=_get_hybrid())


def _render_kg_subgraph(metadata: dict[str, Any]) -> None:
    """KG 모드 column 안에 작은 그래프 시각화 — streamlit-agraph 미설치 시 텍스트 fallback."""
    sg_dict = metadata.get("subgraph") or {}
    nodes = sg_dict.get("nodes") or []
    if not nodes:
        st.caption("(부분 그래프 비어 있음)")
        return

    try:
        from rag_core.kg.graph_renderer import to_agraph_format
        from rag_core.kg.port import SubgraphData
        from streamlit_agraph import Config as AgraphConfig
        from streamlit_agraph import agraph

        sg = SubgraphData(**sg_dict)
        data = to_agraph_format(sg)
        st.markdown(f"**관계 그래프** ({len(data['nodes'])}개 노드)")
        agraph(
            nodes=data["nodes"],
            edges=data["edges"],
            config=AgraphConfig(
                height=320,
                width=420,
                directed=True,
                physics=True,
                hierarchical=False,
            ),
        )
    except ImportError:
        with st.expander("관계 그래프 (텍스트)"):
            for edge in (sg_dict.get("edges") or [])[:15]:
                st.text(f"({edge['source']}) -[{edge['label']}]-> ({edge['target']})")


# ============================================
# 메인
# ============================================
st.title("3 모드 동시 비교")
st.caption(
    "같은 질문을 Hybrid / Agentic / KG에 병렬로 투입해 답변/메타/그래프를 나란히 비교합니다."
)

# 세션 통계 공유 (메인 페이지와 동일 객체)
if "usage_stats" not in st.session_state:
    st.session_state.usage_stats = SessionStats()
stats: SessionStats = st.session_state.usage_stats

kg_avail, kg_reason = _kg_status()
if not kg_avail:
    st.warning(f"**KG 모드 비활성화** — {kg_reason}\n\nHybrid + Agentic 2 모드만 비교됩니다.")

with st.sidebar:
    st.title("비교 페이지")
    st.caption(
        "이 페이지는 메인 챗봇과 ``usage_stats`` 를 공유합니다. "
        "사이드바의 누적 통계는 메인 페이지에서 확인하세요."
    )
    if stats.total_calls > 0:
        st.metric("누적 LLM 호출", stats.total_calls)
        st.metric("누적 비용", f"₩{stats.total_cost_krw:.1f}")

prompt = st.chat_input("예: 칼빈은 예정론을 어떻게 정의하는가?")
if not prompt:
    st.info(
        "예시 질문 (`docs/demo-questions.md` 참고):\n"
        "- 예정론을 둘러싼 칼빈과 어거스틴의 관계는?\n"
        "- 자유의지를 칼빈은 어떻게 정의하며, 어떤 관점과 대립하는가?\n"
        "- 이신칭의의 정의를 한 단락으로 설명해줘"
    )
else:
    # 입력 가드 — 비교 페이지도 동일 정책
    input_guard = get_input_guardrail()
    input_decision = input_guard.check(prompt, GuardrailDirection.INPUT)
    if not input_decision.allow:
        st.error(f"입력 차단: {input_decision.reason}")
        st.stop()

    st.markdown(f"### 질문\n> {prompt}")

    hybrid = _get_hybrid()
    agentic = _get_agentic()
    kg = _get_kg_or_none()

    callbacks_per_mode: dict[str, list[Any]] = {
        "Hybrid": [UsageTracker(stats, mode="Hybrid", model=_DEFAULT_MODEL)],
        "Agentic": [UsageTracker(stats, mode="Agentic", model=_DEFAULT_MODEL)],
    }
    if kg is not None:
        callbacks_per_mode["Knowledge Graph"] = [
            UsageTracker(stats, mode="Knowledge Graph", model=_DEFAULT_MODEL)
        ]

    with st.spinner("3 모드 동시 호출 중 (병렬)..."):
        results = compare_all_modes(
            question=prompt,
            hybrid=hybrid,
            agentic=agentic,
            kg=kg,
            callbacks_per_mode=callbacks_per_mode,
        )

    output_guard = get_output_guardrail()
    cols = st.columns(len(results))
    for col, result in zip(cols, results, strict=False):
        with col:
            st.subheader(result.mode_name)
            if result.error:
                st.error(result.error)
                continue
            st.caption(f"응답 시간 {result.elapsed:.2f}초")

            # 출력 가드 — 모드별 답변에 동일 적용
            out_decision = output_guard.check(
                result.answer, GuardrailDirection.OUTPUT
            )
            if not out_decision.allow:
                st.warning("답변이 정책에 의해 필터링되었습니다.")
                continue
            displayed_answer = out_decision.sanitized or result.answer
            if out_decision.sanitized:
                st.caption(f"가드: {out_decision.reason}")
            st.markdown(displayed_answer)
            if result.mode_name == "Knowledge Graph":
                _render_kg_subgraph(result.metadata)
            with st.expander("메타데이터"):
                meta_compact = {
                    k: v
                    for k, v in result.metadata.items()
                    if k != "subgraph"  # subgraph는 위에서 시각화로 표시
                }
                st.json(meta_compact)
            if result.source_documents:
                with st.expander(f"출처 ({len(result.source_documents)}개 발췌)"):
                    for i, src in enumerate(result.source_documents[:3], 1):
                        preview = src.strip().replace("\n", " ")[:240]
                        st.caption(f"[{i}] {preview}{'…' if len(src) > 240 else ''}")
