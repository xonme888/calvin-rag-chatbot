"""Calvin Theology Chatbot - Streamlit 진입점.

두 가지 모드 제공:
- Hybrid: 정해진 흐름 (retrieve → generate). 빠르고 저렴, 토큰 스트리밍 지원.
- Agentic: LLM이 도구 호출 자율 결정 (langchain create_agent). 무관 질문엔 검색 안 함.

칼빈 강요 PDF (1,251 페이지) 인덱스를 두 모드가 공유한다.

실행:
    streamlit run app/calvin_chatbot.py

기능:
- 사이드바: 모드 토글, dense_weight 슬라이더(Hybrid 전용)
- 멀티턴 채팅 히스토리 (Hybrid는 chat_history를 LLM에 전달)
- 토큰 스트리밍 (Hybrid: st.write_stream)
- 단계 진행 표시 (Agentic: st.status)
- 출처 페이지/청크 본문 expander, 도구 호출 내역 expander, LLM 캐시 통계
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Streamlit은 프로젝트 루트를 sys.path에 자동 추가하지 않음
# (pip install -e . 안 한 상태에서도 rag_core/infra를 import 가능하게 함)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage  # noqa: E402

from rag_core.builder import build_calvin_rag  # noqa: E402


def _messages_to_history(messages: list[dict]) -> list[BaseMessage]:
    """Streamlit session_state의 dict 메시지를 LangChain BaseMessage로 변환."""
    history: list[BaseMessage] = []
    for msg in messages:
        if msg["role"] == "user":
            history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            history.append(AIMessage(content=msg["content"]))
    return history


def _render_sources(
    pages: list[int | None],
    docs: list[str],
    elapsed: float | None = None,
) -> None:
    """Hybrid 모드 답변 아래에 출처 페이지 + 청크 본문 미리보기 + 응답 시간 렌더링."""
    if elapsed is not None:
        st.caption(f"응답 시간 {elapsed:.2f}초")

    valid = [(p, d) for p, d in zip(pages, docs, strict=False) if p is not None]
    if not valid:
        return

    with st.expander(f"출처 ({len(valid)}개 청크)"):
        for i, (page, content) in enumerate(valid, 1):
            preview = content.strip().replace("\n", " ")[:250]
            st.markdown(f"**[{i}] p.{page + 1}**")
            st.caption(preview + ("…" if len(content) > 250 else ""))
            if i < len(valid):
                st.divider()


def _render_agentic_meta(
    tool_calls: list[dict[str, Any]],
    source_documents: list[str],
    elapsed: float | None = None,
    llm_calls: int | None = None,
    cache_hits: int | None = None,
    cache_hit_rate: float | None = None,
) -> None:
    """Agentic 모드 답변 아래에 도구 호출 내역 + 검색 결과 + 캐시 통계 렌더링."""
    parts: list[str] = []
    if elapsed is not None:
        parts.append(f"응답 시간 {elapsed:.2f}초")
    parts.append(f"도구 호출 {len(tool_calls)}회")
    if llm_calls is not None:
        parts.append(f"LLM 호출 {llm_calls}회")
    if cache_hits is not None and cache_hits > 0:
        rate_str = f" ({cache_hit_rate * 100:.0f}%)" if cache_hit_rate else ""
        parts.append(f"Cache hit {cache_hits}회{rate_str}")
    if parts:
        st.caption(" | ".join(parts))

    if tool_calls:
        with st.expander(f"도구 호출 내역 ({len(tool_calls)}회)"):
            for i, tc in enumerate(tool_calls, 1):
                st.markdown(f"**[{i}] {tc.get('tool', '?')}**")
                st.code(str(tc.get("args", {})))

    if source_documents:
        with st.expander(f"검색된 본문 ({len(source_documents)}회 검색)"):
            for i, src in enumerate(source_documents, 1):
                preview = src.strip().replace("\n", " ")[:500]
                st.markdown(f"**[검색 {i}]**")
                st.caption(preview + ("…" if len(src) > 500 else ""))
                if i < len(source_documents):
                    st.divider()


# ============================================
# 페이지 설정
# ============================================
st.set_page_config(
    page_title="Calvin Theology Chatbot",
    layout="wide",
)


# ============================================
# RAG 캐싱 (Streamlit 세션 간 공유)
# ============================================
@st.cache_resource(show_spinner="Hybrid RAG (칼빈 강요 인덱스) 로드 중...")
def get_hybrid_rag():
    """Hybrid RAG 인스턴스를 한 번만 빌드하고 재사용한다."""
    return build_calvin_rag()


@st.cache_resource(show_spinner="Agentic RAG 로드 중...")
def get_agentic_rag():
    """Agentic RAG는 Hybrid의 검색 인프라를 그대로 컴포지션해 사용."""
    from rag_core.agentic import AgenticRAG

    return AgenticRAG(hybrid_rag=get_hybrid_rag())


# ============================================
# 사이드바
# ============================================
with st.sidebar:
    st.title("설정")

    mode = st.radio(
        "모드",
        options=["Hybrid", "Agentic"],
        index=0,
        help=(
            "Hybrid: 정해진 흐름 (retrieve → generate). 빠르고 저렴. 토큰 스트리밍.\n"
            "Agentic: LLM이 도구 호출 자율 결정 (create_agent). 무관 질문엔 검색 안 함."
        ),
    )

    if mode == "Hybrid":
        dense_weight = st.slider(
            "Dense weight",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.1,
            help="0.0 = BM25(키워드)만 / 1.0 = FAISS(의미)만 / 0.5 = RRF 균형",
        )
        bm25_weight = 1.0 - dense_weight
        st.caption(f"BM25 weight: {bm25_weight:.1f}")
    else:
        dense_weight = 0.5
        st.caption("Agentic 모드는 LLM이 검색 파라미터를 자율 결정합니다.")

    st.divider()

    st.markdown(
        """
        ### 데이터
        - **기독교 강요** (Institutes of the Christian Religion, 1559)
        - 존 칼빈 (John Calvin)
        - 1,251 페이지 → **5,657 청크**

        ### 기술 스택
        - **Hybrid RAG**: BM25 + Dense + RRF (LangGraph)
        - **Agentic RAG**: langchain `create_agent` + InMemoryCache
        - 임베딩: `text-embedding-3-small`
        - LLM: `gpt-4o-mini`
        - 한국어 토크나이저: 자체 구현

        ### 모드 비교 팁
        - Hybrid: 짧은 응답시간, 토큰 스트리밍
        - Agentic: 도메인 외 질문 거절, 도구 호출 자율 결정
        """
    )

    st.divider()
    if st.button("대화 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ============================================
# 메인 화면
# ============================================
st.title("칼빈 신학 챗봇")
if mode == "Hybrid":
    st.caption("Hybrid RAG (BM25 + Dense + RRF) - 칼빈 강요 1,251페이지에 대해 무엇이든 물어보세요")
else:
    st.caption("Agentic RAG (create_agent) - 도구 호출을 LLM이 자율 결정합니다")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 기존 대화 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            if "tool_calls" in msg:
                _render_agentic_meta(
                    tool_calls=msg.get("tool_calls", []),
                    source_documents=msg.get("source_documents_agentic", []),
                    elapsed=msg.get("elapsed"),
                    llm_calls=msg.get("llm_calls"),
                    cache_hits=msg.get("cache_hits"),
                    cache_hit_rate=msg.get("cache_hit_rate"),
                )
            else:
                _render_sources(
                    pages=msg.get("sources", []),
                    docs=msg.get("source_documents", []),
                    elapsed=msg.get("elapsed"),
                )
                if msg.get("rrf_scores"):
                    with st.expander("RRF top scores (debug)"):
                        st.write(msg["rrf_scores"])

# 사용자 입력
if prompt := st.chat_input("예: 칼빈은 예정론을 어떻게 정의하는가?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if mode == "Agentic":
        # ----- Agentic 모드 -----
        agentic_rag = get_agentic_rag()
        with st.chat_message("assistant"):
            with st.status("Agent 작동 중...", expanded=True) as status:
                final_answer_buf = ""
                for event in agentic_rag.stream_steps(prompt):
                    if event["type"] == "thinking":
                        st.markdown(f"**{event['message']}**")
                        details = event.get("details")
                        if details:
                            st.caption(details)
                    elif event["type"] == "tool_result":
                        st.markdown(event["message"])
                    elif event["type"] == "answer":
                        final_answer_buf = event["content"]
                        st.markdown("답변 생성 완료")
                status.update(label="완료", state="complete", expanded=False)

            meta: dict[str, Any] = agentic_rag._last_metadata or {}
            answer: str = final_answer_buf or meta.get("final_answer", "")
            if answer:
                st.markdown(answer)
            tool_calls = meta.get("tool_calls", [])
            source_documents_agentic = meta.get("source_documents", [])
            elapsed = meta.get("elapsed_seconds")
            llm_calls = meta.get("llm_calls")
            cache_hits = meta.get("cache_hits")
            cache_hit_rate = meta.get("cache_hit_rate")

            _render_agentic_meta(
                tool_calls=tool_calls,
                source_documents=source_documents_agentic,
                elapsed=elapsed,
                llm_calls=llm_calls,
                cache_hits=cache_hits,
                cache_hit_rate=cache_hit_rate,
            )

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "tool_calls": tool_calls,
                    "source_documents_agentic": source_documents_agentic,
                    "elapsed": elapsed,
                    "llm_calls": llm_calls,
                    "cache_hits": cache_hits,
                    "cache_hit_rate": cache_hit_rate,
                }
            )
    else:
        # ----- Hybrid 모드 -----
        hybrid_rag = get_hybrid_rag()
        hybrid_rag.config.dense_weight = dense_weight

        # 멀티턴: 현재까지의 대화를 history로 변환 (방금 추가한 prompt는 제외)
        history = _messages_to_history(st.session_state.messages[:-1])

        with st.chat_message("assistant"):
            with st.spinner(f"검색 중 (dense_weight={dense_weight})..."):
                stream_gen = hybrid_rag.stream_query(prompt, chat_history=history)
                answer = st.write_stream(stream_gen)

            meta = hybrid_rag._last_metadata or {}
            sources = meta.get("source_pages", [])
            rrf_scores = meta.get("rrf_top_scores", [])
            source_documents = meta.get("source_documents", [])
            elapsed = meta.get("elapsed_seconds")

            _render_sources(pages=sources, docs=source_documents, elapsed=elapsed)
            if rrf_scores:
                with st.expander("RRF top scores (debug)"):
                    st.write(rrf_scores)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "source_documents": source_documents,
                    "rrf_scores": rrf_scores,
                    "elapsed": elapsed,
                }
            )
