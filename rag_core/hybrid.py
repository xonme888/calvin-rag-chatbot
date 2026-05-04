"""Hybrid RAG - LangGraph 기반 BM25 + Dense + RRF 결합 검색.

핵심 아이디어:
- 의미 기반 검색은 동의어/맥락에 강하지만 정확한 용어 매칭에 약하다.
- 키워드 기반(BM25)은 정확한 용어에 강하지만 의미적 유사성에 약하다.
- 둘을 RRF로 결합하면 양쪽 장점을 모두 얻는다.

추가 토글 (config 기반):
- ``reranker_enabled``: cross-encoder 재랭킹 + Long-context reorder
- ``self_rag_enabled``: groundedness check + query rewrite 루프
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field as PydanticField
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_core.retriever import HybridRetriever, RetrieverPort

# 기본 시스템 프롬프트 — 도메인 교체 시 ``HybridRAGConfig(system_prompt=...)``로 외부 주입
DEFAULT_SYSTEM_PROMPT = (
    "당신은 친절한 학습 도우미입니다. "
    "아래 본문을 바탕으로 정확하게 답변하세요.\n\n"
    "## 답변 가이드:\n"
    "1. 제공된 정보 내에서만 답변\n"
    "2. 정보가 없으면 '해당 정보를 찾을 수 없습니다'라고 안내\n"
    "3. 가능하면 출처(페이지 번호)를 인용\n\n"
    "## 참고 본문:\n{context}"
)


class HybridRAGConfig(BaseSettings):
    """Hybrid RAG 설정. ``.env`` 자동 로드."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    open_api_key: Annotated[SecretStr, Field(alias="OPENAI_API_KEY")] = SecretStr("")
    openai_model: Annotated[str, Field(alias="OPENAI_MODEL")] = "gpt-4o-mini"
    embedding_model: Annotated[str, Field(alias="EMBEDDING_MODEL")] = "text-embedding-3-small"

    chunk_size: Annotated[int, Field(alias="CHUNK_SIZE")] = 500
    chunk_overlap: Annotated[int, Field(alias="CHUNK_OVERLAP")] = 50
    top_k: Annotated[int, Field(alias="TOP_K")] = 5

    # BM25/Dense 가중치 (RRF)
    dense_weight: Annotated[float, Field(alias="DENSE_WEIGHT")] = 0.5
    rrf_k: Annotated[int, Field(alias="RRF_K")] = 60

    # 시스템 프롬프트 — 도메인별 외부 주입 가능, ``{context}`` 자리표시자 필수
    system_prompt: Annotated[str, Field(alias="SYSTEM_PROMPT")] = DEFAULT_SYSTEM_PROMPT

    # Reranker 토글 — True 시 ``rag_core.reranker`` 의 FlashRankReranker 적용
    # 활성화 전제: ``uv pip install -e '.[rerank]'``
    reranker_enabled: Annotated[bool, Field(alias="RERANKER_ENABLED")] = False
    reranker_top_k: Annotated[int, Field(alias="RERANKER_TOP_K")] = 5

    # Self-RAG (Groundedness Check) 토글
    # True 시 generate 후 grade 노드에서 답변의 본문 근거 충실도를 LLM으로 평가.
    # 부족하면 rewrite 노드가 질문을 재작성해 retrieve를 재실행.
    # 비용 영향: 답변당 LLM 콜이 1회 → 2~3회로 증가. ``query()`` 모드에만 적용.
    self_rag_enabled: Annotated[bool, Field(alias="SELF_RAG_ENABLED")] = False
    max_self_rag_retries: Annotated[int, Field(alias="MAX_SELF_RAG_RETRIES")] = 2


@lru_cache
def get_config() -> HybridRAGConfig:
    return HybridRAGConfig()


# ====================================================================
# Structured Output 스키마
# ====================================================================
class RAGResponse(PydanticBaseModel):
    """LLM이 채울 구조화된 응답 스키마."""

    answer: str = PydanticField(description="질문에 대한 본문 답변")
    cited_pages: list[int] = PydanticField(
        default_factory=list,
        description=(
            "답변에 사용된 페이지 번호 리스트 (1-indexed). "
            "본문 [page N] 표시에서 추출. 없으면 빈 리스트."
        ),
    )
    confidence: float = PydanticField(
        default=0.5,
        description=(
            "0.0~1.0. 답변이 본문 근거로 얼마나 뒷받침되는지의 자기 평가. "
            "근거가 풍부하면 0.9+, 추론이 많이 섞이면 0.4 이하."
        ),
    )


