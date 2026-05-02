"""Agentic RAG - LangChain ``create_agent`` 기반.

Tool calling 자율 결정 에이전트가 검색 전략을 스스로 선택한다.

핵심 차이 (vs Hybrid RAG):
- Hybrid RAG: 정해진 흐름 (retrieve → generate)
- Agentic RAG: LLM이 매 턴 도구 호출 여부를 자율 결정 (ReAct 패턴)

도구:
- ``search_documents(query, k)``: Hybrid 검색 인프라를 도구로 노출

LLM Cache: ``InMemoryCache`` 적용 (전역). hit/miss 카운트를 metadata에 노출.

Spring AI 매핑: ``@Tool`` 어노테이션 + ``ChatClient`` 의 ``ToolCallback``.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain_core.caches import InMemoryCache
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.globals import set_llm_cache
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_core.hybrid import HybridRAG, _format_doc_with_meta


class TrackedInMemoryCache(InMemoryCache):
    """``InMemoryCache``를 확장해 lookup 시 hit/miss 카운트를 누적한다.

    LangChain LLM은 cache 사용 시 매 호출마다 ``lookup(prompt, llm_string)``을
    호출한다. None 반환은 cache miss(LLM 호출), 값 반환은 cache hit.
    이 카운터를 metadata에 노출해 시연 시 캐시 효율을 직접 보여줄 수 있다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.hits: int = 0
        self.misses: int = 0

    def lookup(self, prompt: str, llm_string: str) -> Any:
        result = super().lookup(prompt, llm_string)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def reset(self) -> None:
        """카운트만 0으로 초기화. 캐시 데이터는 보존."""
        self.hits = 0
        self.misses = 0


class LLMCallTracker(BaseCallbackHandler):
    """LLM 실제 호출(=cache miss) 횟수를 추적하는 콜백.

    ``on_llm_start``는 cache hit 시에는 호출되지 않으므로(LLM이 안 불림),
    이 카운터는 사실상 cache miss와 거의 동일한 값이 된다.
    """

    def __init__(self) -> None:
        self.llm_calls: int = 0

    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self.llm_calls += 1

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self.llm_calls += 1

    def reset(self) -> None:
        self.llm_calls = 0


class AgenticRAGConfig(BaseSettings):
    """Agentic RAG 설정. ``HybridRAGConfig``와 별개지만 동일한 ``.env``를 공유한다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    open_api_key: Annotated[SecretStr, Field(alias="OPENAI_API_KEY")] = SecretStr("")
    openai_model: Annotated[str, Field(alias="OPENAI_MODEL")] = "gpt-4o-mini"
    embedding_model: Annotated[str, Field(alias="EMBEDDING_MODEL")] = "text-embedding-3-small"

    chunk_size: Annotated[int, Field(alias="CHUNK_SIZE")] = 500
    chunk_overlap: Annotated[int, Field(alias="CHUNK_OVERLAP")] = 50
    top_k: Annotated[int, Field(alias="TOP_K")] = 5
    dense_weight: Annotated[float, Field(alias="DENSE_WEIGHT")] = 0.5
    rrf_k: Annotated[int, Field(alias="RRF_K")] = 60

    # recursion_limit: ReAct loop 폭주 방지. 도구 호출 + 답변 생성을 합친 노드 수 한도.
    recursion_limit: Annotated[int, Field(alias="AGENT_RECURSION_LIMIT")] = 10
    enable_llm_cache: Annotated[bool, Field(alias="ENABLE_LLM_CACHE")] = True

    # 시스템 프롬프트 (칼빈 도메인 + ReAct 행동 가이드)
    system_prompt: Annotated[str, Field(alias="AGENTIC_SYSTEM_PROMPT")] = (
        "당신은 칼빈 신학 전문 학습 도우미입니다.\n"
        "주어진 도구를 사용해 칼빈 강요(Institutes of the Christian Religion) 본문을 "
        "검색하고 답변하세요.\n\n"
        "## 행동 가이드:\n"
        "1. 질문이 칼빈 신학과 관련 있다면 search_documents 도구로 본문을 검색하세요.\n"
        "2. 검색 결과로 충분하지 않으면 다른 키워드로 한 번 더 검색해도 됩니다 "
        "(최대 2~3회).\n"
        "3. 검색 결과가 답변에 충분하면 그 본문을 근거로 답변하세요.\n"
        "4. 칼빈 신학과 무관한 질문 (예: 날씨, 일반 지식)은 도구를 호출하지 말고 "
        "'본 챗봇은 칼빈 신학에 한정된 답변만 가능합니다'라고 안내하세요.\n"
        "5. 답변 시 가능하면 권/장 번호를 인용하세요.\n"
        "6. 본문에서 직접 찾을 수 없으면 '본문에서 직접 찾을 수 없습니다'라고 명확히 "
        "안내하고, 추측이나 외부 지식으로 빈 곳을 메우지 마세요."
    )


class AgenticRAG:
    """Tool calling 기반 자율 에이전트 RAG (langchain ``create_agent``).

    HybridRAG를 검색 인프라로 컴포지션하여 BM25 + Dense + RRF + 한국어 토크나이저를
    그대로 재사용한다. 차이점은 LLM이 검색 여부/시점/쿼리를 스스로 결정한다는 것.
    """

    PATTERN_NAME: str = "Agentic RAG"

    def __init__(
        self,
        config: AgenticRAGConfig | None = None,
        hybrid_rag: HybridRAG | None = None,
        llm: BaseChatModel | None = None,
    ) -> None:
        """Agentic RAG 인스턴스를 생성한다.

        Args:
            config: Agentic 전용 설정. None이면 .env 기반 기본 설정.
            hybrid_rag: 검색 인프라로 사용할 HybridRAG. None이면 ``build_calvin_rag()``
                로 자동 생성 (인덱스 캐시 사용).
            llm: 외부 주입 LLM. None이면 ``hybrid_rag.llm`` 재사용.
        """
        self.config: AgenticRAGConfig = config or AgenticRAGConfig()

        # LLM Cache (전역). hit/miss 카운트 노출 가능.
        self._tracked_cache: TrackedInMemoryCache | None = None
        if self.config.enable_llm_cache:
            self._tracked_cache = TrackedInMemoryCache()
            set_llm_cache(self._tracked_cache)

        self._llm_tracker: LLMCallTracker = LLMCallTracker()

        # Hybrid 인프라 컴포지션. build_calvin_rag()는 인덱스 캐시 사용.
        if hybrid_rag is None:
            from rag_core.builder import build_calvin_rag

            hybrid_rag = build_calvin_rag()
        self.hybrid: HybridRAG = hybrid_rag
        self.llm: BaseChatModel = llm or self.hybrid.llm

        self._tools: list[BaseTool] = [self._make_search_tool()]

        # langchain 1.x create_agent — middleware/cache 등 확장 파라미터 지원.
        # 반환은 CompiledStateGraph 이므로 .invoke/.stream 호출부는 호환.
        self._agent = create_agent(
            model=self.llm,
            tools=self._tools,
            system_prompt=self.config.system_prompt,
        )

        self._last_metadata: dict[str, Any] | None = None

    def _make_search_tool(self) -> BaseTool:
        """search_documents 도구를 만든다.

        HybridRAG의 검색 인프라(BM25 + Dense + RRF)를 도구 형태로 노출.
        클로저로 self.hybrid를 캡처해 도구 호출 시 같은 인덱스를 사용.
        """
        rag = self.hybrid

        @tool
        def search_documents(query: str, k: int = 5) -> str:
            """칼빈 강요(Institutes of the Christian Religion) 본문에서 관련 청크를 검색한다.

            Args:
                query: 검색 쿼리 (한국어 또는 영어). 핵심 키워드 또는 자연어 질문.
                k: 검색할 청크 수. 기본 5. (1~10 권장)

            Returns:
                검색된 청크들의 텍스트와 페이지 번호. 형식:
                "[page N] 청크 내용\\n\\n---\\n\\n[page M] ..."
            """
            if rag.vector_store is None or rag.bm25_retriever is None:
                return "검색기가 초기화되지 않았습니다. 먼저 인덱싱이 필요합니다."

            bm25_results = rag.bm25_retriever.search(query, k=k)
            dense_results = rag.vector_store.similarity_search_with_score(query, k=k)
            fused = rag._reciprocal_rank_fusion(bm25_results, dense_results)
            top_docs = [doc for doc, _ in fused[:k]]

            if not top_docs:
                return "관련된 본문을 찾을 수 없습니다."

            return "\n\n---\n\n".join(_format_doc_with_meta(d) for d in top_docs)

        return search_documents

    def index_documents(self, documents: list[Document]) -> int:
        """문서를 인덱싱한다 (hybrid에 위임)."""
        return self.hybrid.index_documents(documents)

    def query(self, question: str) -> dict[str, Any]:
        """질문에 답한다 (Agent가 도구 호출 자율 결정).

        Returns:
            {
                "final_answer": str,
                "source_documents": list[str],
                "metadata": {pattern, tool_calls, tool_call_count, elapsed_seconds,
                             cache_hits, cache_misses, cache_hit_rate, llm_calls, model}
            }
        """
        start = time.time()

        if self._tracked_cache is not None:
            self._tracked_cache.reset()
        self._llm_tracker.reset()

        input_state: dict[str, Any] = {"messages": [HumanMessage(content=question)]}
        config: dict[str, Any] = {
            "recursion_limit": self.config.recursion_limit,
            "callbacks": [self._llm_tracker],
        }

        final_state: dict[str, Any] = self._agent.invoke(input_state, config=config)

        messages: list[BaseMessage] = final_state.get("messages", [])

        final_answer: str = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                content = msg.content
                if isinstance(content, str) and content.strip():
                    final_answer = content
                    break

        tool_calls: list[dict[str, Any]] = []
        source_docs: list[str] = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                msg_tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in msg_tool_calls:
                    tool_calls.append(
                        {
                            "tool": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                    )
            msg_name = getattr(msg, "name", None)
            if msg_name == "search_documents":
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                source_docs.append(content)

        elapsed = time.time() - start

        cache_hits = self._tracked_cache.hits if self._tracked_cache else 0
        cache_misses = self._tracked_cache.misses if self._tracked_cache else 0
        llm_calls = self._llm_tracker.llm_calls
        total_lookups = cache_hits + cache_misses
        cache_hit_rate = (cache_hits / total_lookups) if total_lookups else 0.0

        return {
            "final_answer": final_answer,
            "source_documents": source_docs,
            "metadata": {
                "pattern": self.PATTERN_NAME,
                "tool_calls": tool_calls,
                "tool_call_count": len(tool_calls),
                "elapsed_seconds": elapsed,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "cache_hit_rate": round(cache_hit_rate, 3),
                "llm_calls": llm_calls,
                "model": self.config.openai_model,
            },
        }

    def stream_steps(self, question: str):
        """LangGraph stream(updates 모드)으로 Agent 실행 단계를 yield한다.

        토큰 단위 스트리밍이 아니라 노드 단위 진행 상황을 친화적 메시지로 yield.
        Streamlit ``st.status``와 결합하면 도구 호출 내역을 실시간 표시 가능.

        Yields:
            dict 형태의 step 이벤트:
            - {"type": "thinking", "message": str, "details": str | None}
            - {"type": "tool_result", "message": str}
            - {"type": "answer", "content": str}

        Stream 종료 후 ``self._last_metadata``에 메타데이터 저장.
        """
        start = time.time()
        self._last_metadata = None

        if self._tracked_cache is not None:
            self._tracked_cache.reset()
        self._llm_tracker.reset()

        input_state: dict[str, Any] = {"messages": [HumanMessage(content=question)]}
        config: dict[str, Any] = {
            "recursion_limit": self.config.recursion_limit,
            "callbacks": [self._llm_tracker],
        }

        tool_calls: list[dict[str, Any]] = []
        source_docs: list[str] = []
        final_answer: str = ""
        seen_msg_ids: set[int] = set()

        # stream_mode="updates": 각 노드 종료 시 변경된 state만 yield
        for chunk in self._agent.stream(input_state, config=config, stream_mode="updates"):
            for _node_name, update in chunk.items():
                new_messages = update.get("messages", []) if isinstance(update, dict) else []
                for msg in new_messages:
                    msg_id = id(msg)
                    if msg_id in seen_msg_ids:
                        continue
                    seen_msg_ids.add(msg_id)

                    if isinstance(msg, AIMessage):
                        msg_tool_calls = getattr(msg, "tool_calls", None) or []
                        if msg_tool_calls:
                            for tc in msg_tool_calls:
                                tool_name = tc.get("name", "")
                                tool_args = tc.get("args", {})
                                tool_calls.append({"tool": tool_name, "args": tool_args})
                                yield {
                                    "type": "thinking",
                                    "message": f"검색 도구 호출: {tool_name}",
                                    "details": ", ".join(
                                        f'{k}="{v}"' for k, v in tool_args.items()
                                    ),
                                }
                        elif msg.content:
                            content = msg.content
                            if isinstance(content, str) and content.strip():
                                final_answer = content
                                yield {"type": "answer", "content": content}

                    elif getattr(msg, "name", None) == "search_documents":
                        content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        source_docs.append(content)
                        n_chunks = content.count("---") + 1 if content else 0
                        yield {
                            "type": "tool_result",
                            "message": f"{n_chunks}개 청크 검색 완료",
                        }

        elapsed = time.time() - start
        cache_hits = self._tracked_cache.hits if self._tracked_cache else 0
        cache_misses = self._tracked_cache.misses if self._tracked_cache else 0
        total_lookups = cache_hits + cache_misses
        cache_hit_rate = (cache_hits / total_lookups) if total_lookups else 0.0

        self._last_metadata = {
            "pattern": self.PATTERN_NAME,
            "tool_calls": tool_calls,
            "tool_call_count": len(tool_calls),
            "elapsed_seconds": elapsed,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": round(cache_hit_rate, 3),
            "llm_calls": self._llm_tracker.llm_calls,
            "model": self.config.openai_model,
            "source_documents": source_docs,
            "final_answer": final_answer,
        }