class GroundednessGrade(PydanticBaseModel):
    """답변의 본문 근거 충실도 평가 결과 (Self-RAG 활성화 시 사용)."""

    is_grounded: bool = PydanticField(description="답변이 제공된 본문으로 충분히 뒷받침되는가?")
    reason: str = PydanticField(description="판단 근거 한 문장")


class RewrittenQuery(PydanticBaseModel):
    """검색 친화적으로 재작성된 질문 (Self-RAG 루프에서 사용)."""

    rewritten: str = PydanticField(
        description="검색에 더 적합하게 재작성된 질문. 동의어/구체적 용어/맥락 보강 활용."
    )


class HybridRAGState(TypedDict, total=False):
    """그래프 노드 간 공유 상태."""

    question: str
    chat_history: Annotated[list[BaseMessage], add_messages]
    bm25_results: list[tuple[Document, float]]
    dense_results: list[tuple[Document, float]]
    fused: list[tuple[Document, float]]
    top_docs: list[Document]
    answer: str
    structured_response: dict[str, Any]
    metadata: dict[str, Any]
    # Self-RAG
    is_grounded: bool
    grade_reason: str
    retry_count: int
    rewritten_question: str


class HybridRAG:
    """BM25 + Dense 검색 결합 RAG (LangGraph 기반)."""

    PATTERN_NAME: str = "Hybrid RAG"

    def __init__(
        self,
        config: HybridRAGConfig | None = None,
        llm: BaseChatModel | None = None,
        embeddings: Embeddings | None = None,
        retriever: RetrieverPort | None = None,
    ) -> None:
        """Hybrid RAG 인스턴스를 생성한다.

        Args:
            config: 설정. None이면 .env 기반 기본 설정 사용.
            llm: 외부 주입 LLM. None이면 ChatOpenAI 생성.
            embeddings: 외부 주입 임베딩. None이면 OpenAIEmbeddings 생성.
                ``retriever`` 가 None일 때만 사용 (retriever 인스턴스 생성용).
            retriever: 검색 인프라. None이면 HybridRetriever 자동 생성.
                Hexagonal: RAG 본체는 RetrieverPort에만 의존.
        """
        self.config: HybridRAGConfig = config or get_config()

        self.llm = llm or ChatOpenAI(
            api_key=self.config.open_api_key,
            model=self.config.openai_model,
            temperature=0,
        )

        self.embeddings = embeddings or OpenAIEmbeddings(
            model=self.config.embedding_model,
            api_key=self.config.open_api_key,
        )

        # Retriever 컴포지션 — 검색 인프라는 별도 객체에 위임 (캡슐화)
        self.retriever: RetrieverPort = retriever or HybridRetriever(
            embeddings=self.embeddings,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            dense_weight=self.config.dense_weight,
            rrf_k=self.config.rrf_k,
        )

        # MessagesPlaceholder("chat_history", optional=True): chat_history가 비어 있어도
        # 에러 없이 단일 턴으로 동작.
        self._prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config.system_prompt),
                MessagesPlaceholder("chat_history", optional=True),
                ("human", "{question}"),
            ]
        )

        # Reranker (lazy)
        self._reranker: Any = None

        # stream_query() 호출 후 메타데이터 보관
        self._last_metadata: dict[str, Any] | None = None

        self._graph: CompiledStateGraph = self._build_graph()

    def index_documents(self, documents: list[Document]) -> int:
        """문서 인덱싱을 retriever에 위임."""
        return self.retriever.index_documents(documents)

    # ================================================================
    # LangGraph 노드
    # ================================================================
    def _retrieve_node(self, state: HybridRAGState) -> dict[str, Any]:
        """검색 노드: retriever에 위임 (BM25 + Dense + RRF 결합)."""
        question = state["question"]
        # retriever_split: bm25/dense/fused 모두 노출 (메타데이터에 활용)
        bm25_results, dense_results, fused = self.retriever.retrieve_split(  # type: ignore[union-attr]
            question, k=self.config.top_k
        )
        top_docs = [doc for doc, _ in fused[: self.config.top_k]]

        return {
            "bm25_results": bm25_results,
            "dense_results": dense_results,
            "fused": fused,
            "top_docs": top_docs,
        }

    def _generate_node(self, state: HybridRAGState) -> dict[str, Any]:
        """생성 노드: top_docs로 컨텍스트를 만들어 LLM 호출.

        - chat_history를 프롬프트에 주입 (멀티턴)
        - ``with_structured_output(RAGResponse)`` 으로 답변/인용/신뢰도 동시 추출
        - (HumanMessage, AIMessage) 페어를 반환해 add_messages reducer로 history 누적
        """
        question = state["question"]
        top_docs = state["top_docs"]
        bm25_results = state.get("bm25_results", [])
        dense_results = state.get("dense_results", [])
        fused = state.get("fused", [])
        chat_history: list[BaseMessage] = state.get("chat_history", [])

        context = "\n\n---\n\n".join(_format_doc_with_meta(d) for d in top_docs)

        structured_llm = self.llm.with_structured_output(RAGResponse)
        chain = self._prompt | structured_llm
        response: RAGResponse = chain.invoke(
            {
                "context": context,
                "question": question,
                "chat_history": chat_history,
            }
        )

        answer = response.answer

        from rag_core.citation_label import labels_for_pages
        from rag_core.followup import generate_followups

        metadata: dict[str, Any] = {
            "pattern": self.PATTERN_NAME,
            "bm25_count": len(bm25_results),
            "dense_count": len(dense_results),
            "rrf_top_scores": [round(s, 4) for _, s in fused[:5]],
            "dense_weight": self.config.dense_weight,
            "source_pages": [d.metadata.get("page") for d in top_docs],
            "source_pages_label": labels_for_pages(
                [d.metadata.get("page") for d in top_docs]
            ),
            "confidence": response.confidence,
            "cited_pages": response.cited_pages,
            "is_grounded": None,  # Self-RAG에서 채워짐
            "tool_calls": [],
            "subgraph": None,
            "suggested_followups": generate_followups(question, answer, self.llm),
        }

        return {
            "answer": answer,
            "metadata": metadata,
            "structured_response": response.model_dump(),
            "chat_history": [
                HumanMessage(content=question),
                AIMessage(content=answer),
            ],
        }

    def _rerank_node(self, state: HybridRAGState) -> dict[str, Any]:
        """재랭킹 노드: cross-encoder + LongContextReorder.

        config.reranker_enabled=True 시에만 그래프에 포함.
        flashrank lazy import — 미설치 시 명확한 ImportError.
        """
        from rag_core.reranker import FlashRankReranker, rerank_and_reorder

        if self._reranker is None:
            self._reranker = FlashRankReranker()

        top_docs = state.get("top_docs", [])
        if not top_docs:
            return {}

        reranked = rerank_and_reorder(
            query=state["question"],
            docs=top_docs,
            reranker=self._reranker,
            top_k=self.config.reranker_top_k,
        )
        return {"top_docs": reranked}

    # ================================================================
    # Self-RAG / Groundedness Check 노드
    # ================================================================
    def _grade_node(self, state: HybridRAGState) -> dict[str, Any]:
        """답변의 grounded 여부를 LLM으로 판단한다."""
        answer = state.get("answer", "")
        top_docs = state.get("top_docs", [])

        if not answer or not top_docs:
            return {
                "is_grounded": False,
                "grade_reason": "답변 또는 문서 누락",
            }

        context = "\n\n---\n\n".join(_format_doc_with_meta(d) for d in top_docs)
        grader_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "당신은 답변의 본문 근거를 검증하는 전문가입니다. "
                        "주어진 본문에 답변이 충분히 뒷받침되는지 판단하세요.\n\n"
                        "## 본문:\n{context}\n\n"
                        "## 답변:\n{answer}\n\n"
                        "## 판단 기준:\n"
                        "- 답변의 핵심 주장이 본문에 명시되어 있으면 grounded=True\n"
                        "- 답변이 본문에 없는 내용을 추가했거나 모순되면 grounded=False\n"
                        "- 부분적으로만 뒷받침되면 grounded=False"
                    ),
                ),
                ("human", "이 답변이 본문으로 뒷받침됩니까?"),
            ]
        )
        grader = self.llm.with_structured_output(GroundednessGrade)
        chain = grader_prompt | grader
        grade: GroundednessGrade = chain.invoke({"context": context, "answer": answer})
        return {
            "is_grounded": grade.is_grounded,
            "grade_reason": grade.reason,
        }

    def _rewrite_node(self, state: HybridRAGState) -> dict[str, Any]:
        """검색에 실패했을 때 질문을 재작성한다."""
        original_question = state["question"]
        grade_reason = state.get("grade_reason", "")
        retry_count = state.get("retry_count", 0) + 1

        rewriter_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "다음 질문을 검색에 더 적합한 형태로 재작성하세요. "
                        "동의어/구체적 용어/맥락 보강 등을 활용.\n\n"
                        "원래 질문: {original}\n"
                        "이전 검색 실패 이유: {reason}"
                    ),
                ),
                ("human", "재작성된 질문은?"),
            ]
        )
        rewriter = self.llm.with_structured_output(RewrittenQuery)
        chain = rewriter_prompt | rewriter
        result: RewrittenQuery = chain.invoke(
            {
                "original": original_question,
                "reason": grade_reason,
            }
        )
        return {
            "question": result.rewritten,
            "rewritten_question": result.rewritten,
            "retry_count": retry_count,
        }

    def _grade_router(self, state: HybridRAGState) -> str:
        if state.get("is_grounded", False):
            return "end"
        retry_count = state.get("retry_count", 0)
        if retry_count >= self.config.max_self_rag_retries:
            return "end"
        return "rewrite"

    def _build_graph(self) -> CompiledStateGraph:
        """검색 → (재랭킹) → 생성 → (grade → rewrite 루프) 그래프를 컴파일한다."""
        builder: StateGraph = StateGraph(HybridRAGState)

        builder.add_node("retrieve", self._retrieve_node)
        builder.add_node("generate", self._generate_node)

        if self.config.reranker_enabled:
            builder.add_node("rerank", self._rerank_node)

        if self.config.self_rag_enabled:
            builder.add_node("grade", self._grade_node)
            builder.add_node("rewrite", self._rewrite_node)

        builder.add_edge(START, "retrieve")

        if self.config.reranker_enabled:
            builder.add_edge("retrieve", "rerank")
            builder.add_edge("rerank", "generate")
        else:
            builder.add_edge("retrieve", "generate")

        if self.config.self_rag_enabled:
            builder.add_edge("generate", "grade")
            builder.add_conditional_edges(
                "grade",
                self._grade_router,
                {
                    "end": END,
                    "rewrite": "rewrite",
                },
            )
            builder.add_edge("rewrite", "retrieve")
        else:
            builder.add_edge("generate", END)

        return builder.compile()

    # ================================================================
    # 외부 통일 인터페이스
    # ================================================================
    def query(
        self,
        question: str,
        chat_history: list[BaseMessage] | None = None,
        callbacks: list[Any] | None = None,
    ) -> dict[str, Any]:
        """그래프를 실행하고 통일 인터페이스 형태로 반환한다.

        Returns:
            {
                "final_answer": str,
                "source_documents": list[str],
                "metadata": {pattern, bm25_count, dense_count, rrf_top_scores,
                             dense_weight, source_pages, confidence, cited_pages,
                             is_grounded, ...},
            }
        """
        from infra.llm_cache import cache_delta, cache_snapshot

        cache_start = cache_snapshot()
        initial_state: HybridRAGState = {"question": question}
        if chat_history:
            initial_state["chat_history"] = chat_history
        invoke_config: dict[str, Any] = {}
        if callbacks:
            invoke_config["callbacks"] = callbacks
        final_state: HybridRAGState = self._graph.invoke(initial_state, config=invoke_config)  # type: ignore[assignment]

        top_docs: list[Document] = final_state.get("top_docs", [])
        metadata: dict[str, Any] = dict(final_state.get("metadata", {}))

        if self.config.self_rag_enabled:
            metadata["is_grounded"] = final_state.get("is_grounded")
            metadata["grade_reason"] = final_state.get("grade_reason")
            metadata["self_rag_attempts"] = final_state.get("retry_count", 0) + 1
            metadata["rewritten_question"] = final_state.get("rewritten_question")

        metadata.update(cache_delta(cache_start))

        return {
            "final_answer": final_state.get("answer", ""),
            "source_documents": [d.page_content for d in top_docs],
            "metadata": metadata,
        }

    def stream_query(
        self,
        question: str,
        chat_history: list[BaseMessage] | None = None,
        callbacks: list[Any] | None = None,
    ):
        """답변 토큰을 yield하는 generator. Streamlit ``st.write_stream`` 호환.

        검색은 동기로 실행하고 LLM 응답만 토큰 단위로 흘려보낸다.
        Structured output 미사용 — UX 우선. 출처 페이지는 검색 결과에서 직접 추출.

        주의 — Self-RAG 미적용:
            stream_query는 그래프를 사용하지 않으므로 ``self_rag_enabled=True``라도
            grade/rewrite 루프가 동작하지 않는다.

        Stream 종료 후 메타데이터는 ``self._last_metadata``에 저장된다.
        """
        from infra.llm_cache import cache_delta, cache_snapshot

        self._last_metadata = None
        start = time.time()
        cache_start = cache_snapshot()

        # 1. 검색 (retriever에 위임)
        bm25_results, dense_results, fused = self.retriever.retrieve_split(  # type: ignore[union-attr]
            question, k=self.config.top_k
        )
        top_docs = [doc for doc, _ in fused[: self.config.top_k]]

        # 2. Reranker (활성화 시)
        if self.config.reranker_enabled:
            from rag_core.reranker import FlashRankReranker, rerank_and_reorder

            if self._reranker is None:
                self._reranker = FlashRankReranker()
            top_docs = rerank_and_reorder(
                query=question,
                docs=top_docs,
                reranker=self._reranker,
                top_k=self.config.reranker_top_k,
            )

        # 3. 컨텍스트 + LLM stream
        context = "\n\n---\n\n".join(_format_doc_with_meta(d) for d in top_docs)
        chain = self._prompt | self.llm
        full_text: list[str] = []

        stream_config: dict[str, Any] = {}
        if callbacks:
            stream_config["callbacks"] = callbacks
        for chunk in chain.stream(
            {
                "context": context,
                "question": question,
                "chat_history": chat_history or [],
            },
            config=stream_config,
        ):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if text:
                full_text.append(text)
                yield text

        elapsed = time.time() - start
        answer_text = "".join(full_text)
        # 후처리 정규식 — LLM 답변에서 [p.N] 패턴을 추출해 cited_pages 채움
        # (stream 모드는 with_structured_output 미사용이라 LLM 자체 emit 의존)
        cited_pages = extract_cited_pages_from_text(answer_text)
        # source_pages_label: 0-indexed page → 권/장 라벨
        from rag_core.citation_label import labels_for_pages
        from rag_core.followup import generate_followups

        source_pages_label = labels_for_pages(
            [d.metadata.get("page") for d in top_docs]
        )
        self._last_metadata = {
            "pattern": self.PATTERN_NAME,
            "bm25_count": len(bm25_results),
            "dense_count": len(dense_results),
            "rrf_top_scores": [round(s, 4) for _, s in fused[:5]],
            "dense_weight": self.config.dense_weight,
            "source_pages": [d.metadata.get("page") for d in top_docs],
            "source_pages_label": source_pages_label,
            "source_documents": [d.page_content for d in top_docs],
            "elapsed_seconds": elapsed,
            "answer_full": answer_text,
            "confidence": None,
            "cited_pages": cited_pages,
            "is_grounded": None,
            "tool_calls": [],
            "subgraph": None,
            "suggested_followups": generate_followups(question, answer_text, self.llm),
            **cache_delta(cache_start),
        }


_CITED_PAGE_PATTERN = re.compile(r"\[p\.(\d+)\]")


def extract_cited_pages_from_text(text: str) -> list[int]:
    """답변 텍스트에서 ``[p.N]`` 패턴을 추출해 1-indexed page 리스트 반환.

    중복 제거 (LLM 이 같은 페이지를 여러 번 인용하는 경우) + 등장 순서 보존.
    """
    seen: set[int] = set()
    out: list[int] = []
    for match in _CITED_PAGE_PATTERN.finditer(text):
        page = int(match.group(1))
        if page not in seen:
            seen.add(page)
            out.append(page)
    return out


def _format_doc_with_meta(doc: Document) -> str:
    """청크 본문에 출처 메타데이터를 prepend한다.

    LLM이 답변에서 출처를 인용할 수 있도록 [page N] 형태로 명시.
    PDF 외(FAQ 등)에서 page가 없으면 source/filename으로 fallback.
    """
    page = doc.metadata.get("page")
    if page is not None:
        return f"[page {page + 1}] {doc.page_content}"

    src = doc.metadata.get("filename") or doc.metadata.get("source")
    if src:
        return f"[{src}] {doc.page_content}"

    return doc.page_content
